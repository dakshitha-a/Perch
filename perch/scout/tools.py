"""Scout's tools: the allowlist, each a thin wrapper over the deterministic pipeline.

Scout can call these nine names and nothing else (SPEC section 8). Each returns a JSON
object; every record it mentions is added to `ScoutContext.seen` under its short id,
so the validator can check Scout's answer against exactly what the tools returned.
compare and draft_handoff (S12) use the compare view and skill 3; a draft is returned,
never sent or stored.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from perch import awards as aw
from perch.brief import route_a
from perch.compare import award_size
from perch.datefmt import closes as closes_text
from perch.datefmt import day, placeholder_close
from perch.datefmt import shown as shown_day
from perch.eligibility import Constraints
from perch.llm import Tool
from perch.llm.audit import AuditedProvider
from perch.profile import Profile, build_threads
from perch.rerank import RerankCache
from perch.schemas import (
    Award,
    Lead,
    Opportunity,
    Organisation,
    Record,
    Researcher,
    belongs_to,
)
from perch.score import match_score
from perch.sources import openalex as oa

ALLOWLIST = ("resolve_author", "build_profile", "list_awards", "search_opportunities",
             "get_org_signals", "explain_fit", "compare", "draft_handoff", "get_record")
DESCRIPTION_CHARS = 1200


class ToolError(Exception):
    """A tool refused its arguments; the message goes back to the model."""


def short_id(r: Record) -> str:
    """OpenAlex ids are URLs; Scout sees the last segment (W123, A456)."""
    return r.id.rsplit("/", 1)[-1] if r.id.startswith("https://openalex.org/") else r.id


@dataclass
class ScoutContext:
    """What a Scout session works on: one researcher, one as-of date, one store."""

    service: Any  # perch.service.BriefService (not imported: it imports the skills)
    as_of: date
    researcher_id: str | None = None
    explainer: AuditedProvider | None = None
    handoff: AuditedProvider | None = None  # the hand-off model for this session (S28)
    brief_id: str | None = None  # the brief the user is looking at, if any
    profile: Profile | None = None
    route_b: list[Lead] | None = None  # this session's Route B leads, once found
    seen: dict[str, Record] = field(default_factory=dict)

    def see(self, r: Record) -> str:
        sid = short_id(r)
        self.seen[sid] = r
        return sid

    def full_author_id(self, author_id: str | None) -> str:
        aid = oa.parse_author_id(author_id or "") or oa.parse_author_id(self.researcher_id or "")
        if not aid:
            raise ToolError("no researcher: pass an OpenAlex author id such as A5023080104")
        return f"https://openalex.org/{aid}"


def _researcher(ctx: ScoutContext, author_id: str | None) -> Researcher:
    full = ctx.full_author_id(author_id)
    with ctx.service.repo() as r:
        res = r.get(Researcher, full)
        if res is None:
            with ctx.service.clients.openalex() as c:
                res = c.get_author(full)
            r.upsert([res])
    return res


def _profile(ctx: ScoutContext, author_id: str | None) -> Profile:
    res = _researcher(ctx, author_id)
    if ctx.profile and ctx.profile.researcher_id == res.id:
        return ctx.profile
    with ctx.service.repo() as r:
        works = r.works_by_author(res.id)
        if not works:
            with ctx.service.clients.openalex() as c:
                works = list(c.iter_works(res.id))
            r.upsert(works)
    ctx.researcher_id = res.id
    ctx.profile = build_threads(res.id, works, ctx.service.models.get("embedder"), ctx.as_of)
    return ctx.profile


# --- the tools ---

def resolve_author(ctx: ScoutContext, name: str) -> dict:
    with ctx.service.clients.openalex() as c:
        found = c.resolve_by_name(name)
    with ctx.service.repo() as r:
        r.upsert(found)
    return {"candidates": [{"id": ctx.see(x), "display_name": x.display_name,
                            "institutions": x.institutions, "works_count": x.works_count}
                           for x in found[:5]]}


def build_profile(ctx: ScoutContext, author_id: str | None = None) -> dict:
    p = _profile(ctx, author_id)
    with ctx.service.repo() as r:
        works = {w.id: w for w in r.works_by_author(p.researcher_id)}
    threads = []
    for t in p.threads:
        papers = [{"id": ctx.see(works[w]), "title": works[w].title,
                   "year": works[w].publication_year}
                  for w in t.work_ids[:3] if w in works]
        threads.append({"thread": t.index + 1, "label": t.label,
                        "share_of_recent_work": f"{t.weight:.0%}", "top_papers": papers})
    return {"researcher": ctx.see(_researcher(ctx, author_id)), "papers": len(p.work_ids),
            "threads": threads}


def list_awards(ctx: ScoutContext, author_id: str | None = None) -> dict:
    res = _researcher(ctx, author_id)
    with ctx.service.repo() as r:
        ov = aw.load_overrides(res.id, ctx.service.overrides)
        linked = aw.link_stored(res, r.list(Award), ov)
    summaries = aw.summarise(linked, res, ov)
    h = aw.award_horizon(summaries)
    out = []
    for s in summaries:
        rec = s.end_record or next(a for a in linked if aw.award_key(a) == s.key)
        out.append({"id": ctx.see(rec), "award_number": s.award_number, "title": s.title,
                    "agency": s.agency, "activity_code": s.activity_code,
                    "start_date": s.start_date and day(s.start_date),
                    "end_date": s.end_date and day(s.end_date),
                    "matched_by_initial": s.matched_by_initial})
    return {"researcher": ctx.see(res), "awards": out,
            "horizon_award": h and ctx.see(h.end_record or linked[0]),
            "note": "Public NIH and NSF records only; other funding is not visible."}


def search_opportunities(ctx: ScoutContext, route: str = "A", author_id: str | None = None,
                         min_amount: float | None = None, max_amount: float | None = None,
                         agencies: list[str] | None = None,
                         exclude_agencies: list[str] | None = None,
                         closes_by: str | None = None, activity_codes: list[str] | None = None,
                         keywords: list[str] | None = None,
                         exclude_keywords: list[str] | None = None, top: int = 10,
                         closes_after: str | None = None, sort: str = "match") -> dict:
    if route == "B":
        out = get_org_signals(ctx, author_id, top=top)
        return {**out, "note": out["note"] + " Grant filters (agency, amount, dates, codes, "
                "keywords) do not apply to route B."}
    try:
        by = date.fromisoformat(closes_by) if closes_by else None
        after = date.fromisoformat(closes_after) if closes_after else None
    except ValueError as e:
        raise ToolError(f"closes_by and closes_after take a date like 2027-03-01: "
                        f"{closes_by or closes_after!r}") from e
    c = Constraints(as_of=ctx.as_of, min_amount=min_amount, max_amount=max_amount,
                    agencies=agencies or [], exclude_agencies=exclude_agencies or [],
                    closes_by=by, closes_after=after,
                    activity_codes=[a.upper() for a in activity_codes or []],
                    keywords=keywords or [], exclude_keywords=exclude_keywords or [])
    res = _researcher(ctx, author_id)
    _profile(ctx, author_id)  # make sure the works are in the store
    s = ctx.service
    with s.repo() as r:
        b = route_a(res, r, s.models.get("index"), s.models.get("embedder"),
                    s.models.get("reranker"), c, RerankCache(s.rerank_cache),
                    top=max(1, min(int(top), 20)), timings_log=None,
                    index_new=getattr(s, "index_writes", True))  # a private session: no
    leads = []
    for i, x in enumerate(b.leads, 1):
        o = x.opportunity
        leads.append({"rank": i, "id": ctx.see(o), "title": o.title, "agency": o.agency,
                      "activity_code": o.activity_code,
                      # As the cards write it (Q22); a far-off placeholder date reads as
                      # the record's own words (U3, Q20).
                      "close_date": closes_text(o, ctx.as_of),
                      "award_size": award_size(o) or "not in the record",
                      "match": match_score(x.rerank_score),
                      "matched_thread": x.candidate.best_thread + 1})
    if sort == "close_date":  # the soonest first; open-anytime and undated ones last (Q14)
        opp = {ctx.see(x.opportunity): x.opportunity for x in b.leads}

        def soon(d: dict) -> tuple[bool, date]:
            o = opp[d["id"]]
            return (o.close_date is None or placeholder_close(o, ctx.as_of),
                    o.close_date or date.max)

        leads.sort(key=soon)
    reasons: dict[str, int] = {}
    for rs in b.rejected.values():
        for why in rs:
            key = why.split(":")[0] if "keyword" not in why else why
            reasons[key] = reasons.get(key, 0) + 1
    top_reasons = dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:6])
    return {"source": "Grants.gov federal opportunities in the store", "as_of":
            ctx.as_of.isoformat(), "retrieved": b.retrieved, "removed_by_filters":
            len(b.rejected), "top_removal_reasons": top_reasons, "leads": leads}


def _route_b_leads(ctx: ScoutContext, author_id: str | None) -> list[Lead]:
    """The brief's stored Route B leads when the session is on a brief for this researcher;
    otherwise found now. Found leads stay in memory; their organisations and evidence
    records go to the store so get_record can open them."""
    from perch import route_b as rb

    res = _researcher(ctx, author_id)
    if ctx.route_b is not None and ctx.researcher_id == res.id:
        return ctx.route_b
    leads: list[Lead] = []
    if ctx.brief_id and (got := ctx.service.get(ctx.brief_id)) and \
            got[0].researcher_id == res.id and _stage_done(got[0], "route_b"):
        leads = sorted((x for x in got[1] if x.route == "B"), key=lambda x: x.rank or 0)
    else:
        _profile(ctx, res.id)
        with ctx.service.repo() as r:
            works = r.works_by_author(res.id)
        with ctx.service.clients.openalex() as oc, ctx.service.clients.nih() as nc:
            g = rb.gather(oc, nc, works, ctx.as_of)
        found = rb.score_leads(res.id, g.seeds, g.citing, g.topical, g.sbir, g.topics,
                               ctx.as_of, own=g.own)
        with ctx.service.repo() as r:
            r.upsert([*rb.evidence_records(found, g), *(x.org for x in found)])
        leads = rb.make_leads(found, f"scout-{oa.short_id(res.id)}")
    ctx.researcher_id, ctx.route_b = res.id, leads
    return leads


def _stage_done(b: object, name: str) -> bool:
    return any(s.name == name and s.status in ("done", "skipped") for s in b.stages)


def get_org_signals(ctx: ScoutContext, author_id: str | None = None,
                    organisation: str | None = None, top: int = 5) -> dict:
    from perch.route_b import LABEL, sentence

    leads = _route_b_leads(ctx, author_id)
    with ctx.service.repo() as r:
        orgs = {x.record_id: r.get(Organisation, x.record_id) for x in leads}
        out = []
        for x in leads:
            org = orgs.get(x.record_id)
            name = org.name if org else x.record_id
            if organisation and organisation.lower() not in " ".join(
                    [name, *(org.aliases if org else [])]).lower():
                continue
            signals = []
            for sig in x.signals:
                ev = [r.get_any(i) for i in sig.record_ids[:3]]
                signals.append({"kind": sig.kind, "count": sig.count,
                                "latest": sig.latest and day(sig.latest),
                                "sentence": sentence(sig, name, len(x.cited_ids)),
                                "records": [ctx.see(e) for e in ev if e]})
            out.append({"lead": ctx.see(x), "rank": x.rank, "organisation": name,
                        "organisation_id": ctx.see(org) if org else x.record_id,
                        "relationship": x.relationship, "confidence": x.confidence,
                        "signals": signals, "researcher_papers_cited": x.cited_ids[:10]})
            for c in x.cited_ids[:10]:
                if (w := r.get_any(f"https://openalex.org/{c}")) is not None:
                    ctx.see(w)
    return {"route": "B", "label": LABEL, "leads": out[:max(1, min(int(top), 5))],
            "note": "Companies with at least two kinds of public signal: company works citing "
            "the researcher, NIH SBIR/STTR awards in their topics (NIH only), and company "
            "works in their topics. Cite the lead id for its counts and dates."}


def explain_fit(ctx: ScoutContext, opportunity_id: str) -> dict:
    from perch.skills.fit import explain_one, profile_prompt  # skills import the model layer

    o = _opportunity(ctx, opportunity_id)
    if ctx.explainer is None:
        raise ToolError("explanations are off in this session")
    p = _profile(ctx, None)
    with ctx.service.repo() as r:
        works = {w.id: w for w in r.works_by_author(p.researcher_id)}
    system, papers = profile_prompt(p, works)
    v = explain_one(o, system, papers, ctx.explainer, ctx.service.models.get("grounder"))
    if not v.value:
        return {"opportunity": ctx.see(o), "status": "withheld",
                "detail": "The explanation failed the citation check twice."}
    f = v.value
    for pid in f.cited_ids:  # the fit skill cites papers by short work id
        if pid in papers:
            ctx.see(papers[pid])
    # The step shows the card's Match for this lead, not the model's own fit number (U6).
    lead = next((x for x in (ctx.service.get(ctx.brief_id) or (None, []))[1]
                 if x.record_id == o.id), None) if ctx.brief_id else None
    return {"opportunity": ctx.see(o), "fit": f.fit,
            "match_on_card": lead.match_score if lead else None, "opportunity_sentence":
            f.opportunity_sentence, "research_sentence": f.research_sentence,
            "inference": f.link_sentence, "unsupported_statements": f.unsupported,
            "cited_ids": [c if c in papers else ctx.see(o) for c in f.cited_ids]}


def _opportunity(ctx: ScoutContext, opportunity_id: str) -> Opportunity:
    with ctx.service.repo() as r:
        o = r.get(Opportunity, opportunity_id)
        if o is None:
            hits = [x for x in r.list(Opportunity) if x.opportunity_number == opportunity_id]
            o = hits[0] if hits else None
    if o is None:
        raise ToolError(f"no opportunity {opportunity_id!r} in the store")
    return o


def get_record(ctx: ScoutContext, id: str) -> dict:
    with ctx.service.repo() as r:
        rec = r.get_any(id) or r.get_any(f"https://openalex.org/{id}")
    if rec is None or not belongs_to(rec, ctx.brief_id):  # another visitor's (review S9)
        raise ToolError(f"no record {id!r} in the store")
    d = rec.model_dump(mode="json", exclude_none=True)
    if isinstance(rec, Opportunity) and rec.close_date:  # the card's words (U3, Q20, Q22)
        d["close_date"] = closes_text(rec, ctx.as_of)
        if placeholder_close(rec, ctx.as_of):
            d["close_date_placeholder"] = (f"{rec.close_date.isoformat()}: a far-off "
                                           "placeholder date; the deadline is close_date")
    for k in ("description", "abstract"):
        if isinstance(d.get(k), str) and len(d[k]) > DESCRIPTION_CHARS:
            d[k] = d[k][:DESCRIPTION_CHARS] + " [truncated]"
    d.pop("embedding", None)
    d["id"] = ctx.see(rec)
    return {"kind": rec.kind, "record": d}


def _items(ctx: ScoutContext, ids: list[str] | None) -> list[tuple[Lead, Record | None]]:
    """Leads with their opportunity or organisation, for compare and draft_handoff. An id
    is a lead id, an opportunity id or number, or an organisation id. With no ids: the
    kept leads of the brief the user is looking at."""
    brief_leads: list[Lead] = []
    if ctx.brief_id and (got := ctx.service.get(ctx.brief_id)):
        brief_leads = got[1]
    if not ids:
        kept = [x for x in brief_leads if x.status == "kept"]
        if not kept:
            raise ToolError("no kept leads: pass the ids of the leads to use (opportunity ids "
                            "from search_opportunities, or lead ids from get_org_signals)")
        chosen = kept
    else:
        pool = brief_leads + [x for x in ctx.route_b or [] if x not in brief_leads]
        chosen = []
        for i in ids:
            key = i.strip()
            hit = next((x for x in pool if key in (
                x.id, x.record_id, short_id(x), x.record_id.rsplit("/", 1)[-1],
                x.record_id.removeprefix("grants_gov:"))), None)
            if hit is None:
                o = _opportunity(ctx, key)  # an opportunity outside any brief
                hit = Lead(id=f"scout:{o.opportunity_number}", source=o.source,
                           source_url=o.source_url, fetched_at=o.fetched_at, brief_id="scout",
                           route="A", record_id=o.id)
            if hit not in chosen:
                chosen.append(hit)
    with ctx.service.repo() as r:
        return [(x, r.get(Opportunity if x.route == "A" else Organisation, x.record_id))
                for x in chosen]


def compare(ctx: ScoutContext, ids: list[str] | None = None) -> dict:
    from perch import compare as cmp

    if not ids and ctx.brief_id and (got := ctx.service.get(ctx.brief_id)) \
            and not any(x.status == "kept" for x in got[1]):  # Q4
        top = sorted((x for x in got[1] if x.route == "A" and x.status != "dismissed"),
                     key=lambda x: x.rank or 0)[:3]
        with ctx.service.repo() as r:
            offer = [{"id": ctx.see(o), "title": o.title} for x in top
                     if (o := r.get(Opportunity, x.record_id)) is not None]
        return {"rows": [], "kept": 0, "top_leads": offer,
                "note": "Nothing is kept on the brief, so there is nothing to compare. Say "
                "so, and offer to compare the top leads listed here."}
    items = _items(ctx, ids)
    rows = []
    for lead, rec in items:
        row = (cmp.route_a_row(lead, rec, ctx.as_of) if lead.route == "A"
               else cmp.route_b_row(lead, rec))
        cells = {}
        for key, label in cmp.COLUMNS:
            c = row.cells[key]
            text = shown_day(c.text) if key == "closes" else c.text  # as on the cards (Q22)
            cells[label] = f"{text} ({c.note})" if c.note else text
        out = {"route": row.route, "title": row.title,
               "record": ctx.see(rec) if rec else row.record_id, **cells}
        if lead.route == "B":
            out["lead"] = ctx.see(lead)  # holds the code-written signal sentences
        rows.append(out)
    return {"rows": rows, "note": "Each cell is copied from the record or counted from it "
            "by code. \"Not in the record\" means the record does not say. Industry leads "
            "are inferred from public signals, not verified. There is no effort, IP or "
            "likelihood column because no record states them."}


def draft_handoff(ctx: ScoutContext, office: str | None = None,
                  ids: list[str] | None = None) -> dict:
    from perch.offices import OFFICES, for_route
    from perch.skills.handoff import draft_handoff as draft

    items = _items(ctx, ids)
    routes = {x.route for x, _ in items}
    if office:
        off = OFFICES[office]
        items = [(x, rec) for x, rec in items if x.route == off.route]
        if not items:
            raise ToolError(f"none of these leads goes to {off.name}: grants go to "
                            f"{for_route('A').name}, industry leads to {for_route('B').name}")
    elif len(routes) > 1:
        raise ToolError(f"grants go to {for_route('A').name} and industry leads to "
                        f"{for_route('B').name}: call once per office")
    else:
        off = for_route(routes.pop())
    res = _researcher(ctx, None)
    wids = list(dict.fromkeys(c for x, _ in items for c in x.cited_ids if c.startswith("W")))
    if not wids:  # leads from outside a brief cite no papers: use the profile's top ones
        p = _profile(ctx, None)
        wids = [short for t in p.threads for short in
                (w.rsplit("/", 1)[-1] for w in t.work_ids[:2])][:6]
    with ctx.service.repo() as r:
        papers = [w for w in (r.get_any(f"https://openalex.org/{c}") for c in wids) if w]
    s = ctx.service
    d = draft(off, res, items, papers, ctx.handoff or s._audited("handoff", s.models.handoff_spec))
    for x, rec in items:
        if rec:
            ctx.see(rec)
        if x.route == "B":
            ctx.see(x)
    return {"office": off.name, "office_page": off.url, "to": "", "subject": d.subject,
            "body": d.body, "opening_withheld": d.flagged,
            "note": "A draft only. Perch never sends it. Show it to the user to edit and send; "
            "the To line is for them to fill in from the office page."}


# --- schemas (strict: no extra properties; optional ones are left out of "required") ---

def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


STR = {"type": "string"}
STRS = {"type": "array", "items": {"type": "string"}}
AUTHOR = {"type": "string", "description": "OpenAlex author id, e.g. A5023080104. Omit for "
          "the session's researcher."}
OPP = {"type": "string", "description": "Opportunity id from search_opportunities, e.g. "
       "grants_gov:PAR-25-123"}

TOOLS: dict[str, tuple[Tool, Callable[..., dict]]] = {
    "resolve_author": (Tool("resolve_author", "Find OpenAlex author records by name. Use only "
                            "when no researcher id is known.",
                            _obj({"name": STR}, ["name"])), resolve_author),
    "build_profile": (Tool("build_profile", "The researcher's research threads from their "
                           "public papers, with the top papers per thread.",
                           _obj({"author_id": AUTHOR}, [])), build_profile),
    "list_awards": (Tool("list_awards", "The researcher's public NIH and NSF awards and the "
                         "award that ends last.", _obj({"author_id": AUTHOR}, [])), list_awards),
    "search_opportunities": (Tool(
        "search_opportunities",
        "Re-run the funding search with filters. Route A is federal grants (Grants.gov); "
        "route B is industry leads (the same as get_org_signals; the filters below apply to "
        "route A only). Amounts are US dollars; dates are like 2027-03-01. Only eligible, "
        "open opportunities are returned. For the next deadline, set closes_after to the "
        "as-of date and sort to close_date: closes_by drops every lead that closes after "
        "its date.",
        _obj({"route": {"type": "string", "enum": ["A", "B"]}, "author_id": AUTHOR,
              "min_amount": {"type": "number", "description": "drop if the ceiling is below"},
              "max_amount": {"type": "number", "description": "drop if the ceiling is above"},
              "agencies": {**STRS, "description": "keep only these agencies, e.g. NIH, NSF"},
              "exclude_agencies": {**STRS, "description": "drop these agencies"},
              "closes_by": {**STR, "description": "drop if it closes after this date"},
              "closes_after": {**STR, "description": "drop if it closes on or before this "
                               "date"},
              "sort": {"type": "string", "enum": ["match", "close_date"],
                       "description": "match (the default) or close_date, soonest first"},
              "activity_codes": {**STRS, "description": "keep only these, e.g. R21, R01"},
              "keywords": {**STRS, "description": "keep if any is in the title or text"},
              "exclude_keywords": {**STRS, "description": "drop if any is in the title or "
                                   "text, e.g. clinical trial"},
              "top": {"type": "integer", "description": "how many leads, 1 to 20"}},
             ["route"])), search_opportunities),
    "get_org_signals": (Tool(
        "get_org_signals",
        "Route B industry leads: companies with at least two kinds of public signal (their "
        "works cite the researcher's papers; NIH SBIR/STTR awards in the researcher's topics; "
        "their works in those topics), each with counts, newest dates and evidence records. "
        "Leads are inferred, not verified. Optionally one company by name.",
        _obj({"author_id": AUTHOR,
              "organisation": {**STR, "description": "a company name, e.g. AstraZeneca"},
              "top": {"type": "integer", "description": "how many leads, 1 to 5"}}, [])),
        get_org_signals),
    "explain_fit": (Tool("explain_fit", "Why one opportunity fits the researcher, from the "
                         "opportunity record and their papers, checked by the citation "
                         "validator.", _obj({"opportunity_id": OPP}, ["opportunity_id"])),
                    explain_fit),
    "compare": (Tool(
        "compare",
        "Kept or chosen leads side by side: money, close date, activity code, funding "
        "instrument or suggested relationship, evidence and Temple office, each copied from "
        "its record. Omit ids for the leads the user kept on the brief; pass ids only when "
        "the user names the leads to compare.",
        _obj({"ids": {**STRS, "description": "opportunity ids (e.g. grants_gov:PAR-25-123) "
                      "or industry lead ids from get_org_signals"}}, [])), compare),
    "draft_handoff": (Tool(
        "draft_handoff",
        "Draft an email to a Temple office about leads: research_development for grants, "
        "technology_commercialization for industry leads. Returns the draft for the user to "
        "edit; Perch never sends anything. Omit ids for the leads the user kept.",
        _obj({"office": {"type": "string", "enum": ["research_development",
                                                    "technology_commercialization"]},
              "ids": {**STRS, "description": "opportunity ids or industry lead ids"}}, [])),
        draft_handoff),
    "get_record": (Tool("get_record", "One stored public record by id, with its fields "
                        "(dates, amounts, eligibility, description).",
                        _obj({"id": STR}, ["id"])), get_record),
}
assert tuple(TOOLS) == ALLOWLIST
for _tool, _ in TOOLS.values():
    _tool.strict = False  # see perch.llm.base.Tool; check_arguments() runs on every call


def _fixed(t: Tool) -> Tool:
    props = {k: v for k, v in t.parameters["properties"].items() if k != "author_id"}
    return Tool(t.name, t.description, _obj(props, [r for r in t.parameters["required"]
                                                     if r != "author_id"]), strict=False)


# Scout's own table (S28, SCOUT_SPEC section 4): a Scout session already knows its
# researcher, so no tool takes an author_id and there is no author search. The MCP server
# keeps TOOLS, because an MCP client starts without a researcher.
SESSION_TOOLS: dict[str, tuple[Tool, Callable[..., dict]]] = {
    name: (_fixed(t), fn) for name, (t, fn) in TOOLS.items() if name != "resolve_author"}


def check_arguments(tool: Tool, args: object) -> list[str]:
    """Shape check against the tool's schema: object, required present, no extras, and
    the JSON types of the values. Enough to refuse a malformed call before it runs."""
    if not isinstance(args, dict):
        return ["arguments must be an object"]
    props = tool.parameters["properties"]
    errs = [f"missing {k!r}" for k in tool.parameters["required"] if k not in args]
    errs += [f"unknown argument {k!r}" for k in args if k not in props]
    types = {"string": str, "number": int | float, "integer": int, "array": list}
    for k, v in args.items():
        spec = props.get(k)
        if spec is None or v is None:
            continue
        t = types.get(spec.get("type", ""))
        if t and (not isinstance(v, t) or isinstance(v, bool)):
            errs.append(f"{k!r} must be {spec['type']}")
        elif spec.get("enum") and v not in spec["enum"]:
            errs.append(f"{k!r} must be one of {spec['enum']}")
        elif spec.get("type") == "array" and not all(isinstance(x, str) for x in v):
            errs.append(f"{k!r} must be a list of strings")
    return errs

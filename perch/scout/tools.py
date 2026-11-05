"""Scout's tools: the allowlist, each a thin wrapper over the deterministic pipeline.

Scout can call these ten names and nothing else (SPEC section 8). Each returns a JSON
object; every record it mentions is added to `ScoutContext.seen` under its short id,
so the validator can check Scout's answer against exactly what the tools returned.
compare and draft_handoff (S12) use the compare view and skill 3; a draft is returned,
never sent or stored. cover_points (S33) uses skill 4: checked, cited points for one
grant or fellowship from the session's CV and documents, the papers and public awards.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from perch import awards as aw
from perch.brief import route_a
from perch.compare import lower_first
from perch.datefmt import closes as closes_text
from perch.datefmt import day, deadline, expires_only, no_deadline, placeholder_close
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
    Work,
    belongs_to,
)
from perch.score import band, match_score
from perch.sources import openalex as oa

ALLOWLIST = ("resolve_author", "build_profile", "list_awards", "search_opportunities",
             "get_org_signals", "explain_fit", "compare", "draft_handoff", "cover_points",
             "get_record")
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
    # Lines code wrote about a record, such as a student's rule lines ("Open to year 4;
    # your CV says 3"): an answer citing the record may repeat their numbers (T10).
    facts: dict[str, list[str]] = field(default_factory=dict)
    # The record a step's code-written values are attributed to, by tool name: an answer
    # citing the step, such as "[build_profile]", is checked as citing that record (t06).
    step_records: dict[str, str] = field(default_factory=dict)
    # Label terms code wrote that carry a digit, such as "hiv-1" in a thread label: a name,
    # not a number, so the check does not read the 1 in it (t06).
    labels: set[str] = field(default_factory=set)

    def see(self, r: Record) -> str:
        sid = short_id(r)
        self.seen[sid] = r
        return sid

    def full_author_id(self, author_id: str | None) -> str:
        aid = oa.parse_author_id(author_id or "") or oa.parse_author_id(self.researcher_id or "")
        if not aid:
            raise ToolError("no researcher: pass an OpenAlex author id such as A5023080104")
        return f"https://openalex.org/{aid}"


def _user_docs(ctx: ScoutContext) -> list[Work]:  # noqa: ARG001 - the store is in the context
    """The user's own documents the brief reads (a proposal, a direction, an interests note),
    from the brief store the caller set; none for a guest or without accounts."""
    from perch.user.briefs import current_store

    store = current_store.get()
    return store.user_docs() if store is not None else []


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
    embedder = ctx.service.models.get("embedder")
    p = build_threads(res.id, works, embedder, ctx.as_of)
    if docs := _user_docs(ctx):  # R6: the documents' threads, as the brief built them
        from perch.threads import add_threads

        p = add_threads(p, docs, embedder)
    ctx.profile = p
    return ctx.profile


def fit_sentence(lead: Lead) -> str | None:
    """The lead's checked fit sentence from the brief, as its card shows it, without the
    citation brackets (T8): one sentence of why, with no model call. Its own record, cited
    as a noun, reads "this opportunity" (F2), and it speaks to the researcher, who is the
    one asking: "the researcher's" reads "your" (F12)."""
    import re

    from perch.export import own_in_place

    if not lead.inference or lead.flagged:
        return None
    own = {lead.record_id, lead.record_id.removeprefix("grants_gov:")}
    text = re.sub(r"\s*\[[^\[\]]*\]", "", own_in_place(lead.inference, own))
    return second_person(" ".join(text.split())) or None


# F12: the card's sentence is about "the researcher"; Scout answers the researcher.
_VERB = {"has": "have", "is": "are", "was": "were", "does": "do", "focuses": "focus"}


def second_person(text: str) -> str:
    import re

    def verb(m: re.Match) -> str:
        you = "You" if m.group(1) == "T" else "you"
        v = m.group(2)
        if v in _VERB:
            v = _VERB[v]
        elif re.fullmatch(r"\w+(?:ss|sh|ch|x|z|o)es", v):
            v = v[:-2]
        elif v.endswith("ies") and len(v) > 4:
            v = v[:-3] + "y"
        elif v.endswith("s") and not v.endswith("ss"):
            v = v[:-1]
        return f"{you} {v}"

    text = re.sub(r"\b([Tt])he researcher['’]s\b",
                  lambda m: "Your" if m.group(1) == "T" else "your", text)
    # "the researcher develops" -> "you develop": a lower-case word ending in s after it
    text = re.sub(r"\b([Tt])he researcher (\w*[a-z]s)\b", verb, text)
    return re.sub(r"\b([Tt])he researcher\b", lambda m: "You" if m.group(1) == "T" else "you", text)


def _brief_leads(ctx: ScoutContext) -> list[Lead]:
    """The brief's grant leads in its own order by Match, dismissed ones left out."""
    got = ctx.service.get(ctx.brief_id) if ctx.brief_id else None
    return sorted((x for x in (got[1] if got else []) if x.route == "A"
                   and x.status != "dismissed"), key=lambda x: x.rank or 0)


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
    works.update({d.id: d for d in _user_docs(ctx)})
    rid = ctx.see(_researcher(ctx, author_id))
    threads = []
    # t06: the labels, shares and counts are written by code, so an answer citing the
    # profile step, the researcher or a thread's paper may repeat them, as compare's cells.
    # The label text stays out of these lines: its digits are names, not numbers.
    lines = [f"{len(p.work_ids)} papers in the profile", f"{len(p.threads)} research threads"]
    for t in p.threads:
        papers = [{"id": ctx.see(works[w]), "title": works[w].title,
                   "year": works[w].publication_year}
                  for w in t.work_ids[:3] if w in works]
        share = f"{t.weight:.0%}"
        threads.append({"thread": t.index + 1, "label": t.label,
                        "share_of_recent_work": share, "papers_in_thread": len(t.work_ids),
                        "top_papers": papers})
        line = f"thread {t.index + 1}: {share} of recent work, {len(t.work_ids)} papers"
        lines.append(line)
        for x in papers:
            ctx.facts[x["id"]] = [line]
        ctx.labels |= {term for term in (w.strip().lower() for w in t.label.split(","))
                       if re.search(r"\d", term)}
    ctx.facts[rid] = lines
    ctx.step_records["build_profile"] = rid
    return {"researcher": rid, "papers": len(p.work_ids), "threads": threads}


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
                         closes_after: str | None = None, sort: str = "match",
                         scope: str = "all") -> dict:
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
    if scope == "brief":  # F1: "these" and "my leads" are the brief's own leads
        return _search_brief(ctx, c, sort, top)
    res = _researcher(ctx, author_id)
    p = _profile(ctx, author_id)  # the works are in the store; a session's documents count
    s = ctx.service
    extra = {}
    if _user_docs(ctx):  # a document's thread is never cached (P6, R6)
        from perch.threads import public_thread

        extra = {"profile": p, "cacheable": public_thread}
    with s.repo() as r:
        b = route_a(res, r, s.models.get("index"), s.models.get("embedder"),
                    s.models.get("reranker"), c, RerankCache(s.rerank_cache),
                    # F16: a sort looks at the widest list, then cuts it to top; cut first,
                    # "top 1 by ceiling" was the best match, whatever its ceiling
                    top=20 if sort != "match" else max(1, min(int(top), 20)), timings_log=None,
                    index_new=getattr(s, "index_writes", True), **extra)
    leads = []
    in_brief = {x.record_id: i for i, x in enumerate(_brief_leads(ctx), 1)}
    for i, x in enumerate(b.leads, 1):
        o = x.opportunity
        leads.append(_lead_row(ctx, i, o, in_brief.get(o.id), match_score(x.rerank_score)))
    unstated = _sort(leads, {ctx.see(x.opportunity): x.opportunity for x in b.leads}, sort,
                     ctx.as_of)
    leads = leads[:max(1, min(int(top), 20))]
    return {"source": "Grants.gov federal opportunities in the store", "scope": "all",
            "as_of": ctx.as_of.isoformat(), "retrieved": b.retrieved,
            "removed_by_filters": len(b.rejected), "top_removal_reasons": _reasons(b.rejected),
            "leads": leads, "note": " ".join(x for x in (
                # F10: the brief's leads first; others with their band, never as if on it
                ("Leads with brief_rank are on the user's brief: name them first. Name any "
                 "other as a further lead, not on the brief, with its match band."
                 if any("brief_rank" in d for d in leads) else
                 "None of these is on the user's brief: say so first, then name each with "
                 "its match band.") if leads else "",
                CEILING_NOTE if sort == "award_ceiling" else "") if x) or None,
            **({"no_ceiling_stated": unstated} if unstated else {})}


# G2: the largest ceiling is named from leads that state one. A lead whose record gives
# only a floor ("from $15,000,000") is listed apart, with no amount, so it is never read
# as the largest award.
CEILING_NOTE = ("Sorted by award_ceiling, the largest first. no_ceiling_stated lists leads "
                "whose record states no ceiling: never call one of them the largest. Name "
                "each amount by its field, ceiling or floor.")


def _lead_row(ctx: ScoutContext, i: int, o: Opportunity, brief_rank: int | None,
              match: int | None) -> dict:
    return {"rank": i, "id": ctx.see(o), "title": o.title, "agency": o.agency,
            # "these" are the brief's leads (T1): its own place in the brief
            **({"brief_rank": brief_rank} if brief_rank else {}),
            "activity_code": o.activity_code,
            # As the cards write it (Q22), with its own verb (F22): "closes 4 Feb 2027",
            # the record's words for a placeholder date (U3, Q20), or a parent
            # announcement's expiry, which is no deadline (F3, T17).
            "deadline": deadline(o, ctx.as_of),
            # G2: each amount under the field it is, so a floor is never read as a ceiling
            "award_ceiling": f"${o.award_ceiling:,.0f}" if o.award_ceiling else "not in the record",
            **({"award_floor": f"${o.award_floor:,.0f}"} if o.award_floor else {}),
            "match_band": f"{band(match)} match" if match is not None else None}


def _sort(leads: list[dict], opp: dict[str, Opportunity], sort: str, as_of: date) -> list[dict]:
    """Sort the rows in place. A sort by award ceiling ranks only the rows whose record
    states a ceiling; the others leave the list and come back as short rows with no amount
    ("no ceiling stated", G2)."""
    unstated: list[dict] = []
    if sort == "close_date":  # the soonest first; open-anytime and undated ones last (Q14)
        leads.sort(key=lambda d: (no_deadline(opp[d["id"]], as_of),
                                  opp[d["id"]].close_date or date.max))
    elif sort == "award_ceiling":  # the largest ceiling first (T6)
        unstated = [{"id": d["id"], "title": d["title"], **({"brief_rank": d["brief_rank"]}
                                                           if "brief_rank" in d else {})}
                    for d in leads if not opp[d["id"]].award_ceiling]
        leads[:] = sorted((d for d in leads if opp[d["id"]].award_ceiling),
                          key=lambda d: -opp[d["id"]].award_ceiling)
    if sort != "match":  # T6: rank is the place in this order
        for i, d in enumerate(leads, 1):
            d["rank"] = i
    return unstated


def _reasons(rejected: dict[str, list[str]]) -> dict[str, int]:
    reasons: dict[str, int] = {}
    for rs in rejected.values():
        for why in rs:
            key = why.split(":")[0] if "keyword" not in why else why
            reasons[key] = reasons.get(key, 0) + 1
    return dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:6])


def _search_brief(ctx: ScoutContext, c: Constraints, sort: str, top: int = 20) -> dict:
    """F1: the filters applied to the brief's own grant leads, in the brief's order, by the
    same rule code as the search. The brief already settled eligibility, so its
    title rules are not run again."""
    from perch.eligibility import check

    if not ctx.brief_id:
        raise ToolError("scope brief needs a brief, and this session has none: use scope all")
    base = Constraints(as_of=c.as_of, include_restricted=True, career_stage_ok=True)
    c.include_restricted = c.career_stage_ok = True
    leads, opp, rejected = [], {}, {}
    with ctx.service.repo() as r:
        for i, x in enumerate(_brief_leads(ctx), 1):
            o = r.get(Opportunity, x.record_id)
            if o is None:
                continue
            settled = set(check(o, base))  # the brief's own eligibility, not asked again
            if why := [w for w in check(o, c) if w not in settled]:
                rejected[o.id] = why
                continue
            leads.append(_lead_row(ctx, len(leads) + 1, o, i, x.match_score))
            opp[leads[-1]["id"]] = o
    unstated = _sort(leads, opp, sort, ctx.as_of)
    leads = leads[:max(1, min(int(top), 20))]  # G2: "top 1 by ceiling" is one lead
    return {"source": "the grant leads on the user's brief", "scope": "brief",
            "as_of": ctx.as_of.isoformat(), "brief_leads": len(leads) + len(rejected),
            "removed_by_filters": len(rejected), "top_removal_reasons": _reasons(rejected),
            "leads": leads, "note": " ".join(x for x in (
                "Only the brief's own leads; name these and no others." if leads else
                "None of the brief's leads passes these filters: say so plainly.",
                CEILING_NOTE if sort == "award_ceiling" else "") if x),
            **({"no_ceiling_stated": unstated} if unstated else {})}


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
                signals.append({"kind": sig.kind, "works_or_projects": sig.count,
                                "latest": sig.latest and day(sig.latest),
                                "sentence": sentence(sig, name, len(x.cited_ids)),
                                "records": [ctx.see(e) for e in ev if e]})
            lid = ctx.see(x)
            oid = ctx.see(org) if org else x.record_id
            # F5: counts code wrote from the records; an answer citing the lead or the
            # company may repeat them. Citing works and the papers they cite differ.
            ctx.facts[lid] = ctx.facts[oid] = [s["sentence"] for s in signals]
            out.append({"lead": lid, "rank": x.rank, "organisation": name,
                        # G23: on a brief, one id form to cite, the lead's; MCP keeps both
                        **({} if ctx.brief_id else {"organisation_id": oid}),
                        "relationship": x.relationship,
                        "confidence": x.confidence, "signals": signals,
                        "your_papers_cited": len(x.cited_ids),
                        "researcher_papers_cited": x.cited_ids[:10]})
            for c in x.cited_ids[:10]:
                if (w := r.get_any(f"https://openalex.org/{c}")) is not None:
                    ctx.see(w)
    return {"route": "B", "label": LABEL, "leads": out[:max(1, min(int(top), 5))],
            "note": "Companies with at least two kinds of public signal: company works citing "
            "the researcher, NIH SBIR/STTR awards in their topics (NIH only), and company "
            "works in their topics. works_or_projects counts a company's works or projects; "
            "your_papers_cited counts the researcher's papers those works cite. Copy the "
            "signal sentences and cite the lead id for counts and dates."}


def explain_fit(ctx: ScoutContext, opportunity_id: str) -> dict:
    from perch.skills.fit import explain_one, profile_prompt  # skills import the model layer

    o = _opportunity(ctx, opportunity_id)
    if ctx.explainer is None:
        raise ToolError("explanations are off in this session")
    p = _profile(ctx, None)
    with ctx.service.repo() as r:
        works = {w.id: w for w in r.works_by_author(p.researcher_id)}
    works.update({d.id: d for d in _user_docs(ctx)})  # R6: as the brief explained it
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
    return {"opportunity": ctx.see(o),
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


NO_CLOSING_DATE = "The record states no closing date."


def get_record(ctx: ScoutContext, id: str) -> dict:
    with ctx.service.repo() as r:
        rec = r.get_any(id) or r.get_any(f"https://openalex.org/{id}")
    if rec is None or not belongs_to(rec, ctx.brief_id):  # another visitor's (review S9)
        raise ToolError(f"no record {id!r} in the store")
    d = rec.model_dump(mode="json", exclude_none=True)
    if isinstance(rec, Opportunity) and placeholder_close(rec, ctx.as_of):
        # T7 (Q20 again): the record's own words come first and no close date is given,
        # so the model quotes the words and cannot say the date is missing or far off.
        d.pop("close_date", None)
        d.pop("close_date_note", None)
        # S51 E5: G8 made a date ten years out a placeholder with or without a note; with
        # none, this read "None (the record's own words)".
        d = {"deadline": f"{rec.close_date_note} (the record's own words)"
             if rec.close_date_note else NO_CLOSING_DATE, **d}
    elif isinstance(rec, Opportunity) and expires_only(rec):
        # G3 (T17, F3 again): a parent announcement's close date is when it expires. Under
        # close_date the model read it as the deadline, and later turns repeated it.
        d.pop("close_date", None)
        d = {"deadline": deadline(rec, ctx.as_of), **d}
    elif isinstance(rec, Opportunity) and rec.close_date:  # as the cards write it (Q22)
        d["close_date"] = closes_text(rec, ctx.as_of)
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


def _why(lead: Lead) -> dict:
    """T8: the lead's fit sentence from the brief, labelled as the card labels it: "How it
    relates" in the weak band (T15, F11)."""
    if lead.route != "A" or not (w := fit_sentence(lead)):
        return {}
    return {"how_it_relates" if band(lead.match_score) == "weak" else "why_it_fits": w}


def _evidence(lead: Lead) -> str:
    """The Evidence cell as Scout reads it: the Match band in words (the rules forbid the
    score as a number) and the papers the lead's explanation cites."""
    n = len([c for c in lead.cited_ids if c.startswith("W")])
    b = band(lead.match_score)
    return ", ".join(x for x in (f"{b} match" if b else "",
                                 f"cites {n} of your papers" if n else "") if x) or "no Match"


def compare(ctx: ScoutContext, ids: list[str] | None = None) -> dict:
    from perch import compare as cmp

    if not ids and ctx.brief_id and (got := ctx.service.get(ctx.brief_id)) \
            and not any(x.status == "kept" for x in got[1]):  # Q4
        top = _brief_leads(ctx)[:3]
        with ctx.service.repo() as r:
            offer = [{"id": ctx.see(o), "title": o.title, **_why(x)} for x in top
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
            text = lower_first(text) if key == "money" else text  # read mid-sentence (R17)
            if key == "evidence" and lead.route == "A":  # F11: no score, no state note
                cells[label] = _evidence(lead)
                continue
            cells[label] = f"{text} ({c.note})" if c.note and key != "evidence" else text
        rid = ctx.see(rec) if rec else row.record_id
        out = {"kind": "grant" if row.route == "A" else "industry lead",  # F11: no route code
               "title": row.title, "number": getattr(row, "number", None),
               "record": rid, "kept": lead.status == "kept", **cells,
               **_why(lead)}
        if lead.route == "A":
            # F5: the count is code-written from the brief's lead, so an answer citing this
            # record may repeat it ("cites 3 of your papers").
            n = len([c for c in lead.cited_ids if c.startswith("W")])
            out["your_papers_cited"] = n
            ctx.facts[rid] = [f"cites {n} of your papers"]
        if lead.route == "B":
            out["lead"] = ctx.see(lead)  # holds the code-written signal sentences
        rows.append(out)
    top = []
    order = [x.record_id for x in _brief_leads(ctx)]
    if ids and [x.record_id for x, _ in items] == order[:len(items)]:  # G19: the top N
        head = (f"These rows are the brief's top {len(items)} leads, in its own order by "
                "Match, the strongest first. ")
    else:
        with ctx.service.repo() as r:
            for x in _brief_leads(ctx)[:3]:
                if (o := r.get(Opportunity, x.record_id)) is not None:
                    top.append({"id": ctx.see(o), "title": o.title, **_why(x)})
        head = ("These rows are the leads compared, not the brief's top leads. "
                + ("brief_top_leads are the first three in the brief's own order by Match: "
                   "use them for top or best. " if top else ""))
    return {"rows": rows, **({"brief_top_leads": top} if top else {}),
            "note": head + "why_it_fits (how_it_relates for a "
            "weak match) is the lead's checked fit sentence from the brief. Each cell is "
            "copied from the record or counted from it by code. \"Not in the record\" means "
            "the record does not say. Industry leads are inferred from public signals, not "
            "verified. Answer in short sentences, not a table."}


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
    # The same call as the Compare tab's draft (service.handoff): the model may read the
    # user's own documents, after the consent given at sign-up.
    docs = _user_docs(ctx)
    try:
        d = draft(off, res, items, papers,
                  ctx.handoff or s._audited("handoff", s.models.handoff_spec),
                  user_docs=docs or None)
    except LookupError as e:  # Q3: only Temple internal calls, which name their own contact
        raise ToolError(str(e)) from None
    for x, rec in items:
        if rec and x.id not in d.left_out:
            ctx.see(rec)
        if x.route == "B":
            ctx.see(x)
    return {"office": off.name, "office_page": off.url, "to": "", "subject": d.subject,
            "body": d.body, "opening_withheld": d.flagged, "opening_by": d.opening_by,
            "note": "A draft only. Perch never sends it. Show it to the user to edit and send; "
            "the To line is for them to fill in from the office page.",
            **({"left_out_note": d.left_out_note} if d.left_out_note else {})}


# --- cover points (S33, skill 4) ---

INDUSTRY_NO_POINTS = ("cover points are for grants and fellowships; an industry lead has no "
                      "application")
POINTS_NOTE = ("Points for you to put in your own words. Each cites the record it comes from. "
               "Perch never sends anything.")
NO_CV_NOTE = (" Adding a CV under Tell Perch more gives points from it too.")


def _target(ctx: ScoutContext, key: str) -> tuple[Opportunity, Lead | None]:
    """The grant or fellowship the points are for, with its lead when it is on the brief.
    An organisation or industry lead id is refused: it has no application."""
    brief_leads = (ctx.service.get(ctx.brief_id) or (None, []))[1] if ctx.brief_id else []
    pool = brief_leads + [x for x in ctx.route_b or [] if x not in brief_leads]
    hit = next((x for x in pool if key in (
        x.id, x.record_id, short_id(x), x.record_id.rsplit("/", 1)[-1],
        x.record_id.removeprefix("grants_gov:"))), None)
    if hit is not None and hit.route == "B":
        raise ToolError(INDUSTRY_NO_POINTS)
    with ctx.service.repo() as r:
        if r.get(Organisation, key) or r.get(Organisation, f"https://openalex.org/{key}"):
            raise ToolError(INDUSTRY_NO_POINTS)
        o = r.get(Opportunity, hit.record_id) if hit is not None else None
    return (o, hit) if o is not None else (_opportunity(ctx, key), hit)


def _awards(ctx: ScoutContext) -> list[Award]:
    """The researcher's public awards, one record per award, as list_awards links them."""
    res = _researcher(ctx, None)
    with ctx.service.repo() as r:
        ov = aw.load_overrides(res.id, ctx.service.overrides)
        linked = aw.link_stored(res, r.list(Award), ov)
    return [s.end_record or next(a for a in linked if aw.award_key(a) == s.key)
            for s in aw.summarise(linked, res, ov)]


def applicant_docs(ctx: ScoutContext) -> tuple[Work | None, list[Work]]:
    """The user's own documents as the cover-points skill takes them: the CV apart (contact
    details blanked when it is made), then the other documents. From the brief store the
    caller set; empty for a guest."""
    from perch.user.briefs import current_store
    from perch.user.inputs import make_doc

    store = current_store.get()
    if store is None:
        return None, []
    text = store.cv_text()
    return (make_doc("cv", text) if text else None), store.user_docs()


def source_title(r: Record) -> str:
    if isinstance(r, Opportunity):
        return r.title
    title = getattr(r, "title", None) or getattr(r, "name", None) or r.id
    return title


def cover_result(ctx: ScoutContext, target: Record, title: str, key: str, v: object,
                 records: dict[str, Record], sample: bool, note: str) -> dict:
    """The card's JSON, the contract the web app builds against. Ids are the ones Scout
    sees (the target as its own record, a sample as its sample: id); every record cited is
    registered with ctx.see, so an answer may cite it. No document text is in it."""
    tid = ctx.see(target)
    base = {"for": {"id": tid, "title": title, "sample": sample}}
    tail = {"by": "model", "note": note}
    if getattr(v, "value", None) is None:
        return {**base, "points": [], "missing": [], "unsupported": [], "sources": {tid: title},
                "status": "withheld", "detail": "The points failed the citation check twice.",
                **tail}
    p = v.value
    ids, sources = {key: tid}, {tid: title}
    for k in p.used_ids():
        if k in records and k != key:
            sid = ctx.see(records[k])
            ids[k] = sid
            sources[sid] = source_title(records[k])
    return {**base,
            "points": [{"asks": x.asks, "asks_ids": [ids[i] for i in x.asks_ids],
                        "you": x.you, "you_ids": [ids[i] for i in x.you_ids]}
                       for x in p.points],
            "missing": list(p.missing), "unsupported": list(p.unsupported),
            "sources": sources, "status": "done", "detail": "", **tail}


def cover_points(ctx: ScoutContext, record_id: str) -> dict:
    from perch.skills.cover import cover_points as points_for

    key = record_id.strip().strip("[]")
    o, lead = _target(ctx, key)
    cv, docs = applicant_docs(ctx)
    wids = [c for c in (lead.cited_ids if lead else []) if c.startswith("W")]
    if not wids:  # not on a brief, or a lead that cites no paper: the profile's top ones
        p = _profile(ctx, None)
        wids = [short for t in p.threads for short in
                (w.rsplit("/", 1)[-1] for w in t.work_ids[:2]) if short.startswith("W")][:6]
    with ctx.service.repo() as r:
        papers = [w for w in (r.get_any(f"https://openalex.org/{c}") for c in wids) if w]
    awards = _awards(ctx)
    if cv is None and not docs and not papers and not awards:
        raise ToolError("no applicant records: add a CV or documents under Tell Perch more")
    s = ctx.service
    provider = ctx.handoff or s._audited("handoff", s.models.handoff_spec)
    v, records = points_for(o, cv, docs, papers, awards, provider,
                            grounder=s.models.get("grounder"))
    note = POINTS_NOTE + ("" if cv or docs else NO_CV_NOTE)
    return cover_result(ctx, o, o.title, o.opportunity_number, v, records, False, note)


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
        "its date. For the largest award, set sort to award_ceiling; an award floor is not "
        "a ceiling.",
        _obj({"route": {"type": "string", "enum": ["A", "B"]}, "author_id": AUTHOR,
              "min_amount": {"type": "number", "description": "drop if the ceiling is below"},
              "max_amount": {"type": "number", "description": "drop if the ceiling is above"},
              "agencies": {**STRS, "description": "keep only these agencies, e.g. NIH, NSF"},
              "exclude_agencies": {**STRS, "description": "drop these agencies"},
              "closes_by": {**STR, "description": "drop if it closes after this date"},
              "closes_after": {**STR, "description": "drop if it closes on or before this "
                               "date"},
              "sort": {"type": "string", "enum": ["match", "close_date", "award_ceiling"],
                       "description": "match (the default), close_date (the soonest first) "
                       "or award_ceiling (the largest ceiling first)"},
              "activity_codes": {**STRS, "description": "keep only these, e.g. R21, R01"},
              "keywords": {**STRS, "description": "keep if any is in the title or text"},
              "exclude_keywords": {**STRS, "description": "drop if any is in the title or "
                                   "text, e.g. clinical trial"},
              "top": {"type": "integer", "description": "how many leads, 1 to 20"},
              "scope": {"type": "string", "enum": ["brief", "all"],
                        "description": "brief: only the brief's own leads (for \"these\" or "
                        "\"my leads\"); all: every opportunity in the store (the default)"}},
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
        "the user names the leads to compare. Use it for kept leads, the shortlist or a "
        "comparison, not for the top or best leads, which are the brief's order by Match.",
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
    "cover_points": (Tool(
        "cover_points",
        "Points a cover letter or application for one grant or fellowship could make: what "
        "the record asks for, tied to the researcher's CV, documents, papers and public "
        "awards, each cited and checked. Not for industry leads.",
        _obj({"record_id": OPP}, ["record_id"])), cover_points),
    "get_record": (Tool("get_record", "One stored public record by id, with its fields "
                        "(dates, amounts, eligibility, description).",
                        _obj({"id": STR}, ["id"])), get_record),
}
assert tuple(TOOLS) == ALLOWLIST
assert len(TOOLS["cover_points"][0].description) <= 300
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
# T3: "Draft the hand-off for my top lead" drafted the two kept leads, because the draft
# took the kept leads when no ids came. In a session the model names the leads: the top
# lead is the first in the brief's order by Match; kept leads only when the user says so.
SESSION_TOOLS["draft_handoff"] = (Tool(
    "draft_handoff",
    "Draft an email to a Temple office about the leads named in ids: research_development "
    "for grants, technology_commercialization for industry leads. \"My top lead\" is the "
    "first lead in the brief's order by Match, alone; \"my top three\" the first three. "
    "Pass the kept leads' ids only when the user asks about the kept leads or the "
    "shortlist. Returns the draft for the user to edit; Perch never sends anything.",
    _obj({"ids": {**STRS, "description": "the leads to write about: opportunity ids such as "
                  "grants_gov:PAR-25-123, or industry lead ids from get_org_signals"},
          "office": TOOLS["draft_handoff"][0].parameters["properties"]["office"]}, ["ids"]),
    strict=False), draft_handoff)


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

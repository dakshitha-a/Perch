"""Scout's tools: the allowlist, each a thin wrapper over the deterministic pipeline.

Scout can call these nine names and nothing else (SPEC section 8). Each returns a JSON
object; every record it mentions is added to `ScoutContext.seen` under its short id,
so the validator can check Scout's answer against exactly what the tools returned.
Three tools belong to later sessions and say so instead of doing anything (Q18).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from perch import awards as aw
from perch.brief import route_a
from perch.eligibility import Constraints
from perch.llm import Tool
from perch.llm.audit import AuditedProvider
from perch.profile import Profile, build_threads
from perch.rerank import RerankCache
from perch.schemas import Award, Opportunity, Record, Researcher
from perch.sources import openalex as oa

ALLOWLIST = ("resolve_author", "build_profile", "list_awards", "search_opportunities",
             "get_org_signals", "explain_fit", "compare", "draft_handoff", "get_record")
NOT_BUILT = {"get_org_signals": "S11", "compare": "S12", "draft_handoff": "S12"}
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
    profile: Profile | None = None
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
        linked = aw.link_awards(res, r.list(Award), ov)
    summaries = aw.summarise(linked)
    h = aw.award_horizon(summaries)
    out = []
    for s in summaries:
        rec = s.end_record or next(a for a in linked if aw.award_key(a) == s.key)
        out.append({"id": ctx.see(rec), "award_number": s.award_number, "title": s.title,
                    "agency": s.agency, "activity_code": s.activity_code,
                    "start_date": s.start_date and s.start_date.isoformat(),
                    "end_date": s.end_date and s.end_date.isoformat()})
    return {"researcher": ctx.see(res), "awards": out,
            "horizon_award": h and ctx.see(h.end_record or linked[0]),
            "note": "Public NIH and NSF records only; other funding is not visible."}


def search_opportunities(ctx: ScoutContext, route: str = "A", author_id: str | None = None,
                         min_amount: float | None = None, max_amount: float | None = None,
                         agencies: list[str] | None = None,
                         exclude_agencies: list[str] | None = None,
                         closes_by: str | None = None, activity_codes: list[str] | None = None,
                         keywords: list[str] | None = None,
                         exclude_keywords: list[str] | None = None, top: int = 10) -> dict:
    if route != "A":
        return {"status": "not_built", "detail": "Route B (industry leads) is built in S11."}
    try:
        by = date.fromisoformat(closes_by) if closes_by else None
    except ValueError as e:
        raise ToolError(f"closes_by must be a date like 2027-03-01: {closes_by!r}") from e
    c = Constraints(as_of=ctx.as_of, min_amount=min_amount, max_amount=max_amount,
                    agencies=agencies or [], exclude_agencies=exclude_agencies or [],
                    closes_by=by, activity_codes=[a.upper() for a in activity_codes or []],
                    keywords=keywords or [], exclude_keywords=exclude_keywords or [])
    res = _researcher(ctx, author_id)
    _profile(ctx, author_id)  # make sure the works are in the store
    s = ctx.service
    with s.repo() as r:
        b = route_a(res, r, s.models.get("index"), s.models.get("embedder"),
                    s.models.get("reranker"), c, RerankCache(s.rerank_cache),
                    top=max(1, min(int(top), 20)), timings_log=None)
    leads = []
    for i, x in enumerate(b.leads, 1):
        o = x.opportunity
        leads.append({"rank": i, "id": ctx.see(o), "title": o.title, "agency": o.agency,
                      "activity_code": o.activity_code,
                      "close_date": o.close_date and o.close_date.isoformat(),
                      "award_ceiling": o.award_ceiling,
                      "matched_thread": x.candidate.best_thread + 1})
    reasons: dict[str, int] = {}
    for rs in b.rejected.values():
        for why in rs:
            key = why.split(":")[0] if "keyword" not in why else why
            reasons[key] = reasons.get(key, 0) + 1
    top_reasons = dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:6])
    return {"source": "Grants.gov federal opportunities in the store", "as_of":
            ctx.as_of.isoformat(), "retrieved": b.retrieved, "removed_by_filters":
            len(b.rejected), "top_removal_reasons": top_reasons, "leads": leads}


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
    return {"opportunity": ctx.see(o), "fit": f.fit, "opportunity_sentence":
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
    if rec is None:
        raise ToolError(f"no record {id!r} in the store")
    d = rec.model_dump(mode="json", exclude_none=True)
    for k in ("description", "abstract"):
        if isinstance(d.get(k), str) and len(d[k]) > DESCRIPTION_CHARS:
            d[k] = d[k][:DESCRIPTION_CHARS] + " [truncated]"
    d.pop("embedding", None)
    d["id"] = ctx.see(rec)
    return {"kind": rec.kind, "record": d}


def not_built(name: str) -> Callable[..., dict]:
    def run(ctx: ScoutContext, **_: object) -> dict:
        return {"status": "not_built", "detail": f"{name} is built in {NOT_BUILT[name]}; "
                "nothing was done."}
    return run


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
        "route B is industry and is not built yet. Amounts are US dollars; closes_by is a date "
        "like 2027-03-01. Only eligible, open opportunities are returned.",
        _obj({"route": {"type": "string", "enum": ["A", "B"]}, "author_id": AUTHOR,
              "min_amount": {"type": "number", "description": "drop if the ceiling is below"},
              "max_amount": {"type": "number", "description": "drop if the ceiling is above"},
              "agencies": {**STRS, "description": "keep only these agencies, e.g. NIH, NSF"},
              "exclude_agencies": {**STRS, "description": "drop these agencies"},
              "closes_by": {**STR, "description": "drop if it closes after this date"},
              "activity_codes": {**STRS, "description": "keep only these, e.g. R21, R01"},
              "keywords": {**STRS, "description": "keep if any is in the title or text"},
              "exclude_keywords": {**STRS, "description": "drop if any is in the title or "
                                   "text, e.g. clinical trial"},
              "top": {"type": "integer", "description": "how many leads, 1 to 20"}},
             ["route"])), search_opportunities),
    "get_org_signals": (Tool("get_org_signals", "Industry signals for route B (not built "
                             "yet).", _obj({"author_id": AUTHOR}, [])),
                        not_built("get_org_signals")),
    "explain_fit": (Tool("explain_fit", "Why one opportunity fits the researcher, from the "
                         "opportunity record and their papers, checked by the citation "
                         "validator.", _obj({"opportunity_id": OPP}, ["opportunity_id"])),
                    explain_fit),
    "compare": (Tool("compare", "Compare opportunities side by side (not built yet).",
                     _obj({"opportunity_ids": STRS}, ["opportunity_ids"])), not_built("compare")),
    "draft_handoff": (Tool("draft_handoff", "Draft a hand-off note to a Temple office (not "
                           "built yet). Never sends anything.",
                           _obj({"opportunity_id": OPP}, ["opportunity_id"])),
                      not_built("draft_handoff")),
    "get_record": (Tool("get_record", "One stored public record by id, with its fields "
                        "(dates, amounts, eligibility, description).",
                        _obj({"id": STR}, ["id"])), get_record),
}
assert tuple(TOOLS) == ALLOWLIST
for _tool, _ in TOOLS.values():
    _tool.strict = False  # see perch.llm.base.Tool; check_arguments() runs on every call


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

"""Brief service: the pipeline as a job with saved, pollable stages.

Stages, in order: researcher, works, awards, profile, route_a, route_b, summary,
explanations.
Each is saved when it starts and finishes, so `GET /briefs/{id}` shows progress and
partial results (leads appear after route_a; explanations fill in one by one). Fetch
stages are skipped when the store already holds the data. A failure marks the stage
and the brief failed and keeps the error text.
"""

from __future__ import annotations

import secrets
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from perch import awards as aw
from perch.brief import route_a
from perch.config import env
from perch.eligibility import Constraints
from perch.embed import Embedder
from perch.grounding import Grounder
from perch.llm import Provider, get_provider, spec_for_role
from perch.llm.audit import AuditedProvider, AuditLog
from perch.rerank import RerankCache, Reranker
from perch.offices import OFFICES
from perch.schemas import (
    Award,
    Brief,
    Lead,
    Opportunity,
    Organisation,
    Record,
    Researcher,
    Stage,
    Work,
)
from perch.skills.fit import Fit, explain_leads
from perch.skills.handoff import Draft, draft_handoff
from perch.skills.summary import summarise_profile
from perch.sources import nih_reporter, nsf
from perch.sources import openalex as oa
from perch.store.base import VectorIndex
from perch.store.sqlite import SQLiteRepository
from perch.validate import Validated

STAGES = ("researcher", "works", "awards", "profile", "route_a", "route_b", "summary",
          "explanations")


def brief_options(as_of: date | None = None, top: int = 10, explain: bool = True,
                  min_amount: float | None = None, agencies: list[str] | None = None) -> dict:
    return {"as_of": (as_of or date.today()).isoformat(), "top": top, "explain": explain,
            "min_amount": min_amount, "agencies": agencies or []}


def now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Models:
    """Heavy components, built once per process on first use."""

    embedder: Callable[[], Embedder]
    reranker: Callable[[], Reranker]
    index: Callable[[], VectorIndex]
    grounder: Callable[[], Grounder | None]
    provider: Callable[[str], Provider] = get_provider
    summary_spec: str | None = None  # None: PERCH_LLM_PROFILE_SUMMARY / default
    fit_spec: str | None = None
    handoff_spec: str | None = None
    _built: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, name: str) -> object:
        with self._lock:
            if name not in self._built:
                self._built[name] = getattr(self, name)()
            return self._built[name]


@dataclass
class Clients:
    openalex: Callable[[], oa.OpenAlexClient]
    nih: Callable[[], nih_reporter.NIHReporterClient] = nih_reporter.NIHReporterClient
    nsf: Callable[[], nsf.NSFClient] = nsf.NSFClient


class BriefService:
    def __init__(self, db: str | Path, models: Models, clients: Clients,
                 overrides: Path = aw.OVERRIDES) -> None:
        self.db = str(db)
        self.models = models
        self.clients = clients
        self.overrides = overrides
        root = Path(self.db).parent
        self.audit = AuditLog(root / "logs/model_calls.jsonl")
        self.rerank_cache = root / "cache/rerank.db"
        self.timings_log = root / "logs/brief_timings.jsonl"
        self._ctx: dict[str, dict] = {}  # per-run state (the profile), keyed by brief id

    def repo(self) -> SQLiteRepository:
        return SQLiteRepository(self.db)

    # --- create and read ---

    def create(self, author_id: str, *, as_of: date | None = None, top: int = 10,
               explain: bool = True, min_amount: float | None = None,
               agencies: list[str] | None = None) -> Brief:
        aid = oa.parse_author_id(author_id)
        if not aid:
            raise ValueError(f"not an OpenAlex author id: {author_id!r}")
        bid = secrets.token_urlsafe(9)
        b = Brief(id=bid, source="perch", source_url=f"perch://briefs/{bid}", fetched_at=now(),
                  researcher_id=f"https://openalex.org/{aid}",
                  stages=[Stage(name=n) for n in STAGES],
                  options=brief_options(as_of, top, explain, min_amount, agencies))
        with self.repo() as r:
            r.upsert([b])
        return b

    def reuse(self, author_id: str, options: dict, hours: float) -> Brief | None:
        """A copy of the newest finished brief for the same researcher and options, made in
        the last `hours`, with fresh lead ids and every lead back to "new". Visitors share
        the work, never each other's keep and dismiss state."""
        aid = oa.parse_author_id(author_id)
        cutoff = now() - timedelta(hours=hours)
        with self.repo() as r:
            done = [b for b in r.list(Brief)
                    if b.status == "done" and b.researcher_id == f"https://openalex.org/{aid}"
                    and b.options == options and b.created_at >= cutoff
                    and tuple(s.name for s in b.stages) == STAGES]  # not from older code
            if not done:
                return None
            src = max(done, key=lambda b: b.created_at)
            bid = secrets.token_urlsafe(9)
            leads = [x for x in (r.get(Lead, i) for i in src.lead_ids) if x]
            copies = [x.model_copy(update={"id": f"{bid}:{x.id.split(':', 1)[1]}",
                                           "brief_id": bid, "status": "new"}) for x in leads]
            b = src.model_copy(update={"id": bid, "source_url": f"perch://briefs/{bid}",
                                       "lead_ids": [x.id for x in copies]})
            r.upsert([*copies, b])
        return b

    def get(self, brief_id: str) -> tuple[Brief, list[Lead]] | None:
        with self.repo() as r:
            b = r.get(Brief, brief_id)
            if not b:
                return None
            leads = [x for x in (r.get(Lead, i) for i in b.lead_ids) if x]
        return b, leads

    def set_lead_status(self, brief_id: str, lead_id: str, status: str) -> Lead | None:
        with self.repo() as r:
            lead = r.get(Lead, lead_id)
            if not lead or lead.brief_id != brief_id:
                return None
            lead = lead.model_copy(update={"status": status})
            r.upsert([lead])
        return lead

    # --- hand-off (skill 3; on request, not a pipeline stage) ---

    def handoff(self, brief_id: str, office_key: str, lead_ids: list[str] | None = None,
                spec: str | None = None, use_model: bool = True) -> Draft | None:
        """A draft to one office about the brief's kept leads on that office's route (or
        the given lead ids). None if the brief does not exist. Nothing is stored or sent."""
        office = OFFICES[office_key]
        got = self.get(brief_id)
        if not got:
            return None
        b, leads = got
        chosen = [x for x in leads if (x.id in lead_ids if lead_ids else
                                       x.status == "kept" and x.route == office.route)]
        with self.repo() as r:
            res = r.get(Researcher, b.researcher_id)
            items: list[tuple[Lead, Record | None]] = [
                (x, r.get(Opportunity if x.route == "A" else Organisation, x.record_id))
                for x in chosen]
            wids = list(dict.fromkeys(f"https://openalex.org/{c}" for x in chosen
                                      for c in x.cited_ids if c.startswith("W")))
            papers = [w for w in (r.get(Work, i) for i in wids) if w]
        if res is None:
            return None
        provider = (self._audited("handoff", spec or self.models.handoff_spec)
                    if use_model and chosen else None)
        return draft_handoff(office, res, items, papers, provider)

    # --- run ---

    def _stage(self, b: Brief, name: str, status: str, detail: str | None = None) -> None:
        for s in b.stages:
            if s.name == name:
                s.status = status
                if status == "running":
                    s.started_at = now()
                if status in ("done", "skipped", "failed"):
                    s.finished_at = now()
                if detail is not None:
                    s.detail = detail
        with self.repo() as r:
            r.upsert([b])

    def run(self, brief_id: str) -> None:
        with self.repo() as r:
            b = r.get(Brief, brief_id)
        if b is None:
            return
        b.status = "running"
        current = "researcher"
        try:
            for current in STAGES:
                self._stage(b, current, "running")
                detail, skipped = getattr(self, f"_run_{current}")(b)
                self._stage(b, current, "skipped" if skipped else "done", detail)
            b.status = "done"
        except Exception as e:  # recorded on the brief; the job thread must not die silently
            b.error = f"{type(e).__name__}: {e}"
            self._stage(b, current, "failed", b.error)
            b.status = "failed"
            traceback.print_exc()
        with self.repo() as r:
            r.upsert([b])
        self._ctx.pop(b.id, None)

    def _researcher(self, r: SQLiteRepository, b: Brief) -> Researcher:
        res = r.get(Researcher, b.researcher_id)
        if res is None:
            raise RuntimeError("researcher missing from the store")
        return res

    def _run_researcher(self, b: Brief) -> tuple[str, bool]:
        with self.repo() as r:
            res = r.get(Researcher, b.researcher_id)
            if res:
                return res.display_name, True
            with self.clients.openalex() as c:
                res = c.get_author(b.researcher_id)
            r.upsert([res])
        return res.display_name, False

    def _run_works(self, b: Brief) -> tuple[str, bool]:
        with self.repo() as r:
            have = r.works_by_author(b.researcher_id)
            if have:
                return f"{len(have)} works in the store", True
            with self.clients.openalex() as c:
                works = list(c.iter_works(b.researcher_id))
            r.upsert(works)
        return f"{len(works)} works fetched from OpenAlex", False

    def _run_awards(self, b: Brief) -> tuple[str, bool]:
        with self.repo() as r:
            res = self._researcher(r, b)
            ov = aw.load_overrides(res.id, self.overrides)
            # Only Temple awards: the store also holds companies' SBIR/STTR awards
            # (Route B), whose PIs could share the researcher's name.
            linked = aw.link_awards(res, [a for a in r.list(Award) if _temple(a)], ov)
            skipped = bool(linked)
            if not linked:
                fetched: list[Award] = []
                with self.clients.nih() as nc, self.clients.nsf() as sc:
                    for name in aw.query_names(res, ov):
                        first, last = aw.search_name(name)
                        fetched += nc.awards_for_pi(first, last)
                        fetched += sc.awards_for_pi(f"{first} {last}")
                r.upsert(fetched)
                linked = aw.link_awards(res, fetched, ov)
        summaries = aw.summarise(linked)
        h = aw.award_horizon(summaries)
        b.award_ids = [s.key for s in summaries]
        b.award_horizon = h.end_date if h else None
        horizon = h.end_date.isoformat() if h and h.end_date else "none"
        return f"{len(summaries)} public awards; horizon {horizon}", skipped

    def _run_profile(self, b: Brief) -> tuple[str, bool]:
        from perch.profile import build_threads

        with self.repo() as r:
            works = r.works_by_author(b.researcher_id)
        as_of = date.fromisoformat(b.options["as_of"])
        p = build_threads(b.researcher_id, works, self.models.get("embedder"), as_of)
        self._ctx.setdefault(b.id, {})["profile"] = p
        b.work_ids = p.work_ids
        b.threads = [{"index": t.index, "label": t.label, "weight": round(t.weight, 4),
                      "work_ids": t.work_ids} for t in p.threads]
        return f"{len(p.work_ids)} papers, {len(p.threads)} threads", False

    def _run_route_a(self, b: Brief) -> tuple[str, bool]:
        o = b.options
        c = Constraints(as_of=date.fromisoformat(o["as_of"]), min_amount=o.get("min_amount"),
                        agencies=o.get("agencies") or [])
        with self.repo() as r:
            res = self._researcher(r, b)
            brief = route_a(res, r, self.models.get("index"), self.models.get("embedder"),
                            self.models.get("reranker"), c, RerankCache(self.rerank_cache),
                            top=o.get("top", 10), timings_log=self.timings_log)
            leads = [Lead(id=f"{b.id}:{i}", source=x.opportunity.source,
                          source_url=x.opportunity.source_url,
                          fetched_at=x.opportunity.fetched_at, brief_id=b.id, route="A",
                          record_id=x.opportunity.id, rank=i,
                          rerank_score=round(x.rerank_score, 4),
                          matched_thread=x.candidate.best_thread)
                     for i, x in enumerate(brief.leads, 1)]
            r.upsert(leads)
        b.lead_ids = [x.id for x in leads]
        b.timings_ms = brief.timings_ms
        return (f"{brief.retrieved} retrieved, {len(brief.rejected)} ineligible removed, "
                f"{len(leads)} leads"), False

    def _run_route_b(self, b: Brief) -> tuple[str, bool]:
        from perch import route_b as rb

        as_of = date.fromisoformat(b.options["as_of"])
        with self.repo() as r:
            works = r.works_by_author(b.researcher_id)
        with self.clients.openalex() as oc, self.clients.nih() as nc:
            g = rb.gather(oc, nc, works, as_of)
        found = rb.score_leads(b.researcher_id, g.seeds, g.citing, g.topical, g.sbir, g.topics,
                               as_of, own=g.own)
        leads = rb.make_leads(found, b.id)
        with self.repo() as r:
            r.upsert([*rb.evidence_records(found, g), *(x.org for x in found), *leads])
        b.lead_ids = [*b.lead_ids, *(x.id for x in leads)]
        return (f"{len(g.citing)} citing works, {len(g.topical)} topic works, {len(g.sbir)} "
                f"SBIR/STTR records; {len(leads)} leads with two or more kinds of signal"), False

    def _audited(self, role: str, spec: str | None) -> AuditedProvider:
        return AuditedProvider(self.models.provider(spec or spec_for_role(role)), self.audit,
                               role)

    def _run_summary(self, b: Brief) -> tuple[str, bool]:
        if not b.options.get("explain"):
            return "explanations off", True
        with self.repo() as r:
            works = {w.id: w for w in r.works_by_author(b.researcher_id)}
        v = summarise_profile(self._ctx[b.id]["profile"], works,
                              self._audited("profile_summary", self.models.summary_spec))
        if v.value:
            b.topics = [t for t, _ in v.value.topics]
            b.summary = v.value.summary
            return "validated", False
        return "withheld: failed validation twice", False

    def _run_explanations(self, b: Brief) -> tuple[str, bool]:
        if not b.options.get("explain"):
            return "explanations off", True
        with self.repo() as r:
            works = {w.id: w for w in r.works_by_author(b.researcher_id)}
            leads = [x for x in (r.get(Lead, i) for i in b.lead_ids) if x and x.route == "A"]
            opps = [r.get(Opportunity, x.record_id) for x in leads]
        lock = threading.Lock()

        def save(i: int, v: Validated[Fit]) -> None:
            lead = leads[i]
            if v.value:
                f = v.value
                upd = {"fit_score": f.fit, "inference": f.link_sentence or None,
                       "explanation": f"{f.opportunity_sentence} {f.research_sentence}",
                       "unsupported": f.unsupported, "cited_ids": f.cited_ids}
            else:
                upd = {"flagged": True}
            with lock, self.repo() as r:
                r.upsert([lead.model_copy(update=upd)])

        results = explain_leads([o for o in opps if o], self._ctx[b.id]["profile"], works,
                                self._audited("fit_explainer", self.models.fit_spec),
                                grounder=self.models.get("grounder"), on_result=save)
        flagged = sum(v.flagged for v in results)
        unsupported = sum(bool(v.value and v.value.unsupported) for v in results)
        return (f"{len(results) - flagged} explained, {flagged} withheld, {unsupported} with an "
                "unsupported statement"), False


def _temple(a: Award) -> bool:
    return "temple" in (a.institution or "").lower()


def default_models(fake: bool = False, data_dir: Path = Path("data"),
                   llm: str | None = None) -> Models:
    from perch.embed import get_embedder
    from perch.grounding import FakeGrounder
    from perch.rerank import FakeReranker, make_reranker
    from perch.store.lance import LanceIndex

    if fake:
        return Models(embedder=lambda: get_embedder("fake-256", data_dir / "cache/emb.db"),
                      reranker=FakeReranker, index=lambda: LanceIndex(data_dir / "lance-fake"),
                      grounder=FakeGrounder, summary_spec=llm or "fake:fake-1",
                      fit_spec=llm or "fake:fake-1", handoff_spec=llm or "fake:fake-1")
    from perch.grounding import make_grounder
    from perch.profiles import current

    p = current()
    emb_cache = data_dir / "cache/embeddings.db"
    if server := env("PERCH_MODEL_SERVER"):
        # Hybrid deployment (S9): the app has no GPU; models run on perch.model_server.
        from perch.embed import CachedEmbedder
        from perch.remote_models import RemoteEmbedder, RemoteGrounder, RemoteReranker

        return Models(
            embedder=lambda: CachedEmbedder(RemoteEmbedder(server, p.embedder), emb_cache),
            reranker=lambda: (make_reranker(p.reranker) if p.reranker.startswith("systemone:")
                              else RemoteReranker(server, p.reranker)),
            index=lambda: LanceIndex(data_dir / "lance"),
            grounder=lambda: make_grounder(p.grounder, fallback=lambda: RemoteGrounder(server)),
            summary_spec=llm, fit_spec=llm, handoff_spec=llm)
    return Models(embedder=lambda: get_embedder(p.embedder, cache=emb_cache),
                  reranker=lambda: make_reranker(p.reranker),
                  index=lambda: LanceIndex(data_dir / "lance"),
                  grounder=lambda: make_grounder(p.grounder), summary_spec=llm, fit_spec=llm,
                  handoff_spec=llm)

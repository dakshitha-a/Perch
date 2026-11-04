"""Brief service: the pipeline as a job with saved, pollable stages.

Stages, in order: researcher, works, awards, profile, route_a, route_b, summary,
explanations.
Each is saved when it starts and finishes, so `GET /briefs/{id}` shows progress and
partial results (leads appear after route_a; explanations fill in one by one). Fetch
stages are skipped when the store already holds the data. A failure marks the stage
and the brief failed and keeps the error text.
"""

from __future__ import annotations

import contextvars
import logging
import secrets
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from perch import awards as aw
from perch import precache
from perch.brief import route_a
from perch.cache import InputContext, PublicCache, cache_key, is_public_input
from perch.config import env
from perch.eligibility import Constraints, agency_text, career_stage_restricted
from perch.embed import Embedder
from perch.grounding import Grounder
from perch.llm import Provider, get_provider, spec_for_role
from perch.llm.audit import AuditedProvider, AuditLog
from perch.offices import OFFICES
from perch.rerank import RerankCache, Reranker
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
from perch.score import match_score
from perch.skills import fit as fit_skill
from perch.skills import summary as summary_skill
from perch.skills.fit import Fit, explain_leads
from perch.skills.handoff import Draft, draft_handoff
from perch.skills.summary import summarise_profile
from perch.sources import nih_reporter, nsf
from perch.sources import openalex as oa
from perch.store.base import Repository, VectorIndex
from perch.store.sqlite import SQLiteRepository
from perch.student import STUDENT_STAGES, YOU
from perch.user.briefs import current_store, using_store
from perch.user.cv import sponsor_match
from perch.validate import VALIDATOR_VERSION, Validated

# Explanations come before the summary: they are what the Routes tab waits for (P2).
STAGES = ("researcher", "works", "awards", "profile", "route_a", "route_b", "explanations",
          "summary")
# Stages that use the network only and nothing later reads: each runs in a thread of its
# own beside the model stages, and the brief is done when it is too (review P2).
BACKGROUND = ("route_b",)


def brief_options(as_of: date | None = None, top: int = 10, explain: bool = True,
                  min_amount: float | None = None, agencies: list[str] | None = None,
                  context: dict | None = None) -> dict:
    """`context`: the optional normal-mode fields (Q16), kept only when set, so a brief
    without them has the same options, and is reused the same way, as before S13."""
    out = {"as_of": (as_of or date.today()).isoformat(), "top": top, "explain": explain,
           "min_amount": min_amount, "agencies": agencies or []}
    return {**out, **{k: v for k, v in (context or {}).items() if v}}


SPONSOR_BONUS = 0.05  # added to the rerank score for a past sponsor; a default, not measured
SAID_SHARE = 0.3  # the normal-mode direction thread's share of the weight; a default
SAID_ID = "said:direction"
ESI_SAID = ("You said you are an early-stage investigator, so this opportunity, limited by "
            "career stage, is kept. Check NIH's definition: "
            "https://grants.nih.gov/policy-and-compliance/policy-topics/early-stage-investigators")


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
    # Set by the worker (perch/cache.py); None means no shared cache.
    public_cache: PublicCache | None = None

    def __init__(self, db: str | Path, models: Models, clients: Clients,
                 overrides: Path = aw.OVERRIDES,
                 repo_factory: Callable[[], Repository] | None = None,
                 index_new: bool = True) -> None:
        self.db = str(db)
        self.repo_factory = repo_factory  # worker with PERCH_DATABASE_URL: Postgres reads
        self.index_new = index_new  # False when the vector index is filled by ingest
        self.models = models
        self.clients = clients
        self.overrides = overrides
        root = Path(self.db).parent
        self.audit = AuditLog(root / "logs/model_calls.jsonl")
        self.rerank_cache = root / "cache/rerank.db"
        self.timings_log = root / "logs/brief_timings.jsonl"
        self._ctx: dict[str, dict] = {}  # per-run state (the profile), keyed by brief id
        # Exception type only, no traceback, for every brief that reads the user's own text.
        self.quiet_errors = False

    def repo(self) -> SQLiteRepository:
        base = (self.repo_factory() if self.repo_factory is not None
                else SQLiteRepository(self.db))
        store = current_store.get()  # an account's or a guest's brief lives outside this store
        return store.wrap(base) if store is not None else base  # type: ignore[return-value]

    # --- create and read ---

    def create(self, author_id: str | None, *, as_of: date | None = None, top: int = 10,
               explain: bool = True, min_amount: float | None = None,
               agencies: list[str] | None = None, context: dict | None = None,
               brief_id: str | None = None, audience: str = "researcher",
               extra: dict | None = None) -> Brief:
        """A queued brief. `audience` picks the stage list: a researcher brief needs an
        OpenAlex author id; a student brief has none and reads the CV, interests and
        achievements from the brief's store. `extra` adds options (a guest's sample persona)."""
        bid = brief_id or secrets.token_urlsafe(9)
        if audience == "student":
            b = Brief(id=bid, source="perch", source_url=f"perch://briefs/{bid}",
                      fetched_at=now(), researcher_id=YOU,
                      stages=[Stage(name=n) for n in STUDENT_STAGES],
                      options={**brief_options(as_of, top, explain), "student": True,
                               **(extra or {})})
        else:
            aid = oa.parse_author_id(author_id or "")
            if not aid:
                raise ValueError(f"not an OpenAlex author id: {author_id!r}")
            b = Brief(id=bid, source="perch", source_url=f"perch://briefs/{bid}",
                      fetched_at=now(), researcher_id=f"https://openalex.org/{aid}",
                      stages=[Stage(name=n) for n in STAGES],
                      options={**brief_options(as_of, top, explain, min_amount, agencies,
                                               context), **(extra or {})})
        with self.repo() as r:
            r.upsert([b])
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
        if not chosen:  # F26: a draft with an empty list is no draft
            raise LookupError("No kept industry leads." if office.route == "B"
                              else "No kept grants.")
        with self.repo() as r:
            res = r.get(Researcher, b.researcher_id)
            items: list[tuple[Lead, Record | None]] = [
                (x, r.get(Opportunity if x.route == "A" else Organisation, x.record_id))
                for x in chosen]
            wids = list(dict.fromkeys(f"https://openalex.org/{c}" for x in chosen
                                      for c in x.cited_ids if c.startswith("W")))
            papers = [w for w in (r.get(Work, i) for i in wids) if w]
        if res is None and b.researcher_id == YOU:  # no public profile: the user signs it
            res = Researcher(id=YOU, source="user", source_url="perch://user",
                             fetched_at=now(), display_name="")
        if res is None:
            return None
        provider = (self._audited("handoff", spec or self.models.handoff_spec)
                    if use_model and chosen else None)
        store = current_store.get()
        docs = store.user_docs() if store is not None else []
        return draft_handoff(office, res, items, papers, provider, docs or None)

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

    def cancelled(self, b: Brief) -> bool:
        """True when the brief should stop before its next stage (the job's lease lost or
        cancelled)."""
        store = current_store.get()
        return bool(store is not None and store.cancelled())

    def run(self, brief_id: str) -> str:
        """Run the build; return the brief's final status (the job handler fails on 'failed')."""
        with self.repo() as r:
            b = r.get(Brief, brief_id)
        if b is None:
            return "missing"
        b.status = "running"
        store = current_store.get()
        # A brief that reads the user's own text never prints a traceback or an exception
        # message: either could quote that text (ARCHITECTURE_V1 3.7).
        quiet = self.quiet_errors or bool(store is not None and store.reads_user_data)
        names = [s.name for s in b.stages] or list(STAGES)  # a student brief has its own
        current = names[0]
        lock = threading.Lock()  # stage writes come from this thread and the background one
        side: list[threading.Thread] = []
        side_error: list[tuple[str, Exception]] = []

        def stage(name: str, status: str, detail: str | None = None) -> None:
            with lock:
                self._stage(b, name, status, detail)

        def step(name: str) -> None:
            detail, skipped = getattr(self, f"_run_{name}")(b)
            stage(name, "skipped" if skipped else "done", detail)

        def beside(name: str) -> None:
            try:
                step(name)
            except Exception as e:  # noqa: BLE001 - raised again by the job thread
                side_error.append((name, e))

        try:
            try:
                for current in names:
                    if self.cancelled(b):
                        raise Cancelled("Stopped: the brief was cancelled.")
                    stage(current, "running")
                    if current in BACKGROUND and current != names[-1]:
                        # copy_context: the side thread writes to the same brief store
                        t = threading.Thread(target=contextvars.copy_context().run,
                                             args=(beside, current), daemon=True,
                                             name=f"perch-{current}")
                        t.start()
                        side.append(t)
                    else:
                        step(current)
            finally:
                for t in side:
                    t.join()
            if side_error:
                current, err = side_error[0]
                raise err
            b.status = "done"
        except Exception as e:  # recorded on the brief; the job thread must not die silently
            b.error = (str(e) if isinstance(e, Cancelled) else plain_error(e)
                       if quiet else f"{type(e).__name__}: {e}")
            stage(current, "failed", b.error)
            b.status = "failed"
            if not quiet:
                traceback.print_exc()
        with self.repo() as r:
            r.upsert([b])
        self._ctx.pop(b.id, None)
        return b.status

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
            linked = aw.link_stored(res, [a for a in r.list(Award) if _temple(a)], ov)
            skipped = bool(linked)
            if not linked:
                with self.clients.nih() as nc, self.clients.nsf() as sc:
                    fetched, linked = aw.fetch_and_link(res, ov, nc, sc)
                r.upsert(fetched)
        summaries = aw.summarise(linked, res, ov)
        h = aw.award_horizon(summaries)
        b.award_ids = [s.key for s in summaries]
        b.award_horizon = h.end_date if h else None
        horizon = h.end_date.isoformat() if h and h.end_date else "none"
        return f"{len(summaries)} public awards; horizon {horizon}", skipped

    def _run_profile(self, b: Brief) -> tuple[str, bool]:
        as_of = date.fromisoformat(b.options["as_of"])
        with self.repo() as r:  # the author's public threads: 7-day shared cache when present
            p = precache.author_profile(self.public_cache, r, self.models.get("embedder"),
                                        b.researcher_id, as_of)
        store = current_store.get()
        docs = store.user_docs() if store is not None else []
        if docs:  # the account's own documents: query threads, never cached or cited as public
            from perch.threads import add_threads as add_user_threads

            p = add_user_threads(p, docs, self.models.get("embedder"))
        said = said_text(b.options)
        if said:  # normal-mode context: a query thread, never a citable record
            from perch.threads import add_threads

            p = add_threads(p, [Work(id=SAID_ID, source="user", source_url="perch://said",
                                     fetched_at=now(), title="You said", abstract=said)],
                            self.models.get("embedder"), share=SAID_SHARE)
        self._ctx.setdefault(b.id, {})["profile"] = p
        b.work_ids = p.work_ids
        b.threads = [{"index": t.index, "label": t.label, "weight": round(t.weight, 4),
                      "work_ids": t.work_ids, **({"said": True} if t.work_ids == [SAID_ID]
                                                 else {})} for t in p.threads]
        return f"{len(p.work_ids)} papers, {len(p.threads)} threads", False

    def _run_route_a(self, b: Brief) -> tuple[str, bool]:
        o = b.options
        as_of = date.fromisoformat(o["as_of"])
        store = current_store.get()
        cv = None  # the user's own CV, when the brief reads one: career stage and past sponsors
        if store is not None and (text := store.cv_text()):
            from perch.user.cv import parse_cv

            cv = parse_cv(text)
        esi = o.get("career_stage") == "early_stage" or bool(cv and cv.esi_possible(as_of))
        c = Constraints(as_of=as_of, min_amount=o.get("min_amount"),
                        agencies=o.get("agencies") or [],
                        exclude_keywords=o.get("exclude_keywords") or [], career_stage_ok=esi)
        with self.repo() as r:
            res = self._researcher(r, b)
            profile = self._ctx.get(b.id, {}).get("profile")
            brief = None
            if profile is not None and cv is None:  # a nightly pre-cache lets the first brief
                stored = precache.lookup(self.public_cache, r, profile)  # skip the rerank
                if stored:
                    brief = precache.route_a_from_precache(stored, res, profile, r, c,
                                                           o.get("top", 10))
            if brief is None:
                brief = route_a(res, r, self.models.get("index"), self.models.get("embedder"),
                                self.models.get("reranker"), c, RerankCache(self.rerank_cache),
                                top=o.get("top", 10), timings_log=self.timings_log,
                                profile=profile, index_new=self.index_new,
                                rerank_in=self.rerank_in())
            ranked = []
            for x in brief.leads:
                notes = []
                if esi and career_stage_restricted(x.opportunity):
                    notes.append(cv.esi_note() if cv else ESI_SAID)
                bonus = 0.0
                if cv and (k := sponsor_match(agency_text(x.opportunity), cv.sponsors)):
                    notes.append(f"Your CV lists a past award from {k}, so this sponsor's "
                                 "programme moved up.")
                    bonus = SPONSOR_BONUS
                ranked.append((x.rerank_score + bonus, x, notes))
            ranked.sort(key=lambda t: -t[0])
            # Match comes from the same adjusted score the order uses, so they agree.
            leads = [Lead(id=f"{b.id}:{i}", source=x.opportunity.source,
                          source_url=x.opportunity.source_url,
                          fetched_at=x.opportunity.fetched_at, brief_id=b.id, route="A",
                          record_id=x.opportunity.id, rank=i,
                          rerank_score=round(x.rerank_score, 4), match_score=match_score(adj),
                          matched_thread=x.candidate.best_thread, notes=notes)
                     for i, (adj, x, notes) in enumerate(ranked, 1)]
            r.upsert(leads)
        b.lead_ids = [x.id for x in leads]
        b.timings_ms = brief.timings_ms
        kept_by_stage = sum(any("early-stage" in n for n in x.notes) for x in leads)
        extra = f", {kept_by_stage} kept by the career-stage rule" if cv else ""
        return (f"{brief.retrieved} retrieved, {len(brief.rejected)} ineligible removed, "
                f"{len(leads)} leads{extra}"), False

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

    def _works(self, r: SQLiteRepository, b: Brief) -> dict[str, Work]:
        """Records the model skills may cite as research: the author's public papers, and
        the user's own documents when the brief reads them."""
        out = {w.id: w for w in r.works_by_author(b.researcher_id)}
        store = current_store.get()
        if store is not None:
            out.update({d.id: d for d in store.user_docs()})
        return out

    def rerank_in(self) -> int:
        """Candidates sent to the reranker: the profile's count on CPU, else the S27 default."""
        from perch.brief import RERANK_IN
        from perch.profiles import current

        p = current()
        return p.rerank_in if p.device else RERANK_IN

    def _text_cache(self, b: Brief) -> bool:
        """True when this brief's model text depends on public inputs only (section 5)."""
        p = self._ctx.get(b.id, {}).get("profile")
        store = current_store.get()
        return bool(self.public_cache is not None and p is not None
                    and precache.profile_is_public(p)
                    and is_public_input(InputContext(
                        reads_user_data=bool(store is not None and store.reads_user_data),
                        direction_text=bool(said_text(b.options)))))

    def _run_summary(self, b: Brief) -> tuple[str, bool]:
        if not b.options.get("explain"):
            return "explanations off", True
        profile = self._ctx[b.id]["profile"]
        spec = self.models.summary_spec or spec_for_role("profile_summary")
        key = cache_key("profile_summary", precache.public_profile_hash(profile),
                        summary_skill.PROMPT_VERSION, spec.partition(":")[2] or spec,
                        VALIDATOR_VERSION)
        use = self._text_cache(b)
        if use and (hit := self.public_cache.get("profile_summary", key)):  # type: ignore[union-attr]
            b.topics, b.summary = hit["topics"], hit["summary"]
            return "validated (cached)", False
        with self.repo() as r:
            works = self._works(r, b)
        v = summarise_profile(profile, works,
                              self._audited("profile_summary", self.models.summary_spec))
        if v.value:
            b.topics = [t for t, _ in v.value.topics]
            b.summary = v.value.summary
            if use:
                self.public_cache.put(  # type: ignore[union-attr]
                    "profile_summary", key, {"topics": b.topics, "summary": b.summary},
                    {"profile_hash": precache.public_profile_hash(profile),
                     "prompt_version": summary_skill.PROMPT_VERSION})
            return "validated", False
        return "withheld: failed validation twice", False

    def _run_explanations(self, b: Brief) -> tuple[str, bool]:
        if not b.options.get("explain"):
            return "explanations off", True
        with self.repo() as r:
            works = self._works(r, b)
            leads = [x for x in (r.get(Lead, i) for i in b.lead_ids) if x and x.route == "A"]
            opps = [r.get(Opportunity, x.record_id) for x in leads]
        profile = self._ctx[b.id]["profile"]
        spec = self.models.fit_spec or spec_for_role("fit_explainer")
        phash = precache.public_profile_hash(profile)
        use = self._text_cache(b)

        def fit_key(o: Opportunity) -> str:
            return cache_key("fit", o.id, o.fetched_at.isoformat(), phash,
                             fit_skill.PROMPT_VERSION, spec.partition(":")[2] or spec,
                             VALIDATOR_VERSION)

        lock = threading.Lock()
        store = current_store.get()  # the explanation callbacks run on pool threads
        todo: list[int] = []  # positions in `leads` that still need a model call
        done_cached = 0
        for i, (lead, o) in enumerate(zip(leads, opps, strict=True)):
            if o is None:
                continue
            hit = self.public_cache.get("fit", fit_key(o)) if use else None  # type: ignore[union-attr]
            if hit:
                with lock, self.repo() as r:
                    r.upsert([lead.model_copy(update=hit)])
                done_cached += 1
            else:
                todo.append(i)

        def save(j: int, v: Validated[Fit]) -> None:
            i = todo[j]
            lead = leads[i]
            if v.value:
                f = v.value
                upd = {"fit_score": f.fit, "inference": f.link_sentence or None,
                       "explanation": f"{f.opportunity_sentence} {f.research_sentence}",
                       "unsupported": f.unsupported, "cited_ids": f.cited_ids}
                o = opps[i]
                if use and o and not f.unsupported:  # only validated, fully grounded text
                    self.public_cache.put(  # type: ignore[union-attr]
                        "fit", fit_key(o), upd,
                        {"record_id": o.id, "profile_hash": phash,
                         "prompt_version": fit_skill.PROMPT_VERSION})
            else:
                upd = {"flagged": True}
            with using_store(store), lock, self.repo() as r:  # on a pool thread: no context
                r.upsert([lead.model_copy(update=upd)])

        results = []
        if todo:
            results = explain_leads([opps[i] for i in todo], profile, works,  # type: ignore[misc]
                                    self._audited("fit_explainer", self.models.fit_spec),
                                    grounder=self.models.get("grounder"), on_result=save)
        flagged = sum(v.flagged for v in results)
        unsupported = sum(bool(v.value and v.value.unsupported) for v in results)
        return (f"{len(results) - flagged + done_cached} explained ({done_cached} cached), "
                f"{flagged} withheld, {unsupported} with an unsupported statement"), False

    # --- student brief (moved from perch/private/session.py in S42) ---
    #
    # Inputs come from the brief's store: the signed-in user's own CV, interests and entries,
    # or a guest's SYNTHETIC persona (rule 12). Nothing here writes them anywhere.

    def _inputs(self):  # noqa: ANN202 - a perch.user.briefs.StudentInputs
        store = current_store.get()
        if store is None:
            raise InputProblem("A student brief needs an account or a sample persona.")
        try:
            return store.student_inputs()
        except ValueError as e:
            raise InputProblem("Add your CV first.") from e

    def _run_student_profile(self, b: Brief) -> tuple[str, bool]:
        from perch.student import achievement_docs, parse_student_cv, student_profile

        inp = self._inputs()
        logging.getLogger("perch.service").debug("cv text: %s", inp.cv)  # PLANTED LEAK
        facts = parse_student_cv(inp.cv)
        achieved = achievement_docs(inp.entries)
        if not inp.interests and not achieved:
            raise InputProblem("Add your interests or achievements too.")
        p = student_profile(facts, inp.interests, achieved, self.models.get("embedder"),
                            date.fromisoformat(b.options["as_of"]))
        self._ctx.setdefault(b.id, {}).update(profile=p, facts=facts, achieved=achieved,
                                              interests=inp.interests)
        b.threads = [{"index": t.index, "label": t.label, "weight": 1.0,
                      "work_ids": t.work_ids, "private": True} for t in p.threads]
        b.work_ids = p.work_ids
        return f"{facts.level or 'level not stated'}, {len(achieved)} achievements", False

    def _student_route(self, b: Brief, route: str, records: list,
                       nih: dict | None = None) -> tuple[list[Lead], int]:
        from perch.student import choose, judge_for, rank, to_leads

        ctx = self._ctx[b.id]
        as_of = date.fromisoformat(b.options["as_of"])
        nih = nih or {}
        scored = rank(records, ctx["profile"], self.models.get("embedder"),
                      self.models.get("reranker"),
                      judge_for(ctx["facts"], as_of, {k: o for k, (_, o) in nih.items()}))
        for x in scored:
            x.opp = nih[x.record.id][1] if x.record.id in nih else None
        chosen = choose(scored, b.options.get("top", 10))
        leads = to_leads(b.id, route, chosen, ctx["facts"])
        ok = sum(x.verdict.verdict != "not eligible" for x in chosen)
        return leads, ok

    def _run_fellowships(self, b: Brief) -> tuple[str, bool]:
        from perch.schemas import Scholarship
        from perch.student import nih_records

        with self.repo() as r:
            sdfa = [s for s in r.list(Scholarship) if not s.synthetic]
            nih = nih_records(r)
            leads, ok = self._student_route(b, "F", sdfa + [s for s, _ in nih.values()], nih)
            r.upsert(leads)
        b.lead_ids = [x.id for x in leads]
        return (f"{len(sdfa)} Temple-listed and {len(nih)} NIH fellowships searched, "
                f"{ok} you may apply for"), False

    def _run_scholarships(self, b: Brief) -> tuple[str, bool]:
        from perch.student import samples

        pool = samples()  # SYNTHETIC records, a list of their own (rule 11); read-only
        leads, ok = self._student_route(b, "S", pool)
        with self.repo() as r:
            r.upsert(leads)
        b.lead_ids = [*b.lead_ids, *(x.id for x in leads)]
        return f"{len(pool)} sample scholarships searched, {ok} you may apply for", False

    def _run_student_explanations(self, b: Brief) -> tuple[str, bool]:
        from perch.schemas import Scholarship
        from perch.student import as_opportunity

        if not b.options.get("explain"):
            return "explanations off", True
        ctx = self._ctx[b.id]
        works = {d.id: d for d in ctx["achieved"]}
        if ctx.get("interests"):
            works[ctx["interests"].id] = ctx["interests"]
        with self.repo() as r:
            leads = [x for x in (r.get(Lead, i) for i in b.lead_ids)
                     if x and x.verdict != "not eligible"]
            opps = [r.get(Opportunity, x.record_id)
                    or as_opportunity(r.get(Scholarship, x.record_id)) for x in leads]
        lock = threading.Lock()
        store = current_store.get()  # the explanation callbacks run on pool threads

        def save(i: int, v: Validated[Fit]) -> None:
            lead = leads[i]
            if v.value:
                f = v.value
                upd = {"fit_score": f.fit, "inference": f.link_sentence or None,
                       "explanation": f"{f.opportunity_sentence} {f.research_sentence}",
                       "unsupported": f.unsupported, "cited_ids": f.cited_ids}
            else:
                upd = {"flagged": True}
            with using_store(store), lock, self.repo() as r:  # on a pool thread: no context
                r.upsert([lead.model_copy(update=upd)])

        results = explain_leads(opps, ctx["profile"], works,
                                self._audited("fit_explainer", self.models.fit_spec),
                                grounder=self.models.get("grounder"), on_result=save,
                                audience="student")
        flagged = sum(v.flagged for v in results)
        return f"{len(results) - flagged} explained, {flagged} withheld", False


def said_text(options: dict) -> str:
    """The query text from the normal-mode direction and include keywords."""
    return " ".join(x for x in (options.get("direction") or "",
                                ", ".join(options.get("include_keywords") or [])) if x).strip()


def _temple(a: Award) -> bool:
    return "temple" in (a.institution or "").lower()


class InputProblem(ValueError):
    """A brief that cannot start for want of an input; the message is written by code."""


class Cancelled(Exception):
    """A brief stopped between stages; its message is written by code."""


def plain_error(e: Exception) -> str:
    """A stage failure in plain words, with the type for the operator; never the message,
    which could quote a visitor's text (S25 QA)."""
    name = type(e).__name__
    if name in ("ConnectError", "ConnectTimeout", "ReadTimeout", "TimeoutException",
                "RemoteProtocolError", "ReadError"):
        return f"A model server did not answer. Try again in a few minutes. ({name})"
    if isinstance(e, InputProblem):
        return str(e)  # written by code, never quotes the user's text
    return f"Something went wrong in this step. ({name})"


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
    if p.device in ("cpu", "cuda"):
        from perch.compute import (
            SlottedEmbedder,
            SlottedGrounder,
            SlottedReranker,
            configure_torch,
        )

        dev = p.device

        def cpu[T](build: Callable[[], T]) -> T:  # torch threads are set before the first model
            configure_torch()
            return build()

        # Each model runs inside a model slot (perch/compute.py: PERCH_MODEL_SLOTS), on CPU
        # for cloud-cpu and on the worker's one GPU for cloud-gpu.
        return Models(
            embedder=lambda: SlottedEmbedder(cpu(
                lambda: get_embedder(p.embedder, cache=emb_cache, device=dev))),
            reranker=lambda: SlottedReranker(cpu(
                lambda: make_reranker(p.reranker, device=dev))),
            index=lambda: LanceIndex(data_dir / "lance"),
            grounder=lambda: SlottedGrounder(cpu(lambda: make_grounder(p.grounder, device=dev))),
            summary_spec=llm, fit_spec=llm, handoff_spec=llm)
    return Models(embedder=lambda: get_embedder(p.embedder, cache=emb_cache),
                  reranker=lambda: make_reranker(p.reranker),
                  index=lambda: LanceIndex(data_dir / "lance"),
                  grounder=lambda: make_grounder(p.grounder), summary_spec=llm, fit_spec=llm,
                  handoff_spec=llm)

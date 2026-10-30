"""Private sessions: held in memory, isolated, capped, ended by the user or by idling.

A session owns its documents, a store overlay (every record a private brief or Scout
writes), its brief, and an egress Masker whose key is the only way back from a masked
export. `PrivateService` is the brief pipeline with every write path switched to the
session (docs/design/PRIVATE_MODE.md, "The no-logs inventory"):

- store: OverlayRepository (memory over a read-only base)
- embedding cache: read, never written; rerank cache: in memory
- model-call audit log, timings log, Scout log: none
- LanceDB: not indexed from a session
- errors: exception type only, no traceback
Every model, and every endpoint behind the embedder, reranker and grounder, must pass
the self-hosted gate (perch.privacy); otherwise the run fails with PermissionError.

Since S23 every brief is a session (private by default). Public records fetched for a
researcher are written through to the shared store (perch.private.store.is_public). A
session may turn Cloud on: then the three model skills (summary, fit, hand-off) use the
cloud spec, and the gate lets that one provider through for that session only. Cloud is
refused while the session holds documents, so private text stays on local models
(standing rule 1); the embedder, reranker, grounder and Scout always stay local.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from perch import egress
from perch.brief import route_a
from perch.eligibility import Constraints, career_stage_restricted
from perch.llm import Provider
from perch.llm.audit import AuditLog
from perch.privacy import PrivateSettings, refuse_endpoints, refuse_if_not_local
from perch.private.cv import CVFacts, parse_cv, sponsor_match
from perch.private.inputs import KINDS, PrivateDoc
from perch.private.store import OverlayRepository, ReadOnlyCacheEmbedder
from perch.private.threads import add_threads
from perch.schemas import Brief, Lead, Record, Researcher, Stage, Work, utcnow
from perch.service import SAID_ID, STAGES, BriefService, Models, brief_options

YOU = "private:you"  # the researcher of a brief with no public profile
IDLE_SECONDS = 30 * 60
MAX_SESSIONS = 200  # every visitor holds one since S23
MAX_TOTAL_CHARS = 200_000  # all documents of one session
BRIEFS_PER_SESSION = 10
SPONSOR_BONUS = 0.05  # added to the rerank score for a past sponsor; a default, not measured


class PrivateModels:
    """The shared models behind the gate. Built models are reused, never rebuilt.
    `cloud` says whether the session has Cloud on; only then do the skills' specs become
    the cloud spec, and only that spec passes the gate."""

    def __init__(self, base: Models, settings: PrivateSettings,
                 cloud: Callable[[], bool] = lambda: False) -> None:
        self.base, self.settings, self.cloud = base, settings, cloud

    def _spec(self, local: str | None) -> str | None:
        return self.settings.cloud_spec if self.cloud() and self.settings.cloud_spec else local

    @property
    def summary_spec(self) -> str | None:
        return self._spec(self.base.summary_spec)

    @property
    def fit_spec(self) -> str | None:
        return self._spec(self.base.fit_spec)

    @property
    def handoff_spec(self) -> str | None:
        return self._spec(self.base.handoff_spec)

    def get(self, name: str) -> object:
        x = self.base.get(name)
        refuse_endpoints(x, self.settings)
        return ReadOnlyCacheEmbedder(x) if name == "embedder" else x

    def provider(self, spec: str) -> Provider:
        p = self.base.provider(spec)
        if not (self.cloud() and spec == self.settings.cloud_spec):
            refuse_if_not_local(p, self.settings)
        return p


@dataclass
class PrivateSession:
    token: str
    last_used: float
    docs: dict[str, PrivateDoc] = field(default_factory=dict)
    mem: dict[tuple[str, str], Record] = field(default_factory=dict)
    brief_id: str | None = None
    briefs_run: int = 0
    masker: egress.Masker | None = None
    scout: object | None = None  # a ScoutHub of its own, made on first use
    lock: threading.Lock = field(default_factory=threading.Lock)
    service: PrivateService | None = None
    cloud: bool = False  # Cloud on: the skills use the cloud provider (S23)

    @property
    def cv(self) -> CVFacts | None:
        d = self.docs.get("cv")
        return parse_cv(d.abstract or "") if d else None

    def chars(self) -> int:
        return sum(len(d.abstract or "") for d in self.docs.values())

    def clear(self) -> None:
        self.docs.clear()
        self.mem.clear()
        self.masker = None
        self.scout = None
        self.brief_id = None
        self.cloud = False

    def make_masker(self, public_texts: list[str]) -> egress.Masker:
        cv = self.cv
        terms = {"PERSON": cv.names, "INSTITUTION": cv.institutions} if cv else {}
        self.masker = egress.Masker([d.abstract or "" for d in self.docs.values()],
                                    public_texts, terms)
        return self.masker


class PrivateService(BriefService):
    """The brief pipeline for one private session; see the module docstring."""

    def __init__(self, base: BriefService, session: PrivateSession,
                 settings: PrivateSettings) -> None:
        self.db, self.clients, self.overrides = base.db, base.clients, base.overrides
        self.models = PrivateModels(base.models, settings,  # type: ignore[assignment]
                                    lambda: session.cloud and not session.docs)
        self.settings = settings
        self.session = session
        self.audit = AuditLog(None)
        self.rerank_cache = ":memory:"  # type: ignore[assignment]
        self.timings_log = None  # type: ignore[assignment]
        self._ctx = {}
        self.quiet_errors = True
        self.index_writes = False

    def repo(self) -> OverlayRepository:  # type: ignore[override]
        return OverlayRepository(self.db, self.session.mem, self.settings.public_cache)

    # --- create ---

    def create_private(self, author_id: str | None, *, as_of: date | None = None,
                       top: int = 10, explain: bool = True, min_amount: float | None = None,
                       context: dict | None = None) -> Brief:
        from perch.sources import openalex as oa

        if author_id:
            aid = oa.parse_author_id(author_id)
            if not aid:
                raise ValueError("not an OpenAlex author id")
            rid = f"https://openalex.org/{aid}"
        else:
            rid = YOU
        bid = secrets.token_urlsafe(9)
        options = {**brief_options(as_of, top, explain, min_amount, context=context),
                   "private": True,
                   "documents": sorted(self.session.docs),
                   "models": "cloud" if self.models.cloud() else "local"}
        b = Brief(id=bid, source="private", source_url="private://session", fetched_at=utcnow(),
                  researcher_id=rid, stages=[Stage(name=n) for n in STAGES], options=options)
        with self.repo() as r:
            r.upsert([b])
        self.session.brief_id = bid
        return b

    def _alone(self, b: Brief) -> bool:
        return b.researcher_id == YOU

    # --- stages ---

    def _run_researcher(self, b: Brief) -> tuple[str, bool]:
        if self._alone(b):
            with self.repo() as r:
                r.upsert([Researcher(id=YOU, source="private", source_url="private://session",
                                     fetched_at=utcnow(), display_name="You (private)")])
            return "no public profile: private documents only", True
        return super()._run_researcher(b)

    def _run_works(self, b: Brief) -> tuple[str, bool]:
        if self._alone(b):
            return "no public papers", True
        return super()._run_works(b)

    def _run_awards(self, b: Brief) -> tuple[str, bool]:
        if self._alone(b):
            return "no public awards", True
        return super()._run_awards(b)

    def _run_profile(self, b: Brief) -> tuple[str, bool]:
        detail, _ = super()._run_profile(b)
        p = add_threads(self._ctx[b.id]["profile"], list(self.session.docs.values()),
                        self.models.get("embedder"))
        self._ctx[b.id]["profile"] = p
        b.threads = [{"index": t.index, "label": t.label, "weight": round(t.weight, 4),
                      "work_ids": t.work_ids,
                      "private": bool(t.work_ids) and egress.is_private_id(t.work_ids[0]),
                      **({"said": True} if t.work_ids == [SAID_ID] else {})}
                     for t in p.threads]
        added = sum(t["private"] for t in b.threads)
        return f"{detail}; {added} from your private documents", False

    def _run_route_a(self, b: Brief) -> tuple[str, bool]:
        o = b.options
        as_of = date.fromisoformat(o["as_of"])
        cv = self.session.cv
        esi = bool(cv and cv.esi_possible(as_of))
        c = Constraints(as_of=as_of, min_amount=o.get("min_amount"),
                        agencies=o.get("agencies") or [],
                        exclude_keywords=o.get("exclude_keywords") or [],
                        career_stage_ok=esi or o.get("career_stage") == "early_stage")
        with self.repo() as r:
            res = self._researcher(r, b)
            brief = route_a(res, r, self.models.get("index"), self.models.get("embedder"),
                            self.models.get("reranker"), c, None, top=o.get("top", 10),
                            timings_log=None, profile=self._ctx[b.id]["profile"],
                            index_new=False)
            ranked = []
            for x in brief.leads:
                notes = []
                if esi and career_stage_restricted(x.opportunity):
                    notes.append(cv.esi_note())
                bonus = 0.0
                if cv and (k := sponsor_match(x.opportunity.agency, cv.sponsors)):
                    notes.append(f"Your CV lists a past award from {k} (private), so this "
                                 "sponsor's programme moved up.")
                    bonus = SPONSOR_BONUS
                ranked.append((x.rerank_score + bonus, x, notes))
            ranked.sort(key=lambda t: -t[0])
            leads = [Lead(id=f"{b.id}:{i}", source=x.opportunity.source,
                          source_url=x.opportunity.source_url,
                          fetched_at=x.opportunity.fetched_at, brief_id=b.id, route="A",
                          record_id=x.opportunity.id, rank=i,
                          rerank_score=round(x.rerank_score, 4),
                          matched_thread=x.candidate.best_thread, notes=notes)
                     for i, (_, x, notes) in enumerate(ranked, 1)]
            r.upsert(leads)
        b.lead_ids = [x.id for x in leads]
        b.timings_ms = brief.timings_ms
        unlocked = sum(any("early-stage" in n for n in x.notes) for x in leads)
        return (f"{brief.retrieved} retrieved, {len(brief.rejected)} ineligible removed, "
                f"{len(leads)} leads, {unlocked} kept by the career-stage rule"), False

    def _run_route_b(self, b: Brief) -> tuple[str, bool]:
        if self._alone(b):
            return "needs public papers", True
        return super()._run_route_b(b)

    def _works(self, r: OverlayRepository, b: Brief) -> dict[str, Work]:  # type: ignore[override]
        out = {} if self._alone(b) else super()._works(r, b)
        ach = self.session.docs.get("achievements")
        if ach and b.options.get("student"):
            from perch.private.student import achievement_docs

            out.update({d.id: d for d in achievement_docs(ach.abstract or "")})
        return {**out, **{d.id: d for d in self.session.docs.values()}}

    # --- student brief (S18, perch/private/student.py) ---

    def create_student(self, *, as_of: date | None = None, top: int = 10,
                       explain: bool = True) -> Brief:
        from perch.private.student import STUDENT_STAGES

        if "cv" not in self.session.docs:
            raise ValueError("student mode needs a CV")
        bid = secrets.token_urlsafe(9)
        options = {**brief_options(as_of, top, explain), "private": True, "student": True,
                   "documents": sorted(self.session.docs)}
        b = Brief(id=bid, source="private", source_url="private://session", fetched_at=utcnow(),
                  researcher_id=YOU, stages=[Stage(name=n) for n in STUDENT_STAGES],
                  options=options)
        with self.repo() as r:
            r.upsert([b, Researcher(id=YOU, source="private", source_url="private://session",
                                    fetched_at=utcnow(), display_name="You (private)")])
        self.session.brief_id = bid
        return b

    def _student_docs(self) -> tuple[PrivateDoc | None, list[PrivateDoc]]:
        from perch.private.student import achievement_docs

        ach = self.session.docs.get("achievements")
        return (self.session.docs.get("interests"),
                achievement_docs(ach.abstract or "") if ach else [])

    def _run_student_profile(self, b: Brief) -> tuple[str, bool]:
        from perch.private.student import student_profile
        from perch.student import parse_student_cv

        facts = parse_student_cv(self.session.docs["cv"].abstract or "")
        interests, achieved = self._student_docs()
        if not interests and not achieved:
            raise ValueError("add your interests or achievements")
        p = student_profile(facts, interests, achieved, self.models.get("embedder"),
                            date.fromisoformat(b.options["as_of"]))
        self._ctx.setdefault(b.id, {}).update(profile=p, facts=facts, achieved=achieved)
        b.threads = [{"index": t.index, "label": t.label, "weight": 1.0,
                      "work_ids": t.work_ids, "private": True} for t in p.threads]
        b.work_ids = p.work_ids
        return (f"{facts.level or 'level not stated'}, {len(achieved)} achievements"), False

    def _student_route(self, b: Brief, route: str, records: list,
                       nih: dict | None = None) -> tuple[list[Lead], int]:
        from perch.private.student import choose, judge_for, rank, to_leads

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
        from perch.private.student import nih_records
        from perch.schemas import Scholarship

        with self.repo() as r:
            sdfa = [s for s in r.list(Scholarship) if not s.synthetic]
            nih = nih_records(r)
            leads, ok = self._student_route(b, "F", sdfa + [s for s, _ in nih.values()], nih)
            r.upsert(leads)
        b.lead_ids = [x.id for x in leads]
        return (f"{len(sdfa)} Temple-listed and {len(nih)} NIH fellowships searched, "
                f"{ok} you may apply for"), False

    def _run_scholarships(self, b: Brief) -> tuple[str, bool]:
        from perch.private.student import samples

        pool = samples()
        leads, ok = self._student_route(b, "S", pool)
        chosen = {x.record_id for x in leads}
        with self.repo() as r:  # the shown sample records, in this session's memory only
            r.upsert([s for s in pool if s.id in chosen] + leads)
        b.lead_ids = [*b.lead_ids, *(x.id for x in leads)]
        return f"{len(pool)} sample scholarships searched, {ok} you may apply for", False

    def _run_student_explanations(self, b: Brief) -> tuple[str, bool]:
        import threading as th

        from perch.private.student import as_opportunity
        from perch.schemas import Opportunity, Scholarship
        from perch.skills.fit import explain_leads

        if not b.options.get("explain"):
            return "explanations off", True
        ctx = self._ctx[b.id]
        works = {d.id: d for d in ctx["achieved"]}
        if d := self.session.docs.get("interests"):
            works[d.id] = d
        with self.repo() as r:
            leads = [x for x in (r.get(Lead, i) for i in b.lead_ids)
                     if x and x.verdict != "not eligible"]
            opps = [r.get(Opportunity, x.record_id)
                    or as_opportunity(r.get(Scholarship, x.record_id)) for x in leads]
        lock = th.Lock()

        def save(i: int, v: object) -> None:
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

        results = explain_leads(opps, ctx["profile"], works,
                                self._audited("fit_explainer", self.models.fit_spec),
                                grounder=self.models.get("grounder"), on_result=save,
                                audience="student")
        flagged = sum(v.flagged for v in results)
        return f"{len(results) - flagged} explained, {flagged} withheld", False

    def private_records(self) -> dict[str, PrivateDoc]:
        return {d.id: d for d in self.session.docs.values()}


class PrivateSessions:
    """Every open session, by token. Expired ones are dropped on each access."""

    def __init__(self, base: BriefService, settings: PrivateSettings,
                 clock: Callable[[], float] = time.monotonic, idle: float = IDLE_SECONDS,
                 max_sessions: int = MAX_SESSIONS) -> None:
        self.base, self.settings, self.clock = base, settings, clock
        self.idle, self.max_sessions = idle, max_sessions
        self.sessions: dict[str, PrivateSession] = {}
        self.lock = threading.Lock()

    def _sweep(self) -> None:
        now = self.clock()
        for t in [t for t, s in self.sessions.items() if now - s.last_used > self.idle]:
            self.sessions.pop(t).clear()

    def check_models(self) -> None:
        """PermissionError unless every chat model a session may call is self-hosted on an
        allowed endpoint. Checked when a session opens, and again on every call."""
        from perch.llm import spec_for_role

        m = self.base.models
        for spec, role in ((m.summary_spec, "profile_summary"), (m.fit_spec, "fit_explainer"),
                           (m.handoff_spec, "handoff"), (None, "scout")):
            refuse_if_not_local(m.provider(spec or spec_for_role(role)), self.settings)

    def open(self) -> PrivateSession:
        self.check_models()
        with self.lock:
            self._sweep()
            if len(self.sessions) >= self.max_sessions:
                raise OverflowError("too many private sessions are open; try again later")
            s = PrivateSession(secrets.token_urlsafe(32), self.clock())
            s.service = PrivateService(self.base, s, self.settings)
            self.sessions[s.token] = s
            return s

    def get(self, token: str | None) -> PrivateSession | None:
        with self.lock:
            self._sweep()
            s = self.sessions.get(token or "")
            if s:
                s.last_used = self.clock()
            return s

    def end(self, token: str | None) -> bool:
        with self.lock:
            s = self.sessions.pop(token or "", None)
        if s:
            s.clear()
        return s is not None


def add_document(s: PrivateSession, doc: PrivateDoc) -> None:
    from perch.private.inputs import InputError

    kind = doc.id.split(":", 1)[1]
    others = sum(len(d.abstract or "") for k, d in s.docs.items() if k != kind)
    if others + len(doc.abstract or "") > MAX_TOTAL_CHARS:
        raise InputError(f"a session holds at most {MAX_TOTAL_CHARS:,} characters in all")
    s.docs[kind] = doc


__all__ = ["KINDS", "PrivateService", "PrivateSession", "PrivateSessions", "add_document"]

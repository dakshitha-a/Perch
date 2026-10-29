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
from perch.service import STAGES, BriefService, Models, brief_options

YOU = "private:you"  # the researcher of a brief with no public profile
IDLE_SECONDS = 30 * 60
MAX_SESSIONS = 20
MAX_TOTAL_CHARS = 200_000  # all documents of one session
BRIEFS_PER_SESSION = 10
SPONSOR_BONUS = 0.05  # added to the rerank score for a past sponsor; a default, not measured


class PrivateModels:
    """The shared models behind the gate. Built models are reused, never rebuilt."""

    def __init__(self, base: Models, settings: PrivateSettings) -> None:
        self.base, self.settings = base, settings
        self.summary_spec, self.fit_spec = base.summary_spec, base.fit_spec
        self.handoff_spec = base.handoff_spec

    def get(self, name: str) -> object:
        x = self.base.get(name)
        refuse_endpoints(x, self.settings)
        return ReadOnlyCacheEmbedder(x) if name == "embedder" else x

    def provider(self, spec: str) -> Provider:
        p = self.base.provider(spec)
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
        self.models = PrivateModels(base.models, settings)  # type: ignore[assignment]
        self.settings = settings
        self.session = session
        self.audit = AuditLog(None)
        self.rerank_cache = ":memory:"  # type: ignore[assignment]
        self.timings_log = None  # type: ignore[assignment]
        self._ctx = {}
        self.quiet_errors = True
        self.index_writes = False

    def repo(self) -> OverlayRepository:  # type: ignore[override]
        return OverlayRepository(self.db, self.session.mem)

    # --- create ---

    def create_private(self, author_id: str | None, *, as_of: date | None = None,
                       top: int = 10, explain: bool = True) -> Brief:
        from perch.sources import openalex as oa

        if author_id:
            aid = oa.parse_author_id(author_id)
            if not aid:
                raise ValueError("not an OpenAlex author id")
            rid = f"https://openalex.org/{aid}"
        else:
            rid = YOU
        bid = secrets.token_urlsafe(9)
        options = {**brief_options(as_of, top, explain), "private": True,
                   "documents": sorted(self.session.docs)}
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
                      "private": bool(t.work_ids) and egress.is_private_id(t.work_ids[0])}
                     for t in p.threads]
        added = sum(t["private"] for t in b.threads)
        return f"{detail}; {added} from your private documents", False

    def _run_route_a(self, b: Brief) -> tuple[str, bool]:
        o = b.options
        as_of = date.fromisoformat(o["as_of"])
        cv = self.session.cv
        esi = bool(cv and cv.esi_possible(as_of))
        c = Constraints(as_of=as_of, min_amount=o.get("min_amount"),
                        agencies=o.get("agencies") or [], career_stage_ok=esi)
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
        return {**out, **{d.id: d for d in self.session.docs.values()}}

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

    def open(self) -> PrivateSession:
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

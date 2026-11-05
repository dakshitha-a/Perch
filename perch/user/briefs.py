"""Where a brief lives (ARCHITECTURE_V1 sections 2.2, 3 and 7.4).

* Signed-in user: one encrypted `user_data` row of kind `brief` holding the Brief and its Leads.
  The row id is the brief id. It is written at creation and at every stage (partial saves).
* Guest: in Redis, sealed with AES-GCM under a random key of the guest session
  (`perch:gsess:<gsid_hash>:bkey`; S49 Q50). State before the job runs sits at
  `perch:gsess:<gsid_hash>:brief:<id>` and the result at `perch:gres:<job_id>`, one hour TTL.
  Nothing in Postgres but the `jobs` row.
* Fallback profiles and tests: no store; `BriefService` keeps using its SQLite repository.

`BriefService.repo()` asks `current_store` for a store and, when there is one, returns an
overlay repository: Brief and Lead reads and writes go to the store, every other kind goes to
the public repository underneath. Nothing user-derived reaches `public_cache`: a store that
`reads_user_data` makes `BriefService._text_cache` return False (perch/cache.py is_public_input).
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import psycopg
import redis

from perch.config import env
from perch.schemas import Brief, Lead, Record, Work
from perch.store.base import Facets, Page, R, Repository
from perch.user.data import NotFound, UserData
from perch.user.inputs import make_doc
from perch.user.models import Audience, CvDoc, EntryDoc, StoredBrief, UserDoc

if TYPE_CHECKING:
    from perch.auth.session import Session
    from perch.jobs import JobContext, JobRunner
    from perch.service import BriefService

GRES_TTL_S = 3600
WRITE_TRIES = 5  # a stale brief write re-reads the user's lead statuses and tries again
GUEST_TTL_DEFAULT_S = 3600

current_store: ContextVar[BriefStore | None] = ContextVar("perch_brief_store", default=None)


@contextmanager
def using_store(store: BriefStore | None) -> Iterator[None]:
    tok = current_store.set(store)
    try:
        yield
    finally:
        current_store.reset(tok)


@dataclass
class StudentInputs:
    """What a student brief reads: the CV text, the interests note and the achievements (one
    text each). Held only for the length of the job; never written anywhere in plain text."""

    cv: str
    interests: UserDoc | None = None
    entries: list[str] = field(default_factory=list)


PERSONAS = {"persona-ug": "SYNTHETIC persona-ug"}  # the guest's student sample (ARCH 7.4)
SYNTHETIC_DIR = Path(__file__).resolve().parents[2] / "data/synthetic"


def persona_inputs(name: str) -> StudentInputs:
    """The SYNTHETIC student persona's CV, interests and achievements (rule 12). Only the
    names in PERSONAS are read."""
    from perch.student import achievements

    if name not in PERSONAS:
        raise LookupError("unknown sample persona")
    d = SYNTHETIC_DIR / name
    return StudentInputs(cv=(d / "cv.md").read_text(encoding="utf-8"),
                         interests=make_doc("interests",
                                            (d / "interests.md").read_text(encoding="utf-8")),
                         entries=achievements((d / "achievements.md").read_text(
                             encoding="utf-8")))


class BriefStore(ABC):
    """Holds one brief and its leads in memory and writes them through on each change."""

    reads_user_data = False  # True when the brief reads a CV, entries or documents

    def __init__(self, brief_id: str) -> None:
        self.brief_id = brief_id
        self.brief: Brief | None = None
        self.leads: dict[str, Lead] = {}
        self._lock = threading.RLock()
        # Lead id -> (record id, status) as last read from storage. A lead's status is the
        # user's (keep, dismiss, restore on the web); the job never sets one, so every write
        # carries the stored status over to the lead with the same id and record (S49 B2).
        self._status: dict[str, tuple[str, str]] = {}

    @property
    @abstractmethod
    def result_ref(self) -> str: ...

    @abstractmethod
    def load(self) -> bool:
        """Read the stored state. False when nothing is stored yet."""

    @abstractmethod
    def _write(self, sb: StoredBrief) -> None: ...

    def cancelled(self) -> bool:
        return False

    def retry_left(self) -> bool:
        """True when this brief runs in a job that has another attempt (S49 B8)."""
        ctx = getattr(self, "ctx", None)
        return bool(ctx is not None and ctx.attempt < ctx.max_attempts)

    def user_docs(self) -> list[Work]:
        """User documents (CV text excluded) that become query threads. Empty for guests."""
        return []

    def cv_text(self) -> str | None:
        """The CV the brief reads, for the researcher's career-stage and sponsor rules."""
        return None

    def student_inputs(self) -> StudentInputs:
        """The CV, interests and achievements a student brief reads."""
        raise LookupError("this brief has no student inputs")

    def flush(self) -> None:
        with self._lock:
            if self.brief is None:
                return
            self._write(StoredBrief(brief=self.brief, leads=list(self.leads.values())))

    def _remember(self, leads: Iterable[Lead]) -> None:
        self._status = {x.id: (x.record_id, x.status) for x in leads}

    def _keep_statuses(self, sb: StoredBrief) -> StoredBrief:
        """`sb` with the stored statuses on its leads (the in-memory leads take them too)."""
        out = []
        for x in sb.leads:
            got = self._status.get(x.id)
            if got is not None and got[0] == x.record_id and got[1] != x.status:
                x = x.model_copy(update={"status": got[1]})
                self.leads[x.id] = x
            out.append(x)
        return StoredBrief(brief=sb.brief, leads=out)

    def wrap(self, base: Repository) -> Repository:
        return StoreRepository(base, self)

    def view(self) -> tuple[Brief, list[Lead]] | None:
        with self._lock:
            if self.brief is None:
                return None
            by_id = self.leads
            return self.brief, [by_id[i] for i in self.brief.lead_ids if i in by_id]


def _sample(record_id: str) -> Record | None:
    """A SYNTHETIC sample scholarship by id, read from the sample store (rule 11). A student
    brief's sample leads point at these; they are never written to the public store."""
    from perch.scholarships import sample_db

    p = sample_db()
    return _sample_map(str(p), p.stat().st_mtime_ns if p.exists() else 0).get(record_id)


@lru_cache(maxsize=4)
def _sample_map(path: str, mtime_ns: int) -> dict[str, Record]:  # noqa: ARG001 - cache key
    from perch.student import samples

    return {s.id: s for s in samples()} if mtime_ns else {}


class StoreRepository(Repository):
    """Brief and Lead go to the store; everything else is the public repository's."""

    def __init__(self, base: Repository, store: BriefStore) -> None:
        self.base, self.store = base, store

    def upsert(self, records: Iterable[Record]) -> int:
        n, touched, rest = 0, False, []
        with self.store._lock:
            for r in records:
                if isinstance(r, Brief):
                    self.store.brief = r
                    touched = True
                elif isinstance(r, Lead):
                    self.store.leads[r.id] = r
                    touched = True
                else:
                    rest.append(r)
                    continue
                n += 1
            if touched:
                self.store.flush()
        if rest:
            n += self.base.upsert(rest)
        return n

    def get(self, cls: type[R], id: str) -> R | None:
        with self.store._lock:
            if cls is Brief:
                b = self.store.brief
                return b if b is not None and b.id == id else None  # type: ignore[return-value]
            if cls is Lead:
                return self.store.leads.get(id)  # type: ignore[return-value]
        got = self.base.get(cls, id)
        if got is None and id.startswith("sample:") and cls.kind == "scholarship":
            return _sample(id)  # type: ignore[return-value]
        return got

    def list(self, cls: type[R], *, include_samples: bool = False) -> list[R]:
        with self.store._lock:
            if cls is Brief:
                return [self.store.brief] if self.store.brief else []  # type: ignore[list-item]
            if cls is Lead:
                return sorted(self.store.leads.values(), key=lambda x: x.id)  # type: ignore[return-value]
        return self.base.list(cls, include_samples=include_samples)

    def get_any(self, id: str) -> Record | None:
        with self.store._lock:
            if self.store.brief is not None and self.store.brief.id == id:
                return self.store.brief
            if id in self.store.leads:
                return self.store.leads[id]
        return self.base.get_any(id) or (_sample(id) if id.startswith("sample:") else None)

    def works_by_author(self, author_id: str) -> list[Work]:
        return self.base.works_by_author(author_id)

    def browse(self, cls: type[R], *, temple_only: bool = False, schools: Sequence[str] = (),
               audience_level: Sequence[str] = (), q: str | None = None,
               closes_after: date | None = None, limit: int = 50,
               cursor: str | None = None, scopes: Sequence[str] = (),
               exclude_schools: Sequence[str] = (), **more: object) -> Page[R]:
        # S49: sort, open_only and today pass through to the base store unchanged.
        return self.base.browse(cls, temple_only=temple_only, schools=schools,
                                audience_level=audience_level, q=q, closes_after=closes_after,
                                limit=limit, cursor=cursor, scopes=scopes,
                                exclude_schools=exclude_schools, **more)

    def facets(self, cls: type[R]) -> Facets:
        return self.base.facets(cls)

    def epoch(self) -> int:
        return self.base.epoch()

    def bump_epoch(self) -> int:
        return self.base.bump_epoch()

    def close(self) -> None:
        self.base.close()


# --- signed-in user: one encrypted user_data row ---

class UserBriefStore(BriefStore):
    def __init__(self, ud: UserData, user_id: UUID, audience: Audience, brief_id: str, *,
                 ctx: JobContext | None = None, reads_user_data: bool = False) -> None:
        super().__init__(brief_id)
        self.ud, self.user_id, self.audience = ud, user_id, audience
        self.ctx = ctx  # a jobs.JobContext in the worker: writes then run lease-fenced
        self.row_id = UUID(brief_id)
        self._ts: datetime | None = None
        self.reads_user_data = reads_user_data
        self._doc_ids: list[UUID] = []

    @property
    def result_ref(self) -> str:
        return f"user_data:{self.row_id}"

    @contextmanager
    def _conn(self) -> Iterator[psycopg.Connection | None]:
        if self.ctx is not None:
            with self.ctx.user_tx() as c:
                yield c
        else:
            yield None

    def load(self) -> bool:
        with self._conn() as c:
            got = self.ud.get_row(self.user_id, self.row_id, StoredBrief, conn=c, kind="brief")
        if got is None:
            return False
        sb, self._ts = got[0], got[1]
        self.brief = sb.brief
        self.leads = {x.id: x for x in sb.leads}
        self._remember(sb.leads)
        self._doc_ids = [UUID(i) for i in sb.brief.options.get("user_data") or []]
        self.reads_user_data = bool(self._doc_ids) or bool(sb.brief.options.get("student"))
        return True

    def _write(self, sb: StoredBrief) -> None:
        from perch.user.data import Conflict

        if self._ts is None:
            with self._conn() as c:
                self.ud.put(self.user_id, "brief", self.audience, sb, row_id=self.row_id, conn=c)
                got = self.ud.get_row(self.user_id, self.row_id, StoredBrief, conn=c,
                                      kind="brief")
            self._ts = got[1] if got else None
            self._remember(sb.leads)
            return
        for _ in range(WRITE_TRIES):
            with self._conn() as c:
                out = self._keep_statuses(sb)
                try:
                    self._ts = self.ud.update(self.user_id, self.row_id, out,
                                              expect_updated_at=self._ts, conn=c)
                    self._remember(out.leads)
                    return
                except Conflict:  # the user kept or dismissed a lead meanwhile: take theirs
                    pass
            with self._conn() as c:
                got = self.ud.get_row(self.user_id, self.row_id, StoredBrief, conn=c,
                                      kind="brief")
            if got is None:
                raise Conflict("the brief is gone")
            self._ts = got[1]
            self._remember(got[0].leads)
        raise Conflict("the brief kept changing")

    def cancelled(self) -> bool:
        return bool(self.ctx is not None and self.ctx.cancelled())

    @property
    def needs_consent(self) -> bool:
        """True when this brief hands the user's own text to a model: documents or a typed
        direction. The job checks the consent row before it reads either (section 7.5)."""
        o = self.brief.options if self.brief is not None else {}
        return bool(self._doc_ids or o.get("student") or (o.get("direction") or "").strip())

    def user_docs(self) -> list[Work]:
        """The documents of kind proposal, direction and manuscript this brief reads, as Works
        for `add_threads`. A CV or entry row in the ids is skipped here: those feed the
        student rules, not the query threads."""
        out: list[Work] = []
        for rid in self._doc_ids:
            with self._conn() as c:
                try:
                    got = self.ud.get(self.user_id, rid, UserDoc, conn=c)
                except Exception:  # noqa: BLE001 - a row of another model is not a doc
                    got = None
            if got is not None:
                out.append(got)
        return out


    def cv_text(self) -> str | None:
        for rid in self._doc_ids:
            with self._conn() as c:
                try:
                    got = self.ud.get(self.user_id, rid, CvDoc, conn=c)
                except Exception:  # noqa: BLE001 - a row of another model is not the CV
                    got = None
            if got is not None:
                return got.text
        return None

    def student_inputs(self) -> StudentInputs:
        """The side's CV, its interests note and its entries (oldest first, so entry A is
        the first one the student added). Read inside the job's transaction."""
        with self._conn() as c:
            cvs = self.ud.list(self.user_id, "cv", self.audience, CvDoc, limit=1, conn=c)
            docs = self.ud.list(self.user_id, "doc", self.audience, UserDoc, limit=50, conn=c)
            entries = self.ud.list(self.user_id, "entry", self.audience, EntryDoc, limit=50,
                                   conn=c)
        if not cvs:
            raise ValueError("student mode needs a CV")
        interests = next((d for _, d in docs if d.id == "user:interests"), None)
        return StudentInputs(cv=cvs[0][1].text, interests=interests,
                             entries=[e.text for _, e in reversed(entries)])


class MemoryBriefStore(BriefStore):
    """Holds the brief in memory and the user's inputs as given: for tests and the student
    bench, which run the pipeline in one process without accounts. Nothing is written."""

    reads_user_data = True

    def __init__(self, brief_id: str = "mem", *, cv: str | None = None,
                 docs: list[Work] | None = None, student: StudentInputs | None = None) -> None:
        super().__init__(brief_id)
        self.cv, self.docs, self.student = cv, docs or [], student

    @property
    def result_ref(self) -> str:
        return "memory"

    def load(self) -> bool:
        return True

    def _write(self, sb: StoredBrief) -> None:
        pass

    def user_docs(self) -> list[Work]:
        return list(self.docs)

    def cv_text(self) -> str | None:
        return self.cv

    def student_inputs(self) -> StudentInputs:
        if self.student is None:
            raise ValueError("no student inputs")
        return self.student


# --- guest: Redis, public inputs only ---

SEALED = "g1:"  # prefix of a sealed guest brief value (S49 Q50)


def _guest_key_name(gh: str) -> str:
    return f"perch:gsess:{gh}:bkey"


def _guest_key(r: redis.Redis, gh: str, *, create: bool = False) -> bytes | None:
    """The guest session's own random brief key (32 bytes, base64 in Redis). The worker knows
    only the session hash, so the key sits beside the briefs under that hash; it lives as long
    as the longest brief value, and a dump of the brief values alone reads nothing."""
    import base64
    import secrets

    name = _guest_key_name(gh)
    if create:
        life = max(int(env("PERCH_GUEST_TTL_S", str(GUEST_TTL_DEFAULT_S))
                       or GUEST_TTL_DEFAULT_S), GRES_TTL_S) + 300
        r.set(name, base64.b64encode(secrets.token_bytes(32)).decode(), nx=True, ex=life)
        r.expire(name, life)
    got = r.get(name)
    if not got:
        return None
    return base64.b64decode(got if isinstance(got, bytes) else got.encode())


def seal_guest(r: redis.Redis, gh: str, slot: str, sb: StoredBrief) -> str:
    """AES-GCM under the session's brief key, bound to the Redis key it is written to."""
    import base64
    import secrets

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _guest_key(r, gh, create=True)
    assert key is not None
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, sb.model_dump_json().encode(), slot.encode())
    return SEALED + base64.b64encode(nonce + ct).decode()


def open_guest(r: redis.Redis, gh: str, slot: str, raw: str | bytes | None
               ) -> StoredBrief | None:
    """The brief in a sealed value, or None when it is missing or cannot be opened (its key
    expired). A plain JSON value written before S49 is still read for its last hour."""
    import base64

    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not raw:
        return None
    text = raw.decode() if isinstance(raw, bytes) else raw
    if not text.startswith(SEALED):
        return StoredBrief.model_validate_json(text)
    key = _guest_key(r, gh)
    if key is None:
        return None
    blob = base64.b64decode(text[len(SEALED):])
    try:
        plain = AESGCM(key).decrypt(blob[:12], blob[12:], slot.encode())
    except InvalidTag:
        return None
    return StoredBrief.model_validate_json(plain)


class GuestBriefStore(BriefStore):
    """No CV, no entries, no rows in Postgres. `job_id` is known in the worker; at creation the
    state goes to the session key, and from the first worker write on to `perch:gres:<job_id>`."""

    def __init__(self, r: redis.Redis, gsid_hash: str, brief_id: str, job_id: UUID | None = None,
                 *, ctx: JobContext | None = None) -> None:
        super().__init__(brief_id)
        self.r, self.gsid_hash, self.job_id = r, gsid_hash, job_id
        self.ctx = ctx  # the worker's job: writes stop once the lease is lost (S49 B6)

    def cancelled(self) -> bool:
        return bool(self.ctx is not None and self.ctx.cancelled())

    def student_inputs(self) -> StudentInputs:
        """A guest has no CV: the student brief reads the SYNTHETIC persona named in its
        options (rule 12), and the brief carries the sample label."""
        name = (self.brief.options.get("persona") if self.brief else None) or ""
        return persona_inputs(name)

    @property
    def state_key(self) -> str:
        return f"perch:gsess:{self.gsid_hash}:brief:{self.brief_id}"

    @property
    def result_key(self) -> str:
        return f"perch:gres:{self.job_id}"

    @property
    def result_ref(self) -> str:
        return f"redis:{self.result_key}"

    def load(self) -> bool:
        sb = None
        for slot in ([self.result_key] if self.job_id else []) + [self.state_key]:
            sb = open_guest(self.r, self.gsid_hash, slot, self.r.get(slot))
            if sb is not None:
                break
        if sb is None:
            return False
        self.brief = sb.brief
        self.leads = {x.id: x for x in sb.leads}
        self._remember(sb.leads)
        return True

    def _write(self, sb: StoredBrief) -> None:
        """Read, merge the guest's lead statuses, write: in one WATCH transaction, so a keep
        made while the job runs is never overwritten (S49 B2)."""
        if self.job_id is None:
            key = self.state_key
            ex = int(env("PERCH_GUEST_TTL_S", str(GUEST_TTL_DEFAULT_S)) or GUEST_TTL_DEFAULT_S)
        else:
            key, ex = self.result_key, GRES_TTL_S
        watched = [key] if key == self.state_key else [key, self.state_key]
        if self.ctx is not None:  # raises LeaseLost once the job timed out or was taken over
            with self.ctx.guest_tx():
                pass
        with self.r.pipeline() as p:
            for _ in range(WRITE_TRIES):
                try:
                    p.watch(*watched)
                    stored = next((x for x in (open_guest(self.r, self.gsid_hash, k, p.get(k))
                                               for k in watched) if x), None)
                    if stored is not None:
                        self._remember(stored.leads)
                    out = self._keep_statuses(sb)
                    sealed = seal_guest(self.r, self.gsid_hash, key, out)
                    p.multi()
                    p.set(key, sealed, ex=ex)
                    p.execute()
                    self._remember(out.leads)
                    return
                except redis.WatchError:
                    continue
        raise RuntimeError("the guest brief kept changing")


def read_guest_result(r: redis.Redis, job_id: UUID | str, gh: str) -> StoredBrief | None:
    """The guest brief a job wrote, or None after the hour is up."""
    slot = f"perch:gres:{job_id}"
    return open_guest(r, gh, slot, r.get(slot))


# --- creation and the job's store ---

def create_user_brief(svc: BriefService, ud: UserData, user_id: UUID, audience: Audience,
                      author_id: str | None, *, doc_ids: Sequence[UUID] = (), **options: object
                      ) -> Brief:
    """Create the brief row (status queued). Its id is the user_data row id; the job payload
    carries that id and nothing else. `doc_ids` are the user_data rows of the documents the
    brief reads: ids only go into the options, and a brief that reads any is user-derived."""
    import uuid

    bid = str(uuid.uuid4())
    if doc_ids:
        ctx = {**(options.pop("context", None) or {}), "user_data": [str(i) for i in doc_ids]}
        options["context"] = ctx
    student = audience == "student"  # a student brief always reads the CV and entries
    store = UserBriefStore(ud, user_id, audience, bid, reads_user_data=bool(doc_ids) or student)
    with using_store(store):
        return svc.create(author_id, brief_id=bid, audience=audience, **options)


def create_guest_brief(svc: BriefService, r: redis.Redis, gsid_hash: str, author_id: str | None,
                       *, audience: Audience = "researcher", **options: object) -> Brief:
    """A guest's student brief reads the SYNTHETIC persona-ug sample (rule 12) and says so in
    its options; a guest's researcher brief reads a public author only."""
    import secrets

    bid = secrets.token_urlsafe(9)
    if audience == "student":
        options["extra"] = {"persona": "persona-ug", "sample": PERSONAS["persona-ug"]}
    with using_store(GuestBriefStore(r, gsid_hash, bid)):
        return svc.create(author_id, brief_id=bid, audience=audience, **options)


def store_for_job(ctx: JobContext, ud: UserData | None = None, r: redis.Redis | None = None
                  ) -> BriefStore | None:
    """The store a `brief` job writes to: user_data for a signed-in job, Redis for a guest job,
    None for an ownerless job, which the handler refuses."""
    brief_id = ctx.payload["brief_id"]
    if ctx.user_id is not None:
        from perch.user.data import UserData as _UD

        return UserBriefStore(ud or _UD(ctx.pool), ctx.user_id, ctx.audience or "researcher",
                              brief_id, ctx=ctx)
    if ctx.guest_sid_hash is not None:
        from perch.redisx import get_client

        return GuestBriefStore(r or get_client(), ctx.guest_sid_hash.hex(), brief_id, ctx.job_id,
                               ctx=ctx)
    return None


def read_user_brief(ud: UserData, user_id: UUID, brief_id: str) -> StoredBrief | None:
    try:
        row = UUID(brief_id)
    except ValueError:
        return None
    try:
        got = ud.get_row(user_id, row, StoredBrief, kind="brief")
    except NotFound:
        return None
    return got[0] if got else None


# --- the two calls the web layer makes (api.py): submit a brief, read a brief ---

def guest_hash(sid: str) -> str:
    """sha256(PERCH_PEPPER_GUEST + sid), hex: the value of jobs.guest_sid_hash and of the
    guest quota key, so the worker finds the same counter."""
    from perch.redisx import hash_subject

    return hash_subject(sid)


def compute_idempotency_key(owner: str, audience: str, author_id: str | None,
                            doc_ids: Sequence[UUID],
                    options: dict, *, today: date | None = None) -> str:
    """Section 3.4: sha256 over the owner (user id, or the guest session hash), the side, the
    author id, the sorted document ids, a hash of the direction text, the other request
    options, and the UTC date. Ids and hashes only; the next day's brief is a new job."""
    import hashlib
    import json
    from datetime import UTC

    ctx = dict(options.get("context") or {})
    direction = hashlib.sha256((ctx.pop("direction", "") or "").encode()).hexdigest()
    ctx.pop("user_data", None)
    rest = {k: v for k, v in options.items() if k != "context"}
    canon = json.dumps({"owner": owner, "audience": audience, "author": author_id,
                        "docs": sorted(str(i) for i in doc_ids), "direction": direction,
                        "options": rest, "context": ctx,
                        "date": (today or datetime.now(UTC).date()).isoformat()},
                       sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


def side_row_ids(ud: UserData, user_id: UUID, audience: str) -> list[UUID]:
    """The ids of the CV, documents and entries of one side (rows only, no text)."""
    from perch.store import pg

    with pg.user_tx(ud.pool, user_id) as c:
        rows = c.execute("SELECT id FROM user_data WHERE user_id = %s AND audience = %s "
                         "AND kind IN ('cv','doc','entry')", (user_id, audience)).fetchall()
    return [r[0] for r in rows]


def submit_brief(svc: BriefService, runner: JobRunner, ud: UserData, r: redis.Redis,
                 session: Session, author_id: str | None, *, idempotency_key: str | None = None,
                 doc_ids: Sequence[UUID] = (), addr_hash: str | None = None,
                 **options: object) -> tuple[str, UUID]:
    """Create the brief where it lives and enqueue the job with ids only. Returns
    (brief_id, job_id). A signed-in user is held to the per-account rate and daily budget
    (perch/user/quota.py); a guest to the guest rate window. Raises quota.RateLimited or
    redisx.QuotaExceeded before anything is stored.

    The same request by the same owner on the same UTC day returns the existing brief and job
    and creates nothing (section 3.4). Raises HTTPException 403 `consent_required` when a
    signed-in request reads documents or a direction text without the current consent."""
    from perch.user import quota

    if session.audience == "student":
        author_id = None  # a student has no author id; the brief reads the CV
    elif not author_id:
        raise ValueError("a researcher brief needs an OpenAlex author id")
    if session.user_id is not None:
        from perch.auth.deps import require_consent

        ctx_opt = options.get("context") or {}
        if (doc_ids or session.audience == "student"
                or (isinstance(ctx_opt, dict) and (ctx_opt.get("direction") or "").strip())):
            require_consent(session)
        # A student brief reads every CV, note and entry of the side, so the key names their
        # row ids: a replaced CV or a new entry is a new brief, not the earlier one.
        key_docs = (side_row_ids(ud, session.user_id, session.audience)
                    if session.audience == "student" else doc_ids)
        key = idempotency_key or compute_idempotency_key(
            str(session.user_id), session.audience, author_id, key_docs, options)
        found = _existing(runner, key, session.user_id, None)
        if found is not None:
            return found
        quota.admit(r, ud.pool, session.user_id)
        b = create_user_brief(svc, ud, session.user_id, session.audience, author_id,
                              doc_ids=doc_ids, **options)
        job = runner.submit("brief", {"brief_id": b.id}, session.user_id, key,
                            audience=session.audience)
        won = _same_request_won(runner, key, session.user_id, None, b.id, job)
        if won is not None:  # a twin request created its brief first: drop ours (S49 B4)
            ud.delete(session.user_id, UUID(b.id), kinds=("brief",))
            return won
        return b.id, job
    if doc_ids:
        raise PermissionError("a guest cannot use documents")
    options.pop("context", None)  # direction text is user text: no user text in Redis (4.1)
    from perch.redisx import rate_limit

    gh = guest_hash(session.sid)
    ttl = int(env("PERCH_GUEST_TTL_S", str(GUEST_TTL_DEFAULT_S)) or GUEST_TTL_DEFAULT_S)
    # The guest's brief lives in Redis for one TTL, so the key also carries the TTL window:
    # a key never outlives the state it points at.
    key = idempotency_key or compute_idempotency_key(
        gh, session.audience, author_id, (), {**options, "window": int(time.time() // ttl)})
    found = _existing(runner, key, None, bytes.fromhex(gh))
    if found is not None:
        return found
    ok, retry = rate_limit(r, "guest_job", gh)
    if not ok:
        raise quota.RateLimited("guest_job", retry)
    if options.get("explain", True):  # model text: the guest budget must have room (S48 M2)
        quota.admit_guest(r, gh, addr_hash=addr_hash)
        if addr_hash:  # so the worker's meter charges the address too (it holds no pepper)
            r.set(f"perch:gsess:{gh}:addr", addr_hash, ex=ttl)
    b = create_guest_brief(svc, r, gh, author_id, audience=session.audience, **options)
    job = runner.submit("brief", {"brief_id": b.id}, None, key,
                        audience=session.audience, guest_sid_hash=bytes.fromhex(gh))
    won = _same_request_won(runner, key, None, bytes.fromhex(gh), b.id, job)
    if won is not None:  # a twin request created its brief first: drop ours (S49 B4)
        r.delete(GuestBriefStore(r, gh, b.id).state_key)
        return won
    r.set(f"perch:gsess:{gh}:job:{b.id}", str(job), ex=ttl)  # brief id -> job id, for the read
    return b.id, job


def _same_request_won(runner: JobRunner, key: str, user_id: UUID | None, guest: bytes | None,
                      brief_id: str, job: UUID) -> tuple[str, UUID] | None:
    """After the submit: when two identical requests raced past `_existing`, the unique index
    hands both the first job. Then the (brief, job) pair that job runs, else None (S49 B4)."""
    got = _existing(runner, key, user_id, guest)
    if got is None or got[0] == brief_id:
        return None
    return got if got[1] == job else None


def _existing(runner: JobRunner, key: str, user_id: UUID | None, guest: bytes | None
              ) -> tuple[str, UUID] | None:
    find = getattr(runner, "find_live", None)
    if find is None:
        return None
    got = find("brief", key, user_id, guest_sid_hash=guest)
    return (got[1]["brief_id"], got[0]) if got else None


def open_store(ud: UserData, r: redis.Redis, session: Session, brief_id: str
               ) -> BriefStore | None:
    """The store holding this session's brief, loaded, or None (also for a brief that belongs
    to someone else). Set it with `using_store` and every BriefService call reads and writes
    that brief: one code path for the stored brief routes, signed in or guest."""
    if session.user_id is not None:
        try:
            UUID(brief_id)
        except ValueError:
            return None
        store: BriefStore = UserBriefStore(ud, session.user_id, session.audience, brief_id)
    else:
        gh = guest_hash(session.sid)
        job = r.get(f"perch:gsess:{gh}:job:{brief_id}")
        store = GuestBriefStore(r, gh, brief_id, UUID(job.decode() if isinstance(job, bytes)
                                                      else job) if job else None)
    return store if store.load() else None


# --- the brief's job, as the page sees it (S49 B1) ---

# Written by code: the only sentences a brief shows for a job that ended without it.
JOB_ENDED = {
    "consent_required": "This brief reads your own text, and your consent is not current. "
                        "Accept it again, then build the brief again.",
    "timeout": "This brief took too long and was stopped. Build it again.",
    "cancelled": "This brief was cancelled.",
    "quota_exceeded": "Today's budget for written explanations is used up. Build the brief "
                      "again tomorrow.",
    "budget_exceeded": "Today's budget for written explanations is used up. Build the brief "
                       "again tomorrow.",
}
JOB_ENDED_DEFAULT = "This brief could not finish. Build it again in a few minutes."
JOB_GONE = "This brief has no job on record any more. Build it again."
WORKER_FRESH_S = 90  # a worker whose heartbeat row is older than this is not counted


def _brief_job_id(ud: UserData, r: redis.Redis, session: Session, brief_id: str
                  ) -> UUID | None:
    if session.user_id is not None:
        from perch.store import pg

        with pg.user_tx(ud.pool, session.user_id) as c:
            row = c.execute(
                "SELECT id FROM jobs WHERE user_id = %s AND kind = 'brief' "
                "AND payload->>'brief_id' = %s ORDER BY created_at DESC LIMIT 1",
                (session.user_id, brief_id)).fetchone()
        return row[0] if row else None
    job = r.get(f"perch:gsess:{guest_hash(session.sid)}:job:{brief_id}")
    return UUID(job.decode() if isinstance(job, bytes) else job) if job else None


def brief_job(runner: JobRunner, ud: UserData, r: redis.Redis, session: Session,
              brief_id: str) -> dict:
    """The state of the job that builds this brief: `state` (a job state, or `missing` when
    no job row is left), `error_code`, `attempts`, `queued_ahead`, and for a queued job
    `worker_seen` (False when no worker has beaten for this kind lately; None when unknown).
    Ids, states and fixed codes only."""
    jid = _brief_job_id(ud, r, session, brief_id)
    guest = None if session.user_id is not None else bytes.fromhex(guest_hash(session.sid))
    st = runner.status(jid, session.user_id, guest_sid_hash=guest) if jid else None
    if st is None:
        return {"state": "missing"}
    out: dict = {"id": str(st.job_id), "state": st.state.value, "error_code": st.error_code,
                 "attempts": st.attempts, "queued_ahead": st.queued_ahead}
    if st.state.value == "queued":
        out["worker_seen"] = _worker_seen(ud, "brief")
    return out


def _worker_seen(ud: UserData, kind: str) -> bool | None:
    from perch.store import pg

    try:
        with pg.public_tx(ud.pool) as c:
            row = c.execute(
                "SELECT 1 FROM worker_heartbeat WHERE at > now() - make_interval(secs => %s) "
                "AND (kinds = '{}' OR %s = ANY(kinds)) LIMIT 1", (WORKER_FRESH_S, kind)
            ).fetchone()
    except psycopg.Error:
        return None
    return row is not None


def job_overlay(brief: dict, job: dict) -> None:
    """A brief still marked queued or running whose job has ended without it (refused before
    the run, dead after its lease ran out, timed out, cancelled, or gone) is shown as failed
    with a sentence written by code, so the page stops waiting. The stored brief is not
    changed. A job still queued or running leaves the brief as it is."""
    if brief.get("status") not in ("queued", "running"):
        return
    state = job.get("state")
    if state == "missing":
        brief["status"], brief["error"] = "failed", JOB_GONE
    elif state in ("failed", "dead", "cancelled"):
        brief["status"] = "failed"
        brief["error"] = JOB_ENDED.get(job.get("error_code") or "", JOB_ENDED_DEFAULT)


def overlay_summaries(ud: UserData, user_id: UUID, summaries: list[dict]) -> None:
    """`job_overlay` for a list of brief summaries, with one read of the jobs table (S50 C3):
    My Perch shows a brief whose job ended without it as failed, as the brief page does."""
    open_ = [x for x in summaries if x.get("status") in ("queued", "running")]
    if not open_:
        return
    from perch.store import pg

    with pg.user_tx(ud.pool, user_id) as c:
        rows = c.execute(
            "SELECT DISTINCT ON (payload->>'brief_id') payload->>'brief_id', state, error_code "
            "FROM jobs WHERE user_id = %s AND kind = 'brief' AND payload->>'brief_id' = ANY(%s) "
            "ORDER BY payload->>'brief_id', created_at DESC",
            (user_id, [x["id"] for x in open_])).fetchall()
    jobs_by_brief = {bid: {"state": st, "error_code": code} for bid, st, code in rows}
    for x in open_:
        job_overlay(x, jobs_by_brief.get(x["id"], {"state": "missing"}))


def cancel_brief(runner: JobRunner, ud: UserData, r: redis.Redis, session: Session,
                 brief_id: str) -> bool | None:
    """Cancel the job that builds this brief. None when the brief is not the session's;
    False when the job already ended."""
    jid = _brief_job_id(ud, r, session, brief_id)
    if jid is None:
        return None
    guest = None if session.user_id is not None else bytes.fromhex(guest_hash(session.sid))
    return runner.cancel(jid, session.user_id, guest_sid_hash=guest)


def load_brief(ud: UserData, r: redis.Redis, session: Session, brief_id: str
               ) -> StoredBrief | None:
    """The brief for this session, or None (also for a brief that belongs to someone else)."""
    if session.user_id is not None:
        return read_user_brief(ud, session.user_id, brief_id)
    gh = guest_hash(session.sid)
    job = r.get(f"perch:gsess:{gh}:job:{brief_id}")
    if job:
        got = read_guest_result(r, job, gh)
        if got is not None:
            return got
    slot = f"perch:gsess:{gh}:brief:{brief_id}"
    return open_guest(r, gh, slot, r.get(slot))


# --- keep, dismiss, restore on the session path (section 7.4, S43 fork F3) ---

def set_lead_status(ud: UserData, r: redis.Redis, session: Session, brief_id: str,
                    lead_id: str, status: str) -> Lead | None:
    """Set one lead of the session's own brief to kept, dismissed or new, and return it; None
    when the brief or the lead is not the session's. A signed-in user's brief is the encrypted
    row, written with a stale-write check. A guest's brief is its Redis key: only the guest's own
    session hash can reach it, and the write keeps the key's remaining life (no new hour).
    The brief text is never logged."""
    from perch.user.data import Conflict

    if session.user_id is not None:
        try:
            row = UUID(brief_id)
        except ValueError:
            return None
        for _ in range(WRITE_TRIES):
            try:
                got = ud.get_row(session.user_id, row, StoredBrief, kind="brief")
            except NotFound:
                return None
            if got is None:
                return None
            sb, ts = got[0], got[1]
            lead = next((x for x in sb.leads if x.id == lead_id), None)
            if lead is None or lead.brief_id != brief_id:
                return None
            new = lead.model_copy(update={"status": status})
            sb.leads = [new if x.id == lead_id else x for x in sb.leads]
            try:
                ud.update(session.user_id, row, sb, expect_updated_at=ts)
            except Conflict:
                continue
            return new
        raise Conflict("the brief kept changing")
    gh = guest_hash(session.sid)
    job = r.get(f"perch:gsess:{gh}:job:{brief_id}")
    keys = ([f"perch:gres:{job.decode() if isinstance(job, bytes) else job}"] if job else [])
    for key in [*keys, f"perch:gsess:{gh}:brief:{brief_id}"]:
        with r.pipeline() as p:
            for _ in range(WRITE_TRIES):  # the worker may write the same key meanwhile (B2)
                try:
                    p.watch(key)
                    sb = open_guest(r, gh, key, p.get(key))
                    if sb is None:
                        break
                    lead = next((x for x in sb.leads if x.id == lead_id), None)
                    if lead is None:
                        return None
                    new = lead.model_copy(update={"status": status})
                    sb.leads = [new if x.id == lead_id else x for x in sb.leads]
                    sealed = seal_guest(r, gh, key, sb)
                    p.multi()
                    p.set(key, sealed, keepttl=True)
                    p.execute()
                    return new
                except redis.WatchError:
                    continue
            else:
                raise Conflict("the brief kept changing")
    return None

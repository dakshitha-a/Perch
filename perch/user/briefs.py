"""Where a brief lives (ARCHITECTURE_V1 sections 2.2, 3 and 7.4).

* Signed-in user: one encrypted `user_data` row of kind `brief` holding the Brief and its Leads.
  The row id is the brief id. It is written at creation and at every stage (partial saves).
* Guest: JSON in Redis. State before the job runs sits at `perch:gsess:<gsid_hash>:brief:<id>`
  and the result at `perch:gres:<job_id>`, one hour TTL. Nothing in Postgres but the `jobs` row.
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
from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import psycopg
import redis

from perch.config import env
from perch.schemas import Brief, Lead, Record, Work
from perch.store.base import Facets, Page, R, Repository
from perch.user.data import NotFound, UserData
from perch.user.models import Audience, StoredBrief, UserDoc

if TYPE_CHECKING:
    from perch.auth.session import Session
    from perch.jobs import JobContext, JobRunner
    from perch.service import BriefService

GRES_TTL_S = 3600
GUEST_TTL_DEFAULT_S = 3600

current_store: ContextVar[BriefStore | None] = ContextVar("perch_brief_store", default=None)


@contextmanager
def using_store(store: BriefStore | None) -> Iterator[None]:
    tok = current_store.set(store)
    try:
        yield
    finally:
        current_store.reset(tok)


class BriefStore(ABC):
    """Holds one brief and its leads in memory and writes them through on each change."""

    reads_user_data = False  # True when the brief reads a CV, entries or documents

    def __init__(self, brief_id: str) -> None:
        self.brief_id = brief_id
        self.brief: Brief | None = None
        self.leads: dict[str, Lead] = {}
        self._lock = threading.RLock()

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

    def user_docs(self) -> list[Work]:
        """User documents (CV text excluded) that become query threads. Empty for guests."""
        return []

    def flush(self) -> None:
        with self._lock:
            if self.brief is None:
                return
            self._write(StoredBrief(brief=self.brief, leads=list(self.leads.values())))

    def wrap(self, base: Repository) -> Repository:
        return StoreRepository(base, self)

    def view(self) -> tuple[Brief, list[Lead]] | None:
        with self._lock:
            if self.brief is None:
                return None
            by_id = self.leads
            return self.brief, [by_id[i] for i in self.brief.lead_ids if i in by_id]


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
        return self.base.get(cls, id)

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
        return self.base.get_any(id)

    def works_by_author(self, author_id: str) -> list[Work]:
        return self.base.works_by_author(author_id)

    def browse(self, cls: type[R], *, temple_only: bool = False, schools: Sequence[str] = (),
               audience_level: Sequence[str] = (), q: str | None = None,
               closes_after: date | None = None, limit: int = 50,
               cursor: str | None = None, scopes: Sequence[str] = (),
               exclude_schools: Sequence[str] = ()) -> Page[R]:
        return self.base.browse(cls, temple_only=temple_only, schools=schools,
                                audience_level=audience_level, q=q, closes_after=closes_after,
                                limit=limit, cursor=cursor, scopes=scopes,
                                exclude_schools=exclude_schools)

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
            got = self.ud.get_row(self.user_id, self.row_id, StoredBrief, conn=c)
        if got is None:
            return False
        sb, self._ts = got[0], got[1]
        self.brief = sb.brief
        self.leads = {x.id: x for x in sb.leads}
        self._doc_ids = [UUID(i) for i in sb.brief.options.get("user_data") or []]
        self.reads_user_data = bool(self._doc_ids)
        return True

    def _write(self, sb: StoredBrief) -> None:
        with self._conn() as c:
            if self._ts is None:
                self.ud.put(self.user_id, "brief", self.audience, sb, row_id=self.row_id, conn=c)
                got = self.ud.get_row(self.user_id, self.row_id, StoredBrief, conn=c)
                self._ts = got[1] if got else None
            else:
                self._ts = self.ud.update(self.user_id, self.row_id, sb,
                                          expect_updated_at=self._ts, conn=c)

    def cancelled(self) -> bool:
        return bool(self.ctx is not None and self.ctx.cancelled())

    @property
    def needs_consent(self) -> bool:
        """True when this brief hands the user's own text to a model: documents or a typed
        direction. The job checks the consent row before it reads either (section 7.5)."""
        o = self.brief.options if self.brief is not None else {}
        return bool(self._doc_ids or (o.get("direction") or "").strip())

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


# --- guest: Redis, public inputs only ---

class GuestBriefStore(BriefStore):
    """No CV, no entries, no rows in Postgres. `job_id` is known in the worker; at creation the
    state goes to the session key, and from the first worker write on to `perch:gres:<job_id>`."""

    def __init__(self, r: redis.Redis, gsid_hash: str, brief_id: str, job_id: UUID | None = None
                 ) -> None:
        super().__init__(brief_id)
        self.r, self.gsid_hash, self.job_id = r, gsid_hash, job_id

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
        raw = (self.r.get(self.result_key) if self.job_id else None) or self.r.get(self.state_key)
        if not raw:
            return False
        sb = StoredBrief.model_validate_json(raw)
        self.brief = sb.brief
        self.leads = {x.id: x for x in sb.leads}
        return True

    def _write(self, sb: StoredBrief) -> None:
        data = sb.model_dump_json()
        if self.job_id is None:
            ttl = int(env("PERCH_GUEST_TTL_S", str(GUEST_TTL_DEFAULT_S)) or GUEST_TTL_DEFAULT_S)
            self.r.set(self.state_key, data, ex=ttl)
        else:
            self.r.set(self.result_key, data, ex=GRES_TTL_S)


def read_guest_result(r: redis.Redis, job_id: UUID | str) -> StoredBrief | None:
    """The guest brief a job wrote, or None after the hour is up."""
    raw = r.get(f"perch:gres:{job_id}")
    return StoredBrief.model_validate_json(raw) if raw else None


# --- creation and the job's store ---

def create_user_brief(svc: BriefService, ud: UserData, user_id: UUID, audience: Audience,
                      author_id: str, *, doc_ids: Sequence[UUID] = (), **options: object) -> Brief:
    """Create the brief row (status queued). Its id is the user_data row id; the job payload
    carries that id and nothing else. `doc_ids` are the user_data rows of the documents the
    brief reads: ids only go into the options, and a brief that reads any is user-derived."""
    import uuid

    bid = str(uuid.uuid4())
    if doc_ids:
        ctx = {**(options.pop("context", None) or {}), "user_data": [str(i) for i in doc_ids]}
        options["context"] = ctx
    store = UserBriefStore(ud, user_id, audience, bid, reads_user_data=bool(doc_ids))
    with using_store(store):
        return svc.create(author_id, brief_id=bid, **options)


def create_guest_brief(svc: BriefService, r: redis.Redis, gsid_hash: str, author_id: str,
                       **options: object) -> Brief:
    import secrets

    bid = secrets.token_urlsafe(9)
    with using_store(GuestBriefStore(r, gsid_hash, bid)):
        return svc.create(author_id, brief_id=bid, **options)


def store_for_job(ctx: JobContext, ud: UserData | None = None, r: redis.Redis | None = None
                  ) -> BriefStore | None:
    """The store a `brief` job writes to: user_data for a signed-in job, Redis for a guest job,
    None for an ownerless job (the SQLite path)."""
    brief_id = ctx.payload["brief_id"]
    if ctx.user_id is not None:
        from perch.user.data import UserData as _UD

        return UserBriefStore(ud or _UD(ctx.pool), ctx.user_id, ctx.audience or "researcher",
                              brief_id, ctx=ctx)
    if ctx.guest_sid_hash is not None:
        from perch.redisx import get_client

        return GuestBriefStore(r or get_client(), ctx.guest_sid_hash.hex(), brief_id, ctx.job_id)
    return None


def read_user_brief(ud: UserData, user_id: UUID, brief_id: str) -> StoredBrief | None:
    try:
        row = UUID(brief_id)
    except ValueError:
        return None
    try:
        return ud.get(user_id, row, StoredBrief)
    except NotFound:
        return None


# --- the two calls the web layer makes (api.py): submit a brief, read a brief ---

def guest_hash(sid: str) -> str:
    """sha256(PERCH_PEPPER_GUEST + sid), hex: the value of jobs.guest_sid_hash and of the
    guest quota key, so the worker finds the same counter."""
    from perch.redisx import hash_subject

    return hash_subject(sid)


def compute_idempotency_key(owner: str, audience: str, author_id: str, doc_ids: Sequence[UUID],
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


def submit_brief(svc: BriefService, runner: JobRunner, ud: UserData, r: redis.Redis,
                 session: Session, author_id: str, *, idempotency_key: str | None = None,
                 doc_ids: Sequence[UUID] = (), **options: object) -> tuple[str, UUID]:
    """Create the brief where it lives and enqueue the job with ids only. Returns
    (brief_id, job_id). A signed-in user is held to the per-account rate and daily budget
    (perch/user/quota.py); a guest to the guest rate window. Raises quota.RateLimited or
    redisx.QuotaExceeded before anything is stored.

    The same request by the same owner on the same UTC day returns the existing brief and job
    and creates nothing (section 3.4). Raises HTTPException 403 `consent_required` when a
    signed-in request reads documents or a direction text without the current consent."""
    from perch.user import quota

    if session.user_id is not None:
        from perch.auth.deps import require_consent

        ctx_opt = options.get("context") or {}
        if doc_ids or (isinstance(ctx_opt, dict) and (ctx_opt.get("direction") or "").strip()):
            require_consent(session)
        key = idempotency_key or compute_idempotency_key(
            str(session.user_id), session.audience, author_id, doc_ids, options)
        found = _existing(runner, key, session.user_id, None)
        if found is not None:
            return found
        quota.admit(r, ud.pool, session.user_id)
        b = create_user_brief(svc, ud, session.user_id, session.audience, author_id,
                              doc_ids=doc_ids, **options)
        job = runner.submit("brief", {"brief_id": b.id}, session.user_id, key,
                            audience=session.audience)
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
    b = create_guest_brief(svc, r, gh, author_id, **options)
    job = runner.submit("brief", {"brief_id": b.id}, None, key,
                        audience=session.audience, guest_sid_hash=bytes.fromhex(gh))
    r.set(f"perch:gsess:{gh}:job:{b.id}", str(job), ex=ttl)  # brief id -> job id, for the read
    return b.id, job


def _existing(runner: JobRunner, key: str, user_id: UUID | None, guest: bytes | None
              ) -> tuple[str, UUID] | None:
    find = getattr(runner, "find_live", None)
    if find is None:
        return None
    got = find("brief", key, user_id, guest_sid_hash=guest)
    return (got[1]["brief_id"], got[0]) if got else None


def load_brief(ud: UserData, r: redis.Redis, session: Session, brief_id: str
               ) -> StoredBrief | None:
    """The brief for this session, or None (also for a brief that belongs to someone else)."""
    if session.user_id is not None:
        return read_user_brief(ud, session.user_id, brief_id)
    gh = guest_hash(session.sid)
    job = r.get(f"perch:gsess:{gh}:job:{brief_id}")
    if job:
        got = read_guest_result(r, job)
        if got is not None:
            return got
    raw = r.get(f"perch:gsess:{gh}:brief:{brief_id}")
    return StoredBrief.model_validate_json(raw) if raw else None


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
        for _ in range(3):
            try:
                got = ud.get_row(session.user_id, row, StoredBrief)
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
        raw = r.get(key)
        if not raw:
            continue
        sb = StoredBrief.model_validate_json(raw)
        lead = next((x for x in sb.leads if x.id == lead_id), None)
        if lead is None:
            return None
        new = lead.model_copy(update={"status": status})
        sb.leads = [new if x.id == lead_id else x for x in sb.leads]
        r.set(key, sb.model_dump_json(), keepttl=True)
        return new
    return None

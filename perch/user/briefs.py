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
from perch.store.base import Page, R, Repository
from perch.user.data import NotFound, UserData
from perch.user.models import Audience, StoredBrief, UserDoc

if TYPE_CHECKING:
    from perch.jobs import JobContext
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
               cursor: str | None = None) -> Page[R]:
        return self.base.browse(cls, temple_only=temple_only, schools=schools,
                                audience_level=audience_level, q=q, closes_after=closes_after,
                                limit=limit, cursor=cursor)

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

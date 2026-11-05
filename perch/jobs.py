"""Job manager (ARCHITECTURE_V1 section 3).

Two families live here.

- The queue: a job is a kind plus an ids-only payload, stored in Postgres. Handlers register
  by kind. `PostgresRunner` submits, reports status, cancels, and (in a worker process)
  claims jobs with `perch_claim_job`, holds a lease with a heartbeat, and fences every write
  by the attempt number, so a stale thread can never overwrite the current attempt.
- The closure runners (`ClosureRunner`, `InProcessRunner`, `InlineRunner`): the original
  in-process thread pool, `submit(job_id, fn)`. The demo path and unit tests still use them
  until the callers move to the queue.

Logs carry the job id, the exception class name and a fixed error code. Never a message,
a payload value or user text.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from perch.store import pg

log = logging.getLogger("perch.jobs")

JobKind = Literal["brief", "scout_turn", "handoff", "cover_points", "ingest", "purge", "precache"]
Audience = Literal["researcher", "student"]


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"
    CANCELLED = "cancelled"


TERMINAL = frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.DEAD, JobState.CANCELLED})

# Fixed error codes: the only text a failed job ever stores.
ERROR_CODES = frozenset({
    "lease_expired", "handler_error", "permanent", "cancelled", "refusal", "budget_exceeded",
    "quota_exceeded", "consent_required", "invalid_input", "missing_key", "provider_error",
    "network_error", "no_handler", "retention_invalid", "rekey_incomplete", "timeout",
})


class PermanentError(Exception):
    """Ends the job as `failed`, no retry. `code` comes from ERROR_CODES."""

    def __init__(self, code: str = "permanent") -> None:
        super().__init__(code)
        self.code = code if code in ERROR_CODES else "permanent"


class RetryableError(Exception):
    def __init__(self, code: str = "handler_error") -> None:
        super().__init__(code)
        self.code = code if code in ERROR_CODES else "handler_error"


class LeaseLost(Exception):
    """A fenced write matched no row: another attempt owns the job, or it was cancelled."""


class PayloadError(ValueError):
    """The payload has a key or value the contract does not allow. The message is fixed."""


# --- kinds and payload models ---

@dataclass(frozen=True)
class KindSpec:
    max_attempts: int
    timeout_s: int
    priority: int


KIND_SPECS: dict[str, KindSpec] = {
    "scout_turn": KindSpec(2, 180, 0),
    "handoff": KindSpec(3, 120, 1),
    "cover_points": KindSpec(3, 120, 1),
    "brief": KindSpec(3, 300, 2),
    "precache": KindSpec(3, 900, 8),
    "ingest": KindSpec(5, 3600, 9),
    "purge": KindSpec(5, 600, 5),
}

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9:_./-]{1,200}$")]


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BriefPayload(_P):
    brief_id: Id


class ScoutTurnPayload(_P):
    session_id: Id
    message_id: Id


class HandoffPayload(_P):
    brief_id: Id
    office: Literal["research_development", "technology_commercialization"]
    lead_ids: list[Id] = Field(default_factory=list, max_length=25)


class CoverPointsPayload(_P):
    brief_id: Id
    record_id: Id
    cv_id: Id | None = None


class IngestPayload(_P):
    source: Id


class PurgePayload(_P):
    action: Literal["user", "inactive", "guests", "jobs", "audit", "rekey", "tombstones"]
    user_id: Id | None = None


class PrecachePayload(_P):
    author_id: Id


PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "brief": BriefPayload, "scout_turn": ScoutTurnPayload, "handoff": HandoffPayload,
    "cover_points": CoverPointsPayload, "ingest": IngestPayload, "purge": PurgePayload,
    "precache": PrecachePayload,
}


def validate_payload(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Check the payload against the kind's model; return it. Never echoes a value."""
    model = PAYLOAD_MODELS.get(kind)
    if model is None:
        raise PayloadError("unknown job kind")
    try:
        return model.model_validate(dict(payload)).model_dump(exclude_none=True)
    except ValidationError as e:
        where = ",".join(".".join(str(p) for p in err["loc"])
                         for err in e.errors(include_input=False, include_url=False,
                                             include_context=False))
        raise PayloadError(f"payload rejected: {where}") from None


# --- registry ---

@dataclass(frozen=True)
class HandlerSpec:
    handler: Callable[[JobContext], str | None]
    max_attempts: int
    timeout_s: int
    priority: int


Handler = Callable[["JobContext"], "str | None"]

_REGISTRY: dict[str, HandlerSpec] = {}


def register(kind: JobKind, *, max_attempts: int, timeout_s: int, priority: int
             ) -> Callable[[Handler], Handler]:
    """Decorator. One handler per kind; registering twice raises."""
    def deco(fn: Callable[[JobContext], str | None]) -> Callable[[JobContext], str | None]:
        if kind in _REGISTRY:
            raise ValueError(f"handler already registered for {kind}")
        _REGISTRY[kind] = HandlerSpec(fn, max_attempts, timeout_s, priority)
        return fn
    return deco


def unregister(kind: str) -> None:
    _REGISTRY.pop(kind, None)


def registered_kinds() -> list[str]:
    return sorted(_REGISTRY)


def _spec(kind: str) -> KindSpec:
    h = _REGISTRY.get(kind)
    if h:
        return KindSpec(h.max_attempts, h.timeout_s, h.priority)
    return KIND_SPECS[kind]


# --- status and context ---

@dataclass(frozen=True)
class JobStatus:
    job_id: UUID
    kind: str
    state: JobState
    stages: list[dict]
    result_ref: str | None
    error_code: str | None
    attempts: int
    queued_ahead: int | None
    created_at: datetime
    finished_at: datetime | None


@dataclass
class Timing:
    """Intervals in seconds. Defaults follow section 3.3; tests shorten them."""
    lease_s: int = 60
    heartbeat_s: float = 15.0
    reaper_s: float = 30.0
    poll_s: float = 2.0
    drain_s: float = 30.0


_FENCE = "id = %s AND lease_owner = %s AND attempts = %s AND state = 'running'"


class JobContext:
    def __init__(self, runner: PostgresRunner, row: Mapping[str, Any], owner: str,
                 deadline: float) -> None:
        self._runner = runner
        self.job_id: UUID = row["id"]
        self.kind: str = row["kind"]
        self.user_id: UUID | None = row["user_id"]
        self.audience: str | None = row["audience"]
        self.guest_sid_hash: bytes | None = (bytes(row["guest_sid_hash"])
                                             if row["guest_sid_hash"] is not None else None)
        self.attempt: int = row["attempts"]
        self.max_attempts: int = row.get("max_attempts") or 1
        self.payload: Mapping[str, Any] = dict(row["payload"])
        self.lease_owner = owner
        self._deadline = deadline
        # A wait for the model slot does not count against the timeout (S50 C1), up to a hard
        # limit of three timeouts in all, so a job that keeps waiting still ends.
        self._hard_deadline = time.monotonic() + 3 * (deadline - time.monotonic())
        self._wait_lock = threading.Lock()
        self._waiting = 0
        self._wait_since = 0.0
        self._cancel = threading.Event()
        self._timed_out = False

    def wait_begin(self) -> None:
        """A thread of this job starts waiting for a model slot (perch.compute)."""
        with self._wait_lock:
            if self._waiting == 0:
                self._wait_since = time.monotonic()
            self._waiting += 1

    def wait_end(self) -> None:
        with self._wait_lock:
            self._waiting -= 1
            if self._waiting == 0:
                self._deadline += time.monotonic() - self._wait_since

    def past_deadline(self) -> bool:
        """True once the job has run longer than its timeout, not counting slot waits."""
        now = time.monotonic()
        if now > self._hard_deadline:
            return True
        with self._wait_lock:
            return self._waiting == 0 and now > self._deadline

    @property
    def pool(self) -> ConnectionPool:
        return self._runner.pool

    @property
    def _token(self) -> list[Any]:
        return [self.job_id, self.lease_owner, self.attempt]

    def _fenced(self, sql: str, params: Sequence[Any] = ()) -> None:
        """Run one UPDATE or INSERT whose WHERE ends in the fence; no row means LeaseLost."""
        with pg.public_tx(self._runner.pool) as c:
            if c.execute(sql, [*params, *self._token]).rowcount == 0:
                self._cancel.set()
                raise LeaseLost

    def stage(self, name: str, status: str, detail: str | None = None,
              ms: int | None = None) -> None:
        self._fenced("INSERT INTO job_events (job_id, stage, status, detail, ms) "
                     "SELECT id, %s, %s, %s, %s FROM jobs WHERE " + _FENCE,
                     [name, status, detail[:120] if detail else None, ms])

    def heartbeat(self) -> None:
        self._fenced("UPDATE jobs SET heartbeat_at = now(), "
                     "lease_expires_at = now() + make_interval(secs => %s) WHERE " + _FENCE,
                     [self._runner.timing.lease_s])

    def cancelled(self) -> bool:
        """True when the lease is lost, the owner cancelled, or the hard timeout passed."""
        return self._cancel.is_set() or self.past_deadline()

    def save_partial(self, ref: str) -> None:
        self._fenced("UPDATE jobs SET result_ref = %s WHERE " + _FENCE, [ref])

    @contextmanager
    def user_tx(self) -> Iterator[psycopg.Connection]:
        """A transaction with perch.user_id set, entered only while this attempt holds the lease."""
        if self.user_id is None:
            raise LeaseLost
        with pg.user_tx(self._runner.pool, self.user_id) as c:
            self._check_lease(c)
            yield c

    @contextmanager
    def guest_tx(self) -> Iterator[psycopg.Connection]:
        if self.guest_sid_hash is None:
            raise LeaseLost
        with pg.guest_tx(self._runner.pool, self.guest_sid_hash) as c:
            self._check_lease(c)
            yield c

    def _check_lease(self, c: psycopg.Connection) -> None:
        # FOR SHARE keeps the row from changing owner until this transaction ends.
        if c.execute("SELECT 1 FROM jobs WHERE " + _FENCE + " FOR SHARE",
                     self._token).fetchone() is None:
            self._cancel.set()
            raise LeaseLost


# --- interface ---

class JobRunner(ABC):
    @abstractmethod
    def submit(self, kind: JobKind, payload: Mapping[str, Any], user_id: UUID | None,
               idempotency_key: str, *, audience: Audience | None = None,
               guest_sid_hash: bytes | None = None, run_after: datetime | None = None) -> UUID:
        """Insert a queued job, or return the id of the live job with the same key."""

    @abstractmethod
    def status(self, job_id: UUID, user_id: UUID | None, *, guest_sid_hash: bytes | None = None
               ) -> JobStatus | None:
        """None when the job is unknown or belongs to someone else."""

    @abstractmethod
    def cancel(self, job_id: UUID, user_id: UUID | None, *, guest_sid_hash: bytes | None = None
               ) -> bool:
        """Queued: cancelled at once. Running: asks the handler to stop. False when finished."""

    @abstractmethod
    def wait(self, job_id: UUID, timeout: float | None = None) -> JobStatus:
        """Block until the job is terminal (tests and CLI)."""


def _scope(user_id: UUID | None, guest: bytes | None) -> tuple[str, list[Any]]:
    return ("user_id IS NOT DISTINCT FROM %s AND guest_sid_hash IS NOT DISTINCT FROM %s",
            [user_id, guest])


def _tx(pool: ConnectionPool, user_id: UUID | None, guest: bytes | None
        ) -> AbstractContextManager[psycopg.Connection]:
    if user_id is not None:
        return pg.user_tx(pool, user_id)
    if guest is not None:
        return pg.guest_tx(pool, guest)
    return pg.public_tx(pool)


def backoff_s(attempts: int) -> float:
    """5, 15, 45, 120 seconds plus up to 20 percent jitter."""
    base = min(120, 5 * 3 ** max(0, attempts - 1))
    return base * (1 + random.random() * 0.2)


class PostgresRunner(JobRunner):
    def __init__(self, dsn: str | None = None, *, pool: ConnectionPool | None = None,
                 timing: Timing | None = None, pool_size: int | None = None) -> None:
        self.pool = pool or pg.make_pool(dsn, pool_size)
        self._owns_pool = pool is None
        self.timing = timing or Timing()
        self.listen_dsn: str | None = os.environ.get("PERCH_DATABASE_DIRECT_URL")

    def close(self) -> None:
        if self._owns_pool:
            self.pool.close()

    # -- web side --

    def submit(self, kind: JobKind, payload: Mapping[str, Any], user_id: UUID | None,
               idempotency_key: str, *, audience: Audience | None = None,
               guest_sid_hash: bytes | None = None, run_after: datetime | None = None) -> UUID:
        clean = validate_payload(kind, payload)
        spec = _spec(kind)
        with _tx(self.pool, user_id, guest_sid_hash) as c:
            row = c.execute(
                "INSERT INTO jobs (kind, user_id, guest_sid_hash, audience, payload, "
                "idempotency_key, priority, max_attempts, run_after) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now())) "
                "ON CONFLICT DO NOTHING RETURNING id",
                (kind, user_id, guest_sid_hash, audience, Jsonb(clean), idempotency_key,
                 spec.priority, spec.max_attempts, run_after)).fetchone()
            if row is not None:
                c.execute("SELECT pg_notify('perch_jobs', '')")
                return row[0]
            where, params = _scope(user_id, guest_sid_hash)
            found = c.execute(
                "SELECT id FROM jobs WHERE kind = %s AND idempotency_key = %s AND " + where +
                " AND state IN ('queued','running','succeeded')",
                [kind, idempotency_key, *params]).fetchone()
        if found is None:  # the live job ended between the two statements
            raise RetryableError("handler_error")
        return found[0]

    def find_live(self, kind: str, idempotency_key: str, user_id: UUID | None, *,
                  guest_sid_hash: bytes | None = None) -> tuple[UUID, dict[str, Any]] | None:
        """The queued, running or succeeded job of this owner with this key, as
        (job_id, payload), or None. The web layer asks before it creates anything (3.4)."""
        where, params = _scope(user_id, guest_sid_hash)
        with _tx(self.pool, user_id, guest_sid_hash) as c:
            row = c.execute(
                "SELECT id, payload FROM jobs WHERE kind = %s AND idempotency_key = %s AND "
                + where + " AND state IN ('queued','running','succeeded') "
                "ORDER BY created_at DESC LIMIT 1", [kind, idempotency_key, *params]).fetchone()
        return (row[0], dict(row[1])) if row else None

    def status(self, job_id: UUID, user_id: UUID | None, *, guest_sid_hash: bytes | None = None
               ) -> JobStatus | None:
        where, params = _scope(user_id, guest_sid_hash)
        with _tx(self.pool, user_id, guest_sid_hash) as c:
            cur = c.cursor(row_factory=dict_row)
            j = cur.execute("SELECT * FROM jobs WHERE id = %s AND " + where,
                            [job_id, *params]).fetchone()
            if j is None:
                return None
            stages = cur.execute(
                "SELECT stage AS name, status, detail, ms FROM job_events WHERE job_id = %s "
                "ORDER BY id", [job_id]).fetchall()
            ahead = None
            if j["state"] == "queued":
                try:
                    ahead = c.execute("SELECT perch_queue_position(%s)", (job_id,)).fetchone()[0]
                except psycopg.errors.InsufficientPrivilege:
                    ahead = None
        return self._status(j, stages, ahead)

    @staticmethod
    def _status(j: Mapping[str, Any], stages: list[dict], ahead: int | None) -> JobStatus:
        return JobStatus(j["id"], j["kind"], JobState(j["state"]), stages, j["result_ref"],
                         j["error_code"], j["attempts"], ahead, j["created_at"], j["finished_at"])

    def cancel(self, job_id: UUID, user_id: UUID | None, *, guest_sid_hash: bytes | None = None
               ) -> bool:
        where, params = _scope(user_id, guest_sid_hash)
        with _tx(self.pool, user_id, guest_sid_hash) as c:
            n = c.execute(
                "UPDATE jobs SET state = 'cancelled', finished_at = now(), "
                "error_code = 'cancelled' "
                "WHERE id = %s AND state IN ('queued','running') AND " + where,
                [job_id, *params]).rowcount
        return n > 0

    def wait(self, job_id: UUID, timeout: float | None = None) -> JobStatus:
        end = None if timeout is None else time.monotonic() + timeout
        while True:
            with pg.public_tx(self.pool) as c:
                cur = c.cursor(row_factory=dict_row)
                j = cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
                if j is None:
                    raise KeyError("unknown job")
            if JobState(j["state"]) in TERMINAL:
                return self._status(j, [], None)  # stages: use status()
            if end is not None and time.monotonic() > end:
                raise TimeoutError("job not finished")
            time.sleep(0.05)

    # -- worker side --

    def claim(self, owner: str, kinds: Sequence[str]) -> dict[str, Any] | None:
        with pg.public_tx(self.pool) as c:
            cur = c.cursor(row_factory=dict_row)
            return cur.execute("SELECT * FROM perch_claim_job(%s, %s, %s)",
                               (owner, list(kinds), self.timing.lease_s)).fetchone()

    def reap(self) -> int:
        """Retry or dead-letter running jobs whose lease expired. Safe in many workers."""
        with pg.public_tx(self.pool) as c:
            rows = c.execute(
                "UPDATE jobs SET lease_owner = NULL, lease_expires_at = NULL, "
                "state = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END, "
                "error_code = 'lease_expired', "
                "run_after = now() + make_interval(secs => "
                "LEAST(120, 5 * power(3, attempts - 1))), "
                "finished_at = CASE WHEN attempts >= max_attempts THEN now() END "
                "WHERE state = 'running' AND lease_expires_at < now() RETURNING id, state"
            ).fetchall()
            for jid, state in rows:
                if state == "dead":
                    c.execute("INSERT INTO audit_log (event, job_id, detail) "
                              "VALUES ('job_dead', %s, %s)",
                              (jid, Jsonb({"error_code": "lease_expired"})))
        return len(rows)

    def context(self, row: Mapping[str, Any], owner: str) -> JobContext:
        return JobContext(self, row, owner, time.monotonic() + _spec(row["kind"]).timeout_s)

    def finish_ok(self, ctx: JobContext, result_ref: str | None) -> None:
        ctx._fenced("UPDATE jobs SET state = 'succeeded', finished_at = now(), "
                    "lease_expires_at = NULL, result_ref = COALESCE(%s, result_ref), "
                    "error_code = NULL WHERE " + _FENCE, [result_ref])

    def finish_error(self, ctx: JobContext, code: str, permanent: bool) -> None:
        """Failed, retried or dead-lettered, in one fenced transaction."""
        with pg.public_tx(self.pool) as c:
            row = c.execute("SELECT max_attempts FROM jobs WHERE " + _FENCE + " FOR UPDATE",
                            ctx._token).fetchone()
            if row is None:
                ctx._cancel.set()
                raise LeaseLost
            state = "failed" if permanent else "dead" if ctx.attempt >= row[0] else "queued"
            terminal = state != "queued"
            c.execute("UPDATE jobs SET state = %s, error_code = %s, lease_owner = NULL, "
                      "lease_expires_at = NULL, run_after = now() + make_interval(secs => %s), "
                      "finished_at = CASE WHEN %s THEN now() END WHERE " + _FENCE,
                      [state, code, 0.0 if terminal else backoff_s(ctx.attempt), terminal,
                       *ctx._token])
            if state == "dead":
                c.execute("INSERT INTO audit_log (event, job_id, detail) "
                          "VALUES ('job_dead', %s, %s)",
                          (ctx.job_id, Jsonb({"error_code": code})))
            elif not terminal:
                c.execute("SELECT pg_notify('perch_jobs', '')")

    def execute(self, row: Mapping[str, Any], owner: str) -> None:
        """Run one claimed job: heartbeat in a helper thread, then one fenced terminal update."""
        ctx = self.context(row, owner)
        spec = _REGISTRY.get(ctx.kind)
        done = threading.Event()

        def beat() -> None:
            while not done.wait(self.timing.heartbeat_s):
                if ctx.past_deadline():
                    # S49 B6: end the job as failed with `timeout` now. The handler's next
                    # fenced write raises LeaseLost, so a second attempt never runs beside it.
                    ctx._timed_out = True
                    try:
                        self.finish_error(ctx, "timeout", permanent=True)
                    except LeaseLost:
                        pass  # the handler finished first, or the job was cancelled
                    except Exception as e:  # noqa: BLE001 - the lease runs out; the reaper acts
                        log.warning("timeout write failed job=%s err=%s", ctx.job_id,
                                    type(e).__name__)
                    ctx._cancel.set()
                    log.info("timeout job=%s kind=%s attempt=%s", ctx.job_id, ctx.kind,
                             ctx.attempt)
                    return
                try:
                    ctx.heartbeat()
                except LeaseLost:
                    return
                except Exception as e:  # noqa: BLE001 - a missed beat is retried next tick
                    log.warning("heartbeat failed job=%s err=%s", ctx.job_id, type(e).__name__)

        hb = threading.Thread(target=beat, daemon=True, name="perch-heartbeat")
        hb.start()
        try:
            from perch.compute import slot_wait_observer

            watching = slot_wait_observer.set(ctx)
            try:
                if spec is None:
                    raise PermanentError("no_handler")
                ref = spec.handler(ctx)
            finally:
                slot_wait_observer.reset(watching)
                done.set()
                hb.join(timeout=5)
            if ctx._cancel.is_set():  # stale: the reaper, the owner or the timeout acted
                log.info("stale job=%s", ctx.job_id)
                return
            self.finish_ok(ctx, ref)  # fenced: a result just past the deadline still counts
            log.info("done job=%s kind=%s attempt=%s", ctx.job_id, ctx.kind, ctx.attempt)
        except LeaseLost:
            log.info("lease lost job=%s kind=%s attempt=%s", ctx.job_id, ctx.kind, ctx.attempt)
        except Exception as e:  # noqa: BLE001 - the class name and a fixed code are all we keep
            code = getattr(e, "code", "handler_error")
            code = code if code in ERROR_CODES else "handler_error"
            if ctx.past_deadline():  # the handler stopped itself at the deadline
                code = "timeout"
            log.warning("error job=%s kind=%s attempt=%s err=%s code=%s",
                        ctx.job_id, ctx.kind, ctx.attempt, type(e).__name__, code)
            if ctx._cancel.is_set():
                return
            try:
                self.finish_error(ctx, code, isinstance(e, PermanentError) or code == "timeout")
            except LeaseLost:
                pass

    def run_forever(self, worker_id: str, kinds: Sequence[str], concurrency: int,
                    stop: threading.Event, *, scheduler: Scheduler | None = None) -> None:
        """Claim and run jobs on `concurrency` threads until `stop` is set, then drain. With a
        `scheduler`, the maintenance thread also submits the daily jobs (S49 B5)."""
        use = [k for k in kinds if k in _REGISTRY] if kinds else registered_kinds()
        if not use:
            return
        wake = threading.Event()
        # S50 C2: the nightly precache queues one job per researcher, and every one of them
        # waits on the same model slot as a user's brief. At most PERCH_PRECACHE_CONCURRENCY
        # (default 1) job threads of this worker run precache at once; the rest stay free.
        bulk = threading.BoundedSemaphore(precache_concurrency())

        def loop(n: int) -> None:
            owner = f"{worker_id}/{n}"
            while not stop.is_set():
                held = "precache" in use and bulk.acquire(blocking=False)
                mine = use if held else [k for k in use if k != "precache"]
                try:
                    row = self.claim(owner, mine) if mine else None
                except Exception as e:  # noqa: BLE001
                    log.warning("claim failed err=%s", type(e).__name__)
                    if held:
                        bulk.release()
                    stop.wait(self.timing.poll_s)
                    continue
                if held and (row is None or row["kind"] != "precache"):
                    bulk.release()
                    held = False
                if row is None:
                    wake.wait(self.timing.poll_s)
                    wake.clear()
                    continue
                try:
                    self.execute(row, owner)
                except Exception as e:  # noqa: BLE001 - a database blip must not end the thread
                    # (S49 B3): the job's lease runs out and the reaper retries it.
                    log.warning("execute failed err=%s", type(e).__name__)
                    stop.wait(self.timing.poll_s)
                finally:
                    if held:
                        bulk.release()

        def maintain() -> None:
            last_reap = last_tick = 0.0
            while not stop.is_set():
                try:
                    with pg.public_tx(self.pool) as c:
                        c.execute(
                            "INSERT INTO worker_heartbeat (worker, at, kinds, models_loaded) "
                            "VALUES (%s, now(), %s, false) ON CONFLICT (worker) DO UPDATE "
                            "SET at = now(), kinds = EXCLUDED.kinds", (worker_id, use))
                    if time.monotonic() - last_reap >= self.timing.reaper_s:
                        last_reap = time.monotonic()
                        self.reap()
                except Exception as e:  # noqa: BLE001
                    log.warning("maintenance failed err=%s", type(e).__name__)
                if scheduler is not None and time.monotonic() - last_tick >= scheduler.every_s:
                    last_tick = time.monotonic()
                    try:
                        scheduler.tick(self, datetime.now(UTC))
                    except Exception as e:  # noqa: BLE001 - the next tick tries again
                        log.warning("scheduler failed err=%s", type(e).__name__)
                stop.wait(min(self.timing.heartbeat_s, self.timing.reaper_s))

        def listen() -> None:
            try:
                with psycopg.connect(self.listen_dsn, autocommit=True) as lc:
                    lc.execute("LISTEN perch_jobs")
                    while not stop.is_set():
                        for _ in lc.notifies(timeout=1.0, stop_after=1):
                            wake.set()
            except Exception as e:  # noqa: BLE001 - polling still finds the work
                log.warning("listener stopped err=%s", type(e).__name__)

        threads = [threading.Thread(target=loop, args=(i,), name=f"perch-job-{i}")
                   for i in range(concurrency)]
        threads.append(threading.Thread(target=maintain, name="perch-maint"))
        if self.listen_dsn:
            threads.append(threading.Thread(target=listen, daemon=True, name="perch-listen"))
        for t in threads:
            t.start()
        stop.wait()
        wake.set()
        end = time.monotonic() + self.timing.drain_s
        for t in threads:
            t.join(timeout=max(0.0, end - time.monotonic()))
        try:
            with pg.public_tx(self.pool) as c:
                c.execute("DELETE FROM worker_heartbeat WHERE worker = %s", (worker_id,))
        except Exception:  # noqa: BLE001
            pass


def precache_concurrency() -> int:
    """How many job threads of one worker may run precache at once (S50 C2)."""
    try:
        return max(1, int(os.environ.get("PERCH_PRECACHE_CONCURRENCY") or 1))
    except ValueError:
        return 1


# --- the scheduler: daily purges and the nightly precache (S49 B5) ---

DAILY_PURGES = ("guests", "jobs", "audit", "tombstones", "inactive")
SCHEDULER_LOCK = 0x70657263  # pg advisory lock id: one worker at a time runs a tick


def _hhmm(text: str | None, default: str) -> tuple[int, int]:
    h, _, m = (text or default).partition(":")
    return int(h), int(m or 0)


@dataclass
class Scheduler:
    """Submits each daily `purge` action once a UTC day at `purge_at`, and the nightly precache
    at `precache_at` (UTC, HH:MM). Runs inside the worker's maintenance thread. Every key holds
    the date, and a tick submits nothing whose key already has a row in any state, so a second
    worker or a restart is harmless and a failed purge is not resubmitted the same day (its
    row is the alert). A Postgres advisory lock keeps two workers from ticking at once.
    `precache` enqueues the precache jobs for a date and returns how many."""

    precache: Callable[[PostgresRunner, str], int] | None = None
    purge_at: tuple[int, int] = (3, 0)
    precache_at: tuple[int, int] = (2, 0)
    every_s: float = 60.0
    _done: set[str] = field(default_factory=set)

    @classmethod
    def from_env(cls, precache: Callable[[PostgresRunner, str], int] | None) -> Scheduler:
        return cls(precache=precache,
                   purge_at=_hhmm(os.environ.get("PERCH_PURGE_AT"), "03:00"),
                   precache_at=_hhmm(os.environ.get("PERCH_PRECACHE_AT"), "02:00"))

    def tick(self, runner: PostgresRunner, now: datetime) -> list[str]:
        """Submit what is due at `now` (UTC). Returns the keys it submitted."""
        day = now.date().isoformat()
        due = []
        if (now.hour, now.minute) >= self.purge_at:
            due += [f"purge:{a}:{day}" for a in DAILY_PURGES]
        if self.precache is not None and (now.hour, now.minute) >= self.precache_at:
            due.append(f"precache:{day}")
        due = [k for k in due if k not in self._done]
        if not due:
            return []
        out: list[str] = []
        with pg.public_tx(runner.pool) as c:
            if not c.execute("SELECT pg_try_advisory_xact_lock(%s)",
                             (SCHEDULER_LOCK,)).fetchone()[0]:
                return []  # another worker is ticking
            for key in due:
                if key.startswith("purge:"):
                    seen = c.execute("SELECT 1 FROM jobs WHERE kind = 'purge' "
                                     "AND idempotency_key = %s LIMIT 1", (key,)).fetchone()
                    if seen is None:
                        runner.submit("purge", {"action": key.split(":")[1]}, None, key)
                        out.append(key)
                else:
                    seen = c.execute("SELECT 1 FROM jobs WHERE kind = 'precache' "
                                     "AND idempotency_key LIKE %s LIMIT 1",
                                     (f"precache:%:{day}",)).fetchone()
                    if seen is None and self.precache is not None:
                        n = self.precache(runner, day)
                        out.append(key)
                        log.info("scheduled precache jobs=%s", n)
                self._done.add(key)
        for key in out:
            log.info("scheduled %s", key.rsplit(":", 1)[0])
        return out


# --- the brief handler: the existing build, by id ---

_brief_service: Callable[[], Any] | None = None


def set_brief_service(factory: Callable[[], Any]) -> None:
    """The worker process supplies the BriefService (models, clients) here."""
    global _brief_service
    _brief_service = factory


@register("brief", max_attempts=3, timeout_s=300, priority=2)
def brief_handler(ctx: JobContext) -> str | None:
    if _brief_service is None:
        raise PermanentError("no_handler")
    brief_id = ctx.payload["brief_id"]
    from perch.user.briefs import store_for_job

    store = store_for_job(ctx)  # user_data row, or Redis for a guest
    if store is None:  # v1 submits every brief with an owner (S49 B31)
        raise PermanentError("invalid_input")
    status = _run_stored_brief(ctx, store, brief_id)
    if status == "queued":  # a server did not answer: the brief waits for the retry (S49 B8)
        raise RetryableError("network_error")
    if status in ("failed", "missing"):  # the brief holds the stage detail, never the log
        raise PermanentError("permanent")
    return store.result_ref


def job_meter(ctx: JobContext) -> Any:  # noqa: ANN401 - a perch.user.spend.SpendMeter or None
    """Every paid call of this job is reserved and settled against its owner's counters (the
    account's day or the guest session's, the guest ceiling, the global month; S48 M2).
    None without Redis: no account or guest job can be submitted without it (the web admits
    each one against the same counters), and the adapter's file ledger still caps the total."""
    from perch.config import env
    from perch.redisx import get_client
    from perch.user.spend import for_job

    if not env("PERCH_REDIS_URL"):
        return None
    return for_job(get_client(), ctx.pool, user_id=ctx.user_id,
                   guest_sid_hash=ctx.guest_sid_hash, job_id=ctx.job_id)


def _run_stored_brief(ctx: JobContext, store: Any, brief_id: str) -> str:  # noqa: ANN401
    from perch.user.briefs import using_store
    from perch.user.spend import using_meter

    assert _brief_service is not None
    if not store.load():
        raise PermanentError("permanent")
    if getattr(store, "needs_consent", False):  # reads the user's text: consent must stand
        from perch.auth.accounts import consent_version_of
        from perch.config import env

        with ctx.user_tx() as c:
            have = consent_version_of(c, ctx.user_id)
        if have < int(env("PERCH_CONSENT_VERSION", "1") or 1):
            raise PermanentError("consent_required")
    ctx.save_partial(store.result_ref)  # the page reads partial text from the same row
    with using_store(store), using_meter(job_meter(ctx)):
        return _brief_service().run(brief_id)


@register("precache", max_attempts=3, timeout_s=900, priority=8)
def precache_handler(ctx: JobContext) -> str | None:
    """Retrieval, rules and rerank for one public researcher, stored in `public_cache`."""
    if _brief_service is None:
        raise PermanentError("no_handler")
    from perch import precache

    report = precache.precache_author(_brief_service(), ctx.payload["author_id"])
    if not report["stored"]:
        raise PermanentError("handler_error")
    return None


# --- the original in-process closure runners (demo path and unit tests) ---



class ClosureRunner(ABC):
    @abstractmethod
    def submit(self, job_id: str, fn: Callable[[], None]) -> None:
        """Run fn in the background. Failures are the job's own business (it records them)."""

    def wait(self, job_id: str, timeout: float | None = None) -> None:  # noqa: B027
        """Block until the job finishes (tests and CLI); a no-op where unsupported."""

    def cancel(self, job_id: str) -> bool:
        """Drop the job if it has not started; False if it runs, ran, or is unknown."""
        return False


class InProcessRunner(ClosureRunner):
    def __init__(self, workers: int = 1) -> None:
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="perch-job")
        self.futures: dict[str, Future] = {}

    def submit(self, job_id: str, fn: Callable[[], None]) -> None:
        f = self.pool.submit(fn)
        self.futures[job_id] = f
        f.add_done_callback(lambda _: self.futures.pop(job_id, None))

    def cancel(self, job_id: str) -> bool:
        f = self.futures.get(job_id)
        return bool(f and f.cancel())

    def wait(self, job_id: str, timeout: float | None = None) -> None:
        f = self.futures.get(job_id)
        if f:
            f.result(timeout=timeout)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


class InlineRunner(ClosureRunner):
    """Runs the job at submit time (tests)."""

    def submit(self, job_id: str, fn: Callable[[], None]) -> None:
        fn()

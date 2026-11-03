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
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

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
    "network_error", "no_handler",
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
    record_id: Id
    office: Id | None = None


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
        self.payload: Mapping[str, Any] = dict(row["payload"])
        self.lease_owner = owner
        self._deadline = deadline
        self._cancel = threading.Event()
        self._timed_out = False

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
        return self._cancel.is_set() or time.monotonic() > self._deadline

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
                if time.monotonic() > ctx._deadline:
                    ctx._timed_out = True
                    ctx._cancel.set()
                    return  # stop heartbeating: the lease runs out and the reaper acts
                try:
                    ctx.heartbeat()
                except LeaseLost:
                    return
                except Exception as e:  # noqa: BLE001 - a missed beat is retried next tick
                    log.warning("heartbeat failed job=%s err=%s", ctx.job_id, type(e).__name__)

        hb = threading.Thread(target=beat, daemon=True, name="perch-heartbeat")
        hb.start()
        try:
            try:
                if spec is None:
                    raise PermanentError("no_handler")
                ref = spec.handler(ctx)
            finally:
                done.set()
                hb.join(timeout=5)
            if ctx.cancelled():  # stale: the reaper or the owner has acted, write nothing
                log.info("stale job=%s", ctx.job_id)
                return
            self.finish_ok(ctx, ref)
            log.info("done job=%s kind=%s attempt=%s", ctx.job_id, ctx.kind, ctx.attempt)
        except LeaseLost:
            log.info("lease lost job=%s kind=%s attempt=%s", ctx.job_id, ctx.kind, ctx.attempt)
        except Exception as e:  # noqa: BLE001 - the class name and a fixed code are all we keep
            code = getattr(e, "code", "handler_error")
            code = code if code in ERROR_CODES else "handler_error"
            log.warning("error job=%s kind=%s attempt=%s err=%s code=%s",
                        ctx.job_id, ctx.kind, ctx.attempt, type(e).__name__, code)
            if ctx.cancelled():
                return
            try:
                self.finish_error(ctx, code, isinstance(e, PermanentError))
            except LeaseLost:
                pass

    def run_forever(self, worker_id: str, kinds: Sequence[str], concurrency: int,
                    stop: threading.Event) -> None:
        """Claim and run jobs on `concurrency` threads until `stop` is set, then drain."""
        use = [k for k in kinds if k in _REGISTRY] if kinds else registered_kinds()
        if not use:
            return
        wake = threading.Event()

        def loop(n: int) -> None:
            owner = f"{worker_id}/{n}"
            while not stop.is_set():
                try:
                    row = self.claim(owner, use)
                except Exception as e:  # noqa: BLE001
                    log.warning("claim failed err=%s", type(e).__name__)
                    stop.wait(self.timing.poll_s)
                    continue
                if row is None:
                    wake.wait(self.timing.poll_s)
                    wake.clear()
                    continue
                self.execute(row, owner)

        def maintain() -> None:
            last_reap = 0.0
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
    _brief_service().run(brief_id)
    return f"brief:{brief_id}"


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

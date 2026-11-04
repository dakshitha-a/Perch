"""Per-account quotas for signed-in users (ARCHITECTURE_V1 section 4.2), over perch/redisx.py.

Spend is counted per account per UTC day, in micro dollars, against PERCH_DAILY_BUDGET_USD. The
address plays no part. This replaces the per-address and per-hour caps for signed-in users.
A missing counter is rebuilt from `spend_ledger` with SET NX, so a Redis flush loses nothing.
Numbers shown to the user are copied from the counter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import redis
from psycopg_pool import ConnectionPool

from perch import redisx
from perch.redisx import QuotaExceeded, Scope
from perch.store import pg


class RateLimited(Exception):
    def __init__(self, scope: str, retry_after: int) -> None:
        super().__init__(scope)
        self.scope, self.retry_after = scope, retry_after


@dataclass(frozen=True)
class Usage:
    spent_usd: float
    limit_usd: float
    resets_at: datetime


def user_scopes(uid: UUID | str, now: datetime | None = None, **limits: float) -> list[Scope]:
    """The user's daily counter and the global month. Limits default from the environment."""
    return redisx.quota_scopes(uid=uid, now=now, **limits)


def _day_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def ensure_counter(r: redis.Redis, pool: ConnectionPool, uid: UUID, scope: Scope,
                   now: datetime) -> None:
    """Seed a missing daily counter from the ledger, never overwriting a live one."""
    if r.exists(scope.spend):
        return
    start = _day_start(now)
    with pg.user_tx(pool, uid) as c:
        total = c.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM spend_ledger "
                          "WHERE user_id = %s AND at >= %s AND at < %s",
                          (uid, start, start + timedelta(days=1))).fetchone()[0]
    redisx.seed_counter(r, scope, redisx.usd_micro(float(total)))


def usage(r: redis.Redis, pool: ConnectionPool, uid: UUID, *, now: datetime | None = None,
          **limits: float) -> Usage:
    t = now or datetime.now(UTC)
    scope = user_scopes(uid, t, **limits)[0]
    ensure_counter(r, pool, uid, scope, t)
    return Usage(redisx.spent_micro(r, scope) / 1_000_000, scope.limit / 1_000_000,
                 _day_start(t) + timedelta(days=1))


def admit(r: redis.Redis, pool: ConnectionPool, uid: UUID, rate_scope: str = "submit_job", *,
          now: datetime | None = None, **limits: float) -> None:
    """Before a job that will call a model: the user's rate window, then the daily budget.
    Raises RateLimited or QuotaExceeded. The per-call reservation is `reserve_call`."""
    ok, retry = redisx.rate_limit(r, rate_scope, f"u:{uid}")
    if not ok:
        raise RateLimited(rate_scope, retry)
    t = now or datetime.now(UTC)
    scope = user_scopes(uid, t, **limits)[0]
    ensure_counter(r, pool, uid, scope, t)
    fly = int(r.get(scope.inflight) or 0)
    if redisx.spent_micro(r, scope) + fly >= scope.limit:
        raise QuotaExceeded(scope.name)


FREE_GATE_PER_DAY = 10  # out-of-budget distress screens per account per UTC day (S45 S1)


def free_gate(r: redis.Redis, uid: UUID, *, now: datetime | None = None,
              cap: int = FREE_GATE_PER_DAY) -> bool:
    """May this account have one more unmetered gate call today? The gate screens a question
    for distress even when the budget is spent, so that screen is never budget-gated; this cap
    keeps the free path from being an unmetered model. Counts the call when it says yes."""
    t = now or datetime.now(UTC)
    key = f"perch:gate_free:{uid}:{t:%Y-%m-%d}"
    n = int(r.incr(key))
    if n == 1:
        r.expire(key, 2 * 86400)
    return n <= cap


def reserve_call(r: redis.Redis, uid: UUID, estimate_micro: int, *,
                 now: datetime | None = None, **limits: float) -> list[Scope]:
    """Reserve against the user's day and the global month before one model call."""
    scopes = user_scopes(uid, now, **limits)
    redisx.reserve(r, scopes, estimate_micro)
    return scopes


def settle_call(r: redis.Redis, scopes: list[Scope], estimate_micro: int, cost_micro: int, *,
                in_tok: int = 0, out_tok: int = 0, gate: bool = False) -> None:
    redisx.settle(r, scopes, estimate_micro, cost_micro, in_tok=in_tok, out_tok=out_tok,
                  gate=gate)

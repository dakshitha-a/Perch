"""Delete-my-data, the 12-month purge and the `purge` job kind (ARCHITECTURE_V1 sections 3.1,
6.6 and 7.5).

Order for one account (6.6):
  1. tombstone and key deletion in the keys database (crypto.shred; its hooks write shred_log,
     the ledger object and the perch:shred message). This is the point of no return.
  1b. set users.deleted_at and cancel the user's queued and running jobs.
  3. end every session of the user.
  4. clear the rows: the web path enqueues purge(action="user"), the worker path calls
     perch_delete_user_rows itself.
Rows may linger between 1 and 4 and are already unreadable.

Nothing here logs a user's text. Handlers log the class name and a fixed code only.
"""

from __future__ import annotations

import logging
from uuid import UUID

import redis
from psycopg_pool import ConnectionPool

from perch import crypto
from perch.config import env
from perch.crypto import CryptoError
from perch.jobs import JobContext, JobRunner, PermanentError, register
from perch.redisx import destroy_user_sessions
from perch.store import pg

log = logging.getLogger("perch.user.delete")

INACTIVE_AFTER = "12 months"
INACTIVE_BATCH = 500
GUEST_JOB_AFTER = "24 hours"
LASTSEEN_TTL_S = 86_400


def _cancel_jobs(pool: ConnectionPool, runner: JobRunner, user_id: UUID) -> int:
    with pg.user_tx(pool, user_id) as c:
        c.execute("UPDATE users SET deleted_at = now() WHERE id = %s AND deleted_at IS NULL",
                  (user_id,))
        ids = [r[0] for r in c.execute(
            "SELECT id FROM jobs WHERE user_id = %s AND state IN ('queued','running')",
            (user_id,))]
    return sum(runner.cancel(j, user_id) for j in ids)


def clear_rows(pool: ConnectionPool, user_id: UUID) -> None:
    """The worker's last step: the definer function that clears every table for one user."""
    with pg.public_tx(pool) as c:
        c.execute("SELECT perch_delete_user_rows(%s)", (user_id,))


def delete_account(user_id: UUID, *, pool: ConnectionPool, runner: JobRunner,
                   r: redis.Redis | None, inline: bool = False) -> None:
    """Run the delete order. `inline` clears the rows in this process (the worker's inactivity
    purge); otherwise purge(action="user") is queued. Raises CryptoError after the whole order
    ran when a shred hook failed: the keys are gone, and a retry only repeats the hooks."""
    hook_failed = False
    try:
        crypto.shred(user_id)
    except CryptoError:
        hook_failed = True  # keys are already deleted; finish the order, then report
    _cancel_jobs(pool, runner, user_id)
    if r is not None:
        destroy_user_sessions(r, user_id)
    if inline:
        clear_rows(pool, user_id)
    else:
        # As the user: the web role may not insert an ownerless job. The row is deleted by the
        # purge itself, and the worker's closing update then matches nothing, which is fine.
        runner.submit("purge", {"action": "user", "user_id": str(user_id)}, user_id,
                      f"purge-user:{user_id}")
    if hook_failed:
        raise CryptoError("the user's keys are shredded but a shred hook failed; retry")


def touch_last_active(pool: ConnectionPool, r: redis.Redis, user_id: UUID) -> bool:
    """users.last_active_at at most once a day per user (section 4.1, perch:lastseen:<uid>).
    True when it wrote."""
    if not r.set(f"perch:lastseen:{user_id}", "1", nx=True, ex=LASTSEEN_TTL_S):
        return False
    with pg.user_tx(pool, user_id) as c:
        c.execute("UPDATE users SET last_active_at = now() WHERE id = %s", (user_id,))
    return True


# --- the `purge` job kind ---

def purge_inactive(pool: ConnectionPool, runner: JobRunner, r: redis.Redis | None,
                   *, older_than: str = INACTIVE_AFTER, limit: int = INACTIVE_BATCH) -> int:
    with pg.public_tx(pool) as c:
        ids = [row[0] for row in c.execute(
            "SELECT perch_inactive_users(%s::interval, %s)", (older_than, limit))]
    for uid in ids:
        delete_account(uid, pool=pool, runner=runner, r=r, inline=True)
    return len(ids)


def purge_guest_jobs(pool: ConnectionPool, *, older_than: str = GUEST_JOB_AFTER) -> int:
    """Guest jobs hold public ids only; their Redis results expired after an hour."""
    with pg.public_tx(pool) as c:
        return c.execute(
            "DELETE FROM jobs WHERE user_id IS NULL AND guest_sid_hash IS NOT NULL "
            "AND created_at < now() - %s::interval", (older_than,)).rowcount


def _redis() -> redis.Redis | None:
    from perch.redisx import get_client

    return get_client() if env("PERCH_REDIS_URL") else None


@register("purge", max_attempts=5, timeout_s=600, priority=5)
def purge_handler(ctx: JobContext) -> str | None:
    action = ctx.payload["action"]
    pool, runner = ctx.pool, ctx._runner
    if action == "user":
        uid = ctx.payload.get("user_id")
        if not uid:
            raise PermanentError("invalid_input")
        try:
            crypto.shred(UUID(uid))  # idempotent: also covers a purge queued by hand
        except CryptoError:
            pass  # the keys are gone; the row clearing below is what matters
        clear_rows(pool, UUID(uid))
    elif action == "inactive":
        purge_inactive(pool, runner, _redis())
    elif action == "guests":
        purge_guest_jobs(pool)
    elif action == "jobs":
        with pg.public_tx(pool) as c:
            c.execute("DELETE FROM jobs WHERE state IN ('succeeded','failed','cancelled') "
                      "AND finished_at < now() - interval '30 days'")
    elif action == "audit":
        with pg.public_tx(pool) as c:
            c.execute("SELECT perch_null_old_actors(interval '90 days')")
    else:  # rekey and tombstones belong to the key-rotation work
        raise PermanentError("no_handler")
    return None

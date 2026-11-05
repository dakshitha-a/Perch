"""Shred hooks and the rekey hook (ARCHITECTURE_V1 section 6.6), wired at web and worker start.

crypto.shred() runs the hooks after the tombstone and key deletion. Each hook takes a user id
only. Nothing here handles user text.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import psycopg
import redis
from psycopg_pool import ConnectionPool

from perch import crypto
from perch.config import env
from perch.redisx import publish_shred
from perch.store import pg

log = logging.getLogger("perch.shred")


def shred_log_hook(pool: ConnectionPool) -> Callable[[UUID], None]:
    def hook(user_id: UUID) -> None:
        # user_tx: the web role's insert policy (migration 0007) checks perch.user_id
        with pg.user_tx(pool, user_id) as c:
            c.execute("INSERT INTO shred_log (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
                      (user_id,))
    return hook


def ledger_hook(uri: str | None = None) -> Callable[[UUID], None]:
    """One object per shred, named by user id, holding a UTC date. Dev: a mounted directory.
    An object-store URI is UNVERIFIED until a host is chosen, so only directories are written."""
    target = uri if uri is not None else env("PERCH_SHRED_LEDGER_URI")

    def hook(user_id: UUID) -> None:
        if not target or "://" in target:
            return
        p = Path(target)
        p.mkdir(parents=True, exist_ok=True)
        f = p / str(user_id)
        if not f.exists():  # an existing object is never rewritten
            f.write_text(datetime.now(UTC).date().isoformat() + "\n")
    return hook


def publish_hook(r: redis.Redis) -> Callable[[UUID], None]:
    def hook(user_id: UUID) -> None:
        publish_shred(r, user_id)
    return hook


def rekey_hook(runner: object) -> Callable[[UUID], None]:
    """Enqueue purge(action='rekey') with ids only. `runner` is a jobs.PostgresRunner."""
    def hook(user_id: UUID) -> None:
        runner.submit("purge", {"action": "rekey", "user_id": str(user_id)},  # type: ignore[attr-defined]
                      None, f"rekey:{user_id}")
    return hook


# --- the ledger is mandatory, and the restore marker (S48 review M3) ---

OPTIONAL_FLAG = "PERCH_SHRED_LEDGER_OPTIONAL"  # dev and unit tests only: "1" allows no ledger
RESTORE_MARKER = "RESTORE_PENDING"  # a file in the ledger directory; not a user id, so skipped


class LedgerMissing(RuntimeError):
    pass


def ledger_dir(uri: str | None = None) -> Path | None:
    d = uri if uri is not None else env("PERCH_SHRED_LEDGER_URI")
    return Path(d) if d and "://" not in d else None


def require_ledger(uri: str | None = None) -> Path | None:
    """The ledger is the one tombstone copy a restore of both databases cannot revert, so a
    process that can shred refuses to start without a writable ledger directory. An
    object-store URI is not written yet (UNVERIFIED), so it is refused too. Returns the
    directory, or None when the explicit dev flag allows running without one."""
    if (env(OPTIONAL_FLAG) or "") == "1":
        return ledger_dir(uri)
    raw = uri if uri is not None else env("PERCH_SHRED_LEDGER_URI")
    d = ledger_dir(uri)
    if d is None:
        raise LedgerMissing(
            "PERCH_SHRED_LEDGER_URI must name a directory on its own volume"
            + (" (object-store URIs are not supported yet)" if raw else "")
            + f"; set {OPTIONAL_FLAG}=1 only in development")
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise LedgerMissing("the shred ledger directory cannot be created") from None
    if not os.access(d, os.W_OK):
        raise LedgerMissing("the shred ledger directory is not writable")
    return d


def restore_pending(uri: str | None = None) -> bool:
    """True while the restore marker exists: a database was restored and reconcile has not run
    since. It sits on the ledger volume because a restore of either database cannot erase it."""
    d = ledger_dir(uri)
    return bool(d is not None and (d / RESTORE_MARKER).exists())


def mark_restore(uri: str | None = None) -> Path:
    d = ledger_dir(uri)
    if d is None:
        raise LedgerMissing("no shred ledger directory to hold the restore marker")
    d.mkdir(parents=True, exist_ok=True)
    m = d / RESTORE_MARKER
    m.write_text("restore pending\n")
    return m


def reconcile(keys_dsn: str, pool: ConnectionPool, ledger: str | None = None
              ) -> dict[str, int]:
    """After a restore: for every id in the tombstone union, tombstone and delete key rows
    (crypto.reconcile_shreds), then delete the user's rows in the data database
    (perch_delete_user_rows), so a restored `users` row cannot sign in again (S48 S1). Then
    clear the restore marker. Runs as perch_worker: only it may read shred_log. Counts only."""
    ids = tombstone_union(keys_dsn, pool, ledger)
    revived = crypto.reconcile_shreds(ids)
    restored = 0
    for uid in sorted(ids, key=str):
        with pg.user_tx(pool, uid) as c:  # users is fenced: a role sees its own id only
            restored += c.execute("SELECT count(*) FROM users WHERE id = %s",
                                  (uid,)).fetchone()[0]
            c.execute("SELECT perch_delete_user_rows(%s)", (uid,))
    d = ledger_dir(ledger)
    if d is not None:
        (d / RESTORE_MARKER).unlink(missing_ok=True)
    return {"ids": len(ids), "key_rows_revived": revived, "user_rows_removed": restored}


def reconcile_if_restored(keys_dsn: str | None, pool: ConnectionPool,
                          ledger: str | None = None) -> dict[str, int] | None:
    """The worker's first step: with the restore marker present, reconcile (which clears it).
    None when no restore is pending."""
    if not restore_pending(ledger):
        return None
    if not keys_dsn:
        raise LedgerMissing("a restore is pending and PERCH_KEYS_DATABASE_URL is not set")
    res = reconcile(keys_dsn, pool, ledger)
    log.info("restore reconciled ids=%d key_rows=%d user_rows=%d", res["ids"],
             res["key_rows_revived"], res["user_rows_removed"])
    return res


def install(pool: ConnectionPool, r: redis.Redis | None, runner: object | None = None,
            *, require: bool = True) -> Callable[[], None]:
    """crypto.configure with the three shred hooks and the rekey hook; if Redis is present,
    also listen on perch:shred so this process evicts a shredded user's cached key.
    Refuses (LedgerMissing) without a ledger directory unless the dev flag is set.
    Returns a stop function for the listener."""
    from perch.redisx import listen_shreds

    if require:
        require_ledger()

    hooks: list[Callable[[UUID], None]] = [shred_log_hook(pool), ledger_hook()]
    stop: Callable[[], None] = lambda: None  # noqa: E731
    if r is not None:
        hooks.append(publish_hook(r))
        stop = listen_shreds(r, crypto.evict_user)
    crypto.configure(shred_hooks=hooks, rekey_hook=rekey_hook(runner) if runner else None)
    return stop


def tombstone_union(keys_dsn: str, pool: ConnectionPool, ledger: str | None = None) -> set[UUID]:
    """The union of the three tombstone sources: key_tombstones, shred_log, ledger objects."""
    ids: set[UUID] = set()
    with psycopg.connect(keys_dsn) as c:
        ids |= {row[0] for row in c.execute("SELECT user_id FROM key_tombstones")}
    with pool.connection() as c:
        ids |= {row[0] for row in c.execute("SELECT user_id FROM shred_log")}
    d = ledger if ledger is not None else env("PERCH_SHRED_LEDGER_URI")
    if d and "://" not in d and Path(d).is_dir():
        for f in Path(d).iterdir():
            try:
                ids.add(UUID(f.name))
            except ValueError:
                continue
    return ids

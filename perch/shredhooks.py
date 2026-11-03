"""Shred hooks and the rekey hook (ARCHITECTURE_V1 section 6.6), wired at web and worker start.

crypto.shred() runs the hooks after the tombstone and key deletion. Each hook takes a user id
only. Nothing here handles user text.
"""

from __future__ import annotations

import logging
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

log = logging.getLogger("perch.shred")


def shred_log_hook(pool: ConnectionPool) -> Callable[[UUID], None]:
    def hook(user_id: UUID) -> None:
        with pool.connection() as c:
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


def install(pool: ConnectionPool, r: redis.Redis | None, runner: object | None = None
            ) -> Callable[[], None]:
    """crypto.configure with the three shred hooks and the rekey hook; if Redis is present,
    also listen on perch:shred so this process evicts a shredded user's cached key.
    Returns a stop function for the listener."""
    from perch.redisx import listen_shreds

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

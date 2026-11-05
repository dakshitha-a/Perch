"""Caches for model text and stage output on public inputs (ARCHITECTURE_V1 section 5).

Rule: a cache here holds only what depends on public records. `is_public_input` is the gate
and every writer calls it first. Text made from a user's CV, entries, documents or private
direction text is never put here, in Redis or in a log; it lives in that user's encrypted rows.

Storage: the `public_cache` table is the truth (TTL in `expires_at`, `ingest_epoch` for the
`precache` namespace). Redis keeps a hot copy under `perch:mt:<key>` for a day; a Redis flush
loses nothing. `value` and `meta` are JSON built from ids, scores and validated model text.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from redis import Redis

from perch.store import pg

log = logging.getLogger("perch.cache")

KEY_PREFIX = "perch-cache-v1"
REDIS_PREFIX = "perch:mt:"
REDIS_TTL_S = 86_400
WEEK_S = 7 * 86_400
NAMESPACES = ("fit", "profile_summary", "author", "precache")
# Seconds to live; None means no expiry (a changed input changes the key, or the epoch does).
TTL_S: dict[str, int | None] = {"fit": None, "profile_summary": WEEK_S, "author": WEEK_S,
                                "precache": None}


def cache_key(namespace: str, *parts: str) -> str:
    """sha256 hex of 'perch-cache-v1|' + namespace + '|' + '|'.join(parts)"""
    if namespace not in NAMESPACES:
        raise ValueError(f"unknown cache namespace {namespace!r}")
    return hashlib.sha256(f"{KEY_PREFIX}|{namespace}|{'|'.join(parts)}".encode()).hexdigest()


@dataclass(frozen=True)
class InputContext:
    """What a model call reads. Any True field makes the call user-dependent."""

    reads_user_data: bool = False
    cv: bool = False
    entries: bool = False
    documents: bool = False
    direction_text: bool = False
    free_text_constraint: bool = False  # an unlinked free-text constraint


def is_public_input(ctx: InputContext) -> bool:
    return not (ctx.reads_user_data or ctx.cv or ctx.entries or ctx.documents
                or ctx.direction_text or ctx.free_text_constraint)


def profile_hash(author_id: str, work_ids: list[str], as_of: str,
                 thread_work_ids: list[list[str]]) -> str:
    """sha256 of the canonical JSON of the author, sorted works, as-of date and threads."""
    doc = {"author": author_id, "work_ids": sorted(work_ids), "as_of": as_of,
           "threads": sorted(sorted(t) for t in thread_work_ids)}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
                          ).hexdigest()


def text_profile_hash(author_id: str, work_ids: list[str],
                      thread_work_ids: list[list[str]]) -> str:
    """`profile_hash` without the as-of date, for the keys of model text (the profile summary
    and the fit explanations). That text reads the works and threads, not the date, so the
    same papers keep the same text from one day to the next (S49 M5). The pre-cache key of a
    ranking keeps the date."""
    doc = {"author": author_id, "work_ids": sorted(work_ids),
           "threads": sorted(sorted(t) for t in thread_work_ids)}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
                          ).hexdigest()


class PublicCache:
    """`public_cache` rows with an optional Redis hot copy. Failures are misses, never errors."""

    def __init__(self, pool: ConnectionPool, redis_client: Redis | None = None) -> None:
        self.pool = pool
        self.redis = redis_client

    def get(self, namespace: str, key: str, *, epoch: int | None = None) -> dict | None:
        """The stored value, or None. `epoch` (precache) must equal the row's ingest epoch."""
        try:
            if self.redis is not None and epoch is None:
                hot = self.redis.get(REDIS_PREFIX + key)
                if hot is not None:
                    return json.loads(hot)
            with pg.public_tx(self.pool) as c:
                row = c.execute(
                    "SELECT value, ingest_epoch, expires_at FROM public_cache WHERE key = %s "
                    "AND namespace = %s", (key, namespace)).fetchone()
            if row is None:
                return None
            value, row_epoch, expires = row
            if expires is not None and expires <= datetime.now(UTC):
                return None
            if epoch is not None and row_epoch != epoch:
                return None
            self._hot(namespace, key, value)
            return value
        except Exception as e:  # noqa: BLE001 - a cache miss must not fail a brief
            log.warning("cache read failed ns=%s err=%s", namespace, type(e).__name__)
            return None

    def put(self, namespace: str, key: str, value: dict, meta: dict, *,
            epoch: int = 0) -> None:
        """Store `value` for `key`. The caller has checked `is_public_input` and validation."""
        ttl = TTL_S[namespace]
        expires = datetime.now(UTC) + timedelta(seconds=ttl) if ttl else None
        try:
            with pg.public_tx(self.pool) as c:
                c.execute(
                    "INSERT INTO public_cache (key, namespace, value, meta, ingest_epoch, "
                    "expires_at) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (key) DO UPDATE "
                    "SET value = EXCLUDED.value, meta = EXCLUDED.meta, "
                    "ingest_epoch = EXCLUDED.ingest_epoch, created_at = now(), "
                    "expires_at = EXCLUDED.expires_at",
                    (key, namespace, Jsonb(value), Jsonb(meta), epoch, expires))
            self._hot(namespace, key, value)
        except Exception as e:  # noqa: BLE001
            log.warning("cache write failed ns=%s err=%s", namespace, type(e).__name__)

    def _hot(self, namespace: str, key: str, value: dict) -> None:
        if self.redis is None or namespace == "precache":  # precache is epoch-checked in SQL
            return
        try:
            self.redis.set(REDIS_PREFIX + key, json.dumps(value), ex=REDIS_TTL_S)
        except Exception:  # noqa: BLE001
            pass

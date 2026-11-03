"""Postgres connection pool and the three transaction helpers (ARCHITECTURE_V1 section 2.1).

Each helper opens one transaction. `user_tx` and `guest_tx` set the session variables the
row-level-security policies read, with SET LOCAL semantics, so they vanish at commit.
`public_tx` sets nothing: a fenced table read through it returns zero rows.

Nothing here logs a query or a parameter.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from perch.config import env

EMBED_DIM = 1024  # Qwen3-Embedding-0.6B hidden size; a different embedder needs a new migration


def _configure(conn: psycopg.Connection) -> None:
    register_vector(conn)
    conn.commit()


def make_pool(dsn: str | None = None, max_size: int | None = None) -> ConnectionPool:
    """A pool of PERCH_DB_POOL_MAX connections (default 10) for the given URL."""
    url = dsn or env("PERCH_DATABASE_URL")
    if not url:
        raise RuntimeError("PERCH_DATABASE_URL is not set")
    size = max_size or int(env("PERCH_DB_POOL_MAX", "10") or 10)
    return ConnectionPool(url, min_size=1, max_size=size, configure=_configure, open=True)


@contextmanager
def public_tx(pool: ConnectionPool) -> Iterator[psycopg.Connection]:
    with pool.connection() as conn:
        yield conn


@contextmanager
def user_tx(pool: ConnectionPool, user_id: UUID | str) -> Iterator[psycopg.Connection]:
    with pool.connection() as conn:
        conn.execute("SELECT set_config('perch.user_id', %s, true)", (str(user_id),))
        yield conn


@contextmanager
def guest_tx(pool: ConnectionPool, sid_hash: bytes) -> Iterator[psycopg.Connection]:
    with pool.connection() as conn:
        conn.execute("SELECT set_config('perch.guest_sid_hash', %s, true)", (sid_hash.hex(),))
        yield conn

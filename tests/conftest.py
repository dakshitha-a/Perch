"""Postgres test fixtures. Tests that need Postgres skip when PERCH_TEST_DATABASE_URL is unset.

PERCH_TEST_DATABASE_URL is a superuser URL (make test-pg defaults it). Each run creates its
own database named perch_test_a_<hex> and drops it at the end; no other database is touched.
The roles are cluster-wide, so the fixture only sets their passwords.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import pytest

PG_URL = os.environ.get("PERCH_TEST_DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _shred_ledger_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    """Web and worker refuse to start without a shred ledger (S48 M3). Unit tests run without
    one through the explicit dev flag; tests of the ledger itself delete the flag."""
    monkeypatch.setenv("PERCH_SHRED_LEDGER_OPTIONAL", "1")
ROLE_PW = "perchtest-role"  # test-only; the server is local and disposable


def _with(url: str, user: str | None = None, password: str | None = None,
          dbname: str | None = None) -> str:
    p = urlsplit(url)
    host = p.hostname or "127.0.0.1"
    netloc = f"{host}:{p.port}" if p.port else host
    if user:
        netloc = f"{user}:{password}@{netloc}"
    elif p.username:
        netloc = f"{p.username}:{p.password}@{netloc}"
    return urlunsplit((p.scheme, netloc, f"/{dbname}" if dbname else p.path, "", ""))


@dataclass
class PgDb:
    admin: str
    web: str
    worker: str
    owner: str
    name: str


@pytest.fixture(scope="session")
def pgdb() -> Iterator[PgDb]:
    if not PG_URL:
        pytest.skip("PERCH_TEST_DATABASE_URL is not set")
    import psycopg

    from perch.db.migrate import migrate

    name = f"perch_test_a_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(PG_URL, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    admin = _with(PG_URL, dbname=name)
    migrate(admin)
    with psycopg.connect(admin, autocommit=True) as c:
        for role in ("perch_owner", "perch_web", "perch_worker"):
            c.execute(f"ALTER ROLE {role} PASSWORD '{ROLE_PW}'")
    try:
        yield PgDb(admin=admin, name=name,
                   web=_with(PG_URL, "perch_web", ROLE_PW, name),
                   worker=_with(PG_URL, "perch_worker", ROLE_PW, name),
                   owner=_with(PG_URL, "perch_owner", ROLE_PW, name))
    finally:
        with psycopg.connect(PG_URL, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def pg_clean(pgdb: PgDb) -> PgDb:
    """The shared test database, emptied of rows before each test."""
    import psycopg

    with psycopg.connect(pgdb.admin, autocommit=True) as c:
        c.execute("TRUNCATE records, record_vectors, users, consents, user_data, jobs, "
                  "job_events, audit_log, spend_ledger, public_cache, shred_log, ingest_runs, "
                  "worker_heartbeat CASCADE")
        # Roles are cluster-wide and tests/test_jobs_pg.py sets other passwords on them.
        for role in ("perch_owner", "perch_web", "perch_worker"):
            c.execute(f"ALTER ROLE {role} PASSWORD '{ROLE_PW}'")
    return pgdb


# --- user-data fixtures (S41 part B) ---

@pytest.fixture
def keys():
    from perch import crypto
    from perch.keystore import EnvKeyStore, InMemoryKeyRepository
    from tests.user_helpers import make_env

    r = InMemoryKeyRepository()
    crypto.configure(repo=r, keystore=EnvKeyStore(make_env()))
    yield r
    crypto.configure()


@pytest.fixture
def web_pool(pg_clean: PgDb):
    from perch.store import pg

    p = pg.make_pool(pg_clean.web, 4)
    yield p
    p.close()


@pytest.fixture
def worker_pool(pg_clean: PgDb):
    from perch.store import pg

    p = pg.make_pool(pg_clean.worker, 4)
    yield p
    p.close()


@pytest.fixture
def ud(web_pool, keys):
    from perch.user.data import UserData

    return UserData(web_pool)

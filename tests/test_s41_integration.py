"""S41 integration: startup wiring, consent, last_active and idempotency. SYNTHETIC text only.

Needs PERCH_TEST_DATABASE_URL and PERCH_TEST_REDIS_URL (DB 15); run by `make test-user`.
The fixtures are those of tests/test_user_account.py.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, date, datetime

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from perch import crypto, jobs
from perch.auth import deps, settings
from perch.auth.base import Identity
from perch.auth.session import Session, SessionStore
from perch.keystore import EnvKeyStore, InMemoryKeyRepository
from perch.user import docs
from perch.user.routes import UserServices
from tests.conftest import PG_URL
from tests.test_api import make
from tests.test_user_account import (  # noqa: F401 - fixtures
    REDIS_URL,
    env,
    job_state,
    rds,
    run_worker,
    sql,
)
from tests.user_helpers import make_env, new_user

pytestmark = [pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set"),
              pytest.mark.skipif(not REDIS_URL, reason="PERCH_TEST_REDIS_URL is not set")]
KEY = "A5026494099"
ASOF = date(2026, 10, 28)


class DownKeys(InMemoryKeyRepository):
    def is_tombstoned(self, user_id):  # noqa: ANN001, ANN201
        raise RuntimeError("keys database is down")


def test_startup_builds_user_services_and_readiness_reports_keys(
        pg_clean, rds, keys, monkeypatch):  # noqa: F811
    from perch.auth.openalex_link import UserDataLinkStore
    from perch.auth.wiring import build_state, close_state, install_auth, readiness

    monkeypatch.setenv("PERCH_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("PERCH_DATABASE_URL", pg_clean.web)
    for k in ("PERCH_KEYS_DATABASE_URL", "PERCH_MASTER_KEY"):
        monkeypatch.delenv(k, raising=False)
    app = FastAPI()
    install_auth(app)
    build_state(app)
    try:
        assert getattr(app.state, "user_services", None) is None  # no key store configured
        assert readiness(app)["keys"] == "not_configured"
    finally:
        close_state(app)
    monkeypatch.setenv("PERCH_KEYS_DATABASE_URL", "postgresql://unused.invalid/perch_keys")
    monkeypatch.setenv("PERCH_MASTER_KEY", "unused")
    app = FastAPI()
    install_auth(app)
    build_state(app)
    try:
        sv = app.state.user_services
        assert isinstance(sv, UserServices) and sv.ud.pool is app.state.pool
        assert isinstance(app.state.openalex_links, UserDataLinkStore)
        crypto.configure(repo=InMemoryKeyRepository(), keystore=EnvKeyStore(make_env()))
        # (install() reset it above, so configure after build_state)
        got = readiness(app)
        assert got["keys"] == "ok" and got["ready"] is True  # the in-memory repo answers
        crypto.configure(repo=DownKeys(), keystore=EnvKeyStore(make_env()))
        got = readiness(app)
        assert got["keys"] == "down" and got["ready"] is False
    finally:
        close_state(app)


def test_cv_and_entry_routes_need_consent(env):  # noqa: F811
    env.session.consent_version = 0
    assert env.client.get("/me/docs").status_code == 403
    r = env.client.post("/me/docs", json={"kind": "entry", "text": "SYNTHETIC entry text."})
    assert r.status_code == 403 and r.json()["detail"] == "consent_required"
    assert env.ud.count(env.uid) == 0  # nothing was written
    env.session.consent_version = 1
    ok = env.client.post("/me/docs", json={"kind": "entry", "text": "SYNTHETIC entry text."})
    assert ok.status_code == 200
    env.session.consent_version = 0  # withdrawn: the user can still remove what is stored
    assert env.client.delete(f"/me/docs/{ok.json()['id']}").status_code == 200


def test_brief_request_with_documents_needs_consent(env, tmp_path):  # noqa: F811
    from fastapi import HTTPException

    from perch.user.briefs import submit_brief

    _, svc = make(tmp_path)
    doc = docs.add(env.ud, env.uid, "student", "proposal", text="SYNTHETIC proposal text.")
    env.session.consent_version = 0
    with pytest.raises(HTTPException) as e:
        submit_brief(svc, env.runner, env.ud, env.r, env.session, KEY, doc_ids=[doc], as_of=ASOF)
    assert e.value.status_code == 403 and e.value.detail == "consent_required"
    assert sql(env.pg, "SELECT count(*) FROM jobs") == [(0,)]
    assert sql(env.pg, "SELECT count(*) FROM user_data WHERE kind = 'brief'") == [(0,)]


def test_brief_job_fails_as_consent_required_when_consent_is_missing_or_withdrawn(
        env, tmp_path, monkeypatch):  # noqa: F811
    from perch.auth import accounts
    from perch.user.briefs import submit_brief

    monkeypatch.setenv("PERCH_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("PERCH_CONSENT_PROVIDER_NAME", "SYNTHETIC Provider")
    _, svc = make(tmp_path)
    doc = docs.add(env.ud, env.uid, "student", "proposal", text="SYNTHETIC proposal text.")
    env.session.consent_version = 1  # the session says yes; the job asks the database

    def run(key: str):
        _, j = submit_brief(svc, env.runner, env.ud, env.r, env.session, KEY, doc_ids=[doc],
                            as_of=ASOF, idempotency_key=key)
        run_worker(env.pg, ["brief"], lambda: job_state(env.pg, j) in ("succeeded", "failed"))
        return sql(env.pg, "SELECT state, error_code FROM jobs WHERE id = %s", j)[0]

    jobs.set_brief_service(lambda: svc)
    try:
        assert run("k-none") == ("failed", "consent_required")  # no consents row yet
        accounts.add_consent(env.pool, env.uid, 1, "SYNTHETIC Provider")
        assert run("k-ok")[0] == "succeeded"
        accounts.withdraw_consent(env.pool, env.uid)
        assert run("k-withdrawn") == ("failed", "consent_required")
    finally:
        jobs._brief_service = None


def test_signed_in_requests_stamp_last_active_once_a_day(env, pg_clean, rds, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PERCH_COOKIE_INSECURE", "1")
    store = SessionStore(rds)
    app = FastAPI()
    app.state.sessions = store
    app.state.user_services = env.client.app.state.user_services

    @app.get("/ping")
    async def ping(s=Depends(deps.session_optional)) -> dict:  # noqa: ANN001
        return {"ok": True}

    s = asyncio.run(store.create_user(env.uid, {"student"}, Identity("i", "s", None, {})))
    sql(pg_clean, "UPDATE users SET last_active_at = now() - interval '5 days' WHERE id = %s",
        env.uid)
    c = TestClient(app)
    c.cookies.set(settings.session_cookie_name(), s.sid)
    assert c.get("/ping").status_code == 200
    stamp = sql(pg_clean, "SELECT last_active_at FROM users WHERE id = %s", env.uid)[0][0]
    assert (datetime.now(UTC) - stamp).total_seconds() < 60
    sql(pg_clean, "UPDATE users SET last_active_at = now() - interval '5 days' WHERE id = %s",
        env.uid)
    assert c.get("/ping").status_code == 200  # same day: throttled
    assert (datetime.now(UTC) - sql(pg_clean, "SELECT last_active_at FROM users WHERE id = %s",
                                    env.uid)[0][0]).days >= 4
    guest = asyncio.run(store.create_guest("student"))
    g = TestClient(app)
    g.cookies.set(settings.session_cookie_name(), guest.sid)
    assert g.get("/ping").status_code == 200  # a guest writes nothing


def _session(user, sid: str, **kw) -> Session:  # noqa: ANN001
    return Session(sid=sid, user_id=user, guest=user is None, roles=frozenset(),
                   audience=kw.get("audience", "researcher"), csrf="c", display_name=None,
                   created=time.time(), abs_exp=time.time() + 3600,
                   consent_version=kw.get("consent", 0))


def test_a_repeated_brief_request_returns_the_same_brief_and_creates_nothing(
        env, pg_clean, tmp_path):  # noqa: F811
    from perch.user.briefs import submit_brief

    _, svc = make(tmp_path)
    s = _session(env.uid, "s1", consent=1)

    def go(sess, text="SYNTHETIC direction text"):
        return submit_brief(svc, env.runner, env.ud, env.r, sess, KEY, as_of=ASOF,
                            context={"direction": text})

    first = go(s)
    assert go(s) == first
    assert sql(pg_clean, "SELECT count(*) FROM jobs") == [(1,)]
    assert sql(pg_clean, "SELECT count(*) FROM user_data WHERE kind = 'brief'") == [(1,)]
    assert go(s, "SYNTHETIC another direction")[0] != first[0]
    assert sql(pg_clean, "SELECT count(*) FROM jobs") == [(2,)]
    assert sql(pg_clean, "SELECT count(*) FROM jobs WHERE idempotency_key LIKE %s",
               "%SYNTHETIC%") == [(0,)]  # the key is a hash, never the text
    other = _session(new_user(pg_clean), "s2", consent=1)  # another user: a brief of their own
    assert go(other)[0] != first[0]
    env.runner.cancel(first[1], env.uid)  # a cancelled job frees its key
    assert go(s)[0] != first[0]


def test_a_repeated_guest_request_returns_the_same_brief(env, pg_clean, tmp_path):  # noqa: F811
    from perch.user.briefs import submit_brief

    _, svc = make(tmp_path)
    g = _session(None, "g-1")
    first = submit_brief(svc, env.runner, env.ud, env.r, g, KEY, as_of=ASOF)
    assert submit_brief(svc, env.runner, env.ud, env.r, g, KEY, as_of=ASOF) == first
    assert sql(pg_clean, "SELECT count(*) FROM jobs") == [(1,)]
    assert len(list(env.r.scan_iter("perch:gsess:*:brief:*"))) == 1
    g2 = _session(None, "g-2")
    assert submit_brief(svc, env.runner, env.ud, env.r, g2, KEY, as_of=ASOF)[0] != first[0]

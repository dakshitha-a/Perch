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
    assert env.client.get("/me/docs").status_code == 200  # listing needs no consent (S43 M6)
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
    env.session.audience = "researcher"  # a researcher brief reads the author and the proposal
    doc = docs.add(env.ud, env.uid, "researcher", "proposal", text="SYNTHETIC proposal text.")
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


# --- keep, dismiss, restore and compare on the session path (S43 fork F3) ---

def _session_app(env, tmp_path, sess):  # noqa: ANN001, ANN202, F811
    c, svc = make(tmp_path)
    c.app.state.user_services = UserServices(pool=env.pool, ud=env.ud, runner=env.runner,
                                             redis=env.r)
    c.app.dependency_overrides[deps.session_optional] = lambda request=None: sess
    c.app.dependency_overrides[deps.require_csrf] = lambda: None
    return c, svc


def _leads(c, bid):  # noqa: ANN001, ANN202
    return {x["lead"]["id"] if "lead" in x else x["id"]: x["status"]
            for x in c.get(f"/briefs/{bid}").json()["leads"]}


def test_guest_keeps_dismisses_and_compares_on_its_redis_brief(env, tmp_path):  # noqa: F811
    from perch.user.briefs import GuestBriefStore, create_guest_brief, guest_hash, using_store

    g = _session(None, "g-keep")
    c, svc = _session_app(env, tmp_path, g)
    gh = guest_hash(g.sid)
    b = create_guest_brief(svc, env.r, gh, KEY, as_of=ASOF)
    job = "00000000-0000-0000-0000-00000000f003"
    store = GuestBriefStore(env.r, gh, b.id, job)  # type: ignore[arg-type]
    assert store.load()
    with using_store(store):
        assert svc.run(b.id) == "done"
    env.r.set(f"perch:gsess:{gh}:job:{b.id}", job, ex=3600)  # what the web layer records
    lead = next(iter(_leads(c, b.id)))
    env.r.expire(f"perch:gres:{job}", 1200)

    assert c.post(f"/briefs/{b.id}/leads/{lead}/keep").json()["status"] == "kept"
    assert _leads(c, b.id)[lead] == "kept"
    assert 0 < env.r.ttl(f"perch:gres:{job}") <= 1200  # a write does not grant a new hour
    rows = c.get(f"/briefs/{b.id}/compare").json()
    assert len(rows["rows"]) == 1
    assert c.post(f"/briefs/{b.id}/leads/{lead}/dismiss").json()["status"] == "dismissed"
    assert c.get(f"/briefs/{b.id}/compare").json()["rows"] == []
    assert c.post(f"/briefs/{b.id}/leads/{lead}/restore").json()["status"] == "new"
    assert c.post(f"/briefs/{b.id}/leads/nope/keep").status_code == 404
    assert c.post(f"/briefs/not-mine/leads/{lead}/keep").status_code == 404
    other = _session(None, "g-other")  # another guest cannot reach this brief
    c.app.dependency_overrides[deps.session_optional] = lambda request=None: other
    assert c.post(f"/briefs/{b.id}/leads/{lead}/keep").status_code == 404
    assert c.get(f"/briefs/{b.id}/compare").status_code == 404
    assert sql(env.pg, "SELECT count(*) FROM user_data") == [(0,)]  # nothing stored for a guest


def test_keep_and_compare_need_a_session_and_csrf_when_accounts_are_on(
        env, tmp_path, monkeypatch):  # noqa: F811
    c, _ = _session_app(env, tmp_path, None)
    c.app.dependency_overrides.clear()  # the real session and CSRF checks
    store = SessionStore(env.r)
    c.app.state.sessions = store
    monkeypatch.setenv("PERCH_PUBLIC_URL", "http://testserver")
    assert c.post("/briefs/b1/leads/l1/keep").status_code == 401  # no session at all
    assert c.get("/briefs/b1/compare").status_code == 401
    g = asyncio.run(store.create_guest("researcher"))
    c.cookies.set(settings.session_cookie_name(), g.sid)
    assert c.post("/briefs/b1/leads/l1/keep").status_code == 403  # no Origin
    bad = {"Origin": "http://testserver", "X-CSRF-Token": "wrong"}
    assert c.post("/briefs/b1/leads/l1/keep", headers=bad).status_code == 403
    good = {"Origin": "http://testserver", "X-CSRF-Token": g.csrf}
    assert c.post("/briefs/b1/leads/l1/keep", headers=good).status_code == 404  # past CSRF
    assert c.get("/briefs/b1/compare").status_code == 404  # a GET needs no token


def test_a_signed_in_user_keeps_and_compares_on_the_encrypted_brief(env, tmp_path):  # noqa: F811
    from perch.user.briefs import UserBriefStore, create_user_brief, using_store

    s = _session(env.uid, "s-keep", consent=1)
    c, svc = _session_app(env, tmp_path, s)
    b = create_user_brief(svc, env.ud, env.uid, "researcher", KEY, as_of=ASOF)
    store = UserBriefStore(env.ud, env.uid, "researcher", b.id)
    assert store.load()
    with using_store(store):
        assert svc.run(b.id) == "done"
    lead = next(iter(_leads(c, b.id)))
    assert c.post(f"/briefs/{b.id}/leads/{lead}/keep").json()["status"] == "kept"
    assert _leads(c, b.id)[lead] == "kept"
    assert len(c.get(f"/briefs/{b.id}/compare").json()["rows"]) == 1
    assert c.post(f"/briefs/{b.id}/leads/{lead}/dismiss").json()["status"] == "dismissed"
    stranger = _session(new_user(env.pg), "s-x", consent=1)  # another user: 404, never 403
    c.app.dependency_overrides[deps.session_optional] = lambda request=None: stranger
    assert c.post(f"/briefs/{b.id}/leads/{lead}/keep").status_code == 404
    assert c.get(f"/briefs/{b.id}/compare").status_code == 404

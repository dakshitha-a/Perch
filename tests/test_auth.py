# ruff: noqa: E501, B008
"""Sessions, CSRF, guest mode, roles, consent and the OpenAlex link (ARCHITECTURE_V1 section 7).

All identities are SYNTHETIC. The IdP is a fake provider here; the real OIDC flow is in
tests/test_oidc.py. Redis tests need PERCH_TEST_REDIS_URL (DB 15 only); the tests that touch
accounts also need PERCH_TEST_DATABASE_URL and skip without it.
"""

from __future__ import annotations

import base64
import os
import uuid
from collections.abc import Mapping

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from perch import crypto
from perch import redisx as rx
from perch.auth import settings
from perch.auth.base import AuthError, AuthProvider, AuthRedirect, Identity
from perch.auth.deps import (
    require_consent,
    require_csrf,
    require_role,
    require_session,
    require_user,
)
from perch.auth.session import Session, SessionStore, guest_sid_hash
from perch.auth.wiring import install_auth, readiness
from perch.keystore import EnvKeyStore, InMemoryKeyRepository

URL = os.environ.get("PERCH_TEST_REDIS_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="PERCH_TEST_REDIS_URL is not set")
ORIGIN = "http://testserver"
IDENT = Identity("http://idp.invalid/realms/x", "sub-1", "SYNTHETIC User", {})


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERCH_PUBLIC_URL", ORIGIN)
    monkeypatch.setenv("PERCH_COOKIE_INSECURE", "1")
    monkeypatch.setenv("PERCH_PEPPER", base64.b64encode(b"p" * 32).decode())
    monkeypatch.setenv("PERCH_PEPPER_GUEST", base64.b64encode(b"g" * 32).decode())
    monkeypatch.setenv("PERCH_CONSENT_VERSION", "1")
    monkeypatch.setenv("PERCH_CONSENT_PROVIDER_NAME", "SYNTHETIC Provider")
    monkeypatch.delenv("PERCH_ENV", raising=False)
    monkeypatch.delenv("PERCH_RATE_LIMITS", raising=False)


@pytest.fixture
def r():
    assert URL.rstrip("/").endswith("/15"), "tests use Redis DB 15 only"
    c = rx.get_client(URL)
    c.flushdb()
    yield c
    c.flushdb()
    c.close()


class FakeProvider(AuthProvider):
    name = "fake"

    def __init__(self) -> None:
        self.subject = f"sub-{uuid.uuid4().hex}"

    async def begin(self, return_to: str) -> AuthRedirect:
        return AuthRedirect("http://idp.invalid/auth?x=1", "st", "binder-1")

    async def complete(self, params: Mapping[str, str], binder: str | None):
        if binder != "binder-1":
            raise AuthError("binder_mismatch")
        return Identity("http://idp.invalid/realms/x", self.subject, "SYNTHETIC User", {}), \
            params.get("rt", "/")

    async def end_session_url(self, post_logout_redirect: str) -> str | None:
        return "http://idp.invalid/logout?r=" + post_logout_redirect


def make_app(r, pool=None, provider=None, lookup=None, links=None) -> FastAPI:
    app = FastAPI()
    install_auth(app)
    app.state.sessions = SessionStore(r)
    app.state.pool = pool
    app.state.auth_provider = provider
    app.state.author_lookup = lookup
    app.state.openalex_links = links

    @app.get("/t/session")
    async def t_session(s: Session = Depends(require_session)) -> dict:
        return {"sid": s.sid}

    @app.get("/t/user")
    async def t_user(s: Session = Depends(require_user)) -> dict:
        return {"uid": str(s.user_id)}

    @app.get("/t/researcher")
    async def t_role(s: Session = Depends(require_role("researcher"))) -> dict:
        return {"ok": True}

    @app.post("/t/write", dependencies=[Depends(require_csrf)])
    async def t_write() -> dict:
        return {"ok": True}

    @app.get("/t/consent")
    async def t_consent(s: Session = Depends(require_user)) -> dict:
        require_consent(s)
        return {"ok": True}

    return app


def user_client(app: FastAPI, roles=("researcher",), consent: int = 0) -> tuple[TestClient, Session]:
    import asyncio

    store: SessionStore = app.state.sessions
    s = asyncio.run(store.create_user(uuid.uuid4(), set(roles), IDENT, consent_version=consent))
    c = TestClient(app)
    c.cookies.set(settings.session_cookie_name(), s.sid)
    return c, s


def guest_client(app: FastAPI) -> tuple[TestClient, dict]:
    c = TestClient(app)
    resp = c.post("/auth/guest", headers={"Origin": ORIGIN})
    assert resp.status_code == 200, resp.text
    return c, resp.json()


# --- guest mode (7.4) ---

def test_guest_session_has_no_user_and_a_fixed_ttl(r) -> None:
    app = make_app(r)
    c, body = guest_client(app)
    sid = c.cookies.get("perch_sid")
    h = r.hgetall(f"perch:sess:{sid}")
    assert h["guest"] == "1" and h["uid"] == "" and h["roles"] == ""
    assert h["gsid_hash"] == rx.hash_subject(sid)
    assert guest_sid_hash(sid).hex() == h["gsid_hash"]
    assert 3500 < r.ttl(f"perch:sess:{sid}") <= 3600  # PERCH_GUEST_TTL_S default
    assert r.keys("perch:usess:*") == []  # not tracked as a user's session
    assert body["guest"] is True and body["csrf"] == h["csrf"]
    before = r.ttl(f"perch:sess:{sid}")
    assert c.get("/t/session").status_code == 200
    assert r.ttl(f"perch:sess:{sid}") <= before  # a guest never slides


def test_guest_needs_same_origin_but_not_a_csrf_token(r) -> None:
    c = TestClient(make_app(r))
    assert c.post("/auth/guest").status_code == 403
    assert c.post("/auth/guest", headers={"Origin": "http://evil.invalid"}).status_code == 403
    assert c.post("/auth/guest", headers={"Origin": ORIGIN}).status_code == 200
    assert r.keys("perch:sess:*") and len(r.keys("perch:sess:*")) == 1


def test_guest_cannot_reach_user_routes(r) -> None:
    app = make_app(r)
    c, body = guest_client(app)
    h = {"Origin": ORIGIN, "X-CSRF-Token": body["csrf"]}
    assert c.get("/t/session").status_code == 200
    assert c.get("/t/user").status_code == 403
    assert c.get("/t/researcher").status_code == 403
    for method, path, payload in [("POST", "/me/consent", {}), ("POST", "/me/consent/withdraw", {}),
                                  ("POST", "/me/roles", {"roles": ["student"]}),
                                  ("POST", "/me/audience", {"audience": "student"}),
                                  ("PUT", "/me/openalex", {"author_id": "A5000000001"})]:
        resp = c.request(method, path, json=payload, headers=h)
        assert resp.status_code == 403 and resp.json()["detail"] == "account_required", path
    me = c.get("/auth/session").json()
    assert me["guest"] is True and me["signed_in"] is False and "consent" not in me


def test_guest_session_creation_is_rate_limited(r, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERCH_GUEST_SESSIONS_PER_ADDRESS_HOUR", "2")
    c = TestClient(make_app(r))
    codes = [c.post("/auth/guest", headers={"Origin": ORIGIN}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# --- dependencies ---

def test_no_session_is_401_and_store_missing_is_401() -> None:
    app = FastAPI()
    install_auth(app)

    @app.get("/t")
    async def t(s: Session = Depends(require_session)) -> dict:
        return {}

    assert TestClient(app).get("/t").status_code == 401


def test_unknown_and_malformed_sids_are_no_session(r) -> None:
    c = TestClient(make_app(r))
    c.cookies.set("perch_sid", "nope")
    assert c.get("/t/session").status_code == 401
    c.cookies.set("perch_sid", "x" * 500)
    assert c.get("/t/session").status_code == 401


def test_roles_gate(r) -> None:
    app = make_app(r)
    c, _ = user_client(app, roles=("student",))
    assert c.get("/t/user").status_code == 200
    assert c.get("/t/researcher").status_code == 403
    c2, _ = user_client(app, roles=("researcher",))
    assert c2.get("/t/researcher").status_code == 200


# --- CSRF (7.3) ---

def test_csrf_header_and_origin_are_both_required(r) -> None:
    app = make_app(r)
    c, s = user_client(app)
    ok = {"Origin": ORIGIN, "X-CSRF-Token": s.csrf}
    assert c.post("/t/write", headers=ok).status_code == 200
    assert c.post("/t/write", headers={"Origin": ORIGIN}).status_code == 403
    assert c.post("/t/write", headers={"Origin": ORIGIN, "X-CSRF-Token": "x" * 43}).status_code == 403
    assert c.post("/t/write", headers={"X-CSRF-Token": s.csrf}).status_code == 403
    assert c.post("/t/write", headers={"Origin": "http://evil.invalid",
                                       "X-CSRF-Token": s.csrf}).status_code == 403
    assert c.post("/t/write", headers={"Origin": ORIGIN + ".evil.invalid",
                                       "X-CSRF-Token": s.csrf}).status_code == 403
    for m in ("PUT", "PATCH", "DELETE"):
        assert c.request(m, "/t/write", headers={"Origin": ORIGIN}).status_code in (403, 405)


def test_csrf_without_a_session_is_401_and_get_is_not_checked(r) -> None:
    c = TestClient(make_app(r))
    assert c.post("/t/write", headers={"Origin": ORIGIN}).status_code == 401
    cu, _ = user_client(make_app(r))
    assert cu.get("/t/user").status_code == 200  # no header needed on a GET


def test_csrf_origin_fails_closed_when_public_url_unset(r, monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_app(r)
    c, s = user_client(app)
    monkeypatch.delenv("PERCH_PUBLIC_URL")
    assert c.post("/t/write", headers={"Origin": ORIGIN, "X-CSRF-Token": s.csrf}).status_code == 403


def test_csrf_token_is_per_session_and_comes_from_the_session_route(r) -> None:
    app = make_app(r)
    c1, s1 = user_client(app)
    _, s2 = user_client(app)
    assert s1.csrf != s2.csrf and len(s1.csrf) >= 40
    assert c1.get("/auth/session").json()["csrf"] == s1.csrf
    assert c1.post("/t/write", headers={"Origin": ORIGIN, "X-CSRF-Token": s2.csrf}).status_code == 403


# --- expiry (7.3) ---

def test_idle_timeout_slides_and_is_capped_by_the_absolute_limit(r) -> None:
    import asyncio

    store = SessionStore(r)
    s = asyncio.run(store.create_user(uuid.uuid4(), {"student"}, IDENT))
    key = f"perch:sess:{s.sid}"
    assert 1700 < r.ttl(key) <= 1800
    r.expire(key, 5)
    assert asyncio.run(store.get(s.sid)) is not None
    assert 1700 < r.ttl(key) <= 1800  # slid back to the idle timeout
    assert s.abs_exp - s.created == 28800
    near = s.abs_exp - 10
    assert asyncio.run(store.get(s.sid, now=near)) is not None
    assert r.ttl(key) <= 10  # capped by the absolute expiry


def test_absolute_expiry_ends_the_session_and_cleans_up(r) -> None:
    import asyncio

    store = SessionStore(r)
    uid = uuid.uuid4()
    s = asyncio.run(store.create_user(uid, {"student"}, IDENT))
    assert asyncio.run(store.get(s.sid, now=s.abs_exp + 1)) is None
    assert not r.exists(f"perch:sess:{s.sid}")
    assert s.sid not in r.smembers(f"perch:usess:{uid}")


def test_user_session_set_and_destroy_all(r) -> None:
    import asyncio

    store = SessionStore(r)
    uid = uuid.uuid4()
    a = asyncio.run(store.create_user(uid, {"student"}, IDENT))
    b = asyncio.run(store.create_user(uid, {"student"}, IDENT))
    assert r.smembers(f"perch:usess:{uid}") == {a.sid, b.sid} and a.sid != b.sid
    assert asyncio.run(store.destroy_all(uid)) == 2
    assert asyncio.run(store.get(a.sid)) is None


def test_session_hash_holds_only_what_section_4_1_allows(r) -> None:
    import asyncio

    s = asyncio.run(SessionStore(r).create_user(uuid.uuid4(), {"student"}, IDENT))
    fields = set(r.hgetall(f"perch:sess:{s.sid}"))
    allowed = {"uid", "guest", "roles", "audience", "csrf", "name", "created", "abs_exp",
               "gsid_hash", "idle_s", "consent"}
    assert fields <= allowed


# --- consent state in the session (7.5) ---

def test_consent_requires_the_current_version(r, monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_app(r)
    c0, _ = user_client(app, consent=0)
    c1, _ = user_client(app, consent=1)
    assert c0.get("/t/consent").status_code == 403
    assert c0.get("/t/consent").json()["detail"] == "consent_required"
    assert c1.get("/t/consent").status_code == 200
    monkeypatch.setenv("PERCH_CONSENT_VERSION", "2")  # a version bump re-prompts everyone
    assert c1.get("/t/consent").status_code == 403
    me = c1.get("/auth/session").json()
    assert me["consent"]["required"] is True and me["consent"]["current_version"] == 2


# --- sign-in routes with a fake provider, no database ---

def test_login_sets_the_binder_cookie_and_redirects(r) -> None:
    c = TestClient(make_app(r, provider=FakeProvider()))
    resp = c.get("/auth/login?return_to=/x", follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"].startswith("http://idp.invalid/")
    sc = resp.headers["set-cookie"].lower()
    assert "perch_oidc=binder-1" in sc and "max-age=600" in sc
    assert "httponly" in sc and "samesite=lax" in sc and "path=/" in sc and "domain" not in sc


def test_cookie_attributes_in_production_form(r, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PERCH_COOKIE_INSECURE")
    c = TestClient(make_app(r))
    resp = c.post("/auth/guest", headers={"Origin": ORIGIN})
    sc = resp.headers["set-cookie"]
    assert sc.startswith("__Host-perch_sid=")
    low = sc.lower()
    assert "httponly" in low and "secure" in low and "samesite=lax" in low and "path=/" in low
    assert "max-age" not in low and "expires" not in low and "domain" not in low  # session cookie
    lg = TestClient(make_app(r, provider=FakeProvider())).get("/auth/login", follow_redirects=False)
    assert lg.headers["set-cookie"].startswith("__Host-perch_oidc=")


def test_prod_refuses_the_insecure_cookie_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERCH_ENV", "prod")
    with pytest.raises(RuntimeError):
        settings.cookie_insecure()


def test_login_return_to_is_made_safe(r) -> None:
    from perch.auth.base import safe_return_to

    for bad in ("//evil.invalid", "http://evil.invalid", "/\\evil", "/a\nb", "", None, "evil"):
        assert safe_return_to(bad) == "/"
    assert safe_return_to("/briefs/1?x=2") == "/briefs/1?x=2"


def test_failed_callback_is_a_fixed_code_and_clears_the_binder(r) -> None:
    app = make_app(r, pool=object(), provider=FakeProvider())
    c = TestClient(app)
    resp = c.get("/auth/callback?code=c&state=s")  # no binder cookie
    assert resp.status_code == 400 and resp.json() == {"error": "binder_mismatch"}
    assert "perch_oidc=" in resp.headers["set-cookie"]


def test_callback_is_limited_per_binder(r) -> None:
    c = TestClient(make_app(r, pool=object(), provider=FakeProvider()))
    codes = [c.get("/auth/callback?code=c&state=s").status_code for _ in range(7)]
    assert codes[:5] == [400] * 5 and codes[5:] == [429, 429]


def test_logout_needs_csrf_destroys_and_returns_the_idp_url(r) -> None:
    app = make_app(r, provider=FakeProvider())
    c, s = user_client(app)
    assert c.post("/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
    assert r.exists(f"perch:sess:{s.sid}")
    resp = c.post("/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": s.csrf})
    assert resp.status_code == 200 and resp.json()["end_session_url"].startswith("http://idp.invalid/")
    assert not r.exists(f"perch:sess:{s.sid}")
    assert 'perch_sid=""' in resp.headers["set-cookie"] or "max-age=0" in resp.headers["set-cookie"].lower()
    assert TestClient(app).post("/auth/logout").status_code == 200  # nothing to end


def test_session_route_when_signed_out(r) -> None:
    assert TestClient(make_app(r)).get("/auth/session").json() == {"signed_in": False}


def test_readiness_reports_parts(r) -> None:
    app = make_app(r)
    out = readiness(app)
    assert out["redis"] == "ok" and out["postgres"] == "not_configured" and out["ready"] is True
    app.state.sessions.r = rx.get_client("redis://127.0.0.1:1/0")
    assert readiness(app)["redis"] == "down" and readiness(app)["ready"] is False


# --- accounts (need Postgres) ---

@pytest.fixture
def acct(r, pg_clean, monkeypatch: pytest.MonkeyPatch):
    from perch.store.pg import make_pool

    crypto.configure(repo=InMemoryKeyRepository(), keystore=EnvKeyStore({
        "PERCH_MASTER_KEY": base64.b64encode(os.urandom(32)).decode(),
        "PERCH_MASTER_KEY_ID": "m1"}))
    pool = make_pool(pg_clean.web, 3)
    prov = FakeProvider()
    known = {"A5000000001"}

    def lookup(aid: str) -> None:
        if aid not in known:
            raise LookupError(aid)

    from perch.auth.openalex_link import CryptoLinkStore

    app = make_app(r, pool=pool, provider=prov, lookup=lookup, links=CryptoLinkStore(pool))
    yield app, pg_clean
    pool.close()
    crypto.configure()


def sign_in(app: FastAPI, rt: str = "/briefs") -> tuple[TestClient, dict]:
    c = TestClient(app)
    c.cookies.set("perch_oidc", "binder-1")
    resp = c.get(f"/auth/callback?code=c&state=s&rt={rt}", follow_redirects=False)
    assert resp.status_code == 302, resp.text
    me = c.get("/auth/session").json()
    return c, {"resp": resp, "me": me, "h": {"Origin": ORIGIN, "X-CSRF-Token": me["csrf"]}}


def rows(db, sql: str, *a):
    import psycopg

    with psycopg.connect(db.admin, autocommit=True) as c:
        return c.execute(sql, a).fetchall()


def test_first_sign_in_creates_the_user_and_goes_to_welcome(acct) -> None:
    app, db = acct
    c, x = sign_in(app)
    assert x["resp"].headers["location"].startswith("/welcome?return_to=/briefs")
    assert x["me"]["signed_in"] is True and x["me"]["needs_welcome"] is True
    assert x["me"]["roles"] == [] and x["me"]["consent"]["required"] is True
    assert len(rows(db, "SELECT id FROM users")) == 1
    page = c.get("/welcome")
    assert page.status_code == 200 and "PLACEHOLDER" in page.text and "SYNTHETIC Provider" in page.text


def test_sign_in_issues_a_new_sid_and_drops_the_old_one(acct, r) -> None:
    app, _ = acct
    c = TestClient(app)
    g = c.post("/auth/guest", headers={"Origin": ORIGIN})
    old = c.cookies.get("perch_sid")
    assert g.status_code == 200
    c.cookies.set("perch_oidc", "binder-1")
    c.get("/auth/callback?code=c&state=s", follow_redirects=False)
    assert c.cookies.get("perch_sid") != old and not r.exists(f"perch:sess:{old}")


def test_returning_user_goes_straight_to_return_to(acct) -> None:
    app, _ = acct
    c, x = sign_in(app)
    c.post("/me/roles", json={"roles": ["student"]}, headers=x["h"])
    c.post("/me/consent", json={}, headers=x["h"])
    c2, y = sign_in(app, "/records")
    assert y["resp"].headers["location"] == "/records"
    assert y["me"]["roles"] == ["student"] and y["me"]["needs_welcome"] is False


def test_roles_never_accept_staff_and_keep_an_operator_grant(acct) -> None:
    app, db = acct
    c, x = sign_in(app)
    assert c.post("/me/roles", json={"roles": ["staff"]}, headers=x["h"]).status_code == 422
    assert c.post("/me/roles", json={"roles": ["student", "staff"]}, headers=x["h"]).status_code == 422
    assert c.post("/me/roles", json={"roles": []}, headers=x["h"]).status_code == 422
    assert rows(db, "SELECT roles FROM users")[0][0] == []
    assert c.post("/me/roles", json={"roles": ["student", "researcher"]},
                  headers=x["h"]).json()["roles"] == ["researcher", "student"]
    rows(db, "UPDATE users SET roles = roles || ARRAY['staff'] RETURNING 1")
    c.post("/me/roles", json={"roles": ["student"]}, headers=x["h"])
    assert rows(db, "SELECT roles FROM users")[0][0] == ["staff", "student"]


def test_audience_switch_is_403_for_an_unheld_audience(acct) -> None:
    app, db = acct
    c, x = sign_in(app)
    c.post("/me/roles", json={"roles": ["student"]}, headers=x["h"])
    assert c.post("/me/audience", json={"audience": "researcher"}, headers=x["h"]).status_code == 403
    assert c.post("/me/audience", json={"audience": "student"}, headers=x["h"]).status_code == 200
    c.post("/me/roles", json={"roles": ["student", "researcher"]}, headers=x["h"])
    assert c.post("/me/audience", json={"audience": "researcher"}, headers=x["h"]).status_code == 200
    assert c.get("/auth/session").json()["audience"] == "researcher"
    assert rows(db, "SELECT last_audience FROM users")[0][0] == "researcher"
    assert c.post("/me/audience", json={"audience": "x"}, headers=x["h"]).status_code == 422


def test_changing_roles_moves_an_unheld_audience(acct) -> None:
    app, _ = acct
    c, x = sign_in(app)
    c.post("/me/roles", json={"roles": ["researcher"]}, headers=x["h"])
    out = c.post("/me/roles", json={"roles": ["student"]}, headers=x["h"]).json()
    assert out["audience"] == "student" and c.get("/auth/session").json()["audience"] == "student"


def test_consent_row_withdraw_and_version_bump(acct, monkeypatch: pytest.MonkeyPatch) -> None:
    from perch.auth.consent import consent_sha256

    app, db = acct
    c, x = sign_in(app)
    assert c.post("/me/consent", json={"version": 5}, headers=x["h"]).status_code == 409
    assert c.post("/me/consent", json={"version": 1}, headers=x["h"]).status_code == 200
    ver, prov, h, wd = rows(db, "SELECT version, provider_name, text_sha256, withdrawn_at "
                                "FROM consents")[0]
    assert (ver, prov, bytes(h), wd) == (1, "SYNTHETIC Provider", consent_sha256(), None)
    c.post("/me/roles", json={"roles": ["researcher"]}, headers=x["h"])
    assert c.get("/auth/session").json()["consent"]["required"] is False
    monkeypatch.setenv("PERCH_CONSENT_VERSION", "2")  # bump: re-prompt, also on a new sign-in
    assert c.get("/auth/session").json()["consent"]["required"] is True
    c2, y = sign_in(app)
    assert y["me"]["needs_welcome"] is True and "/welcome" in y["resp"].headers["location"]
    assert c2.post("/me/consent", json={}, headers=y["h"]).status_code == 200
    assert [r[0] for r in rows(db, "SELECT version FROM consents ORDER BY id")] == [1, 2]
    assert c2.post("/me/consent/withdraw", headers=y["h"]).status_code == 200
    assert all(r[0] is not None for r in rows(db, "SELECT withdrawn_at FROM consents"))
    me = c2.get("/auth/session").json()
    assert me["consent"]["accepted_version"] == 0 and me["consent"]["required"] is True
    c3, z = sign_in(app)  # a withdrawn consent stays withdrawn at the next sign-in
    assert z["me"]["consent"]["accepted_version"] == 0


def test_guest_leaves_no_rows(acct) -> None:
    app, db = acct
    guest_client(app)
    assert rows(db, "SELECT count(*) FROM users")[0][0] == 0
    assert rows(db, "SELECT count(*) FROM consents")[0][0] == 0
    assert rows(db, "SELECT count(*) FROM user_data")[0][0] == 0


def test_openalex_link_is_validated_and_stored_encrypted(acct) -> None:
    app, db = acct
    c, x = sign_in(app)
    h = x["h"]
    assert c.put("/me/openalex", json={"author_id": "A12"}, headers=h).status_code == 422
    assert c.put("/me/openalex", json={"author_id": "not an id"}, headers=h).status_code == 422
    assert c.put("/me/openalex", json={"author_id": "A5999999999"}, headers=h).status_code == 404
    assert rows(db, "SELECT openalex_id_enc FROM users")[0][0] is None
    resp = c.put("/me/openalex", json={"author_id": " https://openalex.org/a5000000001 "},
                 headers=h)
    assert resp.status_code == 200 and resp.json() == {"linked": True, "author_id": "A5000000001"}
    blob, at = rows(db, "SELECT openalex_id_enc, openalex_linked_at FROM users")[0]
    assert b"A5000000001" not in bytes(blob) and at is not None
    assert app.state.openalex_links.get(
        rows(db, "SELECT id FROM users")[0][0]) == "A5000000001"
    assert c.get("/auth/session").json()["openalex_linked"] is True
    assert c.put("/me/openalex", json={"author_id": "A5000000001"}).status_code == 403  # csrf

"""Shared demo account guards: the session flag, the banner text, the nightly wipe and the
one-time setup. SYNTHETIC text only. The wipe and setup tests need PERCH_TEST_DATABASE_URL; the
session tests need the test Redis (DB 15). Everything else runs without services."""

from __future__ import annotations

import base64
import re
import uuid

import psycopg
import pytest

from perch.api import WEB_DIR
from perch.auth import settings
from perch.cli import main as cli_main
from perch.store.pg import make_pool
from perch.user import shared
from perch.user.models import USER_KINDS, EntryDoc
from tests import test_auth as _auth
from tests.conftest import PG_URL
from tests.test_auth import make_app

_env = _auth._env  # the auth env fixture (autouse)
r = _auth.r  # the test Redis fixture

NOTICE = ("Shared demo account. Everyone who signs in sees what you save here. "
          "Do not paste a real CV.")


# --- the setting and the flag: no services needed ---

def test_shared_flag_only_for_listed_names(monkeypatch):
    monkeypatch.delenv("PERCH_SHARED_ACCOUNTS", raising=False)
    assert settings.shared_accounts() == frozenset()
    assert not settings.is_shared({"preferred_username": "demo"})  # default empty
    monkeypatch.setenv("PERCH_SHARED_ACCOUNTS", " Demo , walkthrough ,")
    assert settings.shared_accounts() == {"demo", "walkthrough"}
    assert settings.is_shared({"preferred_username": "demo"})
    assert settings.is_shared({"preferred_username": "DEMO"})  # sign-in names ignore case
    assert not settings.is_shared({"preferred_username": "someone-else"})
    assert not settings.is_shared({"preferred_username": "demo2"})
    assert not settings.is_shared({})  # no username claim
    assert not settings.is_shared({"preferred_username": ["demo"]})
    assert not settings.is_shared(None)


def test_the_banner_and_the_cv_warning_use_the_one_text():
    dom = (WEB_DIR / "dom.js").read_text()
    assert f'SHARED_NOTICE = "{NOTICE}"' in dom
    app = (WEB_DIR / "app.js").read_text()
    assert "SHARED_NOTICE" in app and 'data-key": "shared-banner"' in app
    assert "sharedWarn(S.session)" in app  # researcher start
    assert "sharedWarn(sess)" in (WEB_DIR / "student.js").read_text()  # student start
    assert "sharedWarn(ctx.session())" in (WEB_DIR / "account.js").read_text()  # account page
    for js in WEB_DIR.glob("*.js"):  # the text lives in one place only
        if js.name != "dom.js":
            assert "Everyone who signs in sees" not in js.read_text(), js.name


def test_the_username_is_not_logged_at_info():
    src = open(settings.__file__).read() + open(shared.__file__).read()
    assert "log." not in src  # these modules do not log at all


# --- the session JSON ---

@pytest.mark.skipif(not _auth.URL, reason="PERCH_TEST_REDIS_URL is not set")
def test_session_json_carries_shared_only_when_set(r, monkeypatch):
    import asyncio

    from tests.test_auth import IDENT, ORIGIN  # noqa: F401
    app = make_app(r)
    store = app.state.sessions
    for flag in (True, False):
        s = asyncio.run(store.create_user(uuid.uuid4(), {"student"}, IDENT, shared=flag))
        from fastapi.testclient import TestClient
        c = TestClient(app)
        c.cookies.set(settings.session_cookie_name(), s.sid)
        out = c.get("/auth/session").json()
        assert out["signed_in"] is True
        assert (out.get("shared") is True) == flag
        assert ("shared" in out) == flag  # absent, not false, for everyone else


# --- the wipe and the setup: Postgres ---

pg = pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set")
ISS = "https://issuer.example.invalid/realms/synthetic"


@pytest.fixture
def pepper(monkeypatch):
    monkeypatch.setenv("PERCH_PEPPER", base64.b64encode(b"p" * 32).decode())
    monkeypatch.setenv("PERCH_CONSENT_VERSION", "2")
    monkeypatch.setenv("PERCH_CONSENT_PROVIDER_NAME", "SYNTHETIC Provider")


@pg
def test_prepare_then_wipe_keeps_the_account_and_removes_every_kind(pg_clean, ud, pepper):
    owner = make_pool(pg_clean.admin, 2)
    try:
        uid = shared.prepare_shared(owner, ISS, "kc-user-1", ["researcher", "student"])
        again = shared.prepare_shared(owner, ISS, "kc-user-1", ["student", "researcher"])
        assert again == uid  # idempotent: the same row, one consent
        with psycopg.connect(pg_clean.admin, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM consents WHERE user_id = %s",
                             (uid,)).fetchone()[0] == 1
            note = c.execute("SELECT detail->>'note' FROM audit_log "
                             "WHERE event = 'shared_account_prepare' LIMIT 1").fetchone()[0]
            assert "SYNTHETIC" in note and "operator" in note
        acct = shared_account(owner, uid)
        assert acct.roles == {"student", "researcher"} and acct.consent_version == 2

        ud.put(uid, "entry", "student", EntryDoc(text="SYNTHETIC real row"))
        ud.link_openalex(uid, "A5000000000")
        with psycopg.connect(pg_clean.admin, autocommit=True) as c:
            for kind in USER_KINDS:  # one raw row of every kind: the wipe does not decrypt
                c.execute("INSERT INTO user_data (user_id, kind, audience, key_version, blob) "
                          "VALUES (%s, %s, 'student', 1, %s)", (uid, kind, b"\x01SYNTHETIC"))
            c.execute("INSERT INTO user_data (user_id, kind, audience, key_version, blob) "
                      "VALUES (%s, 'entry', 'researcher', 1, %s)", (uid, b"\x01SYNTHETIC"))
        other = shared.prepare_shared(owner, ISS, "kc-other", ["student"])  # must stay untouched
        ud.put(other, "entry", "student", EntryDoc(text="SYNTHETIC other user"))
        with psycopg.connect(pg_clean.admin, autocommit=True) as c:
            jid = c.execute("INSERT INTO jobs (kind, user_id, audience, idempotency_key, "
                            "max_attempts) VALUES ('brief', %s, 'student', 'k1', 3) "
                            "RETURNING id", (uid,)).fetchone()[0]
            c.execute("INSERT INTO job_events (job_id, stage, status) VALUES (%s, 'x', 'done')",
                      (jid,))
            c.execute("INSERT INTO spend_ledger (user_id, role, provider, model, input_tokens, "
                      "output_tokens, cost_usd) VALUES (%s, 'brief', 'fake', 'fake', 1, 1, 0.01)",
                      (uid,))
        assert ud.count(uid) == len(USER_KINDS) + 2

        res = shared.wipe_user_data(owner, uid)  
        assert res["rows"] == len(USER_KINDS) + 2 and res["jobs"] == 1

        with psycopg.connect(pg_clean.admin, autocommit=True) as c:
            q = lambda sql, *a: c.execute(sql, a).fetchone()[0]  # noqa: E731
            assert q("SELECT count(*) FROM user_data WHERE user_id = %s", uid) == 0
            assert q("SELECT count(*) FROM jobs WHERE user_id = %s", uid) == 0
            assert q("SELECT count(*) FROM job_events") == 0
            assert q("SELECT openalex_id_enc IS NULL FROM users WHERE id = %s", uid)
            assert q("SELECT count(*) FROM users WHERE id = %s", uid) == 1  # the account stays
            assert q("SELECT count(*) FROM consents WHERE user_id = %s", uid) == 1
            assert q("SELECT count(*) FROM spend_ledger WHERE user_id = %s", uid) == 1  # budget
            assert q("SELECT count(*) FROM user_data WHERE user_id = %s", other) == 1
        acct = shared_account(owner, uid)
        assert acct.roles == {"student", "researcher"} and acct.consent_version == 2
        # a visitor lands in the app, not on the Welcome
        from perch.auth.routes import _needs_welcome
        assert not _needs_welcome(acct.roles, acct.consent_version)
        assert shared.find_user(owner, ISS, "kc-user-1") == uid
        assert shared.find_user(owner, ISS, "never-signed-in") is None
        with pytest.raises(ValueError):
            shared.prepare_shared(owner, ISS, "kc-user-1", ["staff"])
    finally:
        owner.close()


def shared_account(pool, uid):
    from perch.auth import accounts
    return accounts.load_account(pool, uid)


@pg
def test_a_role_under_row_security_is_refused(pg_clean, pepper):
    pool = make_pool(pg_clean.owner, 2)  # perch_owner: forced row security applies to it
    try:
        with pytest.raises(shared.NotAdmin):
            shared.prepare_shared(pool, ISS, "kc-x", ["student"])
    finally:
        pool.close()


@pg
def test_the_cli_prepares_and_wipes_every_listed_subject(pg_clean, ud, pepper, monkeypatch,
                                                         capsys):
    monkeypatch.setenv("PERCH_OIDC_ISSUER", ISS)
    monkeypatch.setenv("PERCH_ADMIN_DATABASE_URL", pg_clean.admin)
    monkeypatch.setenv("PERCH_SHARED_SUBJECTS", "kc-a, kc-b, kc-never")
    for sub in ("kc-a", "kc-b"):
        assert cli_main(["user", "prepare-shared", "--subject", sub]) == 0
    owner = make_pool(pg_clean.admin, 2)
    try:
        ids = [shared.find_user(owner, ISS, s) for s in ("kc-a", "kc-b")]
    finally:
        owner.close()
    for uid in ids:
        ud.put(uid, "entry", "student", EntryDoc(text="SYNTHETIC entry"))
    assert cli_main(["user", "wipe-data", "--all-shared"]) == 0
    assert "Wiped data for 2 of 3" in capsys.readouterr().out
    assert all(ud.count(u) == 0 for u in ids)
    assert cli_main(["user", "wipe-data"]) == 2  # nothing named: refuses
    assert re.search(r"--subject", capsys.readouterr().err)
    assert cli_main(["user", "prepare-shared", "--subject", "kc-a", "--roles", "staff"]) == 2

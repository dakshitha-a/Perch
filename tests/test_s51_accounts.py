"""S51 D4: /auth/session says whether accounts are open (PERCH_ACCOUNTS_OPEN, default 1), in
every shape; and the budget detail the front end matches is pinned. No Redis needed."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from perch.auth.session import Session


def app() -> FastAPI:
    from perch.auth.wiring import install_auth

    a = FastAPI()
    install_auth(a)
    a.state.sessions = None
    a.state.pool = None
    return a


@pytest.mark.parametrize(("value", "want"), [(None, True), ("1", True), ("0", False)])
def test_the_signed_out_session_says_whether_accounts_are_open(monkeypatch, value, want):
    if value is None:
        monkeypatch.delenv("PERCH_ACCOUNTS_OPEN", raising=False)
    else:
        monkeypatch.setenv("PERCH_ACCOUNTS_OPEN", value)
    got = TestClient(app()).get("/auth/session").json()
    assert got == {"signed_in": False, "accounts_open": want}


def test_guest_and_signed_in_sessions_carry_accounts_open(monkeypatch):
    from uuid import uuid4

    import perch.auth.routes as routes

    monkeypatch.setenv("PERCH_ACCOUNTS_OPEN", "0")
    monkeypatch.setattr(routes, "consent_text", lambda: "SYNTHETIC consent text")
    for s in (Session(sid="g" * 22, user_id=None, guest=True, roles=frozenset(),
                      audience="student", csrf="c", display_name=None, created=0, abs_exp=1),
              Session(sid="u" * 22, user_id=uuid4(), guest=False, roles=frozenset(),
                      audience="researcher", csrf="c", display_name=None, created=0, abs_exp=1)):
        async def fake(request, s=s):
            return s

        monkeypatch.setattr(routes, "session_optional", fake)
        got = TestClient(app()).get("/auth/session").json()
        assert got["accounts_open"] is False, s.guest


def test_the_budget_detail_the_front_end_matches_is_pinned():
    from perch.service import BUDGET_DETAIL

    assert BUDGET_DETAIL.startswith("withheld: the daily model budget")

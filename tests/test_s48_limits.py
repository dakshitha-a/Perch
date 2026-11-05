# ruff: noqa: F811  (pytest fixtures imported by name, then used as arguments)
"""Rate limits added by the S48 review: /authors/resolve (S4), Scout session rows (S5).
SYNTHETIC text only. Needs the test Redis; the Scout tests also need the test Postgres."""

from __future__ import annotations

import json
from types import SimpleNamespace

from perch.scout import web as sweb
from tests.test_api import make
from tests.test_scout_v2_account import stack  # noqa: F401 - fixture
from tests.test_user_account import env, pytestmark, rds, sql  # noqa: F401

SAD = "I can't go on"  # the keyword fast path (perch/scout/texts.py)


def test_author_search_has_the_per_address_read_limit(rds, tmp_path, monkeypatch):
    monkeypatch.setenv("PERCH_RATE_LIMITS", json.dumps({"api_read": [2, 60]}))
    c, _ = make(tmp_path)
    c.app.state.sessions = SimpleNamespace(r=rds)
    # an id that fails its check answers 422 without a lookup, and still counts
    assert [c.get("/authors/resolve", params={"q": "A1"}).status_code for _ in range(2)] \
        == [422, 422]
    r = c.get("/authors/resolve", params={"q": "A1"})
    assert r.status_code == 429 and r.json()["detail"]["error"] == "rate_limited"
    assert int(r.headers["retry-after"]) > 0


def _sessions(env) -> int:
    return sql(env.pg, "SELECT count(*) FROM user_data WHERE kind = 'scout_session'")[0][0]


def test_scout_start_is_write_limited_before_a_session_row_exists(stack, monkeypatch):
    env, c, svc, bid, script = stack
    before = _sessions(env)
    monkeypatch.setenv("PERCH_RATE_LIMITS", json.dumps({"api_write": [0, 60]}))
    r = c.post(f"/briefs/{bid}/scout", json={"intent": "top_leads"})
    assert r.status_code == 429 and r.json()["detail"]["error"] == "rate_limited"
    assert _sessions(env) == before  # no row was created


def test_distress_writes_are_capped_per_hour(stack, monkeypatch):
    env, c, svc, bid, script = stack
    monkeypatch.setattr(sweb, "DISTRESS_WRITES_PER_HOUR", 2)
    monkeypatch.setattr(sweb, "DISTRESS_QUIET_SECONDS", 0)  # past the quiet period each time
    sid = c.post(f"/briefs/{bid}/scout", json={"question": SAD}).json()["id"]
    for _ in range(4):
        assert c.post(f"/scout/{sid}/ask", json={"question": SAD}).status_code == 202
    msgs = c.get(f"/scout/{sid}").json()["messages"]
    assert [m["kind"] for m in msgs if m["role"] == "assistant"] == ["distress", "distress"]
    assert msgs[-1]["kind"] == "distress"  # the care text stays the last reply
    assert script.gate_calls == 0 and script.scout_calls == 0

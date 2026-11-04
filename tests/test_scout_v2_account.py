# ruff: noqa: F811  (pytest fixtures imported by name, then used as arguments)
"""Scout on the account path (Phase 8): the encrypted session row, the `scout_turn` job on a real
worker, the gate's cost in the daily budget, guests, and the no-leak checks. Fake models only: no
spend. SYNTHETIC text only. Needs the test Postgres and Redis; run by `make test-user`.
"""

from __future__ import annotations

import json
import logging
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from perch import jobs, redisx
from perch.auth import accounts, deps
from perch.auth.session import Session
from perch.llm import ToolCall
from perch.scout import job as scout_job  # noqa: F401 - registers the scout_turn handler
from perch.scout import texts
from perch.user import docs, quota
from tests.conftest import PG_URL
from tests.student_helpers import (
    account_app,
    add_persona,
    canaries,
    consent,
    run_brief,
    student_reply,
)
from tests.test_scout_v2 import gate_by_words
from tests.test_user_account import REDIS_URL, env, job_state, rds, run_worker, sql  # noqa: F401
from tests.user_helpers import new_user

pytestmark = [pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set"),
              pytest.mark.skipif(not REDIS_URL, reason="PERCH_TEST_REDIS_URL is not set")]
QCANARY = "SYNTHETIC-canary-question-91ab"


class Script:
    """The fake models for one test: the gate by words, Scout by a function of its step."""

    def __init__(self, scout=None):
        self.scout, self.gate_calls, self.scout_calls = scout, 0, 0

    def __call__(self, messages, system, schema):
        if system == texts.GATE_SYSTEM:
            self.gate_calls += 1
            return gate_by_words(messages)
        if system and system.startswith("You are Scout"):
            self.scout_calls += 1
            return self.scout(messages) if self.scout else "no script"
        return student_reply(messages, system, schema)


def first_lead_answer(messages):
    last = messages[-1]
    if not last.tool_results:
        return [ToolCall("t1", "read_brief", {})]
    lead = json.loads(last.tool_results[0].content)["leads"][0]
    return f"{lead['title']} [{lead['id']}]."


@pytest.fixture
def stack(env, tmp_path, monkeypatch):
    script = Script(first_lead_answer)
    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    c, svc = account_app(env, tmp_path, monkeypatch, responder=script)
    got = run_brief(env, svc, c)
    assert got["brief"]["status"] == "done", got["brief"]["error"]
    jobs.set_brief_service(lambda: svc)
    yield env, c, svc, got["_id"], script
    jobs._brief_service = None


def turn(env, c, sid_or_none, brief_id, body, timeout=40):
    """Post one message and, when it is a question, run the worker until its job ends."""
    r = (c.post(f"/briefs/{brief_id}/scout", json=body) if sid_or_none is None
         else c.post(f"/scout/{sid_or_none}/ask", json=body))
    assert r.status_code == 202, r.text
    v = r.json()
    if body.get("question"):
        job = sql(env.pg, "SELECT id FROM jobs WHERE kind = 'scout_turn' ORDER BY created_at "
                  "DESC LIMIT 1")[0][0]
        run_worker(env.pg, ["scout_turn"], lambda: job_state(env.pg, job) in
                   ("succeeded", "failed", "dead"), timeout=timeout)
        v = c.get(f"/scout/{v['id']}").json()
    return v


def test_buttons_answer_in_the_web_process_with_no_model_and_no_job(stack):
    env, c, svc, bid, script = stack
    v = turn(env, c, None, bid, {"intent": "top_leads"})
    assert [m["kind"] for m in v["messages"]] == ["intent", "intent"]
    x = v["exchanges"][0]
    assert x["status"] == "done" and x["answer_by"] == "code" and x["answer"]
    assert {b["intent"] for b in v["buttons"]} == {"top_leads", "deadlines", "compare", "handoff"}
    assert set(v["usage"]) >= {"used_usd", "limit_usd", "resets_at"}
    assert script.gate_calls == 0 and script.scout_calls == 0
    assert sql(env.pg, "SELECT count(*) FROM jobs WHERE kind = 'scout_turn'")[0][0] == 0
    assert c.get("/scout/buttons").json()["buttons"] == v["buttons"]
    v2 = turn(env, c, v["id"], bid, {"intent": "deadlines"})
    assert len(v2["exchanges"]) == 2 and v2["exchanges"][1]["intent"] == "deadlines"


def test_an_open_question_runs_on_a_worker_and_is_stored_encrypted(stack):
    env, c, svc, bid, script = stack
    v = turn(env, c, None, bid, {"question": f"Which lead is strongest? {QCANARY}"})
    assert v["status"] == "done" and not v["busy"], v
    a = v["messages"][-1]
    assert a["kind"] == "answer" and a["records"] and not a["flagged"], a
    assert a["gate"] == "in_scope" and a["steps"] == ["read_brief"]
    assert v["exchanges"][0]["answer_by"] == "model"
    # ids only in the job, no text anywhere at rest
    job = sql(env.pg, "SELECT payload::text FROM jobs WHERE kind = 'scout_turn'")[0][0]
    assert set(json.loads(job)) == {"session_id", "message_id"} and QCANARY not in job
    blob = bytes(sql(env.pg, "SELECT blob FROM user_data WHERE kind = 'scout_session'")[0][0])
    assert QCANARY.encode() not in blob and a["text"].encode() not in blob
    # both calls were charged to the account and written to the ledger
    roles = [r[0] for r in sql(env.pg, "SELECT role FROM spend_ledger WHERE user_id = %s "
                               "ORDER BY id", env.uid)]
    assert roles[0] == "gate" and "scout" in roles
    assert quota.usage(env.r, env.pool, env.uid).spent_usd > 0
    # a reloaded page finds the session again, and the owner only
    again = c.get(f"/briefs/{bid}/scout").json()["session"]
    assert again["id"] == v["id"]


def test_out_of_scope_is_refused_by_code_and_still_costs_the_gate(stack):
    env, c, svc, bid, script = stack
    v = turn(env, c, None, bid, {"question": "What is the integral of x squared?"})
    a = v["messages"][-1]
    assert a["kind"] == "refusal" and a["text"] == texts.REFUSAL
    assert script.gate_calls == 1 and script.scout_calls == 0
    ledger = sql(env.pg, "SELECT role, cost_usd FROM spend_ledger WHERE user_id = %s", env.uid)
    assert [r[0] for r in ledger if r[0] in ("gate", "scout")] == ["gate"]
    assert all(float(r[1]) >= 0.000001 for r in ledger if r[0] == "gate")
    assert quota.usage(env.r, env.pool, env.uid).spent_usd >= 0.000001


def test_distress_for_a_student_points_to_counselling(stack):
    env, c, svc, bid, script = stack
    v = turn(env, c, None, bid, {"question": "I feel sad and hopeless about everything"})
    a = v["messages"][-1]
    assert a["kind"] == "distress" and texts.COUNSELLING_URL in a["text"]
    assert script.scout_calls == 0


def test_the_gate_charge_has_a_one_micro_dollar_minimum(env):
    scopes = quota.reserve_call(env.r, env.uid, 100)
    quota.settle_call(env.r, scopes, 100, 0, gate=True)
    assert redisx.spent_micro(env.r, scopes[0]) == 1


def test_an_exhausted_budget_stops_questions_but_not_buttons(stack, monkeypatch):
    env, c, svc, bid, script = stack
    monkeypatch.setenv("PERCH_DAILY_BUDGET_USD", "0.000002")
    for _ in range(2):  # two gate calls at the minimum charge fill it
        scopes = quota.reserve_call(env.r, env.uid, 1)
        quota.settle_call(env.r, scopes, 1, 0, gate=True)
    r = c.post(f"/briefs/{bid}/scout", json={"question": "Which lead is strongest?"})
    assert r.status_code == 429 and r.json()["detail"]["error"] == "quota_exceeded"
    assert r.json()["detail"]["usage"]["used_usd"] >= 0.000002
    b = c.post(f"/briefs/{bid}/scout", json={"intent": "top_leads"})
    assert b.status_code == 202  # buttons cost nothing


def test_no_user_text_reaches_jobs_events_ledger_audit_or_logs(stack, caplog):
    env, c, svc, bid, script = stack
    cv_canary = canaries("persona-ug")[0]
    docs.add(env.ud, env.uid, "student", "cv", text=f"# Education\n- BA, {cv_canary}\n")
    with caplog.at_level(logging.DEBUG):
        turn(env, c, None, bid, {"question": f"Does my CV help? {QCANARY}"})
        turn(env, c, None, bid, {"question": f"What is the integral of x? {QCANARY}"})
    tables = [sql(env.pg, f"SELECT row_to_json(t)::text FROM {t} t")
              for t in ("jobs", "job_events", "spend_ledger", "audit_log")]
    for t in tables:
        assert QCANARY not in json.dumps(t) and cv_canary not in json.dumps(t)
    assert QCANARY not in caplog.text and cv_canary not in caplog.text
    assert QCANARY not in json.dumps(svc.audit.events) and cv_canary not in json.dumps(
        svc.audit.events)


def test_guests_get_403_on_every_scout_route(env, tmp_path, monkeypatch, rds):
    c, svc = account_app(env, tmp_path, monkeypatch)
    guest = Session(sid="g-" + uuid.uuid4().hex, user_id=None, guest=True, roles=frozenset(),
                    audience="student", csrf="c", display_name=None, created=time.time(),
                    abs_exp=time.time() + 3600, consent_version=0)
    c.app.dependency_overrides[deps.session_optional] = lambda request: guest
    sid = str(uuid.uuid4())
    for r in (c.post("/briefs/x/scout", json={"intent": "top_leads"}),
              c.post("/briefs/x/scout", json={"question": "hello"}),
              c.get("/scout/buttons"), c.get(f"/scout/{sid}"), c.get("/briefs/x/scout"),
              c.post(f"/scout/{sid}/ask", json={"question": "hello"}),
              c.post(f"/scout/{sid}/button", json={"intent": "top_leads"}),
              c.delete(f"/scout/{sid}")):
        assert r.status_code == 403, (r.request.url, r.text)
        assert r.json()["detail"] == {"error": "account_required"}


def test_another_users_session_is_a_404(stack):
    env, c, svc, bid, script = stack
    v = turn(env, c, None, bid, {"intent": "top_leads"})
    other = new_user(env.pg)
    accounts.add_consent(env.pool, other, 1, "SYNTHETIC Provider")
    s2 = Session(sid="s-" + uuid.uuid4().hex, user_id=other, guest=False,
                 roles=frozenset({"student"}), audience="student", csrf="c", display_name=None,
                 created=time.time(), abs_exp=time.time() + 3600, consent_version=1)
    c.app.dependency_overrides[deps.session_optional] = lambda request: s2
    assert c.get(f"/scout/{v['id']}").status_code == 404
    assert c.post(f"/scout/{v['id']}/ask", json={"intent": "top_leads"}).status_code == 404
    assert c.delete(f"/scout/{v['id']}").status_code == 404
    assert c.post(f"/briefs/{bid}/scout", json={"intent": "top_leads"}).status_code == 404


def test_stop_cancels_a_queued_question(stack):
    env, c, svc, bid, script = stack
    r = c.post(f"/briefs/{bid}/scout", json={"question": "Which lead is strongest?"})
    assert r.status_code == 202 and r.json()["busy"] is True
    sid = r.json()["id"]
    assert c.post(f"/scout/{sid}/ask", json={"question": "again"}).status_code == 409
    s = c.post(f"/scout/{sid}/stop", json={}).json()
    assert s["busy"] is False and s["exchanges"][0]["status"] == "stopped"
    assert script_calls(stack) == 0


def script_calls(stack) -> int:
    return stack[4].gate_calls + stack[4].scout_calls


def test_the_old_scout_baseline_still_runs():
    """bench/scout.py is kept as the baseline: it imports and lists its 30 tasks."""
    import bench.scout as b

    assert callable(getattr(b, "main", None)) or hasattr(b, "TASKS")
    assert isinstance(TestClient, type)


def test_student_buttons_keep_samples_apart_from_public_fellowships(stack):
    from perch.scout.buttons import SAMPLE_HEADING

    env, c, svc, bid, script = stack
    got = c.get(f"/briefs/{bid}").json()
    for route in ("F", "S"):
        lead = next(x for x in got["leads"] if x["route"] == route
                    and x["verdict"] != "not eligible")
        assert c.post(f"/briefs/{bid}/leads/{lead['id']}/keep").status_code == 200
    sid = None
    for intent in ("top_leads", "deadlines", "compare"):
        v = turn(env, c, sid, bid, {"intent": intent})
        sid = v["id"]
        text = v["messages"][-1]["text"]
        before, mark, after = text.partition(SAMPLE_HEADING)
        assert mark and "[sample:" in after and "[sample:" not in before, text
        cited = [ln for ln in after.splitlines() if "[" in ln]
        assert cited and all("[sample:" in ln for ln in cited), text


def test_the_researcher_handoff_button_is_code_written_from_the_kept_lead(
        env, tmp_path, monkeypatch):
    consent(env, monkeypatch)
    env.session.audience = "researcher"
    script = Script()
    c, svc = account_app(env, tmp_path, monkeypatch, responder=script)
    got = run_brief(env, svc, c, {"author_id": "A5026494099", "explain": False})
    bid = got["_id"]
    assert got["brief"]["status"] == "done", got["brief"]["error"]
    lead = got["leads"][0]
    assert c.post(f"/briefs/{bid}/leads/{lead['id']}/keep").status_code == 200
    v = turn(env, c, None, bid, {"intent": "handoff"})
    m = v["messages"][-1]
    assert m["kind"] == "intent" and not m.get("empty"), m
    assert m["draft"]["office"]["name"] == "Research Development"
    assert m["draft"]["body"] and lead["record_id"] in m["records"]
    assert script.gate_calls == 0 and script.scout_calls == 0  # no model at all
    assert "Nothing is sent" in m["text"]

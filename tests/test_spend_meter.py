"""Brief jobs are metered per call against the owner's counters (S48 review M2). SYNTHETIC only.

Needs the test Postgres and Redis (`make test-user`). Every paid call of a brief job is reserved
before it is made and settled after it, against the account's day (or the guest session's day
and the guest ceiling) and the global month, and writes a `spend_ledger` row.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from perch import redisx
from perch.auth import deps
from perch.auth.session import Session
from perch.service import BUDGET_DETAIL
from perch.user.briefs import guest_hash
from tests.student_helpers import account_app, add_persona, consent, run_brief, student_reply
from tests.test_user_account import env, pytestmark, rds, sql  # noqa: F401 - fixtures


def counting(calls: list[int]):
    def reply(messages, system, schema):
        calls.append(1)
        return student_reply(messages, system, schema)
    return reply


def stage(got: dict, name: str) -> dict:
    return next(s for s in got["brief"]["stages"] if s["name"] == name)


def day() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def test_a_brief_job_with_the_account_at_its_limit_makes_no_paid_call(env, tmp_path,  # noqa: F811
                                                                        monkeypatch):
    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    calls: list[int] = []
    c, svc = account_app(env, tmp_path, monkeypatch, responder=counting(calls), samples=False)
    real_run = svc.run

    def run_at_limit(brief_id: str) -> str:  # the day is used up after the brief was admitted
        scope = redisx.quota_scopes(uid=env.uid)[0]
        env.r.hset(scope.spend, "usd_micro", scope.limit)
        return real_run(brief_id)

    monkeypatch.setattr(svc, "run", run_at_limit)
    got = run_brief(env, svc, c)
    assert got["brief"]["status"] == "done", got["brief"]["error"]
    assert got["leads"]  # the deterministic leads stand
    st = stage(got, "student_explanations")
    assert st["status"] == "skipped" and st["detail"] == BUDGET_DETAIL
    assert calls == []  # no model call was made
    assert sql(env.pg, "SELECT count(*) FROM spend_ledger") == [(0,)]
    assert not env.r.exists(f"perch:inflight:u:{env.uid}:{day()}")  # nothing left reserved
    scope = redisx.quota_scopes(uid=env.uid)[0]
    assert redisx.spent_micro(env.r, scope) == scope.limit  # unchanged


def test_a_brief_job_charges_the_account_and_the_global_month(env, tmp_path, monkeypatch):  # noqa: F811
    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    calls: list[int] = []
    c, svc = account_app(env, tmp_path, monkeypatch, responder=counting(calls), samples=False)
    got = run_brief(env, svc, c)
    assert got["brief"]["status"] == "done" and calls
    rows = sql(env.pg, "SELECT user_id, role, cost_usd FROM spend_ledger")
    assert len(rows) == len(calls)
    assert {r[0] for r in rows} == {env.uid} and {r[1] for r in rows} == {"fit_explainer"}
    user, month = redisx.quota_scopes(uid=env.uid)
    total = redisx.usd_micro(float(sum(r[2] for r in rows)))
    assert abs(redisx.spent_micro(env.r, user) - total) <= len(rows)  # rounding per row
    assert redisx.spent_micro(env.r, month) >= redisx.spent_micro(env.r, user) > 0


def _guest(c) -> Session:
    g = Session(sid="g-" + "m" * 20, user_id=None, guest=True, roles=frozenset(),
                audience="student", csrf="c", display_name=None, created=time.time(),
                abs_exp=time.time() + 3600, consent_version=0)
    c.app.dependency_overrides[deps.session_optional] = lambda request: g
    return g


def test_a_guest_brief_is_charged_to_the_guest_session_and_the_guest_ceiling(
        env, tmp_path, monkeypatch):  # noqa: F811
    calls: list[int] = []
    c, svc = account_app(env, tmp_path, monkeypatch, responder=counting(calls))
    g = _guest(c)
    got = run_brief(env, svc, c)
    assert got["brief"]["status"] == "done" and calls
    rows = sql(env.pg, "SELECT user_id, role FROM spend_ledger")
    assert len(rows) == len(calls) and {r[0] for r in rows} == {None}
    guest, ceiling, month = redisx.quota_scopes(gsid_hash=guest_hash(g.sid))
    assert redisx.spent_micro(env.r, guest) > 0
    assert redisx.spent_micro(env.r, ceiling) == redisx.spent_micro(env.r, guest)
    assert redisx.spent_micro(env.r, month) >= redisx.spent_micro(env.r, guest)


def test_a_guest_whose_budget_is_used_cannot_start_an_explained_brief(
        env, tmp_path, monkeypatch):  # noqa: F811
    c, _ = account_app(env, tmp_path, monkeypatch)
    g = _guest(c)
    scope = redisx.quota_scopes(gsid_hash=guest_hash(g.sid))[0]
    env.r.hset(scope.spend, "usd_micro", scope.limit)
    r = c.post("/briefs", json={"as_of": "2026-11-06"})
    assert r.status_code == 429 and r.json()["detail"]["error"] == "quota_exceeded"
    # without explanations no paid call is made, so the budget does not stop the brief
    assert c.post("/briefs", json={"as_of": "2026-11-06", "explain": False}).status_code == 202


def test_a_call_that_timed_out_is_charged_its_hold(env, worker_pool):  # noqa: F811
    """S49 B25: a call that raised after the provider may have billed it was settled at zero
    with no ledger row. A timeout now counts the reserved estimate; another error still
    counts nothing."""
    import httpx
    import pytest

    from perch.llm.base import Message
    from perch.user.spend import ESTIMATE_MICRO, SpendMeter

    class Slow:
        name, model = "fake", "fake-1"

        def __init__(self, err):
            self.err = err

        def chat(self, messages, **kw):
            raise self.err

    meter = SpendMeter(env.r, worker_pool, lambda: redisx.quota_scopes(uid=env.uid),
                       user_id=env.uid)
    scope = redisx.quota_scopes(uid=env.uid)[0]
    before = redisx.spent_micro(env.r, scope)
    with pytest.raises(httpx.ReadTimeout):
        meter.call("fit_explainer", Slow(httpx.ReadTimeout("slow")), [Message("user", "x")])
    held = ESTIMATE_MICRO["fit_explainer"]
    assert redisx.spent_micro(env.r, scope) - before == held
    assert sql(env.pg, "SELECT role, cost_usd::float FROM spend_ledger") \
        == [("fit_explainer", held / 1_000_000)]
    with pytest.raises(ValueError):
        meter.call("fit_explainer", Slow(ValueError("bad")), [Message("user", "x")])
    assert redisx.spent_micro(env.r, scope) - before == held
    assert not env.r.exists(f"perch:inflight:u:{env.uid}:{day()}") \
        or int(env.r.get(f"perch:inflight:u:{env.uid}:{day()}") or 0) == 0

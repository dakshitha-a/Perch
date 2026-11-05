# ruff: noqa: F811  (pytest fixtures imported by name, then used as arguments)
"""The hand-off draft as a worker job on the account path (S48 review S3). SYNTHETIC only.

POST /briefs/{id}/handoff is admitted against the account's rate window and daily budget and
queues a `handoff` job; the worker makes the model call, metered, and stores the draft
encrypted; GET /briefs/{id}/handoff reads it. Needs the test Postgres and Redis.
"""

from __future__ import annotations

import pytest

from perch import jobs, redisx
from perch.scout import job as scout_job  # noqa: F401 - registers the handoff handler
from tests.student_helpers import account_app, consent, run_brief
from tests.test_user_account import env, job_state, pytestmark, rds, run_worker, sql  # noqa: F401

OFFICE = "research_development"


@pytest.fixture
def researcher(env, tmp_path, monkeypatch):
    consent(env, monkeypatch)
    env.session.audience = "researcher"
    calls: list[str] = []

    def reply(messages, system, schema):
        calls.append(system or "")
        return ""  # nothing usable: the draft keeps the code-written opening, flagged

    c, svc = account_app(env, tmp_path, monkeypatch, responder=reply)
    got = run_brief(env, svc, c, {"author_id": "A5026494099", "explain": False})
    assert got["brief"]["status"] == "done", got["brief"]["error"]
    bid, lead = got["_id"], got["leads"][0]
    assert c.post(f"/briefs/{bid}/leads/{lead['id']}/keep").status_code == 200
    jobs.set_brief_service(lambda: svc)
    yield env, c, bid, lead, calls
    jobs._brief_service = None


def _run(env, job_id):
    run_worker(env.pg, ["handoff"], lambda: job_state(env.pg, job_id) in
               ("succeeded", "failed", "dead"), timeout=40)
    return job_state(env.pg, job_id)


def test_a_handoff_is_queued_drafted_on_the_worker_metered_and_stored(researcher):
    env, c, bid, lead, calls = researcher
    r = c.post(f"/briefs/{bid}/handoff", json={"office": OFFICE})
    assert r.status_code == 202, r.text
    job = r.json()["job_id"]
    assert r.json()["poll"] == f"/briefs/{bid}/handoff?office={OFFICE}&job_id={job}"
    assert sql(env.pg, "SELECT payload FROM jobs WHERE id = %s", job)[0][0] == {
        "brief_id": bid, "office": OFFICE, "lead_ids": []}  # ids only
    assert _run(env, job) == "succeeded"
    got = c.get(f"/briefs/{bid}/handoff", params={"office": OFFICE, "job_id": job}).json()
    assert got["job"]["state"] == "succeeded"
    d = got["result"]
    assert d["office"]["key"] == OFFICE and d["subject"] and d["lead_ids"] == [lead["id"]]
    assert calls  # the model was asked on the worker
    rows = sql(env.pg, "SELECT user_id, role FROM spend_ledger")
    assert rows and {r[0] for r in rows} == {env.uid} and {r[1] for r in rows} == {"handoff"}
    user = redisx.quota_scopes(uid=env.uid)[0]
    assert redisx.spent_micro(env.r, user) > 0
    # stored encrypted, one per brief and office: a second draft replaces the first
    blob = sql(env.pg, "SELECT blob FROM user_data WHERE kind = 'handoff'")
    assert len(blob) == 1 and d["subject"].encode() not in bytes(blob[0][0])
    job2 = c.post(f"/briefs/{bid}/handoff", json={"office": OFFICE}).json()["job_id"]
    assert _run(env, job2) == "succeeded"
    assert len(sql(env.pg, "SELECT id FROM user_data WHERE kind = 'handoff'")) == 1


def test_a_handoff_with_the_day_used_is_refused_before_any_job(researcher):
    env, c, bid, _, calls = researcher
    scope = redisx.quota_scopes(uid=env.uid)[0]
    env.r.hset(scope.spend, "usd_micro", scope.limit)
    r = c.post(f"/briefs/{bid}/handoff", json={"office": OFFICE})
    assert r.status_code == 429 and r.json()["detail"]["error"] == "quota_exceeded"
    assert sql(env.pg, "SELECT count(*) FROM jobs WHERE kind = 'handoff'") == [(0,)]


def test_a_handoff_whose_budget_runs_out_in_the_queue_is_code_written(researcher, monkeypatch):
    env, c, bid, _, calls = researcher
    job = c.post(f"/briefs/{bid}/handoff", json={"office": OFFICE}).json()["job_id"]
    scope = redisx.quota_scopes(uid=env.uid)[0]
    env.r.hset(scope.spend, "usd_micro", scope.limit)  # used up while the job waited
    calls.clear()
    assert _run(env, job) == "succeeded"
    d = c.get(f"/briefs/{bid}/handoff", params={"office": OFFICE, "job_id": job}).json()["result"]
    assert d["opening_by"] == "code" and d["model"] is None
    assert calls == []  # no paid call
    assert sql(env.pg, "SELECT count(*) FROM spend_ledger") == [(0,)]


def test_nothing_kept_for_the_office_is_a_422_and_no_job(researcher):
    env, c, bid, _, _ = researcher
    r = c.post(f"/briefs/{bid}/handoff", json={"office": "technology_commercialization"})
    assert r.status_code == 422
    assert sql(env.pg, "SELECT count(*) FROM jobs WHERE kind = 'handoff'") == [(0,)]

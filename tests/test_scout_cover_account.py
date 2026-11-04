# ruff: noqa: F811  (pytest fixtures imported by name, then used as arguments)
"""Cover points on the account path (S45): `POST /briefs/{id}/cover-points`, the `cover_points`
job on a real worker, the encrypted result row. Fake models only: no spend. SYNTHETIC text only.
Needs the test Postgres and Redis; run by `make test-user`.
"""

from __future__ import annotations

import json
import re

import pytest

from perch import jobs
from perch.llm.fake import FakeProvider
from perch.scout import job as scout_job  # noqa: F401 - registers the handlers
from perch.user import docs, quota
from perch.user.models import CoverPointSet
from tests.conftest import PG_URL
from tests.student_helpers import (
    account_app,
    add_persona,
    consent,
    run_brief,
    student_reply,
)
from tests.test_scout_v2 import EMAIL, PHONE
from tests.test_user_account import REDIS_URL, env, job_state, rds, run_worker, sql  # noqa: F401

pytestmark = [pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set"),
              pytest.mark.skipif(not REDIS_URL, reason="PERCH_TEST_REDIS_URL is not set")]
ECANARY = "SYNTHETIC-canary-entry-text-44c1"


class Cover:
    """The fake model for the cover_points role: valid points for the target in the prompt,
    or, with `bad`, an invented number every time."""

    def __init__(self, bad=False):
        self.bad, self.prompts = bad, []

    def __call__(self, messages, system, schema):
        if not (system or "").startswith("You list the points"):
            return student_reply(messages, system, schema)
        text = messages[-1].content
        self.prompts.append((system or "") + text)
        key = re.search(r"Target record:\n\[([^\]]+)\]", text).group(1)
        ask = "The record supports applicants who describe their prior work."
        if self.bad:
            ask = "The record pays 987654321 dollars to every applicant."
        pts = [{"asks": ask, "asks_ids": [key],
                "you": "You describe your education and activities in your CV.",
                "you_ids": ["user:cv"]}] * 3
        return json.dumps({"reasoning": "r", "points": pts,
                           "missing": ["The record asks for a recommender; nothing you added "
                                       "shows one."],
                           "cited_ids": [key, "user:cv"]})


@pytest.fixture
def stack(env, tmp_path, monkeypatch):
    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    note = f"Led a food drive. {ECANARY} {EMAIL} {PHONE}"
    docs.add(env.ud, env.uid, "student", "entry", text=note)
    c, svc = account_app(env, tmp_path, monkeypatch)
    got = run_brief(env, svc, c)
    assert got["brief"]["status"] == "done", got["brief"]["error"]
    jobs.set_brief_service(lambda: svc)
    lead = c.get(f"/briefs/{got['_id']}").json()["leads"][0]
    yield env, c, svc, got["_id"], lead["record_id"]
    jobs._brief_service = None


def go(env, c, svc, bid, rid, model, timeout=40, again=False):
    svc.models.provider = lambda spec: FakeProvider(responder=model)
    r = c.post(f"/briefs/{bid}/cover-points", json={"record_id": rid, "again": again})
    assert r.status_code == 202, r.text
    job = r.json()["job_id"]
    run_worker(env.pg, ["cover_points"], lambda: job_state(env.pg, job) in
               ("succeeded", "failed", "dead"), timeout=timeout)
    return job, c.get(f"/briefs/{bid}/cover-points", params={"record_id": rid, "job_id": job})


def test_cover_points_run_on_a_worker_and_are_stored_encrypted(stack):
    env, c, svc, bid, rid = stack
    model = Cover()
    job, r = go(env, c, svc, bid, rid, model)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job"] == {"id": job, "state": "succeeded"}
    got = body["result"]
    assert got["status"] == "done" and len(got["points"]) == 3 and got["missing"]
    assert got["points"][0]["asks_ids"] == [rid] and got["points"][0]["you_ids"] == ["user:cv"]
    assert rid in got["sources"] and got["note"]
    # ids only in the job; the points live in one encrypted row, nothing in a public table
    payload = sql(env.pg, "SELECT payload::text FROM jobs WHERE kind = 'cover_points'")[0][0]
    assert set(json.loads(payload)) == {"brief_id", "record_id"}
    rows = sql(env.pg, "SELECT blob FROM user_data WHERE kind = 'cover_points'")
    assert len(rows) == 1 and b"describe their prior work" not in bytes(rows[0][0])
    stored = env.ud.list(env.uid, "cover_points", "student", CoverPointSet)
    assert [x.record_id for _, x in stored] == [rid]
    # the call was charged to the account and written to the ledger
    roles = [x[0] for x in sql(env.pg, "SELECT role FROM spend_ledger WHERE user_id = %s",
                               env.uid)]
    assert "cover_points" in roles
    assert quota.usage(env.r, env.pool, env.uid).spent_usd > 0
    # contact details and the entry canary never reach the model's prompt as contacts
    assert model.prompts and not any(EMAIL in p or PHONE in p for p in model.prompts)
    # a second run replaces the stored set instead of adding another
    go(env, c, svc, bid, rid, Cover())
    assert len(env.ud.list(env.uid, "cover_points", "student", CoverPointSet)) == 1


def test_a_sample_scholarship_lead_resolves_and_stays_marked_sample(stack):
    env, c, svc, bid, rid = stack
    leads = c.get(f"/briefs/{bid}").json()["leads"]
    samples = [x["record_id"] for x in leads if x["record_id"].startswith("sample:")]
    assert samples, "the student brief should hold SYNTHETIC sample leads"
    _, r = go(env, c, svc, bid, samples[0], Cover())
    got = r.json()["result"]
    assert got["status"] == "done" and got["sample"] is True and got["points"]


def test_points_that_fail_the_check_twice_are_stored_withheld(stack):
    env, c, svc, bid, rid = stack
    model = Cover(bad=True)
    _, r = go(env, c, svc, bid, rid, model)
    got = r.json()["result"]
    assert got["status"] == "withheld" and got["points"] == []
    assert len(model.prompts) == 2  # regenerated once, then flagged


def test_a_record_not_in_the_brief_is_404_and_a_guest_is_403(stack, env):
    env_, c, svc, bid, rid = stack
    assert c.post(f"/briefs/{bid}/cover-points", json={"record_id": "grants_gov:0"}
                  ).status_code == 404
    assert c.get(f"/briefs/{bid}/cover-points", params={"record_id": rid}
                 ).json() == {"result": None, "job": None}
    env_.session.user_id = None  # a guest session
    assert c.post(f"/briefs/{bid}/cover-points", json={"record_id": rid}).status_code == 403
    assert c.get(f"/briefs/{bid}/cover-points", params={"record_id": rid}).status_code == 403


def test_the_same_question_twice_is_one_live_job(stack):
    env, c, svc, bid, rid = stack
    a = c.post(f"/briefs/{bid}/cover-points", json={"record_id": rid}).json()
    b = c.post(f"/briefs/{bid}/cover-points", json={"record_id": rid}).json()
    assert a["job_id"] == b["job_id"] and a["status"] == "queued"


def test_again_makes_a_new_job_and_spends_quota_only_then(stack, monkeypatch):
    from perch.scout import web as sweb

    env, c, svc, bid, rid = stack
    spent = []
    real = sweb.quota.admit
    monkeypatch.setattr(sweb.quota, "admit",
                        lambda *a, **k: (spent.append(a[-1]), real(*a, **k))[1])
    first, _ = go(env, c, svc, bid, rid, Cover())
    assert len(spent) == 1
    # a second plain call returns the finished job and spends nothing
    again_plain = c.post(f"/briefs/{bid}/cover-points", json={"record_id": rid}).json()
    assert again_plain["job_id"] == first and len(spent) == 1
    # "again" is a new job, charged once, and the stored set is replaced by the newer one
    second, r = go(env, c, svc, bid, rid, Cover(), again=True)
    assert second != first and len(spent) == 2
    assert len(env.ud.list(env.uid, "cover_points", "student", CoverPointSet)) == 1
    assert r.json()["job"]["state"] == "succeeded" and r.json()["result"]["points"]
    # another "again" is another attempt; a plain call still returns the first job
    a = c.post(f"/briefs/{bid}/cover-points", json={"record_id": rid, "again": True}).json()
    b = c.post(f"/briefs/{bid}/cover-points", json={"record_id": rid}).json()
    assert a["job_id"] != second and b["job_id"] == first


def test_the_brief_lists_the_records_that_have_stored_points(stack):
    env, c, svc, bid, rid = stack
    assert c.get(f"/briefs/{bid}").json()["cover_points"] == []
    go(env, c, svc, bid, rid, Cover())
    assert c.get(f"/briefs/{bid}").json()["cover_points"] == [rid]

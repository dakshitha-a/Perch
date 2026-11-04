# ruff: noqa: F811  (pytest fixtures imported by name, then used as arguments)
"""S45 on the account path: a stuck busy session escapes on a timer. Fake models only.
SYNTHETIC text only. Needs the test Postgres and Redis; run by `make test-user`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from perch.scout import session as ssn
from perch.scout.turn import user_message
from tests.conftest import PG_URL
from tests.test_scout_v2_account import stack  # noqa: F401
from tests.test_user_account import REDIS_URL, env, rds  # noqa: F401

pytestmark = [pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set"),
              pytest.mark.skipif(not REDIS_URL, reason="PERCH_TEST_REDIS_URL is not set")]


def _stuck(stack, age_s, job=False):
    """A session whose last question has no job (or an unknown one), made `age_s` old."""
    env, c, svc, bid, script = stack
    sid = ssn.create(env.ud, env.uid, "student", bid)
    um = user_message(question="Which lead is strongest?")
    um["at"] = (datetime.now(UTC) - timedelta(seconds=age_s)).isoformat()
    if job:
        um["job_id"] = str(uuid.uuid4())  # a job the queue does not know
    ssn.append(env.ud, env.uid, sid, [um])
    return c, sid


def test_a_question_with_no_job_is_busy_only_for_a_short_time(stack):
    c, sid = _stuck(stack, 5)
    assert c.get(f"/scout/{sid}").json()["busy"] is True
    assert c.post(f"/scout/{sid}/ask", json={"question": "again"}).status_code == 409


@pytest.mark.parametrize("job", [False, True])
def test_an_old_question_with_no_or_an_unknown_job_is_not_busy(stack, job):
    c, sid = _stuck(stack, 600, job=job)
    v = c.get(f"/scout/{sid}").json()
    assert v["busy"] is False and v["status"] == "failed" and v["error"]
    assert c.post(f"/scout/{sid}/ask", json={"question": "again"}).status_code == 202

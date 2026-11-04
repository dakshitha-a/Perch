"""The student brief and its screens on the account path (S42, ported from test_student.py).

SYNTHETIC text only. Needs the test Postgres and Redis; run by `make test-user`. The brief runs
on a real worker with the fake models; the signed-in user's CV, interests and entries are
stored encrypted and read by the job.
"""

from __future__ import annotations

import pytest

from tests.conftest import PG_URL
from tests.student_helpers import (
    PERSONAS,
    account_app,
    add_persona,
    canaries,
    consent,
    run_brief,
)
from tests.test_user_account import REDIS_URL, env, rds  # noqa: F401 - fixtures

pytestmark = [pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set"),
              pytest.mark.skipif(not REDIS_URL, reason="PERCH_TEST_REDIS_URL is not set")]


@pytest.mark.parametrize("name", PERSONAS)
def test_each_persona_gets_leads_on_both_tabs(env, tmp_path, monkeypatch, name):  # noqa: F811
    consent(env, monkeypatch)
    add_persona(env, name)
    c, svc = account_app(env, tmp_path, monkeypatch)
    got = run_brief(env, svc, c)
    b = got["brief"]
    assert b["status"] == "done", b["error"]
    assert [s["name"] for s in b["stages"]] == ["student_profile", "fellowships",
                                                "scholarships", "student_explanations"]
    by = {"F": [], "S": []}
    for x in got["leads"]:
        by[x["route"]].append(x)
    ok = lambda xs: [x for x in xs if x["verdict"] != "not eligible"]  # noqa: E731
    assert ok(by["F"]) and ok(by["S"])
    assert all(x["sample"] and x["record"]["source"] == "synthetic" for x in by["S"])
    assert not any(x["sample"] for x in by["F"])
    s = ok(by["S"])[0]
    assert s["explanation"] and "user:achievement-a" in s["cited_ids"]
    assert all(isinstance(g, str) for x in by["S"] for g in x["gaps"])
    assert canaries(name)  # the persona carries its canary tokens (rule 12)


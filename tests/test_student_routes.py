"""Exports, samples and the hand-off on a student brief, through the account routes
(S42, ported from test_student.py). The Scout tests of this file moved to
tests/test_scout_v2_account.py when Scout was rebuilt (S44). SYNTHETIC text only; needs the
test Postgres and Redis (`make test-user`)."""

from __future__ import annotations

import time

import pytest

from tests.conftest import PG_URL
from tests.student_helpers import (
    account_app,
    add_persona,
    consent,
    run_brief,
)
from tests.test_user_account import REDIS_URL, env, rds  # noqa: F401 - fixtures

pytestmark = [pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set"),
              pytest.mark.skipif(not REDIS_URL, reason="PERCH_TEST_REDIS_URL is not set")]


def _keep(c, bid, lead):
    r = c.post(f"/briefs/{bid}/leads/{lead['id']}/keep")
    assert r.status_code == 200, r.text
    return r.json()


# --- a guest's student brief reads the SYNTHETIC sample persona (ARCHITECTURE_V1 7.4) ---

def test_a_guest_student_brief_reads_the_sample_persona_and_stores_nothing(
        env, tmp_path, monkeypatch):  # noqa: F811
    from perch.auth import deps
    from perch.auth.session import Session
    from perch.user.briefs import guest_hash
    from tests.test_user_account import sql

    c, svc = account_app(env, tmp_path, monkeypatch)
    guest = Session(sid="g-" + "x" * 20, user_id=None, guest=True, roles=frozenset(),
                    audience="student", csrf="c", display_name=None, created=time.time(),
                    abs_exp=time.time() + 3600, consent_version=0)
    c.app.dependency_overrides[deps.session_optional] = lambda request: guest
    got = run_brief(env, svc, c)
    b = got["brief"]
    assert b["status"] == "done", b["error"]
    assert b["options"]["persona"] == "persona-ug" and b["options"]["sample"].startswith(
        "SYNTHETIC")
    assert {x["route"] for x in got["leads"]} == {"F", "S"}
    assert all(x["sample"] for x in got["leads"] if x["route"] == "S")
    assert sql(env.pg, "SELECT count(*) FROM user_data") == [(0,)]  # a guest stores nothing
    assert guest_hash(guest.sid) in "".join(env.r.keys("perch:gsess:*"))
    # a guest has no hand-off, no Scout and no documents
    assert c.post(f"/briefs/{got['_id']}/scout", json={"question": "hi"}).status_code == 403
    r = c.post(f"/briefs/{got['_id']}/handoff", json={"office": "research_development"})
    assert r.status_code == 403
    # a note to an office needs an account too (decided 2026-11-04)
    assert c.get(f"/briefs/{got['_id']}/student/note?route=F").status_code == 403
    md = c.get(f"/briefs/{got['_id']}/export.md").text
    assert "SAMPLE DATA" in md and "your own documents" not in md


# --- exports, samples and the note on the account path ---

def test_a_student_export_is_full_and_carries_the_sample_banner(env, tmp_path, monkeypatch):  # noqa: F811
    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    c, svc = account_app(env, tmp_path, monkeypatch)
    got = run_brief(env, svc, c)
    bid = got["_id"]
    lead = next(x for x in got["leads"] if x["route"] == "S")
    assert _keep(c, bid, lead)["status"] == "kept"
    for ext in ("json", "md", "html"):
        e = c.get(f"/briefs/{bid}/export.{ext}").text
        assert "SAMPLE DATA" in e, ext  # every export carries the banner (rule 11)
        assert "withheld: this" not in e and "Withheld:" not in e, ext
        if ext != "json":
            assert "Verdict: " in e and "includes text drawn from your own documents" in e, ext
    exp = c.get(f"/briefs/{bid}/export.json").json()
    assert exp["sample_notice"] and exp["samples"]["leads"] and exp["samples"]["records"]
    assert all(x["route"] == "F" for x in exp["leads"])  # samples never share a public list
    # a student brief has no researcher hand-off; its note is written on the Compare tab
    assert c.post(f"/briefs/{bid}/handoff", json={"office": "research_development"}
                  ).status_code == 422


def test_no_sample_record_is_reachable_outside_student_briefs(env, tmp_path, monkeypatch):  # noqa: F811
    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    c, svc = account_app(env, tmp_path, monkeypatch)
    run_brief(env, svc, c)
    assert c.get("/records/sample:sch-0001").status_code == 404
    from perch.schemas import Scholarship

    with svc.repo() as r:  # nothing synthetic was written to the public store
        assert not [s for s in r.list(Scholarship, include_samples=True) if s.synthetic]


def test_the_compare_note_is_written_once_on_the_server(env, tmp_path, monkeypatch):  # noqa: F811
    """Review W9: the Compare tab's note comes from the same code as Scout's draft_note."""
    from perch.scout.student_tools import OFFICES

    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    c, svc = account_app(env, tmp_path, monkeypatch)
    got = run_brief(env, svc, c)
    bid = got["_id"]
    lead = next(x for x in got["leads"] if x["route"] == "S" and x["verdict"] != "not eligible")
    assert c.get(f"/briefs/{bid}/student/note?route=S").status_code == 404  # none kept
    _keep(c, bid, lead)
    n = c.get(f"/briefs/{bid}/student/note?route=S").json()
    assert n["office"] == OFFICES["S"][0] and n["sample"] and n["to"] == ""
    assert n["body"].startswith("SAMPLE DATA") and "(SAMPLE record, not real)" in n["body"]
    assert n["subject"] == "Advice on scholarships: 1 on my list"


def test_a_signed_in_student_brief_has_no_sample_route(env, tmp_path, monkeypatch):  # noqa: F811
    """S43 M4: the SYNTHETIC samples live on their own screen, so a real account's brief
    holds public leads only and its sample stage is skipped."""
    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    c, svc = account_app(env, tmp_path, monkeypatch, samples=False)
    got = run_brief(env, svc, c)
    assert got["brief"]["status"] == "done"
    assert {x["route"] for x in got["leads"]} == {"F"} and not any(x["sample"] for x in got["leads"])
    stage = next(s for s in got["brief"]["stages"] if s["name"] == "scholarships")
    assert stage["status"] == "skipped"


def test_a_brief_poll_answers_304_while_nothing_changed(env, tmp_path, monkeypatch):  # noqa: F811
    """P3: a poll that sends the last ETag gets 304 and no body; an answer is no-store."""
    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    c, svc = account_app(env, tmp_path, monkeypatch)
    got = run_brief(env, svc, c)
    bid = got["_id"]
    first = c.get(f"/briefs/{bid}")
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    tag = first.headers["etag"]
    again = c.get(f"/briefs/{bid}", headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b""
    _keep(c, bid, got["leads"][0])
    changed = c.get(f"/briefs/{bid}", headers={"If-None-Match": tag})
    assert changed.status_code == 200 and changed.headers["etag"] != tag

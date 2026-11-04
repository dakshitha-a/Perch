"""Exports, samples, the hand-off and Scout on a student brief, through the account routes
(S42, ported from test_student.py). SYNTHETIC text only; needs the test Postgres and Redis
(`make test-user`)."""

from __future__ import annotations

import json
import time

import pytest

from perch.llm.fake import FakeProvider
from tests.conftest import PG_URL
from tests.student_helpers import (
    account_app,
    add_persona,
    canaries,
    consent,
    run_brief,
    student_reply,
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


# --- Scout on a student brief, through the account path ---

def _ask(c, bid, question, sid=None):
    r = (c.post(f"/scout/{sid}/ask", json={"question": question}) if sid
         else c.post(f"/briefs/{bid}/scout", json={"question": question}))
    assert r.status_code == 202, r.text
    v = r.json()
    for _ in range(50):
        v = c.get(f"/scout/{v['id']}").json()
        if not v["busy"] and v["status"] != "running":
            return v
        time.sleep(0.1)
    raise AssertionError("Scout did not finish")


def test_student_scout_uses_only_the_student_tools_and_never_shows_the_cv(
        env, tmp_path, monkeypatch):  # noqa: F811
    from perch.llm import ToolCall
    from perch.scout.student_tools import STUDENT_ALLOWLIST
    from perch.scout.tools import ALLOWLIST

    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    steps = iter([[ToolCall("c1", "search_options", {"route": "S"})],
                  [ToolCall("c2", "read_cv", {})],
                  [ToolCall("c3", "search_opportunities", {"route": "A"})],  # not allowed
                  [ToolCall("c4", "draft_note", {"route": "S"})],
                  "Your sample options are listed above, and the note is ready to copy."])

    def reply(messages, system, schema):
        if system and system.startswith("You are Scout"):
            assert "student" in system and "SAMPLE" in system
            return next(steps)
        return student_reply(messages, system, schema)

    c, svc = account_app(env, tmp_path, monkeypatch, responder=reply)
    got = run_brief(env, svc, c)
    bid = got["_id"]
    lead = next(x for x in got["leads"] if x["route"] == "S" and x["verdict"] != "not eligible")
    _keep(c, bid, lead)
    v = _ask(c, bid, "What can I apply for?")
    cards = {x["tool"]: x for x in v["exchanges"][0]["cards"]}
    assert set(cards) == {"search_options", "read_cv", "search_opportunities", "draft_note"}
    assert cards["search_opportunities"]["status"] == "refused"
    assert set(STUDENT_ALLOWLIST).isdisjoint(set(ALLOWLIST) - {"get_record", "cover_points"})
    assert cards["search_options"]["status"] == "done"
    assert all(r.startswith("sample:") for r in cards["search_options"]["records"])
    assert cards["read_cv"]["status"] == "done"
    note = cards["draft_note"]["draft"]
    assert note and "SAMPLE" in note["body"] and note["office"] == "Student Financial Services"
    x = v["exchanges"][0]
    assert x["answer_by"] == "code" and x["answer"].startswith(
        "The note to Student Financial Services is below. Perch never sends it")
    assert not any(t in json.dumps(v) for t in canaries("persona-ug"))  # no CV text in the view


def test_one_user_cannot_open_anothers_scout_session_or_brief(env, tmp_path, monkeypatch):  # noqa: F811
    from tests.user_helpers import new_user

    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    c, svc = account_app(env, tmp_path, monkeypatch, responder=lambda m, s, sc: "An answer.")
    got = run_brief(env, svc, c)
    bid = got["_id"]
    v = _ask(c, bid, "Hello?")
    env.session.user_id = new_user(env.pg)  # another account, same cookie
    assert c.get(f"/scout/{v['id']}").status_code == 404
    assert c.get(f"/briefs/{bid}").status_code == 404
    assert c.get(f"/briefs/{bid}/export.md").status_code == 404


def _compare_answers(c, svc, bid, got, answers):
    """Keep one fellowship and one sample, ask Scout to compare them; the fake model calls
    compare_options, then gives each answer in turn, built from the tool result's ids."""
    from perch.llm import ToolCall

    for route in ("F", "S"):
        lead = next(x for x in got["leads"] if x["route"] == route
                    and x["verdict"] != "not eligible")
        _keep(c, bid, lead)
    seen: dict = {}

    def reply(messages, system, schema):
        if system and system.startswith("You are Scout"):
            last = messages[-1]
            if last.tool_results:
                res = json.loads(last.tool_results[0].content)
                seen["result"] = res
                rows = [r for k in ("rows", "fellowships", "sample_scholarships")
                        for r in res.get(k, [])]
                seen["f"] = next(r["id"] for r in rows if not r.get("sample"))
                seen["s"] = next(r["id"] for r in rows if r.get("sample"))
            if not seen:
                return [ToolCall("c1", "compare_options", {})]
            return next(answers).format(f=seen["f"], s=seen["s"])
        return student_reply(messages, system, schema)

    svc.models.provider = lambda spec: FakeProvider(responder=reply)
    v = _ask(c, bid, "Compare my kept options")
    return v["exchanges"][-1], seen["result"]


def test_scout_never_lists_samples_with_public_fellowships(env, tmp_path, monkeypatch):  # noqa: F811
    """Q1, standing rule 11, enforced by code: compare_options returns two groups, and an
    answer whose list or sentence cites a sample with a public record is rewritten once,
    then withheld."""
    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    c, svc = account_app(env, tmp_path, monkeypatch)
    got = run_brief(env, svc, c)
    bid = got["_id"]
    mixed = "Your kept options:\n- A fellowship [{f}]\n- A sample scholarship [{s}]"
    x, res = _compare_answers(c, svc, bid, got, iter([mixed, mixed]))
    assert "rows" not in res and res["fellowships"] and res["sample_scholarships"]
    assert x["answer"] is None and x["flagged"]
    assert any("sample" in e for e in x["errors"])
    one = "The fellowship [{f}] and the sample scholarship [{s}] are kept."
    x, _ = _compare_answers(c, svc, bid, got, iter([one, one]))
    assert x["answer"] is None and x["flagged"]
    apart = ("Fellowships:\n- A fellowship [{f}]\n\nSample scholarships (invented):\n"
             "- A sample scholarship [{s}]")
    x, _ = _compare_answers(c, svc, bid, got, iter([apart]))
    assert x["answer"] and not x["flagged"], x["errors"]


def test_student_cover_points_on_a_fellowship_and_on_a_sample(env, tmp_path, monkeypatch):  # noqa: F811
    """S33: cover_points on the student allowlist reads the CV, interests and achievements
    for one option; a sample option is allowed and the result stays marked sample. The
    answer line is code; no CV text reaches the view."""
    from perch.llm import ToolCall
    from tests.test_scout import points_reply

    consent(env, monkeypatch)
    add_persona(env, "persona-ug")
    c, svc = account_app(env, tmp_path, monkeypatch)
    got = run_brief(env, svc, c)
    bid = got["_id"]
    fellowship = next(x for x in got["leads"] if x["route"] == "F"
                      and x["verdict"] != "not eligible")
    sample = next(x for x in got["leads"] if x["route"] == "S"
                  and x["verdict"] != "not eligible")
    steps = iter([[ToolCall("c1", "cover_points", {"record_id": fellowship["record_id"]})],
                  [ToolCall("c2", "cover_points", {"record_id": sample["record_id"]})]])

    def reply(messages, system, schema):
        if system and system.startswith("You are Scout"):
            assert "cover_points reads the CV itself for one option" in system
            return next(steps)
        return points_reply(messages, system, schema) or student_reply(messages, system, schema)

    svc.models.provider = lambda spec: FakeProvider(responder=reply)
    v = _ask(c, bid, "What points could my application make for it?")
    v = _ask(c, bid, "And for the sample one?", sid=v["id"])
    first, second = v["exchanges"]
    pts = first["cards"][0]["points"]
    assert first["cards"][0]["status"] == "done"
    assert pts["for"]["id"] == fellowship["record_id"] and pts["for"]["sample"] is False
    assert all(p["asks_ids"] == [fellowship["record_id"]] for p in pts["points"])
    assert pts["points"][0]["you_ids"] == ["user:cv"] and pts["status"] == "done"
    assert pts["sources"]["user:cv"] == "Your CV" and "note" not in pts
    assert first["answer_by"] == "code" and first["answer"].startswith(
        f"Points for {pts['for']['title']} are below: 3 points")
    spts = second["cards"][0]["points"]
    assert spts["for"]["id"].startswith("sample:") and spts["for"]["sample"] is True
    assert second["answer"].endswith("Perch never sends anything. This is an invented sample "
                                     "record.")
    assert not any(t in json.dumps(v) for t in canaries("persona-ug"))

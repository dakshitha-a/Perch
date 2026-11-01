"""Student mode (S18): the rules against the hand-written keys, the student brief in a
private session, the canary, and that no sample record leaves student mode.
Inputs are the SYNTHETIC student personas; models are fakes."""

import json
import re
import time
from datetime import date
from pathlib import Path

import pytest

from perch import scholarships as S
from perch.llm.fake import FakeProvider
from perch.retrieve import index_opportunities
from perch.sources import temple
from perch.student import check, gaps, parse_student_cv

from .test_api import make
from .test_private import files_with, private_env, snapshot

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data/synthetic"
PERSONAS = ("persona-ug", "persona-masters", "persona-phd")
FILES = {"cv": "cv.md", "interests": "interests.md", "achievements": "achievements.md"}


def canaries(name: str) -> list[str]:
    return [re.search(r"PERCH-CANARY-[A-Z0-9-]+", (SYN / name / f).read_text()).group(0)
            for f in FILES.values()]


def student_reply(messages, system, schema):
    """A valid fit explanation citing the record shown and the first achievement."""
    if schema and "fit" in schema.get("properties", {}):
        rid = re.search(r"Opportunity:\n\[([^\]]+)\]", messages[-1].content).group(1)
        assert "[private:achievement-a]" in system
        pid = "achievement-a"  # models drop the "private:" prefix; the skill maps it back
        return json.dumps({
            "reasoning": "r", "fit": 60,
            "opportunity_sentence": f"The award supports students in this field [{rid}].",
            "research_findings": [{"paper_id": pid, "finding": "presented a poster"}],
            "link_sentence": "The student's work matches the award.",
            "cited_ids": [rid, pid]})
    return ""


@pytest.mark.parametrize("name", PERSONAS)
def test_rules_match_the_hand_written_keys(name):
    facts = parse_student_cv((SYN / name / "cv.md").read_text())
    key = json.loads((SYN / name / "answer_key.json").read_text())
    by = {s.id: s for s in S.read_samples()}
    as_of = date.fromisoformat(key["as_of"])
    for c in key["cases"]:
        v = check(by[c["id"]], facts, as_of)
        g = [k for k, _ in gaps(by[c["id"]], facts)] if v.verdict != "not eligible" else []
        assert (v.verdict, v.reason, g) == (c["verdict"], c["reason"], c["gaps"]), c["id"]


def test_missing_facts_never_give_eligible():
    facts = parse_student_cv("# CV\n\n## Education\n- B.S. candidate, Biology\n")
    s = next(s for s in S.read_samples() if s.id == "sample:sch-0001")  # GPA, year, full-time
    v = check(s, facts, date(2026, 11, 6))
    assert v.verdict == "may be eligible"
    assert {"class_year_unstated", "gpa_unstated", "enrolment_unstated"} <= set(v.unknown)


def student_app(tmp_path, monkeypatch):
    private_env(monkeypatch)
    monkeypatch.setenv("PERCH_SAMPLE_DB", str(tmp_path / "sample.db"))
    c, service = make(tmp_path)
    with service.repo() as r:
        index_opportunities(r, service.models.get("index"), service.models.get("embedder"))
        r.upsert(temple.parse_listing((ROOT / "tests/fixtures/temple/sdfa_find_fellowship.html")
                                      .read_text()))
    service.models.provider = lambda spec: FakeProvider(responder=student_reply)
    return c, service


def open_student(c, name):
    tok = c.post("/private/session").json()["token"]
    h = {"X-Perch-Private": tok}
    for kind, f in FILES.items():
        r = c.post("/private/documents", headers=h,
                   json={"kind": kind, "text": (SYN / name / f).read_text()})
        assert r.status_code == 201, r.text
    return h


@pytest.mark.parametrize("name", PERSONAS)
def test_each_persona_gets_leads_on_both_tabs(tmp_path, monkeypatch, name):
    c, _ = student_app(tmp_path, monkeypatch)
    h = open_student(c, name)
    assert c.post("/private/student/brief", headers=h,
                  json={"as_of": "2026-11-06"}).status_code == 202
    got = c.get("/private/brief", headers=h).json()
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
    assert s["explanation"] and "private:achievement-a" in s["cited_ids"]
    assert "private:achievement-a" in got["papers"]
    # Every gap line and verdict line is code-written from the record and the CV.
    assert all(isinstance(g, str) for x in by["S"] for g in x["gaps"])
    assert c.post("/private/end", headers=h).json()["ended"]


def test_student_canary_leaves_no_trace(tmp_path, monkeypatch, capfd):
    start = time.time()
    c, service = student_app(tmp_path, monkeypatch)
    before = snapshot(tmp_path)
    toks = []
    for name in PERSONAS:
        toks += canaries(name)
        h = open_student(c, name)
        assert c.post("/private/student/brief", headers=h,
                      json={"as_of": "2026-11-06"}).status_code == 202
        got = c.get("/private/brief", headers=h).json()
        assert got["brief"]["status"] == "done"
        lead = next(x for x in got["leads"] if x["route"] == "S")
        c.post(f"/private/leads/{lead['id']}/keep", headers=h)
        for ext in ("json", "md", "html"):
            e = c.get(f"/private/export.{ext}", headers=h).text
            assert "SAMPLE DATA" in e, ext  # every export carries the banner
            assert not re.search(r"your CV (says|lists)", e), ext  # CV facts are withheld
        assert c.post("/private/handoff", headers=h,
                      json={"office": "research_development"}).status_code == 422
        c.post("/private/end", headers=h)
    assert snapshot(tmp_path) == before, "a student session wrote to the data directory"
    assert files_with(tmp_path, toks) == []
    assert files_with("/tmp", toks, since=start) == []
    out, err = capfd.readouterr()
    assert not any(t in out + err for t in toks)


def test_no_sample_record_is_reachable_outside_student_mode(tmp_path, monkeypatch):
    c, service = student_app(tmp_path, monkeypatch)
    sid = "sample:sch-0001"
    assert c.get(f"/records/{sid}").status_code == 404
    with service.repo() as r:
        from perch.schemas import Scholarship

        assert not [s for s in r.list(Scholarship) if s.synthetic]
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28",
                                  "explain": False}).json()["id"]
    got = c.get(f"/briefs/{bid}").json()
    assert not any(x.get("sample") or str(x.get("record_id", "")).startswith("sample:")
                   for x in got["leads"])
    # A researcher's private session cannot open a sample record either.
    h = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    assert c.get(f"/private/records/{sid}", headers=h).status_code == 404


def test_only_student_mode_opens_the_sample_store():
    """Rule 11: the back-test, the bench, the public API and the monitor cannot list a
    sample record, because only student-mode code opens the sample store."""
    allowed = {"perch/scholarships.py", "perch/private/student.py", "perch/private/routes.py",
               "perch/cli.py", "bench/student_mode.py"}
    pat = re.compile(r"\b(sample_records|ensure_samples|read_samples|load_samples|SAMPLE_JSONL|"
                     r"sample_db)\b")
    users = {str(p.relative_to(ROOT)) for d in ("perch", "bench", "scripts")
             for p in (ROOT / d).rglob("*.py") if pat.search(p.read_text())}
    users -= {"scripts/make_sample_scholarships.py"}  # writes the corpus file itself
    assert users <= allowed, users - allowed
    # The bench summary and the results page never mention the sample corpus.
    for f in ("bench/results/SUMMARY.md", "bench/results/RESULTS.md"):
        p = ROOT / f
        if p.exists():
            assert "sample:sch-" not in p.read_text() and S.CANARY_PREFIX not in p.read_text()


def test_student_scout_uses_only_the_student_tools(tmp_path, monkeypatch):
    """Ask Scout on a student brief (S24): the student allowlist, rule results only, no CV
    text in any tool result, sample records marked, a code-written note never sent."""
    from perch.llm import ToolCall
    from perch.scout.student_tools import STUDENT_ALLOWLIST
    from perch.scout.tools import ALLOWLIST

    c, service = student_app(tmp_path, monkeypatch)
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

    service.models.provider = lambda spec: FakeProvider(responder=reply)
    h = open_student(c, "persona-ug")
    c.post("/private/student/brief", headers=h, json={"as_of": "2026-11-06"})
    got = c.get("/private/brief", headers=h).json()
    lead = next(x for x in got["leads"] if x["route"] == "S" and x["verdict"] != "not eligible")
    c.post(f"/private/leads/{lead['id']}/keep", headers=h)
    v = c.post("/private/scout", headers=h, json={"question": "What can I apply for?",
                                                  "mode": "run"}).json()
    for _ in range(50):
        v = c.get(f"/private/scout/{v['id']}", headers=h).json()
        if not v["busy"] and v["status"] != "running":
            break
        time.sleep(0.1)
    cards = {x["tool"]: x for x in v["exchanges"][0]["cards"]}
    assert set(cards) == {"search_options", "read_cv", "search_opportunities", "draft_note"}
    assert cards["search_opportunities"]["status"] == "refused"
    assert set(STUDENT_ALLOWLIST).isdisjoint(set(ALLOWLIST) - {"get_record"})
    assert cards["search_options"]["status"] == "done"
    assert all(r.startswith("sample:") for r in cards["search_options"]["records"])
    assert cards["read_cv"]["status"] == "done"
    note = cards["draft_note"]["draft"]
    assert note and "SAMPLE" in note["body"] and note["office"] == "Student Financial Services"
    canary = canaries("persona-ug")
    assert not any(t in json.dumps(v) for t in canary)  # no CV text reached Scout's view
    assert c.post("/private/end", headers=h).json()["ended"]


def test_the_compare_note_is_written_once_on_the_server(tmp_path, monkeypatch):
    """Review W9: the Compare tab's note comes from the same code as Scout's draft_note,
    and the web app keeps no copy of the note or of the office names."""
    from perch.scout.student_tools import OFFICES

    c, _ = student_app(tmp_path, monkeypatch)
    h = open_student(c, "persona-ug")
    c.post("/private/student/brief", headers=h, json={"as_of": "2026-11-06"})
    got = c.get("/private/brief", headers=h).json()
    lead = next(x for x in got["leads"] if x["route"] == "S" and x["verdict"] != "not eligible")
    assert c.get("/private/student/note?route=S", headers=h).status_code == 404  # none kept
    c.post(f"/private/leads/{lead['id']}/keep", headers=h)
    n = c.get("/private/student/note?route=S", headers=h).json()
    assert n["office"] == OFFICES["S"][0] and n["sample"] and n["to"] == ""
    assert n["body"].startswith("SAMPLE DATA") and "(SAMPLE record, not real)" in n["body"]
    assert n["subject"] == "Advice on scholarships: 1 on my list"
    assert c.get("/private").json()["student_offices"]["F"]["name"] == OFFICES["F"][0]
    # A researcher's brief has no note.
    t = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    c.post("/private/brief", headers=t, json={"author_id": "A5026494099", "explain": False})
    assert c.get("/private/student/note?route=F", headers=t).status_code == 422
    js = (ROOT / "web/student.js").read_text()
    assert "/private/student/note" in (ROOT / "web/api.js").read_text()
    assert OFFICES["S"][0] not in js and "I am a student looking at" not in js


def test_scout_search_all_keeps_samples_in_their_own_list(monkeypatch):
    """U10, standing rule 11: with public fellowships and SYNTHETIC samples both found,
    search_options returns two lists and tells the model to keep them apart."""
    from types import SimpleNamespace as NS

    from perch.scout import student_tools as st

    leads = [NS(route="F", rank=1, verdict="may be eligible", sample=False, id="f"),
             NS(route="S", rank=1, verdict="eligible", sample=True, id="s")]
    monkeypatch.setattr(st, "_brief", lambda ctx: (None, leads))
    monkeypatch.setattr(st, "_record", lambda ctx, x: None)
    monkeypatch.setattr(st, "_row",
                        lambda ctx, x: {"id": x.id, **({"sample": True} if x.sample else {})})
    got = st.search_options(None, route="all")
    assert [r["id"] for r in got["fellowships"]] == ["f"]
    assert [r["id"] for r in got["sample_scholarships"]] == ["s"]
    assert "options" not in got and "own heading" in got["note"] and got["count"] == 2
    only = st.search_options(None, route="S")
    assert [r["id"] for r in only["options"]] == ["s"]


def _scout_answers(c, service, h, answers):
    """Keep one fellowship and one sample, ask Scout to compare them; the fake model calls
    compare_options, then gives each answer in turn, built from the tool result's ids."""
    from perch.llm import ToolCall

    got = c.get("/private/brief", headers=h).json()
    for route in ("F", "S"):
        lead = next(x for x in got["leads"] if x["route"] == route
                    and x["verdict"] != "not eligible")
        c.post(f"/private/leads/{lead['id']}/keep", headers=h)
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

    service.models.provider = lambda spec: FakeProvider(responder=reply)
    v = c.post("/private/scout", headers=h, json={"question": "Compare my kept options"}).json()
    for _ in range(50):
        v = c.get(f"/private/scout/{v['id']}", headers=h).json()
        if not v["busy"] and v["status"] != "running":
            break
        time.sleep(0.1)
    return v["exchanges"][-1], seen["result"]


def test_scout_never_lists_samples_with_public_fellowships(tmp_path, monkeypatch):
    """Q1, standing rule 11, enforced by code: compare_options returns two groups, and an
    answer whose list or sentence cites a sample with a public record is rewritten once,
    then withheld."""
    c, service = student_app(tmp_path, monkeypatch)
    h = open_student(c, "persona-ug")
    c.post("/private/student/brief", headers=h, json={"as_of": "2026-11-06"})
    mixed = "Your kept options:\n- A fellowship [{f}]\n- A sample scholarship [{s}]"
    x, res = _scout_answers(c, service, h, iter([mixed, mixed]))
    assert "rows" not in res and res["fellowships"] and res["sample_scholarships"]
    assert x["answer"] is None and x["flagged"]
    assert any("sample" in e for e in x["errors"])
    one = "The fellowship [{f}] and the sample scholarship [{s}] are kept."
    x, _ = _scout_answers(c, service, h, iter([one, one]))
    assert x["answer"] is None and x["flagged"]
    apart = ("Fellowships:\n- A fellowship [{f}]\n\nSample scholarships (invented):\n"
             "- A sample scholarship [{s}]")
    x, _ = _scout_answers(c, service, h, iter([apart]))
    assert x["answer"] and not x["flagged"], x["errors"]

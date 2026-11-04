"""The open-question bench (S45) runs offline: the question set, the fake run, the cap, the
grading sheet and the scrub. No spend, no network. SYNTHETIC text only."""

from __future__ import annotations

import csv
from datetime import date

import pytest

from bench import scout_open as so
from perch.grounding import FakeGrounder

from .test_api import make


@pytest.fixture(scope="module")
def questions():
    return so.load_questions()


def of(qs, s):
    return [q for q in qs if q["set"] == s]


def test_the_question_set_has_the_required_counts_and_kinds(questions):
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))
    assert len(of(questions, "in")) >= 30
    assert len(of(questions, "out")) >= 20
    assert len(of(questions, "distress")) == 5
    assert {q["audience"] for q in questions} == {"student", "researcher"}
    in_kinds = {q["kind"] for q in of(questions, "in")}
    assert {"how_to", "cv_feedback", "general_advice", "cover_points", "compare", "filter",
            "themes", "count"} <= in_kinds
    out_kinds = {q["kind"] for q in of(questions, "out")}
    assert {"math", "coding", "trivia", "homework", "therapy", "mixed"} <= out_kinds
    assert all(q.get("leak") for q in questions if q["kind"] == "mixed")
    assert all(q.get("why") for q in of(questions, "in"))


def test_cv_questions_use_synthetic_personas_only(questions):
    for q in questions:
        if q.get("persona"):
            cv, entries = so.persona(q["persona"])
            assert cv and "SYNTHETIC" in cv, q["id"]
            assert "unpublished" not in q["persona"]
    # persona-1's unpublished-work stand-in is never loaded
    cv, entries = so.persona("persona-1")
    assert not any("MS-T8V3" in t for _, t in entries) and "MS-T8V3" not in (cv or "")


def test_run_order_mixes_the_sets(questions):
    first = [q["set"] for q in so.interleave(questions)[:12]]
    assert set(first) == {"in", "out", "distress"}


def fake_run(tmp_path, questions, max_usd=2.0):
    _, service = make(tmp_path / "store")
    pf = so.fake_provider_for(questions)
    service.models.provider = lambda spec: pf("scout")
    out = tmp_path / "out"
    run = so.execute(service, questions, out, fake=True, max_usd=max_usd,
                     as_of=date(2026, 10, 28), grounder=FakeGrounder(), provider_for=pf,
                     say=lambda s: None)
    return run, out


def rows_of(p):
    return list(csv.DictReader(p.open(encoding="utf-8")))


def test_the_fake_run_scores_both_engines_and_writes_a_blank_grading_sheet(tmp_path, questions):
    run, out = fake_run(tmp_path, questions)
    assert not run.stopped
    new, old = rows_of(out / "new.csv"), rows_of(out / "old.csv")
    assert len(new) == len(old) == len(questions)
    assert list(new[0]) == so.NEW_FIELDS and list(old[0]) == so.OLD_FIELDS
    # the new engine refuses every out-of-scope question and gives care to every distress one
    assert all(r["correct"] == "True" for r in new if r["set"] in ("out", "distress")), \
        [r["id"] for r in new if r["set"] != "in" and r["correct"] != "True"]
    assert all(r["wrongly_blocked"] == "False" for r in new if r["set"] == "in")
    assert {r["gate"] for r in new if r["set"] == "out"} == {"out_of_scope"}
    assert all(r["answer_kind"] == "distress" for r in new if r["set"] == "distress")
    # the old engine ran on researcher questions and says why it did not run on the others
    assert any(r["ran"] == "True" for r in old)
    assert {r["answer_kind"][:3] for r in old if r["audience"] == "student"} == {"n/a"}
    assert all(r["gate"].startswith("n/a") for r in old if r["ran"] == "True")
    # every answered row has the citation checks filled in
    ans = [r for r in new if r["answer_kind"] == "answer"]
    assert ans and all(r["cites_valid"] in ("True", "False") and r["layer1_pass"] != ""
                       for r in ans)
    # the grading sheet: both engines, every question, usefulness blank for a person
    g = rows_of(out / "grades.csv")
    assert list(g[0]) == so.GRADE_FIELDS and len(g) == 2 * len(questions)
    assert {r["engine"] for r in g} == {"new", "old"}
    assert all(r["usefulness"] == "" for r in g)
    assert {"summary.csv", "report.md"} <= {p.name for p in out.iterdir()}
    assert "correct" in (out / "report.md").read_text()


def test_the_cap_stops_the_run_and_the_partial_results_are_still_written(tmp_path, questions):
    run, out = fake_run(tmp_path, questions, max_usd=3 * so.FAKE_CALL_USD)
    new = rows_of(out / "new.csv")
    assert run.stopped and 0 < len(new) < len(questions)
    assert run.total_usd <= 6 * so.FAKE_CALL_USD  # one question may overshoot the cap
    assert len(rows_of(out / "grades.csv")) == 2 * len(new)


def test_answer_text_is_scrubbed_through_the_alias_map(tmp_path):
    p = tmp_path / "aliases.csv"
    p.write_text("alias,openalex_id,name,note\nPI-9,A1,Zora Quillfeather,SYNTHETIC\n")
    al = so.alias_map(p)
    assert so.scrub("Grant for ZORA QUILLFEATHER's lab", al) == "Grant for PI-9's lab"


def test_ids_and_judgement_helpers():
    assert so.ids_in("A [grants_gov:1, user:cv:education]. B [x].") == [
        "grants_gov:1", "user:cv:education", "x"]
    mixed = {"set": "out", "kind": "mixed", "leak": ["Paris"]}
    assert so.judge(mixed, "answer", "Your top lead closes soonest.") == (True, False)
    assert so.judge(mixed, "answer", "It is Paris.") == (False, False)
    assert so.judge(mixed, "refusal", "") == (True, False)
    assert so.judge({"set": "out", "kind": "math"}, "answer", "x") == (False, False)
    assert so.judge({"set": "out", "kind": "therapy"}, "distress", "") == (True, False)
    assert so.judge({"set": "in", "kind": "x"}, "refusal", "") == (False, True)
    assert so.judge({"set": "distress", "kind": "distress"}, "refusal", "") == (False, False)

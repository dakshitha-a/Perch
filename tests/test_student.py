"""Student mode: the rules, the sample store's separation and the student tools' wording
(S18 and later). The brief itself, on the account path, is in tests/test_student_account.py.
SYNTHETIC text only."""

import json
import re
from datetime import date
from pathlib import Path

import pytest

from perch import scholarships as S
from perch.student import check, gaps, parse_student_cv

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data/synthetic"
PERSONAS = ("persona-ug", "persona-masters", "persona-phd")


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


def test_only_student_mode_opens_the_sample_store():
    """Rule 11: the back-test, the bench, the public API and the monitor cannot list a
    sample record, because only student-mode code opens the sample store."""
    allowed = {"perch/scholarships.py", "perch/student.py", "perch/api.py", "perch/cli.py",
               "perch/user/briefs.py", "bench/student_mode.py",
               "perch/browse/routes.py"}  # the /samples route: SYNTHETIC only, its own list (S43)
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


def test_a_word_search_matches_any_word_and_says_which(monkeypatch):
    """R7: "stream,monitoring" had to find both words, so the Streams scholarship was
    missed and Scout said nothing matched. Words split on commas and spaces; any matches."""
    from types import SimpleNamespace as NS

    from perch.scout import student_tools as st
    from perch.scout.loop import summarise

    leads = [NS(route="S", rank=1, verdict="eligible", sample=True, id="s1"),
             NS(route="S", rank=2, verdict="eligible", sample=True, id="s2")]
    recs = {"s1": NS(name="Ostrevel Regional Streams Scholarship", purpose="River work.",
                     deadline=None, amount_max=None),
            "s2": NS(name="Inkwater Travel Grant", purpose="Conference travel.", deadline=None,
                     amount_max=None)}
    monkeypatch.setattr(st, "_brief", lambda ctx: (None, leads))
    monkeypatch.setattr(st, "_record", lambda ctx, x: recs[x.id])
    monkeypatch.setattr(st, "facts_of", lambda rec: {"title": rec.name})
    monkeypatch.setattr(st, "_row", lambda ctx, x: {"id": x.id, "sample": True})
    got = st.search_options(None, words="stream,monitoring")
    assert [r["id"] for r in got["options"]] == ["s1"]
    assert got["words_used"] == ["stream", "monitoring"]
    assert st.search_words("my stream monitoring work") == ["stream", "monitoring"]
    assert summarise("search_options", got) == "1 option match any of: stream, monitoring"


def test_every_targeted_criterion_reads_as_a_sentence():
    """R11: "For a student who first-generation college student." The line reads "For a
    student who ..." only before a verb, over every sample record's criterion."""
    from perch.student import VERBS, for_whom

    assert for_whom("first-generation college student") == \
        "For a first-generation college student."
    assert for_whom("is a parent or guardian of a dependent child") == \
        "For a student who is a parent or guardian of a dependent child."
    crits = {(json.loads(x).get("eligibility") or {}).get("targeted_criterion")
             for x in (SYN / "scholarships.jsonl").read_text().splitlines() if x.strip()}
    for c in filter(None, crits):
        line = for_whom(c)
        assert line.endswith(".") and not line.endswith("..")
        assert ("who" in line.split(c)[0]) == (c.split()[0].lower() in VERBS), line


def test_a_student_answer_never_leads_with_a_sample():
    """R13: "The soonest deadline is 15 Feb 2027 for the Quillmere ... Scholarship
    (sample)" opened the answer. The lead sentence cites public records only; samples come
    after their own heading. "Soonest" sorts every option by deadline."""
    from types import SimpleNamespace as NS

    from perch.scout import student_tools as st

    seen = {"sample:sch-0001": NS(source="synthetic"), "temple_sdfa:a": NS(source="temple_sdfa")}
    bad = ("The soonest deadline is 15 Feb 2027 for the Quillmere Scholarship (sample) "
           "[sample:sch-0001].\n\nSample scholarships (invented):\n- Quillmere [sample:sch-0001]")
    assert st.mixed_lists(bad, seen) and "opens with a sample" in st.mixed_lists(bad, seen)[0]
    for ok in ("No fellowship on your list states a deadline.\n\nSample scholarships "
               "(invented):\n- Quillmere, 15 Feb 2027 [sample:sch-0001]",
               "The soonest is the A fellowship [temple_sdfa:a].\n\nSample scholarships "
               "(invented):\n- Quillmere [sample:sch-0001]"):
        assert st.mixed_lists(ok, seen) == [], ok
    assert "sort" in st.STUDENT_TOOLS["search_options"][0].parameters["properties"]
    assert "soonest deadline" in " ".join(st.STUDENT_RULES.split())


def test_student_tool_amounts_and_notes_read_as_the_cards():
    """T27: Scout wrote "(10,000 US dollars)" where the card writes "$10,000". T13: the
    note is the student's, so a gap's CV fact reads in the first person."""
    from datetime import UTC, datetime
    from types import SimpleNamespace as NS

    from perch.schemas import Scholarship
    from perch.scout.student_tools import facts_of, mine, write_note

    t = datetime(2026, 10, 29, tzinfo=UTC)
    rec = Scholarship(id="sample:sch-x", source="synthetic", source_url="u", fetched_at=t,
                      name="SYNTHETIC award", sponsor="SYNTHETIC sponsor", amount_max=10000,
                      canary="PERCH-CANARY-TEST-T27")
    assert facts_of(rec)["amount"] == "$10,000"
    assert facts_of(rec.model_copy(update={"amount_min": 500}))["amount"] == "$500 to $10,000"
    gap = "3 letters of recommendation; your CV lists 2 referees"
    assert mine(gap) == "3 letters of recommendation (my CV lists 2 referees)"
    lead = NS(sample=False, verdict="eligible", gaps=["An essay", gap])
    body = write_note("F", [(lead, {"title": "SYNTHETIC fellowship", "deadline": "1 Mar 2027"})])
    assert "Still needed: an essay; 3 letters of recommendation (my CV lists 2 referees)" in \
        body["body"] and "your CV" not in body["body"]


def test_a_word_search_reads_the_cards_fit_sentence(monkeypatch):
    """T10: "Which fellowships fit my stream monitoring work?" said none did, although the
    REU card's own sentence says stream monitoring fits. A word search also reads the fit
    sentence and says where each match was found."""
    from types import SimpleNamespace as NS

    from perch.scout import student_tools as st

    leads = [NS(route="F", rank=1, verdict="may be eligible", sample=False, id="f",
                inference="Your SYNTHETIC stream monitoring fits", status="new"),
             NS(route="F", rank=2, verdict="may be eligible", sample=False, id="g",
                inference="Unrelated", status="new")]
    monkeypatch.setattr(st, "_brief", lambda ctx: (None, leads))
    monkeypatch.setattr(st, "_record", lambda ctx, x: None)
    monkeypatch.setattr(st, "_row", lambda ctx, x: {"id": x.id})
    got = st.search_options(None, route="all", words="stream monitoring")
    assert got["options"] == [{"id": "f", "words_found_in": "its fit sentence on the card",
                               "fit_sentence": "Your SYNTHETIC stream monitoring fits"}]
    assert "Every option listed matches" in got["note"]




def test_plain_headings_are_read_s53():
    """S53: a CV that writes "Education" with no "#", capitals or colon is still read."""
    from perch.student import parse_student_cv

    cv = ("SYNTHETIC example student (invented).\n\nSample student\n\nEducation\n"
          "- B.S. candidate, Environmental Science, SYNTHETIC State University\n"
          "- Third-year student (junior), full-time\n- Expected graduation: May 2028\n"
          "- GPA: 3.40\n\nHonours\n- SYNTHETIC Dean's List, 2025\n")
    f = parse_student_cv(cv)
    assert f.level == "bachelor's" and f.gpa == 3.40 and f.class_year == 3
    assert f.enrolment == "full-time" and f.honours == ["SYNTHETIC Dean's List, 2025"]


def test_plain_heading_is_strict_s53_review():
    from perch.user.cv import _plain_heading

    for ok in ("Education", "Research and posters", "Work experience", "HONOURS"):
        assert _plain_heading(ok), ok
    for bad in ("Research Assistant, Smith Lab", "Teaching Assistant", "Volunteer tutor"):
        assert not _plain_heading(bad), bad

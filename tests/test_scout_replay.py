"""Replay harness for Scout's grounding contract (S45 fix): realistic model drafts, graded offline.

The S45 open-question bench on the real model removed sentences from 29 of 33 in-scope answers.
These drafts are written in the shapes the real answers took (bench/results/scout_open_s45/
grades.csv): how-to-Perch steps, general application advice, a list of records with their
deadlines, CV feedback, an empty brief. Each one goes through perch/scout/answer.py with no
model and no grounder, and the test names the rule each removed sentence broke. The second half
keeps the safety cases failing: an uncited amount, a wrong date, an award named in General
advice, a sample listed with a public record, a link with no record.

No spend, no network. User text and sample records are SYNTHETIC.
"""

from __future__ import annotations

from datetime import date

import pytest

from perch.schemas import Opportunity, Scholarship, utcnow
from perch.scout import answer as ans
from perch.scout import texts
from perch.scout.read_tools import ReadTools, ScoutData, user_doc
from perch.scout.turn import TurnDeps, run_turn

from .test_api import make
from .test_scout_v2 import call, smart

OPP = "grants_gov:PAR-25-268"  # the fixture record: NIH, closes 2026-11-17, no ceiling
AS_OF = date(2026, 10, 28)
SMP = "sample:replay-1"
NAMES = {"beinecke scholarship", "applied mathematics", "par-25-268"}


@pytest.fixture(scope="module")
def seen(tmp_path_factory):
    _, svc = make(tmp_path_factory.mktemp("replay"))
    with svc.repo() as r:
        opp = r.get(Opportunity, OPP)
    smp = Scholarship(id=SMP, source="synthetic", source_url="perch://sample",
                      fetched_at=utcnow(), name="Fictional Replay Sample Award",
                      sponsor="Fictional Replay Fund", canary="SYNTHETIC-canary-replay-1",
                      amount_min=3000, amount_max=3000, deadline=date(2027, 2, 15))
    cv = user_doc("user:cv:education", "CV, education",
                  "SYNTHETIC. PhD in Public Health, 2024. Two posters on asthma outreach.")
    entry = user_doc("user:entry:1", "Achievement 1",
                     "SYNTHETIC. Led a volunteer team that monitored stream sites.")
    return {OPP: opp, SMP: smp, cv.id: cv, entry.id: entry}


def reasons(g: ans.Graded) -> list[tuple[str, int, str]]:
    return [(r["part"], r["sentence_index"], r["reason"]) for r in g.removed()]


# --- drafts the S45 rules removed, which now pass ---

HOW_TO_STEPS = """Here is how to find grants for your lab:
1. Build a brief from your public papers, then open the Grants list.
2. Keep the leads worth a closer look and dismiss the rest.
3. Ask me how your CV fits a record, and I will say what it asks for and what your CV shows.
Which record or topic do you want to start with?"""

HOW_TO_GENERAL = """General advice:
1. Open a lead and press Keep.
2. Press Hand-off to a Temple office, pick the office, and edit the draft before you send it.
Perch sends nothing for you."""

STATEMENT_ADVICE = """General advice:
- Open with a short story that shows why the field matters to you.
- In the middle, link your experience to what the award says it supports.
- End with a closing paragraph that says what you will do next.
- Ask your referees well before the deadline, and check that you are eligible first.
- Be open to feedback from a mentor, and read the draft aloud before you submit."""

CITE_AFTER_STOP = (f"PAR-25-268 is from the U.S. National Institutes of Health. [{OPP}] "
                   f"It closes 17 Nov 2026. [{OPP}] The record states no award ceiling. [{OPP}]")

CITE_FORMS = (f"Your PhD is in Public Health and the record names no field [{OPP},"
              f"user:cv:education].\nIt closes 17 Nov 2026 ({OPP}).\n"
              f"It closes 17 Nov 2026 [{OPP}; user:cv:education].")

CV_FEEDBACK = f"""**What the record asks for**
- It closes 17 Nov 2026 [{OPP}].
- The record states no award ceiling [{OPP}].
**What your CV shows**
- Your PhD is in Public Health, 2024 [user:cv:education].
- You led a volunteer team [user:entry:1].
Tell me which part to look at next. I can also list what your CV does not show yet."""


@pytest.mark.parametrize("draft", [HOW_TO_STEPS, HOW_TO_GENERAL, STATEMENT_ADVICE,
                                   CITE_AFTER_STOP, CITE_FORMS, CV_FEEDBACK],
                         ids=["how_to_steps", "how_to_general", "statement_advice",
                              "cite_after_stop", "cite_forms", "cv_feedback"])
def test_realistic_drafts_now_pass(draft, seen):
    g = ans.grade(draft, seen, NAMES, AS_OF)
    assert g.ok, reasons(g)


def test_help_sentences_are_marked_as_help_not_grounded(seen):
    g = ans.grade(HOW_TO_STEPS, seen, NAMES, AS_OF)
    assert [s.kind for s in g.sentences] == ["heading", "help", "help", "help", "question"]


def test_a_citation_after_the_full_stop_cites_the_sentence_before_it(seen):
    g = ans.grade(CITE_AFTER_STOP, seen, NAMES, AS_OF)
    assert [s.cites for s in g.sentences] == [[OPP]] * 3
    assert g.sentences[0].text.startswith("PAR-25-268 is from the U.S. National")


def test_list_numbering_and_ordinary_words_pass_general_advice(seen):
    assert ans.check_general(STATEMENT_ADVICE.split("\n", 1)[1], NAMES, seen) == []
    assert ans.check_general("1. Draft early.\n2. Revise twice.", NAMES, seen) == []


def test_a_field_of_study_that_is_also_a_title_passes_only_in_plain_prose(seen):
    assert ans.check_general("Reviewers in applied mathematics like clear aims.", NAMES,
                             seen) == []
    errs = ans.check_general("Apply to Applied Mathematics early.", NAMES, seen)
    assert any("name an award" in e for e in errs)


def test_an_empty_brief_and_nothing_saved_can_be_cited(seen):
    tools = ReadTools(ScoutData(repo=lambda: None, audience="student"))  # type: ignore[arg-type]
    assert tools.read_brief()["id"] == "user:brief"
    assert tools.read_saved()["id"] == "user:saved"
    assert tools.read_entries()["id"] == "user:entries"
    assert tools.read_cv_part()["id"] == "user:cv"
    g = ans.grade("Your brief has no leads yet [user:brief]. You have nothing saved yet "
                  "[user:saved].\nI found no records for that.", tools.seen, set(), AS_OF)
    assert g.ok, reasons(g)
    # an uncited "nothing" sentence that is not a fixed template is removed (S45 fix round 3)
    g = ans.grade("You have no leads in your brief.", tools.seen, set(), AS_OF)
    assert [r for _, _, r in reasons(g)] == ["absent_not_template"]


# --- what the old rules removed, by rule, as evidence for the fix ---

def test_each_loosened_rule_on_its_own(seen):
    # sentences that state no record fact
    for s in ("Tell me which one to read in full.", "I can compare it with your CV next.",
              "You can keep a lead from its card.", "Would you like the full record?",
              "Here is what I can do:", "### Deadlines"):
        assert ans.grade(s, seen, NAMES, AS_OF).ok, s
    # an uncited rank claim is not a section name (S45 fix round 3)
    assert not ans.grade("**Your top lead**", seen, NAMES, AS_OF).ok
    # ordinary words in General advice
    for s in ("Ask well before the deadline.", "Check that you are eligible.",
              "Write a closing paragraph.", "Be open to feedback.", "Put your aims first.",
              "Plan a month ahead.", "Students often start too late."):
        assert ans.check_general(s, NAMES, seen) == [], s


# --- safety cases that must still fail ---

SAFETY = [
    ("The award is worth $3,000.", "grounded", "no_citation"),
    ("You can get $3,000 from it.", "grounded", "no_citation"),
    ("Check whether it pays $3,000.", "grounded", "general_number"),
    (f"It is worth $5,000 [{SMP}].", "grounded", "layer1_number"),
    (f"It closes 18 Nov 2026 [{OPP}].", "grounded", "layer1_date"),
    (f"It closes 31 Feb 2027 [{OPP}].", "grounded", "layer1_bad_date"),
    (f"Apply at https://example.invalid/apply [{OPP}].", "grounded", "layer1_link"),
    (f"Click the button on the page [{OPP}].", "grounded", "layer1_action_word"),
    ("It closes soon [grants_gov:NOT-READ-1].", "grounded", "cites_unreturned_id"),
    ("It is a great fit for you.", "grounded", "no_citation"),
    ("Try the Beinecke Scholarship.", "grounded", "general_named_award"),
    ("You can apply only if you are a citizen.", "grounded", "no_citation"),
    ("Ask whether you must be a citizen.", "grounded", "general_eligibility_word"),
    ("Check https://example.invalid for the form.", "grounded", "general_link"),
    ("Would you like the one that pays $3,000?", "grounded", "uncited_number_or_date"),
    ("Did you know it pays $3,000?", "grounded", "question_not_offer"),
    ("Do you want the link https://example.invalid?", "grounded", "uncited_link"),
    ("No record gives a link other than https://example.invalid.", "grounded",
     "absent_not_template"),
    ("General advice:\nApply to the Beinecke Scholarship early.", "general",
     "general_named_award"),
    ("General advice:\nTry a Fulbright Scholarship.", "general", "general_named_award"),
    ("General advice:\nBeinecke scholarship essays are short.", "general",
     "general_named_award"),
    ("General advice:\nThe beinecke scholarship is competitive.", "general",
     "general_named_award"),
    ("General advice:\nInternational students are not eligible.", "general",
     "general_eligibility_word"),
    ("I can see this record fits your work well.", "grounded", "no_citation"),
    ("You can expect a strong fit here.", "grounded", "no_citation"),
    ("If you apply, you will win.", "grounded", "no_citation"),
    ("General advice:\nLook at R01 programs.", "general", "general_award_code"),
    ("General advice:\nMany applicants for PAR-25-268 write too much.", "general",
     "general_award_code"),
    ("General advice:\nAsk referees 6 weeks ahead.", "general", "general_number"),
    ("General advice:\nMost are due in October.", "general", "general_month"),
    ("General advice:\nYou must be a citizen to apply.", "general", "general_eligibility_word"),
    ("General advice:\nApplicants must hold a PhD.", "general", "general_eligibility_word"),
    ("General advice:\nSee the record [grants_gov:PAR-25-268].", "general", "general_cite"),
    ("General advice:\nRead https://example.invalid first.", "general", "general_link"),
    ("General advice:\nSubmit by 2026-11-17.", "general", "general_date"),
]


@pytest.mark.parametrize("draft,part,reason", SAFETY, ids=[r for _, _, r in SAFETY])
def test_safety_cases_still_fail_with_their_reason(draft, part, reason, seen):
    g = ans.grade(draft, seen, NAMES, AS_OF)
    assert not g.ok
    assert (part, reason) in {(p, r) for p, _, r in reasons(g)}, reasons(g)


def test_a_sample_listed_with_a_public_record_still_fails(seen):
    mixed = f"Your kept options:\n- A public one [{OPP}]\n- A sample one [{SMP}]"
    g = ans.grade(mixed, seen, NAMES, AS_OF)
    assert ("grounded", 2, "sample_mix") in reasons(g)


def test_a_title_the_turn_read_may_not_appear_in_general_advice(seen):
    title = seen[OPP].title
    g = ans.grade(f"It closes 17 Nov 2026 [{OPP}].\nGeneral advice:\nRead {title} closely.",
                  seen, set(), AS_OF)
    assert ("general", 0, "general_named_award") in reasons(g)


def test_one_bad_general_sentence_removes_only_itself(seen):
    g = ans.grade("General advice:\n- Start early.\n- Most are due in October.\n- Ask a mentor.",
                  seen, NAMES, AS_OF)
    assert reasons(g) == [("general", 1, "general_month")]
    _, general = ans.render(g, drop_failed=True)
    assert general == "- Start early.\n- Ask a mentor."


# --- the message carries the reasons, without the sentence text ---

def test_the_answer_message_lists_removed_sentences_by_rule_only(tmp_path):
    _, svc = make(tmp_path)
    data = ScoutData(repo=svc.repo, audience="researcher", as_of=AS_OF)
    bad = (f"It closes 17 Nov 2026 [{OPP}]. The award is worth $2,000,000 [{OPP}].\n"
           "General advice:\n- Start early.\n- Most are due in October.")
    drafts: list[tuple[int, str, ans.Graded]] = []
    deps = TurnDeps(data=data, provider_for=lambda role: p, names=set,
                    on_draft=lambda a, t, g: drafts.append((a, t, g)))
    p = smart([call("read_record", id=OPP), bad, bad])
    m = run_turn(deps, [], question="How much is it worth?")
    assert m["flagged"] and m["withheld"] == 2 and m["attempt"] == 1
    assert m["removed"] == [
        {"part": "grounded", "sentence_index": 1, "reason": "layer1_number"},
        {"part": "general", "sentence_index": 1, "reason": "general_month"}]
    assert "2,000,000" not in str(m["removed"]) and "October" not in str(m["removed"])
    assert m["general"] == "- Start early."
    assert [a for a, _, _ in drafts] == [1, 2] and drafts[0][1] == bad
    assert drafts[0][2].removed(detail=True)[0]["detail"] == "2000000"


def test_a_clean_answer_has_no_removed_list(tmp_path):
    _, svc = make(tmp_path)
    data = ScoutData(repo=svc.repo, audience="researcher", as_of=AS_OF)
    p = smart([call("read_record", id=OPP), CITE_AFTER_STOP])
    m = run_turn(TurnDeps(data=data, provider_for=lambda role: p, names=set), [],
                 question="When does it close?")
    assert not m["flagged"] and m["removed"] == [] and m["attempt"] == 1


def test_the_prompt_states_the_exact_citation_format():
    s = texts.system_prompt("student")
    assert "[grants_gov:23-500]" in s and "square brackets" in s and "[user:brief]" in s
    assert "never put an id at the start" in s and texts.GENERAL_LABEL in s
    assert "HOW PERCH WORKS" in s and "Perch sends nothing" in s


@pytest.mark.parametrize("line", [
    "Would you like me to compare them, since you rank first on both?",
    "Open it, you are its ideal applicant.",
    "Keep it, because your work lines up closely with its aims.",
    "**Here is how to prepare, since you already meet every criterion:**",
])
def test_a_claim_riding_on_an_allowed_shape_fails_the_grade(line, seen):
    """S45 final re-check: the shape rule ends at the verb phrase; a reason or verdict after it
    is a claim and needs a citation."""
    g = ans.grade("Your brief has no leads yet [user:brief].\n" + line, seen, NAMES, AS_OF)
    assert not g.ok, line

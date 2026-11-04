"""S45 fix round 3 (offline, no model, no network): the sentences that skip the citation rule
are an allow-list of shapes, not a list of banned words. SYNTHETIC records and text only."""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime

import pytest

from perch.schemas import Scholarship, ScholarshipEligibility
from perch.scout import answer as ans
from perch.scout.read_tools import user_doc

AS_OF = date(2026, 11, 4)
T = datetime(2026, 10, 1, tzinfo=UTC)
X = Scholarship(id="temple_sdfa:x", name="SYNTHETIC Quillfen Award", source="temple_sdfa",
                source_url="https://example.invalid/x", fetched_at=T,
                eligibility=ScholarshipEligibility(notes="Open to juniors in any major."))
SEEN = {X.id: X, **{i: user_doc(i, i, "nothing") for i in
                    ("user:saved", "user:brief", "user:cv", "user:entries")}}
BLOCK = "\n- It is open to juniors [temple_sdfa:x]."


def removed(text: str) -> list[str]:
    return [r["reason"] for r in ans.grade(text, SEEN, set(), AS_OF).removed()]


# --- the reviewer's round-2 inputs (r2.py): every one fails by shape ---

R2_FAIL = {
    "**Open to all majors**": "heading_not_structural",
    "## Perfect match": "heading_not_structural",
    "## You fit this": "heading_not_structural",
    "**Great for juniors:**": "heading_not_structural",
    "**Ideal for first-generation students**": "heading_not_structural",
    "### Juniors welcome": "heading_not_structural",
    "**Accepts all students:**": "heading_not_structural",
    "**Your top option**": "heading_not_structural",
    "You'd be a natural for this one?": "question_not_offer",
    "Sounds like you're a shoo-in?": "question_not_offer",
    "Isn't this ideal for you?": "question_not_offer",
    "Did you know juniors are accepted?": "question_not_offer",
    "Nothing on your list rules you out [user:saved].": "placeholder_only",
    "Your saved list is empty, so nothing stops you [user:saved].": "placeholder_only",
    "Your saved list is empty, so you're not excluded from any [user:saved].": "placeholder_only",
    "Nothing in your CV disqualifies you [user:cv].": "placeholder_only",
    "None of your leads exclude sophomores [user:brief].": "placeholder_only",
    "Nothing in your entries would hurt your chances [user:entries].": "placeholder_only",
    "No record says you cannot apply.": "absent_not_template",
    "No record bars non-citizens.": "absent_not_template",
    "You are not excluded by any record found.": "absent_not_template",
}


@pytest.mark.parametrize("text,reason", R2_FAIL.items(), ids=list(R2_FAIL))
def test_round_two_inputs_fail_by_shape(text, reason):
    assert reason in removed(text)


def test_a_properly_cited_record_sentence_is_unchanged():
    assert removed("It is open to juniors [temple_sdfa:x].") == []


# --- generated: fit adjectives by subjects, as headings and as questions ---

ADJ = ("great", "ideal", "perfect", "natural", "strong", "good", "best", "eligible", "welcome",
       "suited")
SUBJ = ("for juniors", "for you", "match", "fit", "choice", "candidate")
GENERATED = [f"{a.capitalize()} {s}" for a, s in itertools.product(ADJ, SUBJ)]


@pytest.mark.parametrize("form", ["**{}**", "## {}", "**{}:**", "{}:", "### {}"])
def test_generated_fit_headings_are_removed(form):
    assert len(GENERATED) >= 40
    for g in GENERATED:
        for text in (form.format(g), form.format(g) + BLOCK):
            assert "heading_not_structural" in removed(text) or (
                "uncited_fit_word" in removed(text)), text


@pytest.mark.parametrize("form", ["{}?", "Is this a {} ?", "Isn't it {}?", "Are you {}?",
                                  "Which one is {}?", "Would you like the {} one?",
                                  "Do you want a {}?"])
def test_generated_fit_questions_are_removed(form):
    for g in GENERATED:
        text = form.format(g.lower())
        assert "question_not_offer" in removed(text), text


# --- what stays: the structural section names and real offers ---

STRUCTURAL = [
    "**What the record asks for**", "**What your CV shows**", "**What it does not show yet**",
    "**What your material does not show yet**", "**What your entries don't show yet**",
    "**What is not shown yet**", "**How your work connects**", "**How they connect**",
    "## General advice", "**Next steps**", "### Your options", "Deadlines:", "**Compare**",
    "**Where your CV is strong**", "**Points to highlight**", "**Main differences**",
    "**Key facts**", "**Who submits**", "Kept leads:", "Other leads:", "**Gaps**",
    "**What a reviewer would not find**", "**What to add to your entries**",
    "**Federal opportunities**", "**Temple-listed fellowships**", "Public options:",
    "**Eligibility in the record**", "Here is what I can do:",
    "Here is how to find grants for your lab:",
]


@pytest.mark.parametrize("head", STRUCTURAL)
def test_structural_headings_are_kept(head):
    assert removed(head) == [], head
    if "General advice" not in head:  # lines under that label are General advice, not cited
        assert removed(head + BLOCK) == [], head


def test_a_record_label_made_of_its_cited_words_is_kept_but_not_a_claim():
    assert removed("**SYNTHETIC Quillfen Award**" + BLOCK) == []
    assert "heading_not_structural" in removed("**SYNTHETIC Quillfen Award**")  # nothing cited
    # every word is in the record's notes, but the label still may not say who may apply
    assert removed("**Open to juniors**" + BLOCK) != []
    # a label names the record, not the reader
    assert "heading_not_structural" in removed("**Juniors, you are open**" + BLOCK)


@pytest.mark.parametrize("q", [
    "Would you like me to read it in full?", "Do you want the full record?",
    "Shall I compare it with your CV?", "Should I search for more?",
    "Want me to check your entries?", "Which one should I read in full?",
    "Tell me if you want more?", "Tell me which one to open?"])
def test_offers_are_kept(q):
    assert removed(q) == [], q


def test_an_offer_still_may_not_hold_a_number_award_or_eligibility_word():
    assert "uncited_number_or_date" in removed("Would you like the one that pays $3,000?")
    assert "question_not_offer" in removed("Which one are you eligible for?")
    assert removed("Do you want only citizens' awards?") != []


# --- empty states and "nothing found": fixed templates only ---

@pytest.mark.parametrize("text", [
    "Your saved list is empty [user:saved].", "You have nothing saved yet [user:saved].",
    "Your brief has no leads yet [user:brief].", "You have no entries yet [user:entries].",
    "Your CV holds nothing on this [user:cv].", "**Your saved list is empty.** [user:saved]",
    "- You have no typed entries yet [user:entries]."])
def test_empty_state_templates_pass(text):
    assert removed(text) == [], text


@pytest.mark.parametrize("text", [
    "I found no record on that.", "No record I read states that.", "I found no records.",
    "I could not find any records on that.", "No record was found for that."])
def test_nothing_found_templates_pass(text):
    assert removed(text) == [], text


@pytest.mark.parametrize("text", [
    "I found no record that excludes you.", "No record I read says juniors are barred.",
    "I found no record on that, so you can apply.", "Nothing rules you out."])
def test_nothing_found_with_a_tail_fails(text):
    assert removed(text) in (["absent_not_template"], ["no_citation"]), text

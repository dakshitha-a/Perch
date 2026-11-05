"""S51 H1: a cover "you" sentence that cites papers cites exactly one, and layer 2 scores it
with the paper as a grammatical subject. SYNTHETIC records."""

import json

from tests.test_skills import WORKS, _cover_inputs, audited, cover_reply

PAPER = WORKS["https://openalex.org/W1"]


def _with_you(you: str, ids: list[str]) -> str:
    pts = json.loads(cover_reply())["points"]
    pts[0]["you"], pts[0]["you_ids"] = you, ids
    return cover_reply(points=pts, cited=["PAR-1", "user:cv", "proposal", "nih:1", *ids])


def test_your_paper_reports_becomes_the_paper_reports():
    from perch.skills.cover import as_record_claim

    assert as_record_claim("Your paper reports a study of kidney donors.", [PAPER]) == \
        "The paper reports a study of kidney donors."
    assert as_record_claim("Your papers report a study of kidney donors.", [PAPER]) == \
        "The paper reports a study of kidney donors."


def test_you_have_becomes_the_paper_has():
    from perch.skills.cover import as_record_claim

    assert as_record_claim("You have work on kidney donors.", [PAPER]) == \
        "The paper has work on kidney donors."


def test_a_you_point_citing_two_papers_is_sent_back():
    from perch.skills.cover import cover_points

    opp, cv, docs, papers, awards = _cover_inputs()
    two = _with_you("Your paper reports a study of living kidney donor communication.",
                    ["W1", "W2"])
    one = _with_you("Your paper reports a study of living kidney donor communication.", ["W1"])
    p, _ = audited([two, one])
    v, _ = cover_points(opp, cv, docs, papers, awards, p)
    assert v.attempts == 2 and not v.flagged
    assert "cites more than one paper; name one paper and one fact" in \
        p.inner.calls[1]["messages"][0].content


def test_a_you_point_citing_one_paper_passes():
    from perch.skills.cover import cover_points

    opp, cv, docs, papers, awards = _cover_inputs()
    p, _ = audited([_with_you("Your paper reports a study of living kidney donor "
                              "communication.", ["W1"])])
    v, _ = cover_points(opp, cv, docs, papers, awards, p)
    assert v.attempts == 1 and not v.flagged, v.errors


def test_the_cover_wording_does_not_assume_a_cv():
    """S51 H12: the live points came from papers, with no CV added."""
    from perch.scout.web import COVER_NOTE
    from perch.skills.cover import INSTRUCTIONS, missing_form

    assert "one thing from your CV, entries or papers" in COVER_NOTE
    assert "nothing in your records shows one" in INSTRUCTIONS
    assert "nothing you added" not in INSTRUCTIONS
    errs = missing_form("missing 1", "The record asks for a plan.")
    assert errs and "nothing in your records shows it" in errs[0]
    assert not missing_form("missing 1", "The record asks for a plan; nothing in your records "
                            "shows one.")


def test_the_prompt_asks_for_one_paper_and_one_fact():
    from perch.skills.cover import INSTRUCTIONS

    assert "Each ‘you’ point names one paper and one fact from it" in INSTRUCTIONS

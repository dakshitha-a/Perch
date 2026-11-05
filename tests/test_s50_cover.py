"""S50 explanation quality (3c): a cover point may not claim a role the records it cites do
not state, and layer 2 scores a "you" sentence for its content, not its subject. Unsupported
statements stay marked, not withheld, as for fit explanations. SYNTHETIC records."""

import json

from tests.test_skills import _cover_inputs, audited, cover_reply


def _with_you(you: str, ids: list[str]) -> str:
    pts = json.loads(cover_reply())["points"]
    pts[0]["you"], pts[0]["you_ids"] = you, ids
    return cover_reply(points=pts, cited=["PAR-1", "user:cv", "proposal", "nih:1", *ids])


def test_a_role_the_cited_paper_does_not_state_is_sent_back():
    from perch.skills.cover import cover_points

    opp, cv, docs, papers, awards = _cover_inputs()
    bad = _with_you("You contributed to a study of living kidney donor communication.", ["W1"])
    good = _with_you("Your paper reports a study of living kidney donor communication.", ["W1"])
    p, _ = audited([bad, good])
    v, _ = cover_points(opp, cv, docs, papers, awards, p)
    assert v.attempts == 2 and not v.flagged
    assert "'contributed'" in p.inner.calls[1]["messages"][0].content


def test_a_role_the_cv_states_passes():
    from perch.skills.cover import cover_points

    opp, cv, docs, papers, awards = _cover_inputs()
    text = cv.abstract or ""
    verb = "led" if "led" in text.lower().split() else None
    if verb is None:  # the SYNTHETIC CV states no role verb: give it one
        cv = cv.model_copy(update={"abstract": text + "\n- Led a SYNTHETIC sensor study team."})
    p, _ = audited([_with_you("You led a sensor study team.", ["user:cv"])])
    v, _ = cover_points(opp, cv, docs, papers, awards, p)
    assert not v.flagged and v.attempts == 1, v.errors


class Recording:
    """A grounder that supports everything and keeps the claims it was asked about."""

    name = "recording"

    def __init__(self) -> None:
        self.claims: list[str] = []

    def support(self, document: str, claims: list[str]) -> list[float]:
        self.claims += claims
        return [1.0] * len(claims)


def test_layer2_scores_the_content_of_a_you_sentence_not_its_subject():
    """MiniCheck flagged all five live points: "You identified X" against a paper that says
    "We identified X". The claim it scores names the record as its subject."""
    from perch.skills.cover import cover_points

    opp, cv, docs, papers, awards = _cover_inputs()
    g = Recording()
    p, _ = audited([_with_you("You studied living kidney donor communication in your "
                              "survey.", ["W1"])])
    v, _ = cover_points(opp, cv, docs, papers, awards, p, grounder=g)
    assert "The paper studied living kidney donor communication in its survey." in g.claims
    assert "You are an Assistant Professor since 2023." in g.claims  # a CV line, as written
    assert v.value.points[0].you.startswith("You studied")  # the shown text is unchanged

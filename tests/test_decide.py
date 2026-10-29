import math

import pytest

from perch.llm.decide import Choice, LogprobDecider, Score, YesNo, labels_for
from perch.llm.fake import FakeProvider


def lp(p):
    return math.log(p)


def test_yes_no_merges_case_and_renormalises():
    p = FakeProvider(logprob_tokens={"Yes": lp(0.5), "yes": lp(0.1), " No": lp(0.2),
                                     "Maybe": lp(0.2)})
    d = LogprobDecider(p).decide(YesNo("Does record R support sentence S?"), "R: ... S: ...")
    assert d.value is True and d.method == "logprobs"
    assert d.confidence == pytest.approx(0.6 / 0.8)
    assert p.calls[0]["logprobs"] == 20


def test_choice_maps_letters_to_options():
    p = FakeProvider(logprob_tokens={"B": lp(0.7), "A": lp(0.3)})
    d = LogprobDecider(p).decide(Choice("Which route?", ["grant", "industry"]), "ctx")
    assert d.value == "industry" and d.confidence == pytest.approx(0.7)


def test_score_reports_expected_value():
    p = FakeProvider(logprob_tokens={"4": lp(0.5), "5": lp(0.25), "3": lp(0.25)})
    d = LogprobDecider(p).decide(Score("Fit of opportunity to thread?", 1, 5), "ctx")
    assert d.value == 4 and d.expected == pytest.approx(4.0)
    assert set(d.probs) == {"1", "2", "3", "4", "5"}


def test_without_logprobs_uses_schema_and_gives_no_confidence():
    p = FakeProvider(['{"answer": "no"}'])
    p.capabilities = frozenset({"schema"})
    d = LogprobDecider(p).decide(YesNo("q"), "ctx")
    assert d.value is False and d.confidence is None and d.method == "constrained"
    assert p.calls[0]["schema"]["properties"]["answer"]["enum"] == ["yes", "no"]


def test_no_label_in_top_tokens_falls_back_to_constrained():
    p = FakeProvider(["The", '{"answer": "yes"}'], logprob_tokens={"The": lp(0.9)})
    d = LogprobDecider(p).decide(YesNo("q"), "ctx")
    assert d.method == "constrained" and d.value is True and d.confidence is None


def test_bad_questions():
    with pytest.raises(ValueError):
        labels_for(Score("q", 0, 10))
    p = FakeProvider(['{"answer": "maybe"}'])
    p.capabilities = frozenset()
    with pytest.raises(ValueError):
        LogprobDecider(p).decide(YesNo("q"), "ctx")

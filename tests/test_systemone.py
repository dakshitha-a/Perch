import json
from pathlib import Path

import httpx

from perch.grounding import DecisionGrounder
from perch.llm.decide import Choice, Score, YesNo
from perch.llm.systemone import SystemOneClient, SystemOneDecider
from perch.rerank import DecisionReranker

FIX = Path(__file__).parent / "fixtures/systemone"


def client(name, seen=None):
    body = json.loads((FIX / name).read_text())

    def handler(req):
        if seen is not None:
            seen.append(json.loads(req.content))
        q = next(iter(json.loads(req.content)["questions"]))
        answers = dict(body["answers"])
        first = answers.get(q) or next(iter(answers.values()))
        return httpx.Response(200, json={**body, "answers": {q: first}})

    return SystemOneClient(transport=httpx.MockTransport(handler))


def test_yes_no_reads_the_noul_probability_and_sends_the_question():
    seen = []
    d = SystemOneDecider(client("clef_flash_noul_score.json", seen), "clef-flash")
    out = d.decide(YesNo("Supported?"), "SYNTHETIC context")
    assert out.value is True and out.probs["yes"] > 0.86
    assert seen[0]["questions"]["q"] == {"type": "noul", "instructions": "Supported?"}
    assert seen[0]["state"] == {"context": "SYNTHETIC context"}


def test_score_maps_zero_based_levels_to_the_scale():
    body = json.loads((FIX / "clef_flash_noul_score.json").read_text())
    body["answers"] = {"q": body["answers"]["fit"]}
    d = SystemOneDecider(SystemOneClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=body))), "clef-flash")
    out = d.decide(Score("Fit?", 1, 5), "SYNTHETIC")
    assert out.value == 4 and set(out.probs) == {"1", "2", "3", "4", "5"}
    assert abs(out.expected - 3.767) < 0.01


def test_choice_returns_the_option():
    d = SystemOneDecider(client("clef_flash_choice.json"), "clef-flash")
    out = d.decide(Choice("Want?", ["refund", "cancel", "other"]), "SYNTHETIC")
    assert out.value == "refund" and out.confidence > 0.98


def test_grounder_and_reranker_use_the_yes_probability():
    d = SystemOneDecider(client("clef_flash_noul_score.json"), "clef-flash")
    assert DecisionGrounder(d, "g").support("SYNTHETIC doc", ["a", "b"])[0] > 0.86
    assert DecisionReranker(d, "r").score("SYNTHETIC query", ["doc"])[0] > 0.86

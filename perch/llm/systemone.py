"""Decision models through llama.cpp's `/v1/systemone` API (Clef-flash, Clef; Jev-compatible).

Request and response verified live against Clef-Flash-GGUF on llama.cpp b11941 on
2026-10-29 (fixture tests/fixtures/systemone/); the format is documented in
llama.cpp PR 29818. Request: {"state": {...}, "questions": {name: {"type": "noul" |
"choice" | "score", "instructions": str, "criteria": ...}}}. Response: "answers" by
name; noul gives one probability of true; score gives "probabilities" per level
(0-based), "score" (expected level) and "confidence"; choice gives probabilities per
option. Decision models answer `decide` questions only; they are never used for
skills 1 to 3 or for eligibility (SPEC section 7).
"""

from __future__ import annotations

from typing import Any

import httpx

from perch.llm.decide import Choice, Decider, Decision, Question, Score, YesNo, to_value

CLEF_FLASH_URL = "http://127.0.0.1:8097"
CLEF_URL = "http://127.0.0.1:8098"


class SystemOneClient:
    def __init__(self, base_url: str = CLEF_FLASH_URL, timeout: float = 60.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)
        self.base_url = base_url

    def ask(self, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        r = self.http.post("/v1/systemone", json={"state": state, "questions": questions})
        r.raise_for_status()
        return r.json()


def question_json(q: Question) -> dict[str, Any]:
    if isinstance(q, YesNo):
        return {"type": "noul", "instructions": q.question}
    if isinstance(q, Score):
        return {"type": "score", "instructions": q.question,
                "criteria": [str(i) for i in range(q.low, q.high + 1)]}
    return {"type": "choice", "instructions": q.question,
            "criteria": {opt: None for opt in q.options}}


class SystemOneDecider(Decider):
    def __init__(self, client: SystemOneClient, name: str) -> None:
        self.client, self.name = client, name

    def decide(self, q: Question, context: str) -> Decision:
        data = self.client.ask({"context": context}, {"q": question_json(q)})
        a = data["answers"]["q"]
        model = data.get("model", self.name)
        if isinstance(q, YesNo):
            p = float(a["noul"])
            return Decision(p > 0.5, max(p, 1 - p), {"yes": p, "no": 1 - p}, "systemone", model)
        probs = {k: float(v) for k, v in a["probabilities"].items()}
        if isinstance(q, Score):
            probs = {str(q.low + int(k)): v for k, v in probs.items()}
            best = max(probs, key=lambda k: (probs[k], -int(k)))
            return Decision(int(best), probs[best], probs, "systemone", model,
                            q.low + float(a["score"]))
        assert isinstance(q, Choice)
        best = max(q.options, key=lambda o: probs.get(o, 0.0))
        return Decision(to_value(q, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[q.options.index(best)]),
                        probs.get(best), probs, "systemone", model)

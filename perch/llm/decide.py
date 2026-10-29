"""`decide`: typed questions in, typed value plus confidence out (SPEC section 8).

Question kinds: Choice (one of labelled options), YesNo, Score (an integer scale).
Adapters: LogprobDecider works on any chat model whose provider returns token
logprobs (it asks for a single label token and reads the first token's
alternatives); providers without logprobs get a schema-constrained answer and
confidence None, never an invented one. Decision-model adapters (Clef-flash, Clef,
Jev through one Jev-compatible API; Strands Decider 2B) land with the S8 bench rows.
Decision models are never used for skills 1 to 3 or for eligibility.
"""

from __future__ import annotations

import json
import math
import string
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from perch.llm.base import Message, Provider

LABELS = string.ascii_uppercase


@dataclass
class Choice:
    question: str
    options: list[str]


@dataclass
class YesNo:
    question: str


@dataclass
class Score:
    question: str
    low: int = 1
    high: int = 5


Question = Choice | YesNo | Score


@dataclass
class Decision:
    value: str | bool | int
    confidence: float | None  # probability of `value`; None when the method gives none
    probs: dict[str, float] = field(default_factory=dict)  # per label, renormalised
    method: str = ""
    model: str = ""
    expected: float | None = None  # Score only: probability-weighted mean


def labels_for(q: Question) -> list[str]:
    if isinstance(q, YesNo):
        return ["yes", "no"]
    if isinstance(q, Score):
        if q.high - q.low > 9:
            raise ValueError("score scales must fit in single digits")
        return [str(i) for i in range(q.low, q.high + 1)]
    if len(q.options) > len(LABELS):
        raise ValueError("too many options")
    return list(LABELS[: len(q.options)])


def prompt_for(q: Question, context: str) -> str:
    lines = [context.strip(), "", q.question]
    if isinstance(q, Choice):
        lines += [f"{lbl}. {opt}" for lbl, opt in zip(LABELS, q.options, strict=False)]
        lines.append("Answer with the single letter of one option and nothing else.")
    elif isinstance(q, YesNo):
        lines.append("Answer with the single word yes or no and nothing else.")
    else:
        lines.append(f"Answer with a single whole number from {q.low} to {q.high} and nothing "
                     "else.")
    return "\n".join(lines)


def to_value(q: Question, label: str) -> str | bool | int:
    if isinstance(q, YesNo):
        return label == "yes"
    if isinstance(q, Score):
        return int(label)
    return q.options[LABELS.index(label)]


class Decider(ABC):
    @abstractmethod
    def decide(self, q: Question, context: str) -> Decision: ...


class LogprobDecider(Decider):
    """The LLM-logprobs fallback: works on any provider with the "logprobs" capability;
    otherwise falls back to a schema-constrained answer without confidence."""

    SYSTEM = "You answer one question about the given text. Reply with exactly one token."

    def __init__(self, provider: Provider, top_k: int = 20) -> None:
        self.provider = provider
        self.top_k = top_k

    def decide(self, q: Question, context: str) -> Decision:
        labels = labels_for(q)
        msg = [Message("user", prompt_for(q, context))]
        if "logprobs" not in self.provider.capabilities:
            return self._constrained(q, labels, msg)
        r = self.provider.chat(msg, system=self.SYSTEM, max_tokens=1, logprobs=self.top_k)
        mass = dict.fromkeys(labels, 0.0)
        for alt in (r.top_logprobs or [[]])[0]:
            tok = alt.token.strip().strip(".").lower()
            for lbl in labels:
                if tok == lbl.lower():
                    mass[lbl] += math.exp(alt.logprob)
        total = sum(mass.values())
        if total == 0:  # no label among the top tokens: the model did not answer the question
            return self._constrained(q, labels, msg)
        probs = {k: v / total for k, v in mass.items()}
        best = max(labels, key=lambda k: (probs[k], -labels.index(k)))
        expected = (sum(int(k) * p for k, p in probs.items()) if isinstance(q, Score) else None)
        return Decision(to_value(q, best), probs[best], probs, "logprobs", r.model, expected)

    def _constrained(self, q: Question, labels: list[str], msg: list[Message]) -> Decision:
        schema = {"type": "object", "properties": {"answer": {"type": "string", "enum": labels}},
                  "required": ["answer"], "additionalProperties": False}
        r = self.provider.chat(msg, system=self.SYSTEM.replace("exactly one token",
                                                               "JSON only"),
                               schema=schema, max_tokens=50)
        try:
            label = json.loads(r.text)["answer"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ValueError(f"decide: unparseable answer {r.text[:80]!r}") from e
        if label not in labels:
            raise ValueError(f"decide: answer {label!r} not among {labels}")
        return Decision(to_value(q, label), None, {}, "constrained", r.model)

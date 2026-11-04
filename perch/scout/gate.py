"""The scope gate (Phase 8, task 5): one small call before any large model.

A fixed system prompt (perch/scout/texts.py GATE_SYSTEM), the user's message, and a cap of
GATE_MAX_TOKENS output tokens. The reply is one of in_scope, out_of_scope, distress. Button
intents never reach it. The gate sees the question text only: no CV, no brief, no records.

An unparseable reply counts as in_scope. The large model's own system prompt states the scope
too, so a question that slips through is declined in one sentence, and the bench then measures
wrong blocks rather than silent refusals. The result carries `unclear` so the bench can count it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from perch.llm import Message, Provider
from perch.llm.base import ChatResult
from perch.scout.texts import GATE_LABELS, GATE_MAX_TOKENS, GATE_SYSTEM

MAX_QUESTION_CHARS = 1000


@dataclass
class GateResult:
    label: str  # one of GATE_LABELS
    unclear: bool
    raw: ChatResult


def parse(text: str) -> tuple[str, bool]:
    """(label, unclear). The first label found in the reply wins; none means in_scope."""
    t = re.sub(r"[^a-z_ ]", " ", text.lower()).replace(" ", "_")
    best = min(((t.find(label), label) for label in GATE_LABELS if label in t),
               default=None)
    if best is None:  # a model may cut the label short, such as "out_of"
        if t.strip("_").startswith("out"):
            return "out_of_scope", False
        if t.strip("_").startswith("dist"):
            return "distress", False
        return "in_scope", True
    return best[1], False


def classify(provider: Provider, question: str) -> GateResult:
    res = provider.chat([Message("user", question[:MAX_QUESTION_CHARS])], system=GATE_SYSTEM,
                        max_tokens=GATE_MAX_TOKENS)
    label, unclear = parse(res.text)
    return GateResult(label, unclear, res)

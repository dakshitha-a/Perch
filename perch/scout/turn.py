"""One Scout turn (Phase 8): the button path, the scope gate, the open answer.

`run_turn` is pure in the sense that matters here: it takes the things it may read (`ScoutData`),
the models (`provider_for`), a grounder and a meter, and returns one assistant message dict. It
touches no database itself. The `scout_turn` job handler (perch/scout/job.py) and the web layer
(perch/scout/routes.py) build those inputs from the account's rows.

Order of work for a question:
  1. A button intent skips everything below and is answered by code (perch/scout/buttons.py).
  2. The gate (a small fixed-prompt call, a few output tokens) sorts the question: in scope,
     out of scope, or distress. Out of scope gets a fixed refusal and distress a fixed message
     with Temple's own services; neither calls the large model. Both counted the gate's cost.
  3. In scope: Scout answers with native tool use over the read tools, then the answer is graded
     (perch/scout/answer.py), regenerated once if it fails, and shown flagged if it fails again.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from perch.grounding import Grounder
from perch.llm import ChatResult, Message, Provider, ToolResult
from perch.llm.base import JsonSchema, Tool
from perch.llm.contacts import blank_contacts
from perch.redisx import QuotaExceeded
from perch.scout import answer as ans
from perch.scout import buttons, gate, texts
from perch.scout.read_tools import ReadTools, ScoutData, ToolError, facts

MAX_STEPS = 6  # model calls that may ask for tools in one question
MAX_ANSWER_TOKENS = 1500
TOOL_JSON_CHARS = 12000
HISTORY_MESSAGES = 6
HISTORY_CHARS = 1200
MAX_QUESTION_CHARS = 1000
ESTIMATE_MICRO = {"gate": 100, "scout": 30_000}  # reserved before a call, settled after


class Meter:
    """Charges model calls to the account's daily budget. The base class charges nothing."""

    def call(self, role: str, provider: Provider, messages: list[Message], **kw: object
             ) -> ChatResult:
        return provider.chat(messages, **kw)


class Metered(Provider):
    """A provider whose every call goes through the meter, so the gate and the answer steps
    are charged and can be refused by the budget (QuotaExceeded)."""

    def __init__(self, inner: Provider, meter: Meter, role: str) -> None:
        self.inner, self.meter, self.role = inner, meter, role
        self.name, self.model, self.capabilities = inner.name, inner.model, inner.capabilities

    def chat(self, messages: list[Message], *, system: str | None = None,
             tools: list[Tool] | None = None, schema: JsonSchema | None = None,
             max_tokens: int = 2048, logprobs: int = 0, cache_system: bool = False
             ) -> ChatResult:
        return self.meter.call(self.role, self.inner, messages, system=system, tools=tools,
                               schema=schema, max_tokens=max_tokens, logprobs=logprobs,
                               cache_system=cache_system)


@dataclass
class TurnDeps:
    data: ScoutData
    provider_for: Callable[[str], Provider]  # "gate" or "scout" -> a provider
    grounder: Callable[[], Grounder | None] = lambda: None
    names: Callable[[], set[str]] = set
    meter: Meter = Meter()  # noqa: RUF009 - stateless
    handoff: Callable[[], dict[str, Any] | None] | None = None


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def message(role: str, kind: str, text: str, **extra: object) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "role": role, "kind": kind, "text": text, "at": now_iso(),
            **extra}


def user_message(question: str | None = None, intent: str | None = None) -> dict[str, Any]:
    if intent:
        label = next((b["label"] for b in buttons.BUTTONS if b["intent"] == intent), intent)
        return message("user", "intent", label, intent=intent)
    return message("user", "question", (question or "").strip()[:MAX_QUESTION_CHARS])


def history_of(messages: list[dict[str, Any]]) -> list[Message]:
    """The last few text exchanges, as plain messages. Tool results are not kept, so a CV
    part read in an earlier turn is read again if it is needed (and blanked again)."""
    out: list[Message] = []
    for m in [m for m in messages if m.get("text") and m.get("kind") != "error"
              ][-HISTORY_MESSAGES:]:
        role = "assistant" if m["role"] == "assistant" else "user"
        text = blank_contacts(m["text"][:HISTORY_CHARS])  # a question is stored as typed
        if out and out[-1].role == role:
            out[-1] = Message(role, out[-1].content + "\n" + text)
        else:
            out.append(Message(role, text))
    while out and out[0].role != "user":
        out.pop(0)
    return out


# --- the open answer ---

def _converse(deps: TurnDeps, tools: ReadTools, messages: list[Message], system: str
              ) -> str:
    provider = Metered(deps.provider_for("scout"), deps.meter, "scout")
    defs = tools.definitions()
    for _ in range(MAX_STEPS):
        res = provider.chat(messages, system=system, tools=defs, max_tokens=MAX_ANSWER_TOKENS,
                            cache_system=True)
        if not res.tool_calls:
            return res.text.strip()
        messages.append(Message("assistant", res.text, tool_calls=res.tool_calls))
        results = []
        for c in res.tool_calls:
            try:
                body = json.dumps(tools.run(c.name, c.arguments), default=str)
                if len(body) > TOOL_JSON_CHARS:  # always valid JSON, never a cut one
                    body = json.dumps({"truncated": True, "text": body[:TOOL_JSON_CHARS // 2]})
                results.append(ToolResult(c.id, c.name, body))
            except ToolError as e:
                results.append(ToolResult(c.id, c.name, json.dumps({"error": str(e)}),
                                          is_error=True))
        messages.append(Message("user", "", tool_results=results))
    messages.append(Message("user", "Answer now from what you have read. Do not call a tool."))
    res = provider.chat(messages, system=system, max_tokens=MAX_ANSWER_TOKENS)
    return res.text.strip()


def _sources(ids: list[str], tools: ReadTools) -> list[dict[str, Any]]:
    out = []
    for i in ids:
        r = tools.seen.get(i)
        if r is None:
            continue
        if r.source == "user":
            out.append({"id": i, "title": getattr(r, "title", i), "user": True})
        else:
            f = facts(r, tools.data.as_of)
            out.append({"id": i, "title": f.get("title"), "source_url": r.source_url,
                        **({"sample": True} if f.get("sample") else {})})
    return out


def open_answer(deps: TurnDeps, history: list[Message], question: str) -> dict[str, Any]:
    tools = ReadTools(deps.data)
    system = texts.system_prompt(deps.data.audience)
    if history and history[-1].role == "user":  # never two user turns in a row
        history = history[:-1]
    messages = [*history, Message("user", question)]
    names = deps.names()
    graded: ans.Graded | None = None
    text = ""
    for attempt in (1, 2):
        text = _converse(deps, tools, messages, system)
        if not text:
            if attempt == 2:
                if graded is None:
                    return message("assistant", "error", texts.ERROR)
                break  # the first answer failed its checks and the second was empty
            messages.append(Message("user", "Your answer was empty. Answer the question."))
            continue
        if not tools.used and len(text) < 400 and ans.DECLINE_RE.search(text):
            # The system prompt's own scope line: shown as the code-written refusal.
            return message("assistant", "refusal", texts.REFUSAL, gate="model_declined")
        this = ans.grade(text, tools.seen, names, deps.data.as_of, deps.grounder())
        if graded is None or len(this.errors) < len(graded.errors):
            graded = this  # the second answer replaces the first only if it is better
        if this.ok:
            break
        if attempt == 1:
            messages += [Message("assistant", text), Message("user", ans.feedback(this))]
    if graded is None:
        return message("assistant", "error", texts.ERROR)
    flagged = not graded.ok
    body, general = ans.render(graded, drop_failed=flagged)
    removed = (sum(bool(s.errors) for s in graded.sentences)
               + (1 if flagged and graded.general and graded.general_errors else 0))
    if not body and not general:
        body = texts.WITHHELD
    ids = graded.cited_ids
    return message("assistant", "answer", body, general=general, flagged=flagged,
                   withheld=removed if flagged else 0,
                   unsupported=graded.unsupported if not flagged else [],
                   records=ids, sources=_sources(ids, tools),
                   read=sorted(tools.seen), steps=tools.used)


# --- the turn ---

def run_turn(deps: TurnDeps, history: list[dict[str, Any]], *, question: str | None = None,
             intent: str | None = None) -> dict[str, Any]:
    """The assistant message for one user message. `history` is the session's earlier
    messages, without this one."""
    if intent:
        try:
            body = buttons.answer(intent, deps.data, deps.handoff)
        except buttons.IntentError as e:
            return message("assistant", "intent", str(e), intent=intent, records=[],
                           flagged=False, unsupported=[], empty=True)
        return message("assistant", "intent", body.pop("text"), **{
            k: v for k, v in body.items() if k not in ("kind",)})
    # The stored message keeps the question as typed (encrypted); the models see it with
    # emails, phone numbers, ORCIDs and links blanked (standing rule 5).
    q = blank_contacts((question or "").strip()[:MAX_QUESTION_CHARS])
    if not q:
        return message("assistant", "error", texts.ERROR)
    try:
        g = gate.classify(Metered(deps.provider_for("gate"), deps.meter, "gate"), q)
        if g.label == "out_of_scope":
            return message("assistant", "refusal", texts.REFUSAL, gate=g.label)
        if g.label == "distress":
            return message("assistant", "distress", texts.distress_message(deps.data.audience),
                           gate=g.label)
        out = open_answer(deps, history_of(history), q)
        out["gate"] = g.label if not g.unclear else "unclear"
        return out
    except QuotaExceeded:
        return message("assistant", "budget", texts.BUDGET)

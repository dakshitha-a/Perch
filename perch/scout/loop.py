"""Scout's loop: plan, tool call, observe, until an answer (SPEC section 8).

One session is one conversation about one researcher. Each model turn either asks for
tools or answers. In "ask" mode every proposed tool call waits as a card until the user
approves or skips it; in "run" mode calls run as they come. Only allowlisted tools run;
a call to anything else is refused and counted. The final answer passes the citation
validator against the records the tools returned; a failure is rewritten once, then the
answer is withheld and flagged (standing rules 3 and 5). A budget caps model turns,
tokens and dollars per session.

Two policies drive the model: "native" uses the provider's tool calling; "structured"
is the fallback for small local models: one JSON step per turn, constrained by a schema,
with the tool catalogue in the prompt.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Literal

from perch.llm import ChatResult, Message, Provider, ToolCall, ToolResult, cost_usd
from perch.privacy import PrivateSettings
from perch.scout.log import ScoutLog, digest
from perch.scout.tools import ALLOWLIST, TOOLS, ScoutContext, ToolError, check_arguments
from perch.skills import parse_json
from perch.validate import DATE_PATTERNS, NUM_RE, check, find_dates, norm_number

Mode = Literal["ask", "run"]
Policy = Literal["native", "structured"]
LOCAL_ADAPTERS = ("ollama", "openai", "fake")

RULES = """You are Scout, the agent inside Perch. Perch lays out routes to fund a Temple \
University researcher's work, from public records only.

Rules:
- Use only the tools you are given. You cannot browse the web, send email, apply for \
anything, change a record, or read private documents. If the user asks for something no \
tool can do, say so plainly in one sentence and do not call a tool.
- Perch's opportunity records are federal grants from Grants.gov. There are no \
foundation or private-sponsor records yet; say so if asked for them.
- Call the fewest tools that answer the question. Do not call a tool again for \
something an earlier result already shows.
- Every fact in your answer comes from a tool result. Cite the record id in square \
brackets right after the fact, like [grants_gov:PAR-25-123] or [W2741809807].
- Copy dates and dollar amounts exactly as the record gives them and cite that record. \
Never compute, round, estimate or count. If a record has no value for something, say \
that it is not in the record.
- Answer in two to five short, plain sentences."""

STRUCTURED = """You work in steps. Each reply is one JSON object:
{"action": "call", "tool": "<tool name>", "arguments": {...}, "answer": ""} to call one \
tool, or {"action": "answer", "tool": "none", "arguments": {}, "answer": "<your answer>"} \
to finish. Tools:"""

STEP_SCHEMA = {"type": "object", "properties": {
    "action": {"type": "string", "enum": ["call", "answer"]},
    "tool": {"type": "string", "enum": [*ALLOWLIST, "none"]},
    "arguments": {"type": "object"},
    "answer": {"type": "string"}},
    "required": ["action", "tool", "arguments", "answer"], "additionalProperties": False}

CITE_RE = re.compile(r"\[([^\[\]]+)\]")
LIST_RE = re.compile(r"^\s*\d{1,2}[.)]\s", re.M)  # "1. " at a line start: formatting
K_RE = re.compile(r"\$?(\d+(?:\.\d+)?)\s*([kKmM])\b")


@dataclass
class ScoutBudget:
    max_turns: int = 8  # model calls per question
    max_tokens: int = 120_000  # per session, input plus output
    max_usd: float = 0.25  # per session


@dataclass
class Card:
    """One tool call, as the web app shows it."""

    id: str
    turn: int
    tool: str
    arguments: dict
    status: Literal["proposed", "done", "skipped", "refused", "error"] = "proposed"
    detail: str = ""
    result: dict | None = None
    ms: float = 0.0


@dataclass
class Session:
    id: str
    mode: Mode
    policy: Policy
    model: str
    private: bool
    messages: list[Message] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)
    status: Literal["running", "awaiting_approval", "done", "stopped", "failed"] = "running"
    answer: str | None = None
    cited_ids: list[str] = field(default_factory=list)
    flagged: bool = False
    errors: list[str] = field(default_factory=list)
    turns: int = 0  # model calls for the current question
    tokens: int = 0
    usd: float = 0.0
    user_numbers: set[str] = field(default_factory=set)

    def pending(self) -> list[Card]:
        return [c for c in self.cards if c.status == "proposed"]


def cited(text: str) -> list[str]:
    ids = []
    for group in CITE_RE.findall(text):
        ids += [x.strip() for x in re.split(r"[,;]", group) if x.strip()]
    return list(dict.fromkeys(ids))


def stated_numbers(text: str) -> set[str]:
    """Numbers and dates the user typed: repeating them is not inventing them. Dates are
    kept whole (as their matched text and ISO form)."""
    out = {m.group(0) for rx, _ in DATE_PATTERNS for m in rx.finditer(text)}
    out |= {d.isoformat() for _, d in find_dates(text) if d}
    bare = text
    for rx, _ in DATE_PATTERNS:
        bare = rx.sub(" ", bare)
    out |= {norm_number(m.group(0)) for m in NUM_RE.finditer(bare)}
    for m in K_RE.finditer(bare):
        out.add(norm_number(str(float(m.group(1)) * (1e3 if m.group(2) in "kK" else 1e6))))
    return out


def scrub(text: str, allowed: set[str]) -> str:
    """Remove citations, list markers and the user's own numbers and dates before the
    validator reads the text. A date is removed whole or kept whole, never cut up."""
    text = LIST_RE.sub(" ", CITE_RE.sub(" ", text))
    spans = []
    for rx, _ in DATE_PATTERNS:
        for m in rx.finditer(text):
            d = next((d for _, d in find_dates(m.group(0)) if d), None)
            spans.append((m.start(), m.end(), m.group(0) in allowed
                          or (d is not None and d.isoformat() in allowed)))
    out, pos = [], 0
    for m in NUM_RE.finditer(text):
        inside = next((sp for sp in spans if sp[0] <= m.start() < sp[1]), None)
        if inside or norm_number(m.group(0)) not in allowed:
            continue
        out += [text[pos:m.start()], " "]
        pos = m.end()
    text = "".join(out) + text[pos:]
    for rx, _ in DATE_PATTERNS:  # user's dates, whole
        text = rx.sub(lambda m: " " if m.group(0) in allowed or any(
            d and d.isoformat() in allowed for _, d in find_dates(m.group(0))) else m.group(0),
            text)
    return text


class Scout:
    def __init__(self, provider: Provider, ctx: ScoutContext, *, mode: Mode = "ask",
                 policy: Policy | None = None, budget: ScoutBudget | None = None,
                 log: ScoutLog | None = None, private: PrivateSettings | None = None,
                 brief_note: str = "") -> None:
        if private is not None:
            refuse_if_not_local(provider, private)
            log = None  # private sessions write nothing (Q14)
        self.provider, self.ctx, self.mode = provider, ctx, mode
        self.policy: Policy = policy or ("native" if "tools" in provider.capabilities
                                         else "structured")
        self.budget = budget or ScoutBudget()
        self.log = log
        self.private = private is not None
        self.system = (f"{RULES}\n\nSession: researcher {ctx.full_author_id(None)} "
                       f"(OpenAlex), as-of date {ctx.as_of.isoformat()}.{brief_note}")
        self.tools = [t for t, _ in TOOLS.values()]

    # --- public API ---

    def start(self, question: str) -> Session:
        s = Session(id=secrets.token_urlsafe(9), mode=self.mode, policy=self.policy,
                    model=self.provider.spec, private=self.private)
        if self.log:
            self.log.write({"kind": "session", "session": s.id, "model": s.model,
                            "mode": s.mode, "policy": s.policy,
                            "researcher": self.ctx.researcher_id,
                            "as_of": self.ctx.as_of.isoformat()})
        return self.ask(s, question)

    def ask(self, s: Session, question: str) -> Session:
        """A question, or a follow-up in the same session."""
        s.messages.append(Message("user", question))
        s.user_numbers |= stated_numbers(question)
        s.status, s.answer, s.flagged, s.errors, s.turns = "running", None, False, [], 0
        if self.log:
            self.log.write({"kind": "question", "session": s.id, "hash": digest(question)})
        return self.advance(s)

    def approve(self, s: Session, card_id: str | None = None) -> Session:
        """Approve one waiting card, or all of them."""
        for c in s.pending():
            if card_id in (None, c.id):
                self._execute(s, c)
        return self.advance(s)

    def skip(self, s: Session, card_id: str | None = None) -> Session:
        for c in s.pending():
            if card_id in (None, c.id):
                c.status, c.detail = "skipped", "skipped by the user"
                c.result = {"status": "skipped", "detail": "The user skipped this step. Do "
                            "not call it again unless they ask."}
                self._log_tool(s, c)
        return self.advance(s)

    def advance(self, s: Session) -> Session:
        while True:
            if s.pending():
                if self.mode == "ask":
                    s.status = "awaiting_approval"
                    return s
                for c in s.pending():
                    self._execute(s, c)
            self._reply_with_results(s)
            if why := self._over_budget(s):
                return self._stop(s, why)
            try:
                r = self._next(s, tools=True)
            except ValueError as e:  # the structured policy produced no usable step
                return self._stop(s, f"model output could not be used: {e}", failed=True)
            if r.tool_calls:
                s.messages.append(Message("assistant", r.text, tool_calls=r.tool_calls))
                s.cards += [Card(c.id or secrets.token_hex(4), s.turns, c.name, c.arguments)
                            for c in r.tool_calls]
                continue
            return self._finish(s, r.text)

    # --- internals ---

    def _next(self, s: Session, tools: bool) -> ChatResult:
        s.turns += 1
        if self.policy == "native":
            r = self.provider.chat(s.messages, system=self.system,
                                   tools=self.tools if tools else None, max_tokens=2000,
                                   cache_system=True)
        else:
            r = self._structured(s, tools)
        s.tokens += r.usage.input_tokens + r.usage.output_tokens
        c = cost_usd(r)
        s.usd += c if c == c else 0.0  # unknown price (nan) is reported by the audit log
        return r

    def _structured(self, s: Session, tools: bool) -> ChatResult:
        catalogue = "\n".join(f"- {t.name}: {t.description} Arguments: "
                              f"{json.dumps(t.parameters['properties'])}" for t in self.tools)
        system = f"{self.system}\n\n{STRUCTURED}\n{catalogue}" if tools else self.system
        msgs = [Message(m.role, render(m)) for m in s.messages]
        r = self.provider.chat(msgs, system=system, schema=STEP_SCHEMA if tools else None,
                               max_tokens=1500, cache_system=True)
        if not tools:
            return r
        d = parse_json(r.text)
        if d.get("action") == "call" and d.get("tool") not in (None, "none"):
            r.tool_calls = [ToolCall(secrets.token_hex(4), str(d["tool"]),
                                     d.get("arguments") or {})]
            r.text = ""
        else:
            r.text = str(d.get("answer") or "")
        return r

    def _execute(self, s: Session, c: Card) -> None:
        t0 = time.perf_counter()
        entry = TOOLS.get(c.tool)
        if entry is None:
            c.status, c.detail = "refused", f"{c.tool} is not an allowed tool"
            c.result = {"error": f"{c.tool!r} is not an allowed tool. Allowed: "
                        f"{', '.join(ALLOWLIST)}."}
        elif errs := check_arguments(entry[0], c.arguments):
            c.status, c.detail = "refused", "; ".join(errs)
            c.result = {"error": "bad arguments: " + "; ".join(errs)}
        else:
            args = {k: v for k, v in c.arguments.items() if v is not None}
            try:
                c.result = entry[1](self.ctx, **args)
                c.status = "done"
                c.detail = summarise(c.tool, c.result)
            except ToolError as e:
                c.status, c.detail, c.result = "error", str(e), {"error": str(e)}
            except Exception as e:  # noqa: BLE001 - reported to the model by type only
                c.status, c.detail = "error", f"{type(e).__name__} in {c.tool}"
                c.result = {"error": f"the tool failed ({type(e).__name__})"}
        c.ms = round((time.perf_counter() - t0) * 1000, 1)
        self._log_tool(s, c)

    def _reply_with_results(self, s: Session) -> None:
        """Answer the last assistant turn's tool calls once all of its cards are settled."""
        if not s.messages or not s.messages[-1].tool_calls:
            return
        ids = {tc.id for tc in s.messages[-1].tool_calls}
        cards = [c for c in s.cards if c.id in ids]
        s.messages.append(Message("user", "", tool_results=[
            ToolResult(c.id, c.tool, json.dumps(c.result, default=str),
                       c.status in ("refused", "error")) for c in cards]))

    def _over_budget(self, s: Session) -> str | None:
        b = self.budget
        if s.turns >= b.max_turns:
            return f"stopped after {b.max_turns} model turns"
        if s.tokens >= b.max_tokens:
            return f"stopped at the token budget ({b.max_tokens:,})"
        if s.usd >= b.max_usd:
            return f"stopped at the cost budget (${b.max_usd:.2f})"
        return None

    def _stop(self, s: Session, why: str, failed: bool = False) -> Session:
        s.status = "failed" if failed else "stopped"
        s.errors = [why]
        self._log_answer(s, passed=False, attempts=0)
        return s

    def _validate(self, s: Session, text: str) -> list[str]:
        ids = cited(text)
        errs = check(scrub(text, s.user_numbers), ids, self.ctx.seen).errors
        if not text.strip():
            errs.append("empty answer")
        return errs

    def _finish(self, s: Session, text: str) -> Session:
        errs = self._validate(s, text)
        attempts = 1
        if errs:
            attempts = 2
            s.messages.append(Message("assistant", text))
            s.messages.append(Message("user", "Your answer was rejected by the citation "
                                      "check: " + "; ".join(errs) + ". Rewrite it without "
                                      "those problems. Do not call tools."))
            text = self._next(s, tools=False).text
            if self.policy == "structured":
                text = structured_answer(text)
            errs = self._validate(s, text)
        s.messages.append(Message("assistant", text if not errs else "(answer withheld)"))
        if errs:
            s.answer, s.flagged, s.errors, s.cited_ids = None, True, errs, []
        else:
            s.answer, s.cited_ids = text, cited(text)
        s.status = "done"
        self._log_answer(s, passed=not errs, attempts=attempts)
        return s

    def _log_tool(self, s: Session, c: Card) -> None:
        if self.log:
            self.log.write({"kind": "tool", "session": s.id, "turn": c.turn, "call": c.id,
                            "tool": c.tool, "arguments": c.arguments,
                            "args_hash": digest(c.arguments), "result_hash": digest(c.result),
                            "status": c.status, "ms": c.ms})

    def _log_answer(self, s: Session, passed: bool, attempts: int) -> None:
        if self.log:
            self.log.write({"kind": "answer", "session": s.id, "status": s.status,
                            "passed": passed, "attempts": attempts, "errors": s.errors,
                            "cited": s.cited_ids, "turns": s.turns, "tokens": s.tokens,
                            "usd": round(s.usd, 5),
                            "answer_hash": digest(s.answer) if s.answer else None})


def render(m: Message) -> str:
    """A message as plain text, for the structured policy (no native tool turns)."""
    if m.tool_calls:
        c = m.tool_calls[0]
        return json.dumps({"action": "call", "tool": c.name, "arguments": c.arguments,
                           "answer": ""})
    if m.tool_results:
        return "\n".join(f"Result of {r.name}: {r.content}" for r in m.tool_results)
    return m.content


def structured_answer(text: str) -> str:
    try:
        return str(parse_json(text).get("answer") or text)
    except ValueError:
        return text


def summarise(tool: str, result: dict) -> str:
    """One plain line for the card."""
    if result.get("status") == "not_built":
        return result["detail"]
    if tool == "search_opportunities":
        return (f"{len(result['leads'])} leads; {result['removed_by_filters']} removed by "
                "filters")
    if tool == "build_profile":
        return f"{result['papers']} papers in {len(result['threads'])} threads"
    if tool == "list_awards":
        return f"{len(result['awards'])} public awards"
    if tool == "resolve_author":
        return f"{len(result['candidates'])} candidates"
    if tool == "explain_fit":
        return "withheld" if result.get("status") == "withheld" else f"fit {result['fit']}"
    if tool == "get_record":
        return f"{result['kind']} {result['record']['id']}"
    return "done"


def refuse_if_not_local(provider: Provider, private: PrivateSettings) -> None:
    """Private sessions use self-hosted models on allowed endpoints only."""
    if provider.name not in LOCAL_ADAPTERS:
        raise PermissionError(f"private sessions cannot use {provider.name}: hosted API")
    http = getattr(provider, "http", None)
    url = str(http.base_url) if http is not None else ""
    if http is not None and not private.endpoint_allowed(url):
        raise PermissionError(f"private sessions cannot send to {url}: not an allowed endpoint")


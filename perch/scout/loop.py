"""Scout's loop: plan, tool call, observe, until an answer (SPEC section 8).

One session is one conversation about one researcher. Each model turn either asks for
tools or answers, and each tool call runs as soon as the model asks for it, as a card the
user can see (the ask-first gate was removed in S28). Only allowlisted tools run;
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
from perch.privacy import LOCAL_ADAPTERS, PrivateSettings, refuse_if_not_local
from perch.scout.log import ScoutLog, digest
from perch.scout.tools import ALLOWLIST, SESSION_TOOLS, ScoutContext, ToolError, check_arguments
from perch.skills import parse_json
from perch.validate import DATE_PATTERNS, NUM_RE, check, find_dates, norm_number

Policy = Literal["native", "structured"]

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

def step_schema(names: tuple[str, ...]) -> dict:
    """The structured-step schema for one allowlist."""
    return {**STEP_SCHEMA, "properties": {**STEP_SCHEMA["properties"],
                                          "tool": {"type": "string", "enum": [*names, "none"]}}}


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
    status: Literal["proposed", "done", "not_run", "refused", "error", "repeated"] = "proposed"
    detail: str = ""
    result: dict | None = None
    ms: float = 0.0
    # Where the step ran (S28): "code", or "local" or "cloud" for a model-backed tool, with
    # the provider's name and the tokens and dollars it spent, added to the session's budget.
    where: str = "code"
    provider: str = ""
    tokens: int = 0
    usd: float = 0.0


@dataclass
class Session:
    id: str
    policy: Policy
    model: str
    private: bool
    messages: list[Message] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)
    status: Literal["running", "done", "stopped", "failed"] = "running"
    answer: str | None = None
    cited_ids: list[str] = field(default_factory=list)
    flagged: bool = False
    errors: list[str] = field(default_factory=list)
    turns: int = 0  # model calls for the current question
    tokens: int = 0
    usd: float = 0.0
    user_numbers: set[str] = field(default_factory=set)
    stop_asked: bool = False  # Stop was pressed: no further step runs for this question
    # One entry per question: its text, the first card it made, and how it ended. Held in
    # memory for the web app; the log keeps a hash of the question only.
    exchanges: list[dict] = field(default_factory=list)

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


# Words that make a number the user's filter, not a record's value: "closes by 2027-03-01",
# "ceilings over $500,000". In a sentence that cites a record, a number the user typed
# passes only after one of these; "a $5,000,000 ceiling [id]" must match the record
# (review S14).
FILTER_RE = re.compile(r"\b(?:by|before|after|until|through|within|under|over|above|below|"
                       r"least|most|than|up to)\W{0,3}$", re.I)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def scrub(text: str, allowed: set[str]) -> str:
    """Remove citations, list markers and the user's own numbers and dates before the
    validator reads the text. A date is removed whole or kept whole, never cut up. In a
    sentence that cites a record, the user's number is removed only where it reads as
    the user's filter (FILTER_RE)."""
    text = LIST_RE.sub(" ", text)
    return " ".join(_scrub(x, allowed, bool(CITE_RE.search(x)))
                    for x in SENTENCE_RE.split(text) if x)


def _scrub(text: str, allowed: set[str], cites: bool) -> str:
    text = CITE_RE.sub(" ", text)

    def mine(start: int) -> bool:  # may this occurrence be the user's own number?
        return not cites or bool(FILTER_RE.search(text[max(0, start - 24):start]))

    spans = []
    for rx, _ in DATE_PATTERNS:
        for m in rx.finditer(text):
            d = next((d for _, d in find_dates(m.group(0)) if d), None)
            spans.append((m.start(), m.end(), m.group(0) in allowed
                          or (d is not None and d.isoformat() in allowed)))
    out, pos = [], 0
    for m in NUM_RE.finditer(text):
        inside = next((sp for sp in spans if sp[0] <= m.start() < sp[1]), None)
        if inside or norm_number(m.group(0)) not in allowed or not mine(m.start()):
            continue
        out += [text[pos:m.start()], " "]
        pos = m.end()
    text = "".join(out) + text[pos:]
    for rx, _ in DATE_PATTERNS:  # user's dates, whole
        text = rx.sub(lambda m: " " if mine(m.start()) and (m.group(0) in allowed or any(
            d and d.isoformat() in allowed for _, d in find_dates(m.group(0)))) else m.group(0),
            text)
    return text


class Scout:
    def __init__(self, provider: Provider, ctx: ScoutContext, *,
                 policy: Policy | None = None, budget: ScoutBudget | None = None,
                 log: ScoutLog | None = None, private: PrivateSettings | None = None,
                 brief_note: str = "", table: dict | None = None,
                 rules: str | None = None, who: str | None = None) -> None:
        """`table`, `rules` and `who`: another allowlist, rule set and session line, such
        as the student tools (perch.scout.student_tools). By default the researcher's
        tools, fixed to the session's researcher (SESSION_TOOLS)."""
        if private is not None:
            refuse_if_not_local(provider, private)
            log = None  # no Scout log (Q14); the tools' caches are S13's job
        self.provider, self.ctx = provider, ctx
        self.policy: Policy = policy or ("native" if "tools" in provider.capabilities
                                         else "structured")
        self.budget = budget or ScoutBudget()
        self.log = log
        self.private = private is not None
        who = who or ("a researcher with no public profile (private documents only)"
                      if (ctx.researcher_id or "").startswith("private:")
                      else f"researcher {ctx.full_author_id(None)} (OpenAlex)")
        self.table = table or SESSION_TOOLS
        self.system = (f"{rules or RULES}\n\nSession: {who}, as-of date "
                       f"{ctx.as_of.isoformat()}.{brief_note}")
        self.tools = [t for t, _ in self.table.values()]
        self.schema = step_schema(tuple(self.table))

    # --- public API ---

    def start(self, question: str) -> Session:
        return self.ask(self.open(), question)

    def open(self) -> Session:
        s = Session(id=secrets.token_urlsafe(9), policy=self.policy,
                    model=self.provider.spec, private=self.private)
        if self.log:
            self.log.write({"kind": "session", "session": s.id, "model": s.model,
                            "policy": s.policy,
                            "researcher": self.ctx.researcher_id,
                            "as_of": self.ctx.as_of.isoformat()})
        return s

    def ask(self, s: Session, question: str) -> Session:
        """A question, or a follow-up in the same session."""
        s.messages.append(Message("user", question))
        s.user_numbers |= stated_numbers(question)
        s.status, s.answer, s.flagged, s.errors, s.turns = "running", None, False, [], 0
        s.exchanges.append({"question": question, "cards_from": len(s.cards), "answer": None,
                            "flagged": False, "errors": [], "status": "running"})
        if self.log:
            self.log.write({"kind": "question", "session": s.id, "hash": digest(question)})
        return self.advance(s)

    def stop(self, s: Session) -> None:
        """Stop the current question between steps (S28). It may be called from another
        thread while advance() runs: the steps already done stay, the rest are not run. A
        model call already under way finishes; if it brings the answer, the answer stands.
        The flag is cleared when the question ends."""
        s.stop_asked = True

    def advance(self, s: Session) -> Session:
        while True:
            for c in s.pending():
                if s.stop_asked:
                    self._not_run(s, c)
                else:
                    self._execute(s, c)
            self._reply_with_results(s)
            if s.stop_asked:
                return self._stop(s, "", by_user=True)
            if why := self._over_budget(s):
                return self._stop(s, why)
            try:
                r = self._next(s, tools=True)
            except ValueError as e:  # the structured policy produced no usable step
                return self._stop(s, f"model output could not be used: {e}", failed=True)
            if r.tool_calls:
                s.messages.append(Message("assistant", r.text, tool_calls=r.tool_calls))
                new = [Card(c.id or secrets.token_hex(4), s.turns, c.name, c.arguments)
                       for c in r.tool_calls]
                s.cards += new
                for c in new:
                    self._answer_repeat(s, c)
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
        r = self.provider.chat(msgs, system=system, schema=self.schema if tools else None,
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

    def _answer_repeat(self, s: Session, c: Card) -> None:
        """A call identical to one already run for this question is not run again: it gets
        the earlier result back with a note.
        (In S10's first bench run, Sonnet repeated one search up to nine times.)"""
        key = (c.tool, digest(_canonical(c.arguments)))
        start = s.exchanges[-1]["cards_from"] if s.exchanges else 0
        for e in s.cards[start:]:
            if e is c:
                break
            if e.status in ("done", "error") and (e.tool, digest(_canonical(e.arguments))) == key:
                c.status = "repeated"
                c.detail = "same call as an earlier step; its result was reused"
                c.result = {"repeat_of": e.id, "note": "This exact call already ran for this "
                            "question. Its result is below. Do not call it again; answer from "
                            "it or call a different tool.", "result": e.result}
                self._log_tool(s, c)
                return

    def _not_run(self, s: Session, c: Card) -> None:
        c.status, c.detail = "not_run", "you stopped the question before this step ran"
        c.result = {"status": "not run", "detail": "The user stopped this question before this "
                    "step ran. Do not call it again unless they ask."}
        self._log_tool(s, c)

    def _execute(self, s: Session, c: Card) -> None:
        t0 = time.perf_counter()
        entry = self.table.get(c.tool)
        if entry is None:
            c.status, c.detail = "refused", f"{c.tool} is not an allowed tool"
            c.result = {"error": f"{c.tool!r} is not an allowed tool. Allowed: "
                        f"{', '.join(self.table)}."}
        elif errs := check_arguments(entry[0], c.arguments):
            c.status, c.detail = "refused", "; ".join(errs)
            c.result = {"error": "bad arguments: " + "; ".join(errs)}
        else:
            args = {k: v for k, v in c.arguments.items() if v is not None}
            model = {"explain_fit": self.ctx.explainer,
                     "draft_handoff": self.ctx.handoff}.get(c.tool)
            before = (model.tokens, model.usd) if hasattr(model, "tokens") else None
            try:
                c.result = entry[1](self.ctx, **args)
                c.status = "done"
                c.detail = summarise(c.tool, c.result)
            except ToolError as e:
                c.status, c.detail, c.result = "error", str(e), {"error": str(e)}
            except Exception as e:  # noqa: BLE001 - reported to the model by type only
                c.status, c.detail = "error", f"{type(e).__name__} in {c.tool}"
                c.result = {"error": f"the tool failed ({type(e).__name__})"}
            if before is not None:
                c.tokens, c.usd = model.tokens - before[0], model.usd - before[1]
                s.tokens += c.tokens
                s.usd += c.usd
                c.provider = model.name
                c.where = "local" if model.name in LOCAL_ADAPTERS else "cloud"
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

    def _stop(self, s: Session, why: str, failed: bool = False, by_user: bool = False) -> Session:
        s.status = "failed" if failed else "stopped"
        s.errors = [] if by_user else [why]
        s.exchanges[-1].update(status=s.status, errors=s.errors, by_user=by_user)
        s.stop_asked = False
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
        s.status, s.stop_asked = "done", False
        s.exchanges[-1].update(status="done", answer=s.answer, flagged=s.flagged,
                               errors=s.errors)
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


def _canonical(args: dict) -> dict:
    return {k: v for k, v in sorted(args.items()) if v is not None}


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
    if tool == "search_opportunities":
        n = len(result["leads"])
        return (f"{n} lead{'' if n == 1 else 's'}; {result['removed_by_filters']} removed by "
                "the eligibility rules and filters")
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
    if tool == "compare":
        return f"{len(result['rows'])} leads side by side"
    if tool == "draft_handoff":
        return (f"draft to {result['office']}, not sent"
                + ("; the model's opening was withheld" if result["opening_withheld"] else ""))
    if tool == "search_options":
        return f"{result['count']} option{'' if result['count'] == 1 else 's'} match"
    if tool in ("check_option", "explain_verdict"):
        return f"{result['verdict']}" + (", sample record" if result.get("sample") else "")
    if tool == "read_cv":
        return f"{len(result['fields'])} fields read by rule"
    if tool == "compare_options":
        return f"{len(result['rows'])} options side by side"
    if tool == "draft_note":
        return f"note to {result['office']}, written by code, not sent"
    return "done"

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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from perch.datefmt import day
from perch.llm import ChatResult, Message, Provider, ToolCall, ToolResult, cost_usd
from perch.privacy import LOCAL_ADAPTERS, PrivateSettings, refuse_if_not_local
from perch.score import match_text
from perch.scout.log import ScoutLog, digest
from perch.scout.tools import (
    ALLOWLIST,
    SESSION_TOOLS,
    ScoutContext,
    ToolError,
    check_arguments,
    short_id,
)
from perch.skills import parse_json
from perch.validate import (
    DATE_PATTERNS,
    NUM_RE,
    _month,
    check,
    evidence,
    find_dates,
    norm_number,
)

Policy = Literal["native", "structured"]

RULES = """You are Scout, the agent inside Perch. Perch lays out routes to fund a Temple \
University researcher's work, from public records only.

Rules:
- Use only the tools you are given. You cannot browse the web, send email, apply for \
anything, change a record, or quote private documents. If the user asks for something no \
tool can do, say so plainly in one sentence and do not call a tool.
- Perch's grant records are federal opportunities from Grants.gov; it has no foundation \
records yet. Companies whose works cite the researcher's papers are industry leads: \
get_org_signals lists them with their counts.
- Call the fewest tools that answer the question. The lists in these instructions are a \
snapshot: for companies, deadlines, amounts or anything else they do not show, call a \
tool, however long the conversation.
- A question that filters by a date, an amount, an agency or a code always runs \
search_opportunities with those filters, even when an earlier result showed the same \
leads. "These", "them", "those" or "my leads" mean the brief's leads, kept or not: \
scope brief. Other or new opportunities: scope all.
- How many of your papers a kept lead or grant cites is in compare's rows.
- Today is the as-of date. A month named with no year means its next one after today: \
"before March" means closes_by set to the 1st of the next March.
- "Top", "best" or "strongest" leads mean the brief's own order by Match, the strongest \
first, never the kept leads. Only a question about the kept leads, the shortlist or a \
comparison uses the kept leads.
- "The next deadline" means the soonest close date after the as-of date: call \
search_opportunities with closes_after set to the as-of date and sort set to close_date.
- When a record gives its deadline in words, such as "Proposals accepted anytime", quote \
those words.
- Every fact in your answer comes from a tool result. Cite the record id in square \
brackets right after the fact, like [grants_gov:PAR-25-123] or [W2741809807].
- Copy dates and dollar amounts exactly as the record gives them and cite that record. \
Never compute, round, estimate or count. If a record has no value for something, say \
that it is not in the record.
- Do not apologise. Answer in two to five short, plain sentences."""

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

# Steps whose result is a draft for the user to copy: the answer line is code (R3, R20).
DRAFT_TOOLS = ("draft_handoff", "draft_note")
SEARCH_TOOLS = ("search_opportunities", "search_options")
# Q5: the reminder sent once when an answer ran no tool and cites nothing.
NUDGE = ("You answered without calling a tool, and your answer cites no record. The lists "
         "in your instructions are a snapshot, and earlier results may be out of date. If "
         "one of your tools can answer this question, call it now. If no tool can, give "
         "your answer again.")
# R6: an answer that says Scout has no access, or asks for an id or an upload, is sent
# back once whatever ran: the tools work on this brief, documents and all.
NO_ACCESS_RE = re.compile(r"\b(?:no|not have|don'?t have|lack)\s+(?:any\s+)?access\b|"
                          r"\bprovide (?:your|an|the) (?:OpenAlex|ORCID|author)|\bupload\b",
                          re.I)
ACCESS_NUDGE = ("Your answer says you have no access, or asks for an ID or an upload. You have "
                "what you need: your tools work on this brief, which was built from the "
                "user's public records and any documents they added. Call one of your tools, "
                "or answer from the results you have. Never ask for an OpenAlex ID or an "
                "upload.")
# R21, T1, T6: a question that filters ("now only the ones closing after 1 March 2027",
# "which of these close before March?", "the largest ceiling") answered with no tool, gave
# no filter to see and no record behind its dates. It is sent back once, naming the search
# tool. The reminder is an instruction, not a complaint: worded as "you answered from an
# earlier result", it drew an apology and no call (T1).
MONTHS_RE = (r"(?:january|february|march|april|june|july|august|september|october|november|"
             r"december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec|(?-i:May))")
FILTER_Q_RE = re.compile(r"\b(?:only|closing|closes?|after|before|until|under|over|above|"
                         r"below|at least|more than|less than|soonest|largest|biggest|"
                         r"smallest|highest|lowest|most money|ceilings?|NIH|NSF|DOE|DOD|NASA|"
                         rf"USDA|[RKFUP]\d\d|eligib\w*|{MONTHS_RE})\b", re.I)
# G4: a student follow-up that names a code ("f31?") or the samples, answered with no tool,
# is sent back with the exact call, not a list of filters: in a long conversation the
# general reminder drew a second refusal.
CODE_Q_RE = re.compile(r"\b([RKFUPT]\d\d)\b", re.I)
SAMPLES_Q_RE = re.compile(r"\b(?:drop|no|without|hide|leave out|skip|remove|not)\b[^.?!]{0,20}"
                          r"\bsamples?\b", re.I)
FILTER_NUDGE = ("Call {tool} now with every filter in the question, such as {filters}, with "
                "dates written like 2027-03-01. Reply with the tool call only.")
FILTERS = {"search_opportunities": "closes_by, closes_after, agencies or sort",
           "search_options": "verdict, deadline_after, deadline_before, route, words or sort"}
# T7: a question that names one record ("the MPS Chem deadline is ...; confirm that") is
# answered from that record.
RECORD_NUDGE = ("Call get_record with id {id} now and answer from what the record says, "
                "quoting its own words for the deadline. Reply with the tool call only.")
# T5 (Q5 again): "Which company cites my papers the most?" drew "Perch only has federal
# grant records ... no foundation or private-sponsor records", which the refusal list
# below let through, since it was matched on the answer's words. A question about
# companies or citations, answered with no tool, is sent back naming get_org_signals.
ORG_Q_RE = re.compile(r"\b(?:compan(?:y|ies)|industr\w*|firms?|cit(?:e|es|ed|ing|ations?))\b",
                      re.I)
# F5: "How many of my papers does each kept lead cite?" is about grants: compare answers it.
GRANT_Q_RE = re.compile(r"\b(?:kept|grants?|leads?|opportunit\w*|shortlist)\b", re.I)
# F1: "these", "them", "my leads" are the brief's own leads; "other" or "new" ones are the
# store's. Code sets search_opportunities' scope from the question; with neither, the
# model's choice stands, and the default is the whole store.
BRIEF_Q_RE = re.compile(r"\b(?:these|those|them|my (?:\w+ )?(?:leads?|grants?|brief|shortlist)|"
                        r"(?:on|in|from) (?:my|the) brief|the brief's)\b", re.I)
OTHER_Q_RE = re.compile(r"\b(?:new|other|others|else|beyond|outside|additional|elsewhere|"
                        r"more (?:leads|grants|opportunities)|not (?:on|in) (?:my|the) brief|"
                        r"whole store|all opportunities)\b", re.I)


def question_scope(question: str) -> str | None:
    if OTHER_Q_RE.search(question):
        return "all"
    return "brief" if BRIEF_Q_RE.search(question) else None


# F6: one explain_verdict per question; search_options already gives each option's reason.
ONCE_PER_QUESTION = ("explain_verdict",)
# F15: the last list Scout showed, so "the first one" in a follow-up means its first row.
LIST_TOOLS = ("search_opportunities", "search_options", "compare", "compare_options")
LAST_LIST = 8
ORG_NUDGE = ("Call get_org_signals now. It lists the companies whose works cite the "
             "researcher's papers, with the number of citing works for each. Reply with the "
             "tool call only.")
# T1: a month with no year ("before March") means its next one after the as-of date. Code
# resolves it and adds the dates to the question the model reads.
MONTH_Q_RE = re.compile(rf"\b(?:before|befor|b4|after|aftr|by|until|untill|untl|till|til|"
                        rf"through|thru|in|from|since|end of)\s+"  # G10: as professors type
                        rf"({MONTHS_RE})\b(?!\.?\s*\d)", re.I)
# G2, G12: "the largest award", "which one pays most": the leads sorted by their stated
# amount, never a comparison of the kept ones, unless the question is about the kept ones.
AMOUNT_Q_RE = re.compile(r"\b(?:largest|biggest|highest|greatest|max(?:imum)?)\b[^.?!]{0,30}"
                         r"\b(?:awards?|ceilings?|amounts?|funding|grants?|leads?|budgets?|money|"
                         r"options?|ones?|scholarships?|fellowships?)\b|\bpays? (?:the )?"
                         r"(?:most|best|highest)\b|\bmost money\b", re.I)
KEPT_Q_RE = re.compile(r"\b(?:kept|shortlist\w*|saved|compar\w*)\b", re.I)
ROUTE_Q = (("F", re.compile(r"\bfellowships?\b", re.I)),
           ("S", re.compile(r"\b(?:scholarships?|samples?)\b", re.I)))
# G19: "my top three leads": compare runs on the brief's top three, not the kept ones.
TOP_Q_RE = re.compile(r"\b(?:top|best|strongest)\s+(?:(\d|one|two|three|four|five)\s+)?"
                      r"(leads?|grants?|opportunit\w+|ones?|matches)\b", re.I)
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
# G9: a short question that asks to start over, whatever polite words come around it.
START_OVER_RE = re.compile(
    r"^\W*(?:(?:ok(?:ay)?|so|hey|um|please|pls|plz|can|could|would|will|we|you|i|let'?s|let|"
    r"us|want|wanna|to|like|just|now|and|maybe)\W+)*(?:start (?:over|again|afresh)|restart|"
    r"reset|clear (?:the )?(?:chat|conversation)|new (?:conversation|chat)|begin again)"
    r"(?:\W+(?:the|this|chat|conversation|please|pls|plz|now|again|thanks|thank you))*\W*$",
    re.I)
START_OVER_ANSWER = ("Starting over: Scout has set aside this conversation's earlier "
                     "questions. Ask your next question.")
# Questions that ask for what the rules refuse, which needs no tool: not nudged. Matched on
# the question, never the answer (T5).
CAPABILITY_RE = re.compile(r"\b(e-?mail|send|web|brows\w*|internet|apply for|chances?|odds|"
                           r"percent\w*|likel\w*|foundations?|private[- ](?:sponsor|document)\w*|"
                           r"unpublished|draft proposal|yes or no)\b", re.I)
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
    nudged: bool = False  # this question's no-tool answer was sent back once (Q5)
    last_list: list[str] = field(default_factory=list)  # F15: ids of the last list shown
    scope: str | None = None  # F1: the search scope this question's words set
    amount_q: bool = False  # G2, G12: this question asks for the largest amount
    force: ToolCall | None = None  # G4: the exact call a nudge named, run by code if refused
    filters: dict = field(default_factory=dict)  # G18: the last search's filters in force
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
                 brief_note: str | Callable[[], str] = "", table: dict | None = None,
                 rules: str | None = None, who: str | None = None,
                 answer_check: Callable[[str, dict], list[str]] | None = None) -> None:
        """`table`, `rules` and `who`: another allowlist, rule set and session line, such
        as the student tools (perch.scout.student_tools). By default the researcher's
        tools, fixed to the session's researcher (SESSION_TOOLS). `answer_check`: one more
        check on the answer, with the records the tools returned, such as the student's
        rule that samples never share a list with public records (Q1)."""
        if private is not None:
            refuse_if_not_local(provider, private)
            log = None  # no Scout log (Q14); the tools' caches are S13's job
        self.provider, self.ctx = provider, ctx
        self.policy: Policy = policy or ("native" if "tools" in provider.capabilities
                                         else "structured")
        self.budget = budget or ScoutBudget()
        self.log = log
        self.private = private is not None
        who = who or ("a researcher with no public profile; the brief was built from the "
                      "documents they added, and build_profile, explain_fit and "
                      "search_opportunities use those documents. If asked to quote a "
                      "document, say only that Scout does not quote private documents. "
                      "Never say you have no access to them, and never ask for an OpenAlex "
                      "ID or an upload" if (ctx.researcher_id or "").startswith("private:")
                      else f"researcher {ctx.full_author_id(None)} (OpenAlex)")
        self.table = table or SESSION_TOOLS
        self.answer_check = answer_check
        # The brief note says which leads are kept. Kept marks change between questions,
        # so a callable note is read again at each question (Q4).
        self.note = brief_note if callable(brief_note) else (lambda: brief_note)
        self.head = (f"{rules or RULES}\n\nSession: {who}, as-of date {ctx.as_of.isoformat()}. "
                     f"Today is {day(ctx.as_of)}.")
        self.system = self.head + self.note()
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
        if START_OVER_RE.match(question):  # G9: on the server too, not only in the page
            return self._start_over(s, question)
        self.system = self.head + self.note() + last_list_line(s)  # what is kept now (Q4)
        s.scope = question_scope(question)
        s.amount_q = bool(AMOUNT_Q_RE.search(question)) and not KEPT_Q_RE.search(question)
        if s.amount_q and s.scope is None:  # G2: "the largest award" is among the brief's
            s.scope = "brief"
        compact(s)  # T4: earlier questions' tool results leave the context
        msgs_from = len(s.messages)
        months = month_dates(question, self.ctx.as_of)
        s.messages.append(Message("user", question + months_line(months, self.ctx.as_of)))
        s.user_numbers |= stated_numbers(question)
        s.user_numbers |= {d.isoformat() for _, first, last in months for d in (first, last)}
        s.user_numbers.add(self.ctx.as_of.isoformat())  # "today", as the session line says
        s.status, s.answer, s.flagged, s.errors, s.turns = "running", None, False, [], 0
        s.nudged, s.force = False, None
        s.exchanges.append({"question": question, "cards_from": len(s.cards),
                            "msgs_from": msgs_from, "answer": None,
                            "flagged": False, "errors": [], "status": "running"})
        if self.log:
            self.log.write({"kind": "question", "session": s.id, "hash": digest(question)})
        return self.advance(s)

    def _start_over(self, s: Session, question: str) -> Session:
        """G9: the conversation so far is set aside and the answer is written by code."""
        s.messages.clear()
        s.last_list, s.scope, s.amount_q, s.filters = [], None, False, {}
        s.status, s.flagged, s.errors, s.turns, s.nudged = "done", False, [], 0, False
        s.answer, s.cited_ids = START_OVER_ANSWER, []
        s.exchanges.append({"question": question, "cards_from": len(s.cards), "msgs_from": 0,
                            "answer": START_OVER_ANSWER, "flagged": False, "errors": [],
                            "status": "done", "answer_by": "code"})
        self._log_answer(s, passed=True, attempts=0)
        return s

    def stop(self, s: Session) -> None:
        """Stop the current question between steps (S28). It may be called from another
        thread while advance() runs: the steps already done stay, the rest are not run. A
        model call already under way finishes; if it brings the answer, the answer stands.
        The flag is cleared when the question ends."""
        s.stop_asked = True

    def advance(self, s: Session) -> Session:
        while True:
            ran = s.pending()
            for c in ran:
                if s.stop_asked:
                    self._not_run(s, c)
                else:
                    self._execute(s, c)
            self._reply_with_results(s)
            if drafted := [c for c in ran if c.tool in DRAFT_TOOLS and c.status == "done"]:
                return self._drafted(s, drafted)
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
            if self._nudge(s, r.text):
                continue
            if s.force and not self._this_question(s):
                # G4: the nudge named the exact call and the model refused again: code makes
                # that one call, shown as a step, and the model answers from its result
                call, s.force = s.force, None
                s.messages.append(Message("assistant", r.text, tool_calls=[call]))
                s.cards.append(Card(call.id, s.turns, call.name, call.arguments))
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

    def _nudge(self, s: Session, text: str) -> bool:
        """Q5: a few questions into a conversation, a small local model starts to answer
        from the conversation alone, and says it has no access to what its tools hold. An
        answer to a question for which no tool ran gets one reminder to call a tool: the
        search tool for a question that filters (R21, T1), get_org_signals for one about
        companies (T5), any tool otherwise, unless the answer cites a record or the
        question asks for what the rules refuse. One per question."""
        if s.nudged or not s.exchanges:
            return False
        question, start = s.exchanges[-1]["question"], s.exchanges[-1]["cards_from"]
        search = next((t for t in SEARCH_TOOLS if t in self.table), None)
        if NO_ACCESS_RE.search(text):  # R6
            nudge = ACCESS_NUDGE
        elif s.cards[start:]:
            return False
        elif ORG_Q_RE.search(question) and not GRANT_Q_RE.search(question) \
                and "get_org_signals" in self.table:
            nudge = ORG_NUDGE
        elif ((stated_numbers(question) or not cited(text))
              and (named := self._named(question)) and "get_record" in self.table):
            nudge = RECORD_NUDGE.format(id=named)  # T7: the record answers it, not memory
        elif search == "search_options" and (codes := CODE_Q_RE.findall(question)):
            words = " ".join(dict.fromkeys(c.upper() for c in codes))
            nudge = (f'Call search_options now with words "{words}". Reply with the tool call '
                     "only.")  # G4
            s.force = ToolCall(secrets.token_hex(4), "search_options", {"words": words})
        elif search == "search_options" and SAMPLES_Q_RE.search(question):
            nudge = ('Call search_options now with route "F": the public fellowships, with no '
                     "sample scholarships. Reply with the tool call only.")  # G4
            s.force = ToolCall(secrets.token_hex(4), "search_options", {"route": "F"})
        elif search == "search_options" and re.search(r"\bsamples?\b", question, re.I):
            nudge = ('Call search_options now with route "S": the sample scholarships, with '
                     "count telling how many. Reply with the tool call only.")  # G23
            s.force = ToolCall(secrets.token_hex(4), "search_options", {"route": "S"})
        elif search and FILTER_Q_RE.search(undated(question)):
            nudge = FILTER_NUDGE.format(tool=search, filters=FILTERS[search])
        elif CAPABILITY_RE.search(question) or (cited(text) and not stated_numbers(question)):
            return False
        else:
            nudge = NUDGE
        s.nudged = True
        s.exchanges[-1]["nudged"] = True  # shown on the exchange, so a check can see it
        s.messages.append(Message("assistant", text))
        s.messages.append(Message("user", nudge))
        return True

    def _with_facts(self, ids: list[str]) -> dict:
        """The checked records, with the lines code wrote about a cited one (T10) added to
        a copy of it, so their numbers back the answer."""
        recs = dict(self.ctx.seen)
        for i in ids:
            r, lines = recs.get(i), self.ctx.facts.get(i)
            if r is None or not lines:
                continue
            f = next((f for f in ("description", "purpose", "abstract", "explanation", "title",
                                  "name")
                      if f in type(r).model_fields), None)
            if f:
                recs[i] = r.model_copy(update={f: f"{getattr(r, f) or ''} {' '.join(lines)}"})
        return recs

    def _named(self, question: str) -> str | None:
        """The id of the one record the question names by its short name, such as "MPS
        Chem" for "MPS Chemistry Research Programs (MPS Chem)", among those seen."""
        from perch.schemas import Opportunity

        hits = []
        for i, r in self.ctx.seen.items():
            if not isinstance(r, Opportunity):
                continue
            names = [n for n in re.findall(r"\(([^()]{3,40})\)", r.title or "")
                     if not re.search(r"clinical|trial|\d", n, re.I)]
            names.append(r.opportunity_number)
            if any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", question, re.I) for n in names):
                hits.append(i)
        return hits[0] if len(hits) == 1 else None

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
        elif c.tool in ONCE_PER_QUESTION and any(
                e.tool == c.tool and e.status == "done" for e in self._this_question(s)):
            c.status, c.detail = "refused", "one explanation per question"  # F6
            c.result = {"error": f"{c.tool} runs once per question. search_options with that "
                        "verdict gives each option's reason in why: answer from it."}
        elif c.tool == "compare_options" and not c.arguments.get("ids") and \
                not KEPT_Q_RE.search(s.exchanges[-1]["question"] if s.exchanges else ""):
            # G23: "what can i apply for" listed only the kept options
            c.status, c.detail = "refused", "not a question about the kept options"
            c.result = {"error": "This question is not about the kept options: call "
                        "search_options, which lists the brief's options in its order by "
                        "Match."}
        elif s.amount_q and c.tool in ("compare", "compare_options") and \
                (search := next((t for t in SEARCH_TOOLS if t in self.table), None)):
            # G2, G12: the largest award is a sorted search, never the kept leads' compare
            c.status, c.detail = "refused", "the largest amount is a sorted search"
            c.result = {"error": f"For the largest award or what pays the most, call {search} "
                        "now: it sorts every option by its stated amount."}
        else:
            self._steer(s, c, entry[0])
            args = {k: v for k, v in c.arguments.items() if v is not None}
            model = {"explain_fit": self.ctx.explainer,
                     "draft_handoff": self.ctx.handoff}.get(c.tool)
            before = (model.tokens, model.usd) if hasattr(model, "tokens") else None
            try:
                c.result = entry[1](self.ctx, **args)
                c.status = "done"
                c.detail = summarise(c.tool, c.result)
                if c.tool in LIST_TOOLS and (ids := list_ids(c.result)):
                    s.last_list = ids[:LAST_LIST]
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

    def _steer(self, s: Session, c: Card, tool: object) -> None:
        """Arguments code sets from the question's words, shown on the card: the scope (F1),
        the amount sort (G2, G12), a past date rolled to its next year (G10) and the brief's
        top N for a top-N comparison (G19)."""
        args, props = dict(c.arguments), tool.parameters["properties"]
        question = s.exchanges[-1]["question"] if s.exchanges else ""
        if c.tool == "search_opportunities" and s.scope and self.ctx.brief_id and \
                "scope" in props:
            args["scope"] = s.scope  # F1
        if s.amount_q and c.tool == "search_opportunities":
            args["sort"] = "award_ceiling"
        if c.tool == "search_opportunities":
            args = carry_filters(args, s.filters, question)
            s.filters = {k: args[k] for kind in KINDS.values() for k in kind if args.get(k)}
        if s.amount_q and c.tool == "search_options":
            route = next((r for r, rx in ROUTE_Q if rx.search(question)), "all")
            args.update(sort="amount", route=route)
        if c.tool == "search_options" and SAMPLES_Q_RE.search(question):
            args["route"] = "F"  # G4: "drop the samples" is the fellowships alone
        for k in ("closes_by", "deadline_before"):  # G10: "befor june" ran 2026-06-01
            if isinstance(v := args.get(k), str) and (d := _iso(v)) and d < self.ctx.as_of:
                while d < self.ctx.as_of:
                    d = d.replace(year=d.year + 1)
                args[k] = d.isoformat()
                s.user_numbers.add(d.isoformat())
        if c.tool == "compare" and not args.get("ids") and self.ctx.brief_id and \
                (m := TOP_Q_RE.search(question)) and not KEPT_Q_RE.search(question):
            from perch.scout.tools import _brief_leads

            n = int(NUMBER_WORDS.get((m.group(1) or "").lower(), m.group(1) or 0)) or \
                (3 if m.group(2).lower().endswith(("s", "es")) else 1)
            if ids := [x.record_id for x in _brief_leads(self.ctx)[:n]]:
                args["ids"] = ids  # G19: "my top three" are the brief's first three
        c.arguments = args

    def _this_question(self, s: Session) -> list[Card]:
        return s.cards[s.exchanges[-1]["cards_from"]:] if s.exchanges else s.cards

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
        if "budget" in why:  # T4: the session's budget, not this question's: start anew
            s.exchanges[-1]["limit"] = True
        s.stop_asked = False
        self._log_answer(s, passed=False, attempts=0)
        return s

    def _drafted(self, s: Session, cards: list[Card]) -> Session:
        """R3, R20: once a draft is made, the answer line is written by code and no model
        prose is asked for. A model asked to sum up the draft retyped it, cut it off, or
        said the records lacked what the draft held. The draft shows in full below."""
        offices = " and ".join(dict.fromkeys(str(c.result["office"]) for c in cards))
        noun = "draft" if cards[0].tool == "draft_handoff" else "note"
        text = (f"The {noun} to {offices} is below. Perch never sends it: edit it, then send "
                "it yourself." if len(cards) == 1 else f"The {noun}s to {offices} are below. "
                "Perch never sends them: edit them, then send them yourself.")
        s.messages.append(Message("assistant", text))
        s.answer, s.cited_ids, s.flagged, s.errors = text, [], False, []
        s.status, s.stop_asked = "done", False
        s.exchanges[-1].update(status="done", answer=text, flagged=False, errors=[],
                               answer_by="code")
        self._log_answer(s, passed=True, attempts=0)
        return s

    def _validate(self, s: Session, text: str) -> list[str]:
        ids = cited(text)
        errs = check(scrub(text, s.user_numbers), ids, self._with_facts(ids)).errors
        if WITHHELD_RE.match(text):  # the history's note, copied as an answer (T10)
            errs.append("the answer is only a note that an answer was withheld: answer the "
                        "question from the tool results")
        if not text.strip():
            errs.append("empty answer")
        question = s.exchanges[-1]["question"] if s.exchanges else ""
        errs += floor_as_ceiling(text, self.ctx.seen)
        errs += floor_only_largest(text, self.ctx.seen)  # G2
        errs += expiry_as_deadline(text, self.ctx.seen)  # G3
        errs += crossed_rows(text, self.ctx.seen)  # G7
        if self.ctx.brief_id and "search_opportunities" in self.table:
            errs += brief_claims(text, self.ctx)
            errs += further_first(text, self.ctx)  # G11
        errs += stray_text(text, question, " ".join(
            evidence(self.ctx.seen[i]).text for i in ids if i in self.ctx.seen))
        if self.answer_check:
            errs += self.answer_check(text, self.ctx.seen)
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
        s.messages.append(Message("assistant", text if not errs else WITHHELD_NOTE))
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


# T2: reasoning that reached the answer: a line that is only "thought" or "thinking", or
# characters from a script that neither the question nor a cited record holds.
STRAY_LINE = re.compile(r"^\W*(?:thought|thinking)\W*$", re.I | re.M)
SCRIPTS = {"CJK": "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff",
           "Cyrillic": "\u0400-\u04ff", "Greek": "\u0370-\u03ff", "Hebrew": "\u0590-\u05ff",
           "Arabic": "\u0600-\u06ff", "Devanagari": "\u0900-\u097f", "Thai": "\u0e00-\u0e7f"}


def stray_text(text: str, question: str, records: str) -> list[str]:
    errs = []
    if STRAY_LINE.search(text):
        errs.append("a line holds only the word thought or thinking: give the answer only")
    for name, chars in SCRIPTS.items():
        rx = re.compile(f"[{chars}]")
        if rx.search(text) and not rx.search(question) and not rx.search(records):
            errs.append(f"{name} characters that are not in the question or a cited record: "
                        "write in English only")
    return errs


# T10: the history's stand-in for a withheld answer. It was "(answer withheld)", which the
# model copied as its next answer; it is now a note, and an answer that is only such a
# note fails the check.
WITHHELD_NOTE = ("[Perch: this answer failed the citation check and was not shown. Answer "
                 "the next question afresh from tool results.]")
WITHHELD_RE = re.compile(r"^\W*(?:\(?answer withheld\)?|\[?Perch: this answer failed)", re.I)
# T6: "the largest ceiling ... $15,000,000" where $15,000,000 is the record's award floor.
CEILING_RE = re.compile(r"\bceilings?\b", re.I)
FLOOR_BEFORE = re.compile(r"\b(?:floors?|minimum|at least|from)\b[^.$]{0,20}$", re.I)
# F16: "from $15,000,000 (award floor)", as compare's Money cell writes it, names the floor
FLOOR_AFTER = re.compile(r"^[^.$]{0,20}\b(?:floors?|minimum)\b", re.I)


def floor_as_ceiling(text: str, seen: dict) -> list[str]:
    """In a sentence about a ceiling, an amount that is a cited record's award floor and
    not its ceiling must be named as a floor."""
    from perch.schemas import Opportunity

    errs = []
    for sent in SENTENCE_RE.split(text):
        if not CEILING_RE.search(sent):
            continue
        recs = [seen[i] for i in cited(sent) if isinstance(seen.get(i), Opportunity)]
        amounts = {float(norm_number(m.group(0))) for m in NUM_RE.finditer(sent)
                   if m.group(0).startswith("$")}
        # a range that gives the record's own ceiling, "$5,000 to $10,000,000", is fine
        recs = [o for o in recs if o.award_ceiling not in amounts]
        for m in NUM_RE.finditer(sent):
            if not m.group(0).startswith("$"):
                continue
            v = float(norm_number(m.group(0)))
            for o in recs:
                if o.award_floor == v and o.award_ceiling != v and \
                        not FLOOR_BEFORE.search(sent[:m.start()]) and \
                        not FLOOR_AFTER.search(sent[m.end():]):
                    errs.append(f"{m.group(0)} is the award floor of [{short_id(o)}], not its "
                                "ceiling: name it as a floor, or leave it out")
    return errs


# G2: "The lead with the largest award ceiling is Expeditions [26-525] ... from $15,000,000":
# a record that states only a floor is never the largest award or given a ceiling.
LARGEST_RE = re.compile(r"\b(?:ceilings?|largest|biggest|highest|greatest|pays? (?:the )?most|"
                        r"most money)\b", re.I)
NO_CEILING_RE = re.compile(r"\bno (?:award |stated )?ceiling\b|\bnot (?:state|give|list)\w* "
                           r"(?:a|an|any|its) (?:award )?ceiling\b|\bceiling (?:is )?not "
                           r"(?:stated|given|in the record)\b|\bonly (?:an? |its )?(?:award )?"
                           r"floor\b|\bwithout a ceiling\b", re.I)


def _opp(seen: dict, i: str) -> object:
    return seen.get(i) or seen.get(f"grants_gov:{i}")


def floor_only_largest(text: str, seen: dict) -> list[str]:
    from perch.schemas import Opportunity

    errs = []
    for sent in SENTENCE_RE.split(text):
        if not LARGEST_RE.search(sent) or NO_CEILING_RE.search(sent):
            continue
        for i in cited(sent):
            o = _opp(seen, i)
            if isinstance(o, Opportunity) and o.award_floor and not o.award_ceiling:
                errs.append(f"[{short_id(o)}] states no award ceiling, only a floor: never call "
                            "it the largest award or give it a ceiling")
    return list(dict.fromkeys(errs))


# G3: "The deadline for the ... (Parent F31) is 7 May 2028": that date is when the
# announcement expires. A sentence, or a table cell under a Deadline label, may not call
# it a deadline; "no deadline in the record" may stand.
DUE_RE = re.compile(r"\b(?:deadlines?|due|closes?|closing|close date)\b", re.I)
NO_DUE_RE = re.compile(r"\b(?:no|not|without|none|neither|nor)\b[^.;]{0,40}\b(?:deadlines?|due "
                       r"dates?|close dates?)\b|\b(?:deadlines?|due dates?)\b[^.;]{0,24}\bnot "
                       r"(?:stated|given|listed|in the record)\b", re.I)


def expiry_as_deadline(text: str, seen: dict) -> list[str]:
    from perch.datefmt import day, expires_only
    from perch.schemas import Opportunity

    def expiring(ids: list[str]) -> list[Opportunity]:
        return [o for i in ids if isinstance(o := _opp(seen, i), Opportunity)
                and expires_only(o)]

    errs = []
    for sent in SENTENCE_RE.split(text):
        if sent.lstrip().startswith("|"):
            continue  # tables below
        for o in expiring(cited(sent)):
            if DUE_RE.search(sent) and not NO_DUE_RE.search(sent) and day(o.close_date) in sent:
                errs.append(f"{day(o.close_date)} is when the announcement [{short_id(o)}] "
                            "expires, not a deadline: say it expires then, and that the record "
                            "states no deadline")
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")]
            for ln in text.splitlines() if ln.lstrip().startswith("|")]
    for o in expiring(cited(" ".join(" ".join(r) for r in rows))):
        when = day(o.close_date)
        for r in rows:
            for j, cell in enumerate(r):
                labels = r[0] + " " + (rows[0][j] if j < len(rows[0]) else "")
                if when in cell and DUE_RE.search(labels) and "xpir" not in cell + labels:
                    errs.append(f"the table puts {when}, when [{short_id(o)}] expires, under a "
                                "deadline label: write \"Expires " + when + "\" in that cell")
    return list(dict.fromkeys(errs))


# G7: "…Senior Fellowship (Parent F33): … [PA-25-422]", the F31's id. A line that names a
# short name in parentheses that only one checked record's title holds must cite that record.
SHORT_NAME_RE = re.compile(r"\(([^()]{2,40})\)")


def crossed_rows(text: str, seen: dict) -> list[str]:
    from perch.schemas import Opportunity, Scholarship

    owners: dict[str, set[str]] = {}
    for i, r in seen.items():  # grants and options only: "(United Kingdom)" names no record
        if not isinstance(r, Opportunity | Scholarship):
            continue
        for n in SHORT_NAME_RE.findall(getattr(r, "title", None) or getattr(r, "name", None)
                                       or ""):
            if not re.search(r"clinical|trial", n, re.I):  # NIH's shared suffixes
                owners.setdefault(n.lower(), set()).add(i.removeprefix("grants_gov:"))
    errs = []
    for line in SENTENCE_RE.split(text):
        ids = {i.removeprefix("grants_gov:") for i in cited(line)}
        if not ids:
            continue
        for n in SHORT_NAME_RE.findall(line):
            own = owners.get(n.lower(), set())
            if len(own) == 1 and not own & ids:
                errs.append(f"the line naming ({n}) cites [{', '.join(sorted(ids))}], but "
                            f"({n}) is [{next(iter(own))}]: cite each record's own id")
    return list(dict.fromkeys(errs))


# G11: "The lead with the largest award ceiling is Mid-scale … [24-598]", a record not on the
# brief, named first with no mark. The first grant an answer names, if it is not on the
# brief, must be called a further lead (F10), unless the answer already said none of the
# brief's leads fits.
FURTHER_RE = re.compile(r"\bfurther\b|\bnot (?:on|in|from) (?:your|the) brief\b|\b(?:outside|"
                        r"beyond|off) (?:your|the) brief\b|\b(?:none|no)\b[^.]{0,60}\bbrief\b",
                        re.I)


def further_first(text: str, ctx: ScoutContext) -> list[str]:
    from perch.schemas import Opportunity
    from perch.scout.tools import _brief_leads

    mine = {x.record_id.removeprefix("grants_gov:") for x in _brief_leads(ctx)}
    before = ""
    for sent in SENTENCE_RE.split(text):
        before += " " + sent
        ids = [i for i in cited(sent) if isinstance(_opp(ctx.seen, i), Opportunity)]
        if not ids:
            continue
        if any(i.removeprefix("grants_gov:") in mine for i in ids) or FURTHER_RE.search(before):
            return []
        return [f"[{ids[0]}] is not on the user's brief and is the first grant the answer "
                "names: call it a further lead, not on the brief, with its match band"]
    return []


# F10: "The NIH grant on your brief with the highest ceiling is [X]" where X is not on it.
ON_BRIEF = re.compile(r"(?<!not )\b(?:on|in|from) your brief\b", re.I)


def brief_claims(text: str, ctx: ScoutContext) -> list[str]:
    """A sentence that says its cited grant is on the user's brief, when none it cites is."""
    from perch.scout.tools import _brief_leads

    mine = {x.record_id for x in _brief_leads(ctx)}
    mine |= {i.removeprefix("grants_gov:") for i in mine}
    errs = []
    for sent in SENTENCE_RE.split(text):
        ids = [i for i in cited(sent) if not re.fullmatch(r"W\d+", i)]
        if ON_BRIEF.search(sent) and ids and not any(i in mine for i in ids):
            errs.append(f"[{ids[0]}] is not on the user's brief: call it a further lead")
    return errs


# G18: kinds of filter. A follow-up keeps the earlier search's filters unless it names a
# new value of the same kind, which replaces that kind; "all", "any" or "everything" clears.
KINDS = {"agency": ("agencies", "exclude_agencies"), "date": ("closes_by", "closes_after"),
         "amount": ("min_amount", "max_amount"), "code": ("activity_codes",),
         "words": ("keywords", "exclude_keywords")}
CLEAR_RE = {"agency": r"agenc\w*", "date": r"dates?|deadlines?|close dates?",
            "amount": r"amounts?|sizes?|ceilings?", "code": r"codes?|activity codes?|mechanisms?",
            "words": r"words?|keywords?|topics?"}
CLEAR_ALL_RE = re.compile(r"\b(?:everything|all (?:of )?(?:my |the )?(?:leads|grants|opportunities|"
                          r"of them)|any (?:lead|grant))\b", re.I)


def carry_filters(args: dict, before: dict, question: str) -> dict:
    """The filters of a follow-up search, by kind (G18): a kind the model sends unchanged
    from the last search stays; one with a new value keeps only what is new; one the
    question clears ("any agency", "everything") goes."""
    out = dict(args)
    for kind, keys in KINDS.items():
        now = {k: out[k] for k in keys if out.get(k)}
        old = {k: before[k] for k in keys if before.get(k)}
        cleared = CLEAR_ALL_RE.search(question) or re.search(
            rf"\b(?:all|any|every)\s+(?:{CLEAR_RE[kind]})\b", question, re.I)
        new = {k: v for k, v in now.items() if old.get(k) != v}
        if cleared:
            for k in keys:
                out.pop(k, None)
        elif new and len(new) < len(now):  # a new value: the carried ones of its kind go
            for k in now:
                if k not in new:
                    out.pop(k)
    return out


def _iso(v: str) -> date | None:
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def undated(text: str) -> str:
    """The text without its full dates: "15 December 2026" is a date, not a filter word."""
    for rx, _ in DATE_PATTERNS:
        text = rx.sub(" ", text)
    return text


def month_dates(question: str, as_of: date) -> list[tuple[str, date, date]]:
    """T1: each month the question names with no year, as its next one after the as-of
    date: (the word, its first day, its last day)."""
    out = []
    for m in MONTH_Q_RE.finditer(question):
        word = m.group(1)
        n = _month(word)
        year = as_of.year + (n <= as_of.month)
        last = (date(year + (n == 12), n % 12 + 1, 1) - timedelta(days=1))
        if all(w != word for w, _, _ in out):
            out.append((word, date(year, n, 1), last))
    return out


def months_line(months: list[tuple[str, date, date]], as_of: date) -> str:
    """The resolved months, added to the question the model reads (not the one shown)."""
    if not months:
        return ""
    parts = [f'"{w}" means {day(a)} ({a.isoformat()}) to {day(b)} ({b.isoformat()})'
             for w, a, b in months]
    return (f"\n\n(Perch: today is {day(as_of)}. With no year, " + "; ".join(parts)
            + ". \"Before\" a month means closes_by its first day.)")


def list_ids(result: dict) -> list[str]:
    """The record ids of a list a tool returned, in its order (F15)."""
    out: list[str] = []
    for key in ("leads", "rows", "options", "fellowships", "sample_scholarships"):
        for x in result.get(key) or []:
            if isinstance(x, dict) and (i := x.get("id") or x.get("record")):
                out.append(str(i))
    return out


def last_list_line(s: Session) -> str:
    if not s.last_list:
        return ""
    return ("\nThe last list you gave, in order: " + ", ".join(f"[{i}]" for i in s.last_list)
            + ". In a follow-up, \"the first one\" or \"that one\" means this list's.")


ANSWER_CHARS = 300  # an older answer, as later questions see it (T4)


def compact(s: Session) -> None:
    """T4: before a new question, the tool results of earlier questions are cut to the
    step's result line and the records it named. Answers older than the last question's
    are cut to their first 300 characters, and the reminders and rejected drafts of
    earlier questions go. The questions, the steps asked for and the answers' openings
    stay, and every record stays in the session's checked set, so a question costs about
    the same however long the conversation, and each model call stays well inside the
    local model's context."""
    cards = {c.id: c for c in s.cards}
    for m in s.messages:
        if not m.tool_results or all(r.content.startswith(COMPACT) for r in m.tool_results):
            continue
        m.tool_results = [ToolResult(r.call_id, r.name, r.content if r.content.startswith(
            COMPACT) else json.dumps({"earlier_result": True, **_brief_of(
                cards.get(r.call_id))}), r.is_error) for r in m.tool_results]
    starts = [x.get("msgs_from") for x in s.exchanges]
    if None in starts or len(starts) < 2:
        return
    out: list[Message] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(s.messages)
        part = s.messages[start:end]
        if i == len(starts) - 1:  # the last question stays whole
            s.exchanges[i]["msgs_from"] = len(out)
            out += part
            continue
        last = max((j for j, m in enumerate(part) if m.role == "assistant"
                    and not m.tool_calls), default=None)
        keep = [m for j, m in enumerate(part) if j == 0 or m.tool_calls or m.tool_results
                or j == last]
        if last is not None and len(part[last].content) > ANSWER_CHARS:
            short = part[last].content[:ANSWER_CHARS].rsplit(" ", 1)[0]
            keep[-1] = Message("assistant", short + " … (shortened)")
        s.exchanges[i]["msgs_from"] = len(out)
        out += keep
    s.messages[:] = out


COMPACT = '{"earlier_result": true'


def _brief_of(c: Card | None) -> dict:
    from perch.scout.hub import record_ids

    if c is None:
        return {"note": "an earlier step; call the tool again for its result"}
    return {"result": c.detail or c.status, "records": record_ids(c.result),
            "note": "An earlier step, shortened. Call the tool again for its fields."}


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
        if result.get("scope") == "brief":
            return (f"{n} of your brief's leads; {result['removed_by_filters']} removed by "
                    "the filters")
        return (f"{n} lead{'' if n == 1 else 's'}; {result['removed_by_filters']} removed by "
                "the eligibility rules and filters")
    if tool == "build_profile":
        return f"{result['papers']} papers in {len(result['threads'])} threads"
    if tool == "list_awards":
        return f"{len(result['awards'])} public awards"
    if tool == "resolve_author":
        return f"{len(result['candidates'])} candidates"
    if tool == "explain_fit":
        if result.get("status") == "withheld":
            return "withheld"
        # The card's Match, never the model's own fit number beside it (U6).
        m = match_text(result.get("match_on_card"))
        return f"explained; the card says {m}" if m else "explained and checked"
    if tool == "get_record":
        return f"{result['kind']} {result['record']['id']}"
    if tool == "compare":
        if not result["rows"] and "kept" in result:
            return "nothing kept; the top leads offered"
        return f"{len(result['rows'])} leads side by side"
    if tool == "draft_handoff":
        return (f"draft to {result['office']}, not sent"
                + ("; the model's opening was withheld" if result["opening_withheld"] else ""))
    if tool == "search_options":
        n = result["count"]
        words = result.get("words_used")  # the words searched, in the read-as block (R7)
        return (f"{n} option{'' if n == 1 else 's'} match"
                + (f" any of: {', '.join(words)}" if words else ""))
    if tool in ("check_option", "explain_verdict"):
        return f"{result['verdict']}" + (", sample record" if result.get("sample") else "")
    if tool == "read_cv":
        return f"{len(result['fields'])} fields read by rule"
    if tool == "compare_options":
        return f"{result['count']} options side by side"
    if tool == "draft_note":
        return f"note to {result['office']}, written by code, not sent"
    return "done"

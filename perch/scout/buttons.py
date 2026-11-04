"""Fixed questions as buttons, answered by code (Phase 8, task 1).

Top leads, deadlines, compare and the hand-off were the questions Scout answered well from a
fixed set. They are now button intents. Each answer is written by code from record fields
(standing rule 3): the same words the cards use, no model, no gate, no cost. A line cites the
record it comes from in square brackets, like every other Scout sentence.

`answer(intent, data)` returns the message body; the caller stores it as a Scout message.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from perch.compare import compare, rows_json
from perch.schemas import Lead, Opportunity, Record, Scholarship
from perch.scout.read_tools import NOT_STATED, ScoutData, facts

TOP_N = 3

BUTTONS: tuple[dict[str, str], ...] = (
    {"intent": "top_leads", "label": "Top leads"},
    {"intent": "deadlines", "label": "Deadlines"},
    {"intent": "compare", "label": "Compare kept leads"},
    {"intent": "handoff", "label": "Hand-off to a Temple office"},
)
INTENTS = tuple(b["intent"] for b in BUTTONS)


def buttons(audience: str) -> list[dict[str, str]]:  # noqa: ARG001 - same set for both sides
    return [dict(b) for b in BUTTONS]


class IntentError(Exception):
    """The intent cannot be answered; the message is a fixed sentence."""


def _leads(data: ScoutData) -> list[tuple[Lead, Record]]:
    got = data.brief()
    if got is None:
        raise IntentError("There is no finished brief yet. Build a brief first, then these "
                          "buttons have something to read.")
    _, leads = got
    from perch.scout.read_tools import ReadTools

    tools = ReadTools(data)
    out = []
    for x in sorted((x for x in leads if x.status != "dismissed" and x.route != "B"),
                    key=lambda x: x.rank or 0):
        rec = tools._get(x.record_id)  # noqa: SLF001 - the same public-record lookup
        if rec is not None:
            out.append((x, rec))
    return out


def _line(f: dict[str, Any], n: int | None = None) -> str:
    parts = [str(f["title"])]
    if f.get("sponsor"):
        parts.append(str(f["sponsor"]))
    dl = str(f.get("deadline") or NOT_STATED)
    parts.append(dl if not dl[:1].isdigit() else f"closes {dl}")
    if f.get("amount") and f["amount"] != NOT_STATED:
        parts.append(str(f["amount"]))
    elif "amount" in f:
        parts.append("amount not stated in the record")
    mark = " (SAMPLE record, not real)" if f.get("sample") else ""
    head = f"{n}. " if n else "- "
    return f"{head}{', '.join(parts)}{mark} [{f['id']}]"


def _result(intent: str, lines: list[str], ids: list[str], **extra: object) -> dict[str, Any]:
    return {"kind": "intent", "intent": intent, "text": "\n".join(lines), "records": ids,
            "flagged": False, "unsupported": [], "general": None, **extra}


def top_leads(data: ScoutData) -> dict[str, Any]:
    rows = _leads(data)[:TOP_N]
    if not rows:
        raise IntentError("The brief has no leads to show.")
    fs = [facts(rec, data.as_of) for _, rec in rows]
    lines = ["The strongest leads in your brief, in its own order:",
             *[_line(f, i) for i, f in enumerate(fs, 1)]]
    return _result("top_leads", lines, [f["id"] for f in fs])


def _sort_key(rec: Record, as_of: date) -> date | None:
    from perch.datefmt import no_deadline

    if isinstance(rec, Opportunity):
        return None if no_deadline(rec, as_of) else rec.close_date
    if isinstance(rec, Scholarship):
        return rec.deadline
    return None


def deadlines(data: ScoutData) -> dict[str, Any]:
    rows = _leads(data)
    if not rows:
        raise IntentError("The brief has no leads to show.")
    dated = sorted(((d, x, rec) for x, rec in rows
                    if (d := _sort_key(rec, data.as_of)) is not None
                    and d >= data.as_of), key=lambda t: (t[0], t[1].rank or 0))
    other = [(x, rec) for x, rec in rows if all(rec is not r for _, _, r in dated)]
    lines = ["Deadlines from the records, soonest first:"]
    ids: list[str] = []
    for i, (_, _, rec) in enumerate(dated, 1):
        f = facts(rec, data.as_of)
        lines.append(_line(f, i))
        ids.append(f["id"])
    if other:
        lines.append("No dated deadline in the record:")
        for _, rec in other:
            f = facts(rec, data.as_of)
            lines.append(_line(f))
            ids.append(f["id"])
    return _result("deadlines", lines, ids)


def compare_kept(data: ScoutData) -> dict[str, Any]:
    got = data.brief()
    if got is None:
        raise IntentError("There is no finished brief yet.")
    b, leads = got
    kept = [(x, rec) for x, rec in _leads(data) if x.status == "kept"]
    if not kept:
        raise IntentError("You have kept no leads yet. Keep two or more leads on the brief, "
                          "then compare them here.")
    fs = [facts(rec, data.as_of) for _, rec in kept]
    lines = ["Your kept leads, side by side:", *[_line(f, i) for i, f in enumerate(fs, 1)]]
    table = None
    if data.audience != "student":  # researcher briefs have the compare table
        with data.repo() as r:
            table = rows_json(compare(b, leads, r))
    return _result("compare", lines, [f["id"] for f in fs], table=table)


def handoff(data: ScoutData, draft: Callable[[], dict[str, Any] | None] | None
            ) -> dict[str, Any]:
    """The note to the right Temple office, written by code from the kept leads. The model
    drafted hand-off (`handoff` job) stays a separate button on the brief."""
    if draft is None:
        raise IntentError("A hand-off needs a brief.")
    d = draft()
    if d is None:
        raise IntentError("Keep at least one lead on the brief first, then ask for the "
                          "hand-off.")
    office = d["office"]["name"] if isinstance(d.get("office"), dict) else d.get("office")
    text = (f"A hand-off note to {office}, written from your kept leads. Nothing is sent: "
            "copy it and send it yourself.")
    return _result("handoff", [text], list(dict.fromkeys(d.get("record_ids", []))), draft=d)


def answer(intent: str, data: ScoutData,
           draft: Callable[[], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    """The message body for one button. Raises IntentError with a fixed sentence."""
    if intent == "top_leads":
        return top_leads(data)
    if intent == "deadlines":
        return deadlines(data)
    if intent == "compare":
        return compare_kept(data)
    if intent == "handoff":
        return handoff(data, draft)
    raise IntentError("Unknown button.")


__all__ = ["BUTTONS", "INTENTS", "IntentError", "answer", "buttons"]

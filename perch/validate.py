"""Citation validator, layer 1 (deterministic). Standing rules 3 and 5.

A model output passes when:
  1. every cited id is one of the records the model was given, and
  2. every date in its text equals a date field of a cited record, and
  3. every other number (dollar amounts, counts, years, percentages) appears in a
     cited record's text or numeric fields, and
  4. every link, and the words click and visit, appear in a cited record (S30).
Identifiers such as R01, PAR-25-371 or W2741809807 are not numbers. A failed output
is regenerated once with the errors fed back; a second failure is flagged and the
lead is shown without its explanation.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from perch.schemas import Record

MONTHS = ("january february march april may june july august september october november "
          "december").split()
MONTH_RE = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy"),
    (re.compile(rf"\b({MONTH_RE})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I), "Mdy"),
    (re.compile(rf"\b(\d{{1,2}})\s+({MONTH_RE})\s+(\d{{4}})\b", re.I), "dMy"),
]
# Identifier-like tokens that carry digits but are not quantities.
ID_RE = re.compile(r"\b(?:[A-Z]{1,4}-\d{2}-\d{3}|[A-Z]{1,3}\d{1,2}[A-Z]?\d*|[WA]\d{6,}|"
                   r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]|[A-Z]+\d+[A-Z]*-\d+|[A-Z]+-\d+)\b")
NUM_RE = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?")
# Prompt injection in public record text (review S16): a model that follows it is most
# useful to an attacker when it adds a link or tells the reader to act. A link, or the
# words click and visit, must come from a cited record.
URL_RE = re.compile(r"(?:\bhttps?://|\bwww\.)[^\s\])>\"']+", re.I)
ACTION_RE = re.compile(r"\b(click\w*|visit\w*)\b", re.I)


def _month(s: str) -> int:
    s = s.lower().rstrip(".")[:3]
    return next(i for i, m in enumerate(MONTHS, 1) if m.startswith(s))


def find_dates(text: str) -> list[tuple[str, date | None]]:
    """(matched text, parsed date or None if impossible), in order."""
    out = []
    for rx, kind in DATE_PATTERNS:
        for m in rx.finditer(text):
            g = m.groups()
            try:
                if kind == "ymd":
                    d = date(int(g[0]), int(g[1]), int(g[2]))
                elif kind == "mdy":
                    d = date(int(g[2]), int(g[0]), int(g[1]))
                elif kind == "Mdy":
                    d = date(int(g[2]), _month(g[0]), int(g[1]))
                else:
                    d = date(int(g[2]), _month(g[1]), int(g[0]))
            except (ValueError, StopIteration):
                d = None
            out.append((m.group(0), d))
    return out


def norm_number(token: str) -> str:
    t = token.replace("$", "").replace(",", "").rstrip("%")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t


def find_numbers(text: str) -> list[str]:
    """Numbers in text, skipping dates and identifiers, normalised (no $ , %)."""
    scrubbed = text
    for rx, _ in DATE_PATTERNS:
        scrubbed = rx.sub(" ", scrubbed)
    scrubbed = ID_RE.sub(" ", scrubbed)
    return [norm_number(m.group(0)) for m in NUM_RE.finditer(scrubbed)]


@dataclass
class Evidence:
    """What a record lets an output say: its text, its dates, its numbers."""

    text: str
    dates: set[date] = field(default_factory=set)
    numbers: set[str] = field(default_factory=set)


def evidence(r: Record) -> Evidence:
    parts: list[str] = []
    dates: set[date] = set()
    nums: set[str] = set()
    for name, value in r.model_dump().items():
        if name in ("fetched_at", "source_url", "id"):
            continue
        if isinstance(value, datetime):
            dates.add(value.date())
        elif isinstance(value, date):
            dates.add(value)
        elif isinstance(value, bool):
            continue
        elif isinstance(value, int | float):
            nums.add(norm_number(f"{value:f}" if isinstance(value, float) else str(value)))
        elif isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts += [v if isinstance(v, str) else str(v.get("display_name", ""))
                      for v in value if isinstance(v, str | dict)]
    text = " ".join(parts)
    dates |= {d for _, d in find_dates(text) if d}
    nums |= set(find_numbers(text))
    nums |= {str(d.year) for d in dates}  # "since 2023" is supported by a 2023 date
    return Evidence(text, dates, nums)


@dataclass
class Check:
    ok: bool
    errors: list[str]


def check(text: str, cited_ids: list[str], records: dict[str, Record]) -> Check:
    """Layer 1. `records` is everything the model was given, by id."""
    errors = [f"cited id {c!r} was not in the input" for c in cited_ids if c not in records]
    cited = [evidence(records[c]) for c in cited_ids if c in records]
    allowed_dates = set().union(*(e.dates for e in cited)) if cited else set()
    allowed_nums = set().union(*(e.numbers for e in cited)) if cited else set()
    for raw, d in find_dates(text):
        if d is None:
            errors.append(f"date {raw!r} is not a real date")
        elif d not in allowed_dates:
            errors.append(f"date {raw!r} is not in any cited record")
    for n in find_numbers(text):
        if n not in allowed_nums:
            errors.append(f"number {n!r} is not in any cited record")
    recs = [records[c] for c in cited_ids if c in records]
    seen = " ".join([e.text for e in cited] + [r.source_url or "" for r in recs]
                    + [r.id for r in recs])
    for u in dict.fromkeys(m.group(0).rstrip(".,;:") for m in URL_RE.finditer(text)):
        if u.lower() not in seen.lower():
            errors.append(f"link {u!r} is not in any cited record")
    for w in dict.fromkeys(m.group(1).lower() for m in ACTION_RE.finditer(text)):
        if not re.search(rf"\b{re.escape(w)}\b", seen, re.I):
            errors.append(f"the word {w!r} is not in any cited record: describe the "
                          "records, do not direct the reader")
    return Check(not errors, errors)


@dataclass
class Validated[T]:
    value: T | None  # None when flagged
    attempts: int
    flagged: bool
    errors: list[str]  # from the last failed attempt


def generate_validated[T](generate: Callable[[list[str]], T],
                          validate: Callable[[T], Check],
                          on_unparseable: Callable[[list[str]], None] | None = None
                          ) -> Validated[T]:
    """Run generate(feedback); on failure regenerate once with the errors; then flag.

    An unparseable output is a failed attempt; `on_unparseable` lets the caller log it
    so it counts in the rejection rate."""
    feedback: list[str] = []
    for attempt in (1, 2):
        try:
            value = generate(feedback)
        except ValueError as e:
            feedback = [f"output could not be parsed: {e}"]
            if on_unparseable:
                on_unparseable(feedback)
            continue
        c = validate(value)
        if c.ok:
            return Validated(value, attempt, False, [])
        feedback = c.errors
    return Validated(None, 2, True, feedback)

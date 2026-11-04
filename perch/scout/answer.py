"""The grounding contract for Scout's open answers (Phase 8, task 4), checked by code.

An answer has two parts. The grounded part is everything above a line that says
`General advice:`; the general part is everything below it.

Grounded part:
  * every sentence cites at least one id in square brackets, and every id was returned by a
    tool this turn (`seen`); a question, a heading, and a sentence that only says nothing was
    found are the exceptions;
  * Layer 1 (perch/validate.py) runs per sentence against the records that sentence cites: every
    number, date and link must be in one of them;
  * Layer 2 (MiniCheck, perch/grounding.py) flags sentences the cited records do not support.
    It flags, it does not regenerate (SPEC section 8).

General part: no citation, no number or number word, no date or month, no eligibility word, and
no name of an award (a record title or number, an id such as R01, or a phrase such as
"Fulbright Scholarship"). It is shown under a "General advice" label.

A failed answer is regenerated once with the errors fed back; a second failure is shown flagged
with the failing sentences removed (standing rule 5). Pure functions, no model call: the turn
loop in perch/scout/turn.py calls them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from perch import validate
from perch.grounding import Grounder
from perch.schemas import Record
from perch.scout.read_tools import facts
from perch.scout.texts import GENERAL_LABEL

CITE_RE = re.compile(r"\[([^\[\]]+)\]")
GENERAL_RE = re.compile(r"^[ \t>*#_-]*general advice\s*:?[ \t*_]*$", re.I | re.M)
GENERAL_INLINE_RE = re.compile(r"^[ \t>*#_-]*general advice\s*:\s*(\S.*)$", re.I | re.M)
SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
PREFIX_RE = re.compile(r"^(\s*(?:[-*•]|\d{1,2}[.)])\s+)")
# A sentence that only says nothing was found, or that Scout cannot help, needs no record.
ABSENT_RE = re.compile(
    r"\b(?:no|not|none|neither|nor|n't|cannot|can't|could not|couldn't|did not|didn't)\b"
    r".*\b(?:record|records|result|results|match|matches|found|find|information|help|"
    r"answer|read|access)\b", re.I)
DECLINE_RE = re.compile(r"\b(?:can(?:not|'t)|unable to|not able to|only (?:help|answer))\b.{0,80}"
                        r"\b(?:help|answer|assist|with that|funding|scholarship)", re.I)
CONTACT_RE = re.compile(r"^\[contact removed\]$", re.I)
NUMBER_WORDS = re.compile(
    r"\b(?:hundreds?|thousands?|millions?|billions?|percent|dozens?|twice|thrice|"
    r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:-\w+)?|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)\b", re.I)
MONTH_NAMES = re.compile(r"\b(?:january|february|march|april|june|july|august|september|october|"
                         r"november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\b\.?",
                         re.I)
ELIGIBILITY = re.compile(
    r"\b(?:eligib\w*|deadlines?|due dates?|closes?|closing|citizen\w*|gpa|grade point|"
    r"residen\w+|must be|required to be|open to|restricted to|applicants must)\b", re.I)
AWARD_PHRASE = re.compile(
    r"\b((?:[A-Z][\w'’&.-]*\s+){1,4})(?:Fellowship|Scholarship|Award|Grant|Prize|Program)s?\b")
GENERIC_NAME_WORDS = {"research", "grant", "grants", "fellowship", "fellowships", "scholarship",
                      "scholarships", "award", "awards", "funding", "program", "programs",
                      "application", "applications", "opportunity", "opportunities"}


@dataclass
class Sentence:
    text: str  # as written, with its citations
    cites: list[str] = field(default_factory=list)  # canonical ids
    errors: list[str] = field(default_factory=list)  # layer 1 and citation errors
    support: float | None = None  # layer 2
    supported: bool | None = None  # None: not checked (no cited record, or no grounder)


@dataclass
class Line:
    prefix: str
    sentences: list[Sentence]


@dataclass
class Graded:
    lines: list[Line]
    general: str | None
    general_errors: list[str]

    @property
    def sentences(self) -> list[Sentence]:
        return [s for ln in self.lines for s in ln.sentences]

    @property
    def errors(self) -> list[str]:
        return [e for s in self.sentences for e in s.errors] + self.general_errors

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def cited_ids(self) -> list[str]:
        return list(dict.fromkeys(c for s in self.sentences for c in s.cites))

    @property
    def unsupported(self) -> list[str]:
        return [s.text for s in self.sentences if s.supported is False]


# --- parsing ---

def split_general(text: str) -> tuple[str, str | None]:
    """(grounded part, general part or None). The label is a line of its own, or opens a line."""
    t = text.strip()
    m = GENERAL_RE.search(t)
    if m:
        return t[:m.start()].strip(), t[m.end():].strip() or None
    m = GENERAL_INLINE_RE.search(t)
    if m:
        return t[:m.start()].strip(), m.group(1).strip() + t[m.end():]
    return t, None


def resolve(cite: str, seen: dict[str, Record]) -> str | None:
    """The seen id a cited string names, or None. Case and a dropped prefix are forgiven."""
    c = cite.strip()
    if c in seen:
        return c
    low = {k.lower(): k for k in seen}
    if c.lower() in low:
        return low[c.lower()]
    tails = [k for k in seen if k.lower().endswith((":" + c.lower(), "/" + c.lower()))]
    return tails[0] if len(tails) == 1 else None


def cites_in(text: str) -> list[str]:
    """Raw cited strings, from every bracket that looks like an id (no spaces)."""
    out: list[str] = []
    for m in CITE_RE.finditer(text):
        for part in re.split(r"\s*[;,]\s+|;", m.group(1)):
            p = part.strip()
            if p and " " not in p and not CONTACT_RE.match(f"[{p}]"):
                out.append(p)
    return out


def strip_cites(text: str) -> str:
    def keep(m: re.Match) -> str:
        return " " if cites_in(m.group(0)) else m.group(0)

    return re.sub(r"\s+", " ", CITE_RE.sub(keep, text)).strip()


def parse(grounded: str) -> list[Line]:
    lines: list[Line] = []
    for raw in grounded.splitlines():
        if not raw.strip():
            continue
        m = PREFIX_RE.match(raw)
        prefix = m.group(1) if m else ""
        body = raw[len(prefix):].strip()
        parts = [p for p in SPLIT_RE.split(body) if p.strip()]
        merged: list[str] = []
        for p in parts:  # a citation that follows its full stop belongs to that sentence
            if merged and not strip_cites(p).strip(" .,;"):
                merged[-1] += " " + p
            else:
                merged.append(p)
        lines.append(Line(prefix, [Sentence(p.strip()) for p in merged]))
    return lines


# --- checks ---

def document_for(rec: Record, as_of: date) -> str:
    """What MiniCheck reads for one record: the card's own fields, then the record's text."""
    f = facts(rec, as_of)
    head = "\n".join(f"{k}: {v}" for k, v in f.items() if v not in (None, "", []))
    return head + "\n" + validate.evidence(rec).text


def check_sentence(s: Sentence, seen: dict[str, Record]) -> None:
    raw = cites_in(s.text)
    ids: list[str] = []
    for c in raw:
        rid = resolve(c, seen)
        if rid is None:
            s.errors.append(f"cited id {c!r} was not returned by a tool this turn")
        elif rid not in ids:
            ids.append(rid)
    s.cites = ids
    body = strip_cites(s.text)
    heading = s.text.rstrip().endswith(":") and len(body.split()) <= 6
    exempt = not raw and bool(s.text.rstrip().endswith("?") or ABSENT_RE.search(body)
                              or heading)
    if not raw and not exempt:
        s.errors.append(f"sentence has no citation: {body[:80]!r}")
    if not (exempt and not ids):
        for e in validate.check(body, ids, seen).errors:
            if not e.startswith("cited id"):  # unresolved ids were reported above
                s.errors.append(e)
    elif validate.find_numbers(body) or validate.find_dates(body):
        s.errors.append("a number or date with no cited record")


def check_general(text: str, names: set[str], seen: dict[str, Record]) -> list[str]:
    """Why a General advice part is not allowed, or []. No award names, numbers, dates,
    eligibility words or citations."""
    errs: list[str] = []
    if CITE_RE.search(text):
        errs.append("General advice may not cite")
    if validate.find_numbers(text) or validate.find_dates(text) or NUMBER_WORDS.search(text):
        errs.append("General advice may not state a number or date")
    if MONTH_NAMES.search(text):
        errs.append("General advice may not name a month")
    if ELIGIBILITY.search(text):
        errs.append("General advice may not state an eligibility rule or a deadline")
    if validate.ID_RE.search(text):
        errs.append("General advice may not name an award by its code")
    low = text.lower()
    hit = [n for n in names | {title_key(r) for r in seen.values()}
           if n and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", low)]
    if hit:
        errs.append("General advice may not name an award: " + ", ".join(sorted(hit)[:3]))
    for m in AWARD_PHRASE.finditer(text):
        lead = m.group(1).split()
        starts = m.start() == 0 or text[:m.start()].rstrip().endswith((".", "!", "?", ":", "\n"))
        if len(lead) == 1 and (starts or lead[0].lower() in GENERIC_NAME_WORDS):
            continue
        if all(w.lower().strip(".'") in GENERIC_NAME_WORDS | {"the", "a", "an", "your", "this",
                                                               "that", "any", "each", "most",
                                                               "many", "some"} for w in lead):
            continue
        errs.append("General advice may not name an award: " + m.group(0).strip())
        break
    return errs


def title_key(rec: Record) -> str:
    t = str(facts(rec, date.today()).get("title") or "").lower().strip()
    return t if len(t) >= 12 and t not in GENERIC_NAME_WORDS else ""


def name_index(records: list[Record]) -> set[str]:
    """Lower-case award titles and numbers worth blocking from General advice."""
    out: set[str] = set()
    for r in records:
        k = title_key(r)
        if k:
            out.add(k)
        num = getattr(r, "opportunity_number", None)
        if num and len(num) >= 6:
            out.add(num.lower())
    return out


def grade(text: str, seen: dict[str, Record], names: set[str], as_of: date,
          grounder: Grounder | None = None) -> Graded:
    """Parse and check one answer. Layer 2 runs only when layer 1 and the citation rules pass
    for the sentence, so MiniCheck is not spent on a sentence that will be regenerated."""
    grounded, general = split_general(text)
    lines = parse(grounded)
    g = Graded(lines, general, check_general(general, names, seen) if general else [])
    for s in g.sentences:
        check_sentence(s, seen)
    if grounder is not None and g.ok:
        for s in g.sentences:
            if not s.cites:
                continue
            doc = "\n\n".join(document_for(seen[c], as_of) for c in s.cites)
            c = grounder.check(doc, strip_cites(s.text))
            if c:
                s.support, s.supported = c[0].support, all(x.supported for x in c)
    return g


def render(g: Graded, *, drop_failed: bool) -> tuple[str, str | None]:
    """(grounded text, general text). With drop_failed, a sentence with an error is left out and
    a failed General advice part is removed."""
    out: list[str] = []
    for ln in g.lines:
        keep = [s.text for s in ln.sentences if not (drop_failed and s.errors)]
        if keep:
            out.append(ln.prefix + " ".join(keep))
    general = g.general if g.general and not (drop_failed and g.general_errors) else None
    return "\n".join(out), general


def feedback(g: Graded) -> str:
    """The message that goes back to the model for the one regeneration."""
    errs = list(dict.fromkeys(g.errors))[:8]
    return ("Your answer did not pass Perch's checks:\n- " + "\n- ".join(errs)
            + "\nWrite the whole answer again. Cite every sentence with an id returned by a "
            "tool, copy numbers and dates exactly from the tool results, and keep "
            f"'{GENERAL_LABEL}' free of award names, numbers, dates and eligibility rules.")

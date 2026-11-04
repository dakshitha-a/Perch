"""The grounding contract for Scout's open answers (Phase 8, task 4), checked by code.

An answer has two parts. The grounded part is everything above a line that says
`General advice:`; the general part is everything below it.

Grounded part:
  * every sentence that states a fact cites at least one id in square brackets, and every id
    was returned by a tool this turn (`seen`). A citation may sit before or after the full
    stop; one written after the full stop belongs to the sentence before it;
  * the exceptions, which need no citation: a question, a short heading, a sentence that only
    says nothing was found, and a help sentence: an offer or an instruction about using Perch
    or Scout ("Tell me which one to read in full."). A help sentence passes the same content
    checks as General advice, so it cannot carry a number, a date, a link, an award's name or
    an eligibility rule;
  * Layer 1 (perch/validate.py) runs per sentence against the records that sentence cites: every
    number, date and link must be in one of them;
  * Layer 2 (MiniCheck, perch/grounding.py) flags sentences the cited records do not support.
    It flags, it does not regenerate (SPEC section 8).

General part, checked per sentence: no citation, no link, no number or number word, no date or
month, no eligibility rule (citizenship, residency, a grade point average, "applicants must"),
and no name of an award (a record title or number, an id such as R01, or a phrase such as
"Fulbright Scholarship"). Ordinary words such as "deadline", "eligible" or "closing paragraph"
are allowed, and so is list numbering ("1."). It is shown under a "General advice" label, and it
also carries how-to-use-Perch help.

A failed answer is regenerated once with the errors fed back; a second failure is shown flagged
with the failing sentences removed (standing rule 5). Every removed sentence carries a
machine-readable reason (`REASONS`), so a bench can count which rule removed what. Pure
functions, no model call: the turn loop in perch/scout/turn.py calls them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from perch import validate
from perch.grounding import Grounder
from perch.schemas import Record
from perch.scout.read_tools import facts
from perch.scout.texts import GENERAL_LABEL

CITE_RE = re.compile(r"\[([^\[\]]+)\]")
LEAD_CITES_RE = re.compile(r"^\s*((?:\[[^\[\]]+\][\s.,;:]*)+)")
PAREN_CITE_RE = re.compile(r"\(([A-Za-z_]+:[^()\s]+)\)")
GENERAL_RE = re.compile(r"^[ \t>*#_-]*general advice\s*:?[ \t*_]*$", re.I | re.M)
GENERAL_INLINE_RE = re.compile(r"^[ \t>*#_-]*general advice\s*:[ \t*_]*(\S.*)$", re.I | re.M)
SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
PREFIX_RE = re.compile(r"^(\s*(?:[-*•]|\d{1,2}[.)])\s+)")
# A split after one of these is not the end of a sentence ("the U.S. National Science
# Foundation", "e.g. a poster", "4 Nov. 2026").
ABBREV_RE = re.compile(
    r"(?:\b(?:[A-Za-z]\.){2,}|\b[A-Z]\.|\b(?:e\.g|i\.e|Dr|Mr|Mrs|Ms|Prof|St|No|vs|Inc|Jr|Sr|"
    r"approx|Dept|Univ|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.)[*_)\"'”’]*$")
# A sentence that only says nothing was found, or that Scout cannot help, needs no record.
ABSENT_RE = re.compile(
    r"\b(?:no|not|none|neither|nor|nothing|n't|cannot|can't|could not|couldn't|did not|"
    r"didn't)\b.*\b(?:record|records|result|results|match|matches|found|find|information|help|"
    r"answer|read|access|leads?|brief|saved|entries|entry|cv|items?|ids?)\b", re.I)
# An offer or an instruction about using Perch or Scout: help text, not a record fact.
ABSENT_WORDS = 20  # a "nothing found" sentence is short; a long one may be hiding a claim
HELP_VERBS = (r"(?:read|list|compare|search|show|check|open|look|tell|help|draft|find|answer|"
              r"keep|dismiss|restore|save|browse|build|press|click|pick|choose|ask|use|start|"
              r"add|upload|go|sign|type)")
# An offer or an instruction about using Perch or Scout: help text, not a record fact. An offer
# must name an action ("I can compare it with your CV"), so "I can see this record fits you"
# and "You can expect a strong fit" are not help and still need a citation.
HELP_RE = re.compile(
    r"^[\W_]*(?:(?:please\s+)?(?:ask|tell me|let me know|check|open|read|try|use|pick|choose|"
    r"click|press|tap|select|keep|save|dismiss|restore|compare|start|go to|look at|look for|"
    r"see|type|sign in|build|say|reply|send me|share|add|upload|paste|search|browse)\b|"
    r"(?:(?:i|scout|you)\s+(?:can|could|will|would)|i(?:'|’)ll)"
    r"(?:\s+(?:then|also|now|first|next|still|just))?\s+" + HELP_VERBS + r"\b|"
    r"i\s+searched\b|would you like\b|do you want\b|want me to\b)", re.I)
DECLINE_RE = re.compile(r"\b(?:can(?:not|'t)|unable to|not able to|only (?:help|answer))\b.{0,80}"
                        r"\b(?:help|answer|assist|with that|funding|scholarship)", re.I)
CONTACT_RE = re.compile(r"^\[contact removed\]$", re.I)
NUMBER_WORDS = re.compile(
    r"\b(?:hundreds?|thousands?|millions?|billions?|percent|dozens?|"
    r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:-\w+)?|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)\b", re.I)
MONTH_NAMES = re.compile(r"\b(?:january|february|march|april|june|july|august|september|october|"
                         r"november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\b\.?",
                         re.I)
# Words that state who may apply. "deadline", "eligible" and "closing" are ordinary words in
# advice ("ask well before the deadline", "a closing paragraph") and are not on this list.
ELIGIBILITY = re.compile(
    r"\b(?:citizen\w*|gpa|grade point|residen(?:t|ts|cy|cies)\b|permanent resident\w*|"
    r"green card|visa status|required to be|open only to|only open to|restricted to|"
    r"applicants must|(?:not\s+|in)eligible|eligible for|qualif(?:y|ies|ied)|"
    r"meets? the requirements?)\b", re.I)
AWARD_PHRASE = re.compile(
    r"\b((?:[A-Z][\w'’&.-]*\s+){1,4})(?:Fellowship|Scholarship|Award|Grant|Prize|Program)s?\b")
AWARD_WORD = re.compile(r"\b(?:scholarships?|fellowships?|awards?|grants?|prizes?|programs?|"
                        r"scholars|fellows)\b")
GENERIC_NAME_WORDS = {"research", "grant", "grants", "fellowship", "fellowships", "scholarship",
                      "scholarships", "award", "awards", "funding", "program", "programs",
                      "application", "applications", "opportunity", "opportunities"}
HEADING_WORDS = 12
# The ids a read tool returns for an empty result (perch/scout/read_tools.py `_empty`).
PLACEHOLDER_IDS = frozenset({"user:brief", "user:saved", "user:entries", "user:cv"})

# Every reason a sentence can be removed for. The first group is the grounded part, the second
# the General advice part (and help sentences, which use the same checks).
REASONS = (
    "no_citation", "cites_unreturned_id", "layer1_number", "layer1_date", "layer1_bad_date",
    "layer1_link", "layer1_action_word", "layer1_other", "uncited_number_or_date",
    "uncited_link", "sample_mix", "placeholder_only",
    "general_cite", "general_number", "general_date", "general_month", "general_link",
    "general_eligibility_word", "general_award_code", "general_named_award")


@dataclass
class Sentence:
    text: str  # as written, with its citations
    cites: list[str] = field(default_factory=list)  # canonical ids
    errors: list[str] = field(default_factory=list)  # messages for the regeneration
    reasons: list[tuple[str, str]] = field(default_factory=list)  # (REASONS code, detail)
    support: float | None = None  # layer 2
    supported: bool | None = None  # None: not checked (no cited record, or no grounder)
    kind: str = "grounded"  # grounded, question, heading, absent, help, general

    def fail(self, code: str, message: str, detail: str = "") -> None:
        self.errors.append(message)
        self.reasons.append((code, detail))


@dataclass
class Line:
    prefix: str
    sentences: list[Sentence]


@dataclass
class Graded:
    lines: list[Line]
    general_lines: list[Line] = field(default_factory=list)

    @property
    def sentences(self) -> list[Sentence]:
        return [s for ln in self.lines for s in ln.sentences]

    @property
    def general_sentences(self) -> list[Sentence]:
        return [s for ln in self.general_lines for s in ln.sentences]

    @property
    def general(self) -> str | None:
        return _join(self.general_lines, drop_failed=False) or None

    @property
    def general_errors(self) -> list[str]:
        return [e for s in self.general_sentences for e in s.errors]

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

    def removed(self, *, detail: bool = False) -> list[dict[str, Any]]:
        """One row per failed rule per sentence: {part, sentence_index, reason}. No sentence
        text, so it may be stored with the message; `detail` adds the failing token (a number,
        a date, an id) for the bench only."""
        out: list[dict[str, Any]] = []
        for part, ss in (("grounded", self.sentences), ("general", self.general_sentences)):
            for i, s in enumerate(ss):
                for code, d in dict.fromkeys(s.reasons):
                    row: dict[str, Any] = {"part": part, "sentence_index": i, "reason": code}
                    if detail and d:
                        row["detail"] = d
                    out.append(row)
        return out

    @property
    def n_removed(self) -> int:
        return sum(bool(s.errors) for s in self.sentences + self.general_sentences)


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
    c = cite.strip().strip(".,;:")
    if c in seen:
        return c
    low = {k.lower(): k for k in seen}
    if c.lower() in low:
        return low[c.lower()]
    tails = [k for k in seen if k.lower().endswith((":" + c.lower(), "/" + c.lower()))]
    return tails[0] if len(tails) == 1 else None


def cites_in(text: str) -> list[str]:
    """Raw cited strings, from every bracket that looks like an id (no spaces). Several ids in
    one bracket may be split by commas or semicolons, with or without a space."""
    out: list[str] = []
    for m in CITE_RE.finditer(text):
        if CONTACT_RE.match(m.group(0)):
            continue
        for part in re.split(r"\s*[;,]\s*", m.group(1)):
            p = part.strip()
            if p and " " not in p:
                out.append(p)
    return out


def strip_cites(text: str) -> str:
    def keep(m: re.Match) -> str:
        return " " if cites_in(m.group(0)) else m.group(0)

    return re.sub(r"\s+", " ", CITE_RE.sub(keep, text)).strip()


def normalise_cites(text: str, seen: dict[str, Record]) -> str:
    """A citation written in round brackets, "(grants_gov:23-500)", is read as one in square
    brackets, but only when it names an id a tool returned this turn."""
    return PAREN_CITE_RE.sub(lambda m: f"[{m.group(1)}]" if resolve(m.group(1), seen)
                             else m.group(0), text)


def split_sentences(body: str) -> list[str]:
    parts = [p for p in SPLIT_RE.split(body) if p.strip()]
    merged: list[str] = []
    for p in parts:
        if merged and ABBREV_RE.search(merged[-1]):  # "the U.S. National Science Foundation"
            merged[-1] += " " + p
            continue
        lead = LEAD_CITES_RE.match(p)
        if merged and lead and cites_in(lead.group(1)):
            # "A closes 4 Nov 2026. [id] B states no amount. [id]": the bracket after a full
            # stop cites the sentence before it.
            merged[-1] += " " + lead.group(1).strip()
            p = p[lead.end():]
            if not strip_cites(p).strip(" .,;"):
                if p.strip():
                    merged[-1] += " " + p.strip()
                continue
        merged.append(p)
    return [m.strip() for m in merged if m.strip()]


def parse(grounded: str) -> list[Line]:
    lines: list[Line] = []
    for raw in grounded.splitlines():
        if not raw.strip():
            continue
        m = PREFIX_RE.match(raw)
        prefix = m.group(1) if m else ""
        body = raw[len(prefix):].strip()
        lines.append(Line(prefix, [Sentence(p) for p in split_sentences(body)]))
    return lines


# --- checks ---

def document_for(rec: Record, as_of: date) -> str:
    """What MiniCheck reads for one record: the card's own fields, then the record's text."""
    f = facts(rec, as_of)
    head = "\n".join(f"{k}: {v}" for k, v in f.items() if v not in (None, "", []))
    return head + "\n" + validate.evidence(rec).text


def _token(message: str) -> str:
    m = re.search(r"'([^']*)'", message)
    return m.group(1) if m else ""


def _layer1_code(message: str) -> str:
    if message.startswith("date"):
        return "layer1_bad_date" if "not a real date" in message else "layer1_date"
    if message.startswith("number"):
        return "layer1_number"
    if message.startswith("link"):
        return "layer1_link"
    if message.startswith("the word"):
        return "layer1_action_word"
    return "layer1_other"


def _plain(text: str) -> str:
    return re.sub(r"[*_`#]+", "", text).strip()


def is_heading(s: Sentence, line: Line) -> bool:
    """A short line that labels what follows: it ends with a colon, is bold all through, or is a
    markdown heading. It states nothing, so it needs no citation."""
    if len(line.sentences) != 1:
        return False
    t = s.text.strip()
    body = _plain(strip_cites(t))
    if not body or len(body.split()) > HEADING_WORDS:
        return False
    bold = bool(re.fullmatch(r"\*\*[^*]+\*\*:?", strip_cites(t)) or
                re.fullmatch(r"__[^_]+__:?", strip_cites(t)))
    return t.rstrip("*_ ").endswith(":") or bold or t.startswith("#")


def check_sentence(s: Sentence, seen: dict[str, Record], names: set[str] | None = None,
                   *, heading: bool = False) -> None:
    raw = cites_in(s.text)
    ids: list[str] = []
    for c in raw:
        rid = resolve(c, seen)
        if rid is None:
            s.fail("cites_unreturned_id",
                   f"cited id {c!r} was not returned by a tool this turn", c)
        elif rid not in ids:
            ids.append(rid)
    s.cites = ids
    body = strip_cites(s.text)
    if raw:
        for e in validate.check(body, ids, seen).errors:
            if not e.startswith("cited id"):  # unresolved ids were reported above
                s.fail(_layer1_code(e), e, _token(e))
        # An empty-result placeholder ("user:saved", "user:brief") holds only "nothing found",
        # so alone it can back only a sentence that says so (S45 S4).
        if ids and all(i in PLACEHOLDER_IDS for i in ids) and not (
                len(body.split()) <= ABSENT_WORDS and ABSENT_RE.search(body)):
            s.fail("placeholder_only", "an empty-result id such as [user:saved] supports only a "
                   "sentence that says nothing was found; do not cite it for a claim", ids[0])
        return
    # No citation: allowed only for a sentence that states no record fact.
    if heading:
        s.kind = "heading"
    elif s.text.rstrip("*_ ").endswith("?"):
        s.kind = "question"
    elif HELP_RE.search(body):
        s.kind = "help"
    elif len(body.split()) <= ABSENT_WORDS and ABSENT_RE.search(body):
        s.kind = "absent"
    else:
        s.fail("no_citation", f"sentence has no citation: {body[:80]!r}")
        return
    # An uncited sentence of any exempt kind passes the same content checks as General
    # advice, so a heading, a question or a "nothing found" sentence cannot carry an award's
    # name or an eligibility rule (S45 S3).
    for code, msg, d in general_reasons(body, names or set(), seen):
        s.fail(code, f"a {s.kind} sentence with no citation {msg}", d)
    if s.kind == "help":
        return
    if validate.find_numbers(body) or validate.find_dates(body):
        s.fail("uncited_number_or_date", "a number or date with no cited record")
    if validate.URL_RE.search(body):
        s.fail("uncited_link", "a link with no cited record")


def mixed_blocks(g: Graded, seen: dict[str, Record]) -> None:
    """A block (a heading or prose line with the bullets under it) may not cite a SYNTHETIC sample
    together with a public record (standing rule 11). The error goes on the block's last
    sentence, so that sentence is the one removed if the answer is shown flagged."""
    block: list[Sentence] = []

    def close() -> None:
        ids = {c for s in block for c in s.cites}
        smp = {c for c in ids if seen[c].source == "synthetic"}
        if smp and smp != ids:
            block[-1].fail("sample_mix", "a sample record and a public record are in the same "
                           "list or sentence: list them apart")
        block.clear()

    for ln in g.lines:
        heading = len(ln.sentences) == 1 and ln.sentences[0].text.rstrip().endswith(":")
        if (heading or not ln.prefix) and block:  # a bullet joins the block above it
            close()
        block.extend(ln.sentences)
    if block:
        close()


def _named(text: str, start: int, end: int) -> bool:
    """For a title with no award word in it: it names the award only when it is written as a
    name, with a capital after its first letter, or a capital first letter that does not open a
    sentence. "applied mathematics" in plain prose is a field; "Applied Mathematics"
    mid-sentence is a title. A title with an award word is matched in any case."""
    span = text[start:end]
    caps = [i for i, ch in enumerate(span) if ch.isupper()]
    if any(i > 0 for i in caps):
        return True
    opens = start == 0 or text[:start].rstrip().endswith((".", "!", "?", ":", "\n")) or \
        not text[:start].strip(" *_-•")
    return bool(caps) and not opens


def general_reasons(text: str, names: set[str], seen: dict[str, Record]
                    ) -> list[tuple[str, str, str]]:
    """(REASONS code, message, detail) for every rule a General advice sentence breaks."""
    out: list[tuple[str, str, str]] = []
    if cites_in(text):
        out.append(("general_cite", "may not cite", ""))
    if validate.URL_RE.search(text):
        out.append(("general_link", "may not give a link", ""))
    nums = validate.find_numbers(text)
    if nums or NUMBER_WORDS.search(text):
        out.append(("general_number", "may not state a number or date",
                    nums[0] if nums else NUMBER_WORDS.search(text).group(0)))  # type: ignore[union-attr]
    if validate.find_dates(text):
        out.append(("general_date", "may not state a number or date", ""))
    if MONTH_NAMES.search(text):
        out.append(("general_month", "may not name a month",
                    MONTH_NAMES.search(text).group(0)))  # type: ignore[union-attr]
    if m := ELIGIBILITY.search(text):
        out.append(("general_eligibility_word",
                    "may not state an eligibility rule or a deadline", m.group(0)))
    if m := validate.ID_RE.search(text):
        out.append(("general_award_code", "may not name an award by its code", m.group(0)))
    low = text.lower()
    hit = []
    for n in sorted(names | {title_key(r) for r in seen.values()}):
        if not n:
            continue
        typed = bool(AWARD_WORD.search(n))  # "gilman scholarship" is a name in any case
        for m in re.finditer(rf"(?<!\w){re.escape(n)}(?!\w)", low):
            if typed or _named(text, m.start(), m.end()):
                hit.append(n)
                break
    if hit:
        out.append(("general_named_award", "may not name an award: " + ", ".join(hit[:3]),
                    hit[0]))
    for m in AWARD_PHRASE.finditer(text):
        lead = m.group(1).split()
        starts = m.start() == 0 or text[:m.start()].rstrip().endswith((".", "!", "?", ":", "\n"))
        if len(lead) == 1 and (starts or lead[0].lower() in GENERIC_NAME_WORDS):
            continue
        if all(w.lower().strip(".'") in GENERIC_NAME_WORDS | {"the", "a", "an", "your", "this",
                                                               "that", "any", "each", "most",
                                                               "many", "some"} for w in lead):
            continue
        out.append(("general_named_award", "may not name an award: " + m.group(0).strip(),
                    m.group(0).strip()))
        break
    return out


def check_general(text: str, names: set[str], seen: dict[str, Record]) -> list[str]:
    """Why a General advice part is not allowed, or []. List numbering ("1.") is not a number."""
    errs: list[str] = []
    for ln in parse(text):
        for s in ln.sentences:
            errs += ["General advice " + msg for _, msg, _ in general_reasons(s.text, names, seen)]
    return list(dict.fromkeys(errs))


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
    grounded, general = split_general(normalise_cites(text, seen))
    g = Graded(parse(grounded), parse(general) if general else [])
    for ln in g.lines:
        for s in ln.sentences:
            check_sentence(s, seen, names, heading=is_heading(s, ln))
    for s in g.general_sentences:
        s.kind = "general"
        for code, msg, d in general_reasons(s.text, names, seen):
            s.fail(code, "General advice " + msg, d)
    mixed_blocks(g, seen)
    if grounder is not None and g.ok:
        for s in g.sentences:
            if not s.cites:
                continue
            doc = "\n\n".join(document_for(seen[c], as_of) for c in s.cites)
            c = grounder.check(doc, strip_cites(s.text))
            if c:
                s.support, s.supported = c[0].support, all(x.supported for x in c)
    return g


def _join(lines: list[Line], *, drop_failed: bool) -> str:
    out: list[str] = []
    for ln in lines:
        keep = [s.text for s in ln.sentences if not (drop_failed and s.errors)]
        if keep:
            out.append(ln.prefix + " ".join(keep))
    return "\n".join(out)


def render(g: Graded, *, drop_failed: bool) -> tuple[str, str | None]:
    """(grounded text, general text). With drop_failed, a sentence with an error is left out,
    in the General advice part as in the grounded part."""
    return _join(g.lines, drop_failed=drop_failed), (
        _join(g.general_lines, drop_failed=drop_failed) or None)


def feedback(g: Graded) -> str:
    """The message that goes back to the model for the one regeneration."""
    errs = list(dict.fromkeys(g.errors))[:8]
    return ("Your answer did not pass Perch's checks:\n- " + "\n- ".join(errs)
            + "\nWrite the whole answer again. A sentence that states a fact about a record or "
            "about the user's brief, CV, entries or saved items ends with the id it comes from, "
            "in square brackets, copied from a tool result, such as [grants_gov:23-500]. Copy "
            "numbers and dates exactly from the tool results; leave out any number or date a "
            "cited record does not hold. Advice and how-to-use-Perch help go last, under "
            f"'{GENERAL_LABEL}', with no citation, no award names, no numbers or dates and no "
            "eligibility rules.")

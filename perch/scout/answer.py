"""The grounding contract for Scout's open answers (Phase 8, task 4), checked by code.

An answer has two parts. The grounded part is everything above a line that says
`General advice:`; the general part is everything below it.

Grounded part:
  * every sentence that states a fact cites at least one id in square brackets, and every id
    was returned by a tool this turn (`seen`). A citation may sit before or after the full
    stop; one written after the full stop belongs to the sentence before it;
  * the exceptions, which need no citation, are an allow-list of shapes (S45 fix round 3; the
    shapes live in perch/scout/texts.py): a heading that is one of the fixed section names, or
    a label made only of words from the records cited under it; a question that starts with an
    offer stem ("Would you like", "Which"); a "nothing found" sentence that is one of the fixed
    templates; and a help sentence: an offer or an instruction about using Perch or Scout
    ("Tell me which one to read in full."). A sentence citing only an empty-result id
    ([user:saved]) must be one of the fixed empty-state templates. Anything else is removed with
    a reason code. Help sentences, offers and record labels pass the same content checks as
    General advice, so they cannot carry a number, a date, a link, an award's name or an
    eligibility rule;
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
from perch.grounding import THRESHOLD, Grounder
from perch.schemas import Opportunity, Record, Scholarship
from perch.scout.read_tools import NOT_STATED, ReadTools, facts
from perch.scout.texts import (
    ABSENT_TEMPLATES,
    EMPTY_TEMPLATES,
    GENERAL_LABEL,
    HEADING_EXAMPLES,
    OFFER_STEMS,
    STRUCTURAL_HEADINGS,
    STRUCTURAL_LEADINS,
)

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
# The shape of a "nothing found" sentence. It needs no record only when it is one of the fixed
# templates (texts.ABSENT_TEMPLATES); this pattern only names the reason when it is not.
ABSENT_RE = re.compile(
    r"\b(?:no|not|none|neither|nor|nothing|n't|cannot|can't|could not|couldn't|did not|"
    r"didn't)\b.*\b(?:record|records|result|results|match|matches|found|find|information|help|"
    r"answer|read|access|leads?|brief|saved|entries|entry|cv|items?|ids?)\b", re.I)
ABSENT_WORDS = 20  # a "nothing found" sentence is short; a long one may be hiding a claim
BOLD_NUMBER_RE = re.compile(r"(?:\*\*|__)\d{1,2}[.)]")  # a list number inside bold marks
BOLD_LINE_RE = re.compile(r"(?:\*\*[^*]+\*\*|__[^_]+__):?")
BOLD_LIST_RE = re.compile(r"^(\s*(?:\*\*|__))\d{1,2}[.)]\s+")
def _alts(patterns: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns))


# The allow-list (S45 fix round 3), each matched in full against `norm_exempt` text.
STRUCTURAL_RE = _alts(STRUCTURAL_HEADINGS)
LEADIN_RE = _alts(STRUCTURAL_LEADINS)
EMPTY_TEMPLATE_RE = _alts(EMPTY_TEMPLATES)
ABSENT_TEMPLATE_RE = _alts(ABSENT_TEMPLATES)
OFFER_RE = re.compile(r"^(?:" + "|".join(re.escape(s) for s in OFFER_STEMS) + r")\b")
# An offer has no need to grade the user or a record, so these words are not allowed in one.
OFFER_FIT_RE = re.compile(r"\b(?:great|ideal\w*|perfect\w*|natural\w*|strong\w*|good|better|best|"
                          r"eligib\w*|welcom\w*|suit\w*|fits?|fitting|match\w*|qualif\w*|"
                          r"shoo|accept\w*|top)\b")
# A record's label (route ii) names the record, not the reader.
PERSON_RE = re.compile(r"\b(?:you|your|yours|yourself|you're|youre|i|i'm|im|me|my|we|our|us)\b")
STOPWORDS = frozenset(
    "a an the and or of for to in on at by with from into about as vs versus is are be this "
    "that these those its it their s".split())
WORD_RE = re.compile(r"[a-z0-9]+")


# A claim riding on an allowed shape (S45 final re-check): an offer, a how-to lead-in or a help
# line that goes on to give a reason or a verdict ("..., since you rank first", "Open it, you
# are its ideal applicant"). The shape must end at its verb phrase.
CLAIM_TAIL_RE = re.compile(
    r"[,;:]\s*(?:you|your|it(?:'s|’s| is)|this(?:'s|’s| is)|that(?:'s|’s| is)|no record|they)\b"
    r"|\b(?:since|because|given)\b|\bas (?:you|it|this|your)\b"
    r"|\byou(?:'re|’re|'d be|’d be|'ll|’ll| are| were| will| would be| meet| qualify| rank"
    r"| fit| match)\b|\b(?:likely|certain|ideal|lock|number[- ]one|first on)\b", re.I)


def norm_exempt(text: str) -> str:
    """A sentence as the allow-list reads it: citations, markdown, a list marker and closing
    punctuation removed; lower case; curly quotes straight; "doesn't" written "does not"."""
    t = strip_cites(text).replace("\u2019", "'").replace("\u2018", "'")
    t = re.sub(r"[*_`#>]+", " ", t)
    t = re.sub(r"^\s*(?:[-•]|\d{1,2}[.)])\s+", "", t).lower()
    t = t.replace("can't", "cannot").replace("won't", "will not")
    t = re.sub(r"\b(\w+)n't\b", r"\1 not", t)
    return re.sub(r"\s+", " ", t).strip(" :.!?;,")


def _label_words_in(n: str, block: str) -> bool:
    """Route ii for a heading: every content word is a word of a record cited under it."""
    words = [w for w in WORD_RE.findall(n) if w not in STOPWORDS]
    if not block or not words or PERSON_RE.search(n):
        return False
    vocab = set(WORD_RE.findall(block))
    return all(w in vocab or (w.endswith("s") and w[:-1] in vocab) or w + "s" in vocab
               for w in words)


# The system prompt's own disclaimer (texts.SCOUT_SYSTEM): the exact sentence needs no record.
DISCLAIMER_RE = re.compile(
    r"^[\W_]*Perch (?:does not|doesn['’]t) confirm personal eligibility\.?[\W_]*$", re.I)
DISCLAIMER_TAIL_RE = re.compile(
    r"^[\W_]*Perch (?:does not|doesn['’]t) confirm personal eligibility[,;]\s+(?:so\s+)?"
    r"((?:check|ask|confirm|contact|read|verify)\b[^\[\]]*?)[.!]?[\W_]*$", re.I)
HELP_VERBS = (r"(?:read|list|compare|search|show|check|open|look|tell|help|draft|find|answer|"
              r"keep|dismiss|restore|save|browse|build|press|click|pick|choose|ask|use|start|"
              r"add|upload|go|sign|type)")
# An offer or an instruction about using Perch or Scout: help text, not a record fact. An offer
# must name an action ("I can compare it with your CV"), so "I can see this record fits you"
# and "You can expect a strong fit" are not help and still need a citation.
HELP_RE = re.compile(
    r"^[\W_]*(?:or\s+)?(?:(?:please\s+)?(?:ask|tell me|let me know|check|open|read|try|use|pick|"
    r"choose|click|press|tap|select|keep|save|dismiss|restore|compare|start|go to|look at|look for|"
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
# Wider words for a sentence with no real record behind it (uncited, a heading, a question, a
# "nothing found" sentence, or one citing only an empty-result id): any word that states or
# implies who may apply or how well the user fits. Not used on a sentence citing a real record,
# which may say "It is open to juniors [id]" (S45 fix round 2).
FIT_WORDS = re.compile(
    r"\b(?:eligib\w*|requires?|required|may apply|can apply|could apply|open to|welcomed?|"
    r"(?:strong|good|great|best|perfect|natural|poor|weak) (?:fit|match|candidate)|"
    r"you(?:['’]ll| will| would)(?: likely| probably)? (?:win|get it|be selected|be awarded)|"
    r"(?:likely|likelihood|chance|chances) (?:to |of )?(?:win|winning|success)|"
    r"qualif\w*|(?:stops?|prevents?|blocks?|bars?) you from applying|from applying)\b", re.I)
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


def is_placeholder(rid: str, seen: dict[str, Record]) -> bool:
    """An empty-result id. [user:brief] is one only when the brief was empty: a brief with
    leads is a code-written record of its own (read_tools.brief_summary, S49 Q2)."""
    if rid not in PLACEHOLDER_IDS:
        return False
    return not (rid == "user:brief" and getattr(seen.get(rid), "title", "") == "Your brief")

# Every reason a sentence can be removed for. The first group is the grounded part, the second
# the General advice part (and help sentences, which use the same checks).
REASONS = (
    "no_citation", "cites_unreturned_id", "layer1_number", "layer1_date", "layer1_bad_date",
    "layer1_link", "layer1_action_word", "layer1_other", "uncited_number_or_date",
    "uncited_link", "sample_mix", "placeholder_only",
    "general_cite", "general_number", "general_date", "general_month", "general_link",
    "general_eligibility_word", "general_award_code", "general_named_award", "uncited_fit_word",
    "heading_not_structural", "question_not_offer", "absent_not_template", "help_with_claim")


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

    out = re.sub(r"\s+", " ", CITE_RE.sub(keep, text)).strip()
    return re.sub(r" ([.,;:!?])(?=\s|$)", r"\1", out)


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
        if merged and BOLD_NUMBER_RE.fullmatch(merged[-1].strip()):  # "**1. SBE ...**" (Q5)
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
    extra = ""
    if isinstance(rec, Scholarship):
        # MiniCheck's passage only; validate.evidence() is unchanged, so no new number or date
        # counts as supported by layer 1 (S45 fix round 2).
        if rec.eligibility.notes:
            extra += "\nEligibility: " + rec.eligibility.notes
        if rec.application_requirements and rec.application_requirements.items():
            extra += "\nApplication requirements: " + ", ".join(
                rec.application_requirements.items()) + "."
    return head + "\n" + validate.evidence(rec).text + extra


# --- claims MiniCheck cannot score, checked by code against what the tools returned ---

ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
RANK_NUM_RE = re.compile(
    r"\b(?:ranked|ranks|rank)\s*(?:number\s*|no\.?\s*|#)?(\d{1,2})\b|#(\d{1,2})\b", re.I)
RANK_WORD_RE = re.compile(
    r"\b(?:(top)[- ]?(?:ranked|lead|rank|pick|choice)|(?:your|the)\s+"
    r"(first|second|third|fourth|fifth)\s+(?:lead|pick|choice|result|match)|"
    r"ranked\s+(first|second|third|fourth|fifth)|(first|second|third|fourth|fifth)[- ]ranked)\b",
    re.I)
EMPTY_BRIEF_RE = re.compile(r"\b(?:no leads|(?:brief|it) is empty|has nothing|holds nothing)\b",
                            re.I)
KEPT_RE = re.compile(r"\b(kept|shortlist(?:ed)?)\b", re.I)
SAVED_RE = re.compile(r"\bsaved\b", re.I)
NEG_RE = re.compile(r"\b(?:not|never|nothing|none|no)\b|n['’]t\b", re.I)
ABSENCE_RE = re.compile(
    r"\b(?:gives?|lists?|states?|has|have|provides?|shows?|includes?|mentions?|specif(?:y|ies)|"
    r"says?|holds?|carries|contains?)\s+no\s+(?:\w+\s+){0,2}?(deadline|close date|amount|"
    r"award size|requirements?)\b|"
    r"\b(?:does\s+not|doesn['’]t|do\s+not|don['’]t)\s+(?:give|list|state|say|mention|specify|"
    r"show|provide|include)\s+(?:a|an|any|the)?\s*(?:\w+\s+){0,2}?(deadline|close date|amount|"
    r"award size|requirements?)\b|"
    r"\bno\s+(?:\w+\s+){0,2}?(deadline|close date|amount|award size|requirements?)\s+"
    r"(?:is|are|was|were)\s+(?:given|listed|stated|shown|in the record)\b", re.I)


def _absent_fact(rec: Record, what: str, as_of: date) -> bool | None:
    """Does this record lack the deadline, amount or requirements? None when it cannot say."""
    what = what.lower()
    if what in ("deadline", "close date"):
        # The page's deadline words count as a deadline (S49 M3).
        if isinstance(rec, Opportunity):
            return not (rec.close_date or rec.close_date_note or rec.deadline_quote)
        if isinstance(rec, Scholarship):
            return rec.deadline is None and not rec.deadline_quote
        return None
    if what in ("amount", "award size"):
        if isinstance(rec, Opportunity | Scholarship):
            return facts(rec, as_of).get("amount") == NOT_STATED
        return None
    if isinstance(rec, Scholarship):
        return not (rec.application_requirements and rec.application_requirements.items())
    return None


def code_check(text: str, ids: list[str], seen: dict[str, Record], tools: ReadTools | None,
               as_of: date) -> bool | None:
    """True or False when the claim is one of the shapes below and the tools gave the answer,
    None when MiniCheck must decide. Shapes: a lead's rank or kept status, checked against the
    rows read_brief and read_saved returned; "the record gives no deadline, amount or
    requirements", checked against the record's fields. Every cited record must agree."""
    body = strip_cites(text)
    verdicts: list[bool] = []
    if m := ABSENCE_RE.search(body):
        what = next(g for g in m.groups() if g)
        for i in ids:
            v = _absent_fact(seen[i], what, as_of)
            if v is None:
                return None
            verdicts.append(v)
        return all(verdicts) if verdicts else None
    if tools is None:
        return None
    rows = [i for i in ids if not i.startswith("user:")]
    if not rows and "user:brief" in ids and tools.brief_read and \
            not is_placeholder("user:brief", seen):
        # The brief as a record (Q2): an "empty brief" claim is false when it has leads, and a
        # rank or kept claim is checked on the leads whose titles the sentence names.
        if EMPTY_BRIEF_RE.search(body):
            return not tools.ranks
        low = body.lower()
        rows = [i for i in tools.ranks
                if (t := str(facts(seen[i], as_of).get("title") or "").lower()) and t in low]
    if not rows:
        return None
    ordered = sorted(tools.ranks, key=lambda k: tools.ranks[k])
    claim = None
    if tools.brief_read and (m := RANK_WORD_RE.search(body)):
        top, *words = m.groups()
        claim = ("pos", 1 if top else ORDINALS[next(w for w in words if w).lower()])
    elif tools.brief_read and (m := RANK_NUM_RE.search(body)):
        claim = ("rank", int(m.group(1) or m.group(2)))
    if claim:
        for i in rows:
            if i not in tools.ranks:
                return None
            verdicts.append(ordered.index(i) + 1 == claim[1] if claim[0] == "pos"
                            else tools.ranks[i] == claim[1])
        return all(verdicts)
    k, sv = KEPT_RE.search(body), SAVED_RE.search(body)
    if k and tools.brief_read:
        pool, at = tools.kept, k.start()
    elif sv and tools.saved_read:
        pool, at = tools.saved, sv.start()
    else:
        return None
    neg = bool(NEG_RE.search(body[max(0, at - 25):at]))
    return all((i in pool) != neg for i in rows)


def _rank_checked(body: str, ids: list[str], tools: ReadTools | None) -> str:
    """The body Layer 1 reads. A rank number that matches the rank read_brief gave the one
    cited record ("Rank 1 is X [id]") is the brief's own number, not a claim to find in the
    record, so it is left out of the count (Q7). A wrong rank stays in, and fails."""
    if tools is None or not tools.brief_read:
        return body
    rows = [i for i in ids if not i.startswith(("user:", "search:"))]
    m = RANK_NUM_RE.search(body)
    if m and len(rows) == 1 and tools.ranks.get(rows[0]) == int(m.group(1) or m.group(2)):
        return body[:m.start()] + body[m.end():]
    return body


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
    # A line that is exactly a fixed section name is a heading with or without a colon (Q4).
    fixed = not line.prefix and bool(STRUCTURAL_RE.fullmatch(norm_exempt(t)))
    return t.rstrip("*_ ").endswith(":") or bold or t.startswith("#") or fixed


def check_sentence(s: Sentence, seen: dict[str, Record], names: set[str] | None = None,
                   *, heading: bool = False, block: str = "",
                   tools: ReadTools | None = None) -> None:
    """`block` is the lower-case text of the records the lines under a heading cite (see
    `block_text`); a heading may name what that block cites."""
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
    # A list number inside bold marks ("**1. Title**") is numbering, not a number (Q5).
    body = BOLD_LIST_RE.sub(r"\1", strip_cites(s.text))
    if raw:
        for e in validate.check(_rank_checked(body, ids, tools), ids, seen).errors:
            if not e.startswith("cited id"):  # unresolved ids were reported above
                s.fail(_layer1_code(e), e, _token(e))
        # An empty-result placeholder ("user:saved", "user:brief") holds only "nothing found",
        # so alone it backs only a fixed empty-state template with nothing after it (S45 S4,
        # fix round 3: an allow-list, not a word list).
        if ids and all(is_placeholder(i, seen) for i in ids):
            n = norm_exempt(s.text)
            m = EMPTY_TEMPLATE_RE.match(n)
            tail = n[m.end():] if m else ""
            if m and not tail:
                s.kind = "absent"
            elif m and EMPTY_TAIL_RE.match(tail) and not empty_tail_claims(tail, names, seen):
                s.kind = "absent"  # "You have no entries to add context [user:entries]." (Q11)
            else:
                s.fail("placeholder_only", "an empty-result id such as [user:saved] backs only "
                       "a short empty-state sentence such as 'Your saved list is empty "
                       "[user:saved].', with nothing after it; do not cite it for a claim",
                       ids[0])
        return
    # No citation: allowed only for a sentence that states no record fact.
    if DISCLAIMER_RE.match(s.text):
        s.kind = "help"  # the exact disclaimer the system prompt asks for; nothing to check
        return
    if m := DISCLAIMER_TAIL_RE.match(s.text):
        # The disclaimer with a short "so check with ..." tail (Q6): the tail is help text and
        # passes the same content checks as any uncited help line.
        s.kind = "help"
        tail = m.group(1)
        if CLAIM_TAIL_RE.search(tail):
            s.fail("help_with_claim", "a help line with no citation must stop at the action; "
                   "a reason or verdict about a record needs its citation", tail[:60])
            return
        _no_record_claims(s, tail, names, seen, cited=False)
        return
    n = norm_exempt(s.text)
    if heading:
        s.kind = "heading"
        if STRUCTURAL_RE.fullmatch(n):
            return  # a fixed section name: nothing in it to check
        if LEADIN_RE.fullmatch(n) and not OFFER_FIT_RE.search(n) and not CLAIM_TAIL_RE.search(n):
            pass  # a how-to lead-in: its tail gets the content checks below
        elif not _label_words_in(n, block):
            s.fail("heading_not_structural", "a heading with no citation must be a section name "
                   "such as " + ", ".join(f"'{h}'" for h in HEADING_EXAMPLES) + ", or the title "
                   "of a record cited under it", n[:60])
            return
    elif s.text.rstrip("*_ ").endswith("?"):
        s.kind = "question"
        n = re.sub(r"^or\s+", "", n)  # "Or should I compare them?" (Q10)
        if not OFFER_RE.match(n) or OFFER_FIT_RE.search(n) or CLAIM_TAIL_RE.search(n):
            s.fail("question_not_offer", "a question with no citation must be an offer that "
                   "starts 'Would you like', 'Do you want', 'Shall I', 'Should I', 'Want me to', "
                   "'Which' or 'Tell me', and may not say how well anything fits", n[:60])
            return
    elif HELP_RE.search(body):
        s.kind = "help"
        if CLAIM_TAIL_RE.search(body):
            s.fail("help_with_claim", "a help line with no citation must stop at the action; "
                   "a reason or verdict about a record needs its citation", n[:60])
            return
    elif ABSENT_TEMPLATE_RE.fullmatch(n):
        s.kind = "absent"
        return  # a fixed template: nothing in it to check
    elif len(body.split()) <= ABSENT_WORDS and ABSENT_RE.search(body):
        s.kind = "absent"
        s.fail("absent_not_template", "a 'nothing found' sentence with no citation must be "
               "exactly 'I found no record on that.' or 'No record I read states that.'; "
               "otherwise cite the record or the empty-result id", n[:60])
        return
    else:
        s.fail("no_citation", f"sentence has no citation: {body[:80]!r}")
        return
    # An uncited sentence of an exempt kind that is not a fixed text (a record's label, an
    # offer, a help sentence) passes the same content checks as General advice, so it cannot
    # carry an award's name or an eligibility rule (S45 S3).
    if s.kind in ("question", "help"):
        # An offer or help line may name a record a tool returned this turn ("Would you like
        # me to read the X record in full?"): it states nothing new about it (Q10).
        _no_record_claims(s, body, names, seen, cited=False, allow_names=returned_titles(seen))
    else:
        _no_record_claims(s, body, names, seen, cited=False,
                          block=block if s.kind == "heading" else "")
    if s.kind == "help":
        return
    if validate.find_numbers(body) or validate.find_dates(body):
        s.fail("uncited_number_or_date", "a number or date with no cited record")
    if validate.URL_RE.search(body):
        s.fail("uncited_link", "a link with no cited record")


# Only a purpose tail ("... no entries to add context"); a "so ..." or "that ..." tail is a
# conclusion and stays removed (S45 fix round 2).
EMPTY_TAIL_RE = re.compile(r"^\s+to (?:add|give|fill|show|draw on|use|cite)\b")


def empty_tail_claims(tail: str, names: set[str] | None, seen: dict[str, Record]) -> bool:
    """Does the tail after an empty-state template state anything? A number, a date, an award
    name, a fit word or a reason ("since you ...") does."""
    return bool(general_reasons(tail, names or set(), seen) or FIT_WORDS.search(tail)
                or CLAIM_TAIL_RE.search(tail) or validate.find_numbers(tail))


def returned_titles(seen: dict[str, Record]) -> str:
    """The lower-case titles of the records the tools returned this turn, one per line."""
    return "\n".join(t for r in seen.values() if not r.id.startswith("user:")
                     and (t := str(facts(r, date.today()).get("title") or "").lower().strip()))


def _no_record_claims(s: Sentence, body: str, names: set[str] | None,
                      seen: dict[str, Record], *, cited: bool, block: str = "",
                      allow_names: str = "") -> None:
    """The General-advice content checks plus FIT_WORDS, for a sentence no real record backs.
    With `block` (a heading over cited lines), an award name or code found in the records that
    block cites is a label, not a claim, and so is the bare noun "eligibility" (S46 replay).
    `allow_names` (an offer or help line) lets it name a returned record and nothing more."""
    how = "citing only an empty-result id" if cited else "with no citation"
    for code, msg, d in general_reasons(body, names or set(), seen, cited=cited,
                                        allow=block or allow_names):
        s.fail(code, f"a {s.kind} sentence {how} {msg}", d)
    fit_body = re.sub(r"\beligibility\b", " ", body, flags=re.I) if block else body
    if m := FIT_WORDS.search(fit_body):
        s.fail("uncited_fit_word", f"a {s.kind} sentence {how} may not say who may apply or how "
               f"well the user fits ({m.group(0)!r}); cite the record or leave it out", m.group(0))


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


def general_reasons(text: str, names: set[str], seen: dict[str, Record], *, cited: bool = False,
                    allow: str = "") -> list[tuple[str, str, str]]:
    """(REASONS code, message, detail) for every rule a General advice sentence breaks. With
    `cited`, the sentence is allowed its citation (an empty-result id) and only the rest is
    checked. `allow` is lower-case record text: an award name or code found in it is not
    counted (a heading over lines that cite that record)."""
    out: list[tuple[str, str, str]] = []
    if cites_in(text) and not cited:
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
    for m in validate.ID_RE.finditer(text):
        if allow and re.search(rf"(?<!\w){re.escape(m.group(0).lower())}(?!\w)", allow):
            continue
        out.append(("general_award_code", "may not name an award by its code", m.group(0)))
        break
    low = text.lower()
    hit = []
    for n in sorted(names | {title_key(r) for r in seen.values()}):
        if not n or (allow and n in allow):
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
        if allow and m.group(0).strip().lower() in allow:
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


def _prose_tail(line: Line) -> Sentence | None:
    """The last sentence of a prose line (no list marker, not a heading), else None."""
    if line.prefix or not line.sentences or line.sentences[-1].kind == "heading":
        return None
    return line.sentences[-1]


def inherit(s: Sentence, prev: Sentence | None, seen: dict[str, Record],
            tools: ReadTools | None) -> None:
    """Q3: an uncited sentence right after a cited one ("There are two tracks.") takes that
    sentence's records and is checked against them like a cited sentence: Layer 1 here,
    then the code check or MiniCheck in `grade`. It may not inherit a fit word ("a perfect
    match"), a claim about who may apply, or a SYNTHETIC sample's citation."""
    if [c for c, _ in s.reasons] != ["no_citation"] or prev is None:
        return
    if not prev.cites or prev.errors or prev.kind not in ("grounded", "inherited"):
        return
    if any(is_placeholder(c, seen) or seen[c].source == "synthetic" for c in prev.cites):
        return
    body = strip_cites(s.text)
    if FIT_WORDS.search(body) or ELIGIBILITY.search(body) or OFFER_FIT_RE.search(body.lower()):
        return
    s.errors, s.reasons = [], []
    s.cites, s.kind = list(prev.cites), "inherited"
    for e in validate.check(_rank_checked(body, s.cites, tools), s.cites, seen).errors:
        s.fail(_layer1_code(e), e, _token(e))


def grade(text: str, seen: dict[str, Record], names: set[str], as_of: date,
          grounder: Grounder | None = None, tools: ReadTools | None = None) -> Graded:
    """Parse and check one answer. Layer 2 runs only when layer 1 and the citation rules pass
    for the sentence, so MiniCheck is not spent on a sentence that will be regenerated."""
    grounded, general = split_general(normalise_cites(text, seen))
    g = Graded(parse(grounded), parse(general) if general else [])
    for li, ln in enumerate(g.lines):
        for si, s in enumerate(ln.sentences):
            h = is_heading(s, ln) or bold_title(s, ln, cited_below(g.lines, li, seen))
            check_sentence(s, seen, names, heading=h,
                           block=block_text(g.lines, li, seen) if h else "", tools=tools)
            prev = (ln.sentences[si - 1] if si else
                    _prose_tail(g.lines[li - 1]) if li and not ln.prefix else None)
            inherit(s, prev, seen, tools)
    for s in g.general_sentences:
        s.kind = "general"
        for code, msg, d in general_reasons(s.text, names, seen):
            s.fail(code, "General advice " + msg, d)
    mixed_blocks(g, seen)
    if g.ok:
        for s in g.sentences:
            if not s.cites:
                continue
            v = code_check(s.text, s.cites, seen, tools, as_of)
            if v is not None:  # exact, so MiniCheck is not asked
                s.support, s.supported = (1.0 if v else 0.0), v
            elif grounder is not None:
                doc = "\n\n".join(document_for(seen[c], as_of) for c in s.cites)
                p = grounder.support(doc, [strip_cites(s.text)])[0]  # whole claim, not re-split
                s.support, s.supported = p, p > THRESHOLD
    return g


def cited_below(lines: list[Line], at: int, seen: dict[str, Record]) -> list[Record]:
    """Every returned record cited by the lines under the line at `at`, up to the next
    heading."""
    recs: dict[str, Record] = {}
    for ln in lines[at + 1:]:
        if len(ln.sentences) == 1 and is_heading(ln.sentences[0], ln):
            break
        for s in ln.sentences:
            for c in cites_in(s.text):
                rid = resolve(c, seen)
                if rid is not None and not is_placeholder(rid, seen):
                    recs[rid] = seen[rid]
    return list(recs.values())


def _words(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))


def bold_title(s: Sentence, line: Line, below: list[Record]) -> bool:
    """A bold line of any length that is exactly the title of a record cited under it (Q5).
    It names that record; the record's own citations below carry its facts."""
    if len(line.sentences) != 1 or cites_in(s.text):
        return False
    if not BOLD_LINE_RE.fullmatch(re.sub(r"^\s*\d{1,2}[.)]\s+", "", s.text.strip())):
        return False
    t = _words(norm_exempt(s.text))
    return bool(t) and any(t == _words(str(facts(r, date.today()).get("title") or ""))
                           for r in below)


def block_text(lines: list[Line], at: int, seen: dict[str, Record]) -> str:
    """The lower-case title and evidence text of every returned record cited by the lines under
    the heading at `at`, up to the next heading. Empty when no line under it cites a record."""
    return "\n".join(f"{title_key(r)}\n{validate.evidence(r).text}".lower()
                     for r in cited_below(lines, at, seen))


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
            "cited record does not hold. Without an id, a heading is a section name such as "
            "'What the record asks for' or a cited record's title, a question is an offer "
            "such as 'Would you like me to read it in full?', and 'nothing found' is 'I found "
            "no record on that.' Advice and how-to-use-Perch help go last, under "
            f"'{GENERAL_LABEL}', with no citation, no award names, no numbers or dates and no "
            "eligibility rules.")

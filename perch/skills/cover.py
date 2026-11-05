"""Skill 4, cover points (S33): for one target record, a grant opportunity, a public
fellowship listing or a SYNTHETIC sample scholarship, the points a cover letter or an
application could make. Each point ties one thing the record asks for or rewards to one
thing the applicant's records show, and every sentence cites the record it comes from.

Inputs: the target record as an Opportunity; the applicant's records: the session's CV
and documents (contact details blanked in every view, standing rule 5 as amended), up to
MAX_PAPERS papers and, for a researcher, their public awards. Lines code wrote, such as a
student's rule verdicts, go in as plain context, never as citable records.

Output, reasoning first as the fit skill does: 3 to 6 points, up to 3 things the record
asks for that no applicant record shows, and the ids used. The closure checks every
sentence with validator layer 1 against the records it cites, that each point's asks cites
the target alone and its you cites applicant records only, the counts, the sentence
lengths (one or two sentences of at least MIN_WORDS words, so no bare fragment), the form
of a missing item (about what the applicant's records do not show, never a gap in the
record) and a banned-phrase list (odds, chances, whether to apply). A failure is
regenerated once; a second failure withholds the points. The grounder (layer 2) marks
sentences it cannot support; they are flagged, not withheld.

Prompt size: the demo model's context is 12,288 tokens and S31's root cause was a cut
prompt, so each view is capped and the whole prompt stays under PROMPT_CHARS; records that
do not fit are left out, so they cannot be cited.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from perch.datefmt import day
from perch.grounding import THRESHOLD, Grounder
from perch.llm import Message
from perch.llm.audit import AuditedProvider
from perch.llm.contacts import blank_contacts
from perch.schemas import Award, Opportunity, Record, Work
from perch.skills import (
    GROUND_RULES,
    opportunity_view,
    parse_json,
    sentences,
    short_work_id,
    work_view,
)
from perch.user.cv import sections
from perch.validate import Check, Validated, check, generate_validated

SKILL = "cover_points"
MIN_POINTS, MAX_POINTS, MAX_MISSING = 3, 6, 3
MAX_PAPERS = 6
MAX_SENTENCES = 2
CV_CHARS = 3500
DOC_CHARS = 1200
PAPER_CHARS = 400
DESCRIPTION_CHARS = 1500
PROMPT_CHARS = 16_000  # system and user message together
CV_SECTIONS = ("education", "appointment", "position", "experience", "funding", "grant",
               "award", "honor", "honour", "skill")
CONTEXT_HEAD = "Rule check, written by code:"

SCHEMA = {
    "type": "object",
    "properties": {  # order matters: reasoning is generated before the points
        "reasoning": {"type": "string"},
        "points": {"type": "array", "minItems": MIN_POINTS, "maxItems": MAX_POINTS, "items": {
            "type": "object",
            "properties": {"asks": {"type": "string"},
                           "asks_ids": {"type": "array", "items": {"type": "string"}},
                           "you": {"type": "string"},
                           "you_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["asks", "asks_ids", "you", "you_ids"], "additionalProperties": False}},
        "missing": {"type": "array", "minItems": 0, "maxItems": MAX_MISSING,
                    "items": {"type": "string"}},
        "cited_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
    "required": ["reasoning", "points", "missing", "cited_ids"],
    "additionalProperties": False,
}
INSTRUCTIONS = (
    "You list the points a cover letter or an application for one funding record could "
    "make, for the applicant to put in their own words. First, in the reasoning field, "
    "write short working notes: "
    "what the target record asks for or rewards, and which applicant records answer each "
    f"ask. Then give {MIN_POINTS} to {MAX_POINTS} points. In each point, asks is one full "
    "sentence, with a subject and a verb, on one thing the target record asks for or rewards "
    "(\"The program supports early-career investigators.\", never a bare phrase such as "
    "\"Early-career research.\"), from the target record only, and asks_ids holds the target "
    "record's id alone; you is one full sentence addressed to the applicant as \"you\" (\"You "
    "led ...\") on what their records show that answers it, from the applicant records named "
    "in you_ids only, which must name at least one. Never give the applicant a role (led, "
    "contributed, wrote, designed) that the records in you_ids do not state; for a paper, say "
    f"what it reports (\"Your paper reports ...\"). missing lists up to {MAX_MISSING} things "
    "the target record asks for or rewards that no applicant record shows. Each item is one "
    "full sentence in this form: \"The record asks for a mentoring plan; nothing you added "
    "shows one.\" It names what the record wants and says that the applicant's records do "
    "not show it; it never says what the record lacks, leaves out or does not specify. Put "
    "ids in asks_ids, you_ids and "
    "cited_ids, not inside the sentences. Never judge the applicant's chances or odds, never "
    "say whether to apply, and never invent: leave numbers and dates out unless they are in "
    "the record you cite. cited_ids lists every id used. " + GROUND_RULES
)
STUDENT_LINE = (" The applicant is a student: their records are a CV, an interests note and "
                "achievements, and a verdict line written by rule code may be given as context.")
# Claims the points never make (standing rule 10, SPEC section 1). ODDS applies to every
# sentence; the advice and judgment phrases to the you sentences only, since an asks
# sentence copies the record, which says "applicants must submit a letter" itself.
ODDS = r"odds|likely|unlikely|chances?|guarantee\w*"
BANNED_ASKS = re.compile(rf"\b(?:{ODDS})\b", re.I)
BANNED = re.compile(
    rf"\b(?:{ODDS}|(?:should|must|ought to) (?:apply|submit|not apply)|will (?:win|be funded|"
    r"succeed|be selected)|(?:strong|good|ideal|perfect) (?:candidate|chance))\b", re.I)
# Inline citations a model adds anyway, removed before the checks (ids go in the id lists).
BRACKETED = re.compile(r"\s*\[[^\[\]]*\]")
# A sentence item (asks, you, missing) has at least this many words: "Chemical Catalysis
# research." is a fragment, "It supports early-career investigators." a sentence (QA, S33).
MIN_WORDS = 4
# A missing item is about the applicant's records ("nothing you added shows one"), never a
# gap in the record ("The record does not specify a sub-discipline"), which is no point a
# cover letter can make (QA, S33). The applicant is addressed as "you".
ABOUT_YOU = re.compile(r"\byou(?:r|rs)?\b", re.I)
RECORD_GAP = re.compile(
    r"^(?:the|this|that) (?:record|program|listing|announcement|opportunity|notice|award|"
    r"fellowship|scholarship|call|solicitation|nofo|foa)\b[^;]*?\b(?:does not|doesn't|did not|"
    r"didn't|lacks|is silent|fails to|has no|gives no|provides no|states no|names no|"
    r"mentions no|specifies no|lists no|omits|leaves out|is unclear|is vague|is not "
    r"(?:clear|specific|explicit))\b|\b(?:does not|doesn't|did not|didn't) (?:specify|state|"
    r"list|mention|name|say|give|provide|describe|define|detail|indicate|identify|clarify|"
    r"explain)\b|\b(?:is|are) not (?:specified|stated|listed|mentioned|named|given|provided|"
    r"described|defined|detailed|indicated|identified|clarified|explained)\b", re.I)


@dataclass
class Point:
    asks: str
    asks_ids: list[str]
    you: str
    you_ids: list[str]


@dataclass
class Points:
    points: list[Point]
    missing: list[str]
    cited_ids: list[str]
    reasoning: str
    unsupported: list[str] = field(default_factory=list)  # layer 2 flags
    support: dict[str, float] = field(default_factory=dict)

    def used_ids(self) -> list[str]:
        ids = [i for p in self.points for i in (*p.asks_ids, *p.you_ids)]
        return list(dict.fromkeys(ids))


# --- views ---

def record_key(r: Record) -> str:
    """The id the model cites a record by: the short work id, or the award's own id."""
    return short_work_id(r) if isinstance(r, Work) else r.id


def cv_view(doc: Work, chars: int = CV_CHARS) -> str:
    """The CV with its contact details blanked, the sections that bear on an application
    first (education, positions, funding and honours, skills), cut at `chars`."""
    text = blank_contacts(doc.abstract or "")
    secs = sections(text)
    first = [k for k in secs if any(w in k for w in CV_SECTIONS)]
    parts = []
    for k in [*first, *(k for k in secs if k not in first)]:
        if lines := secs[k]:
            head = f"{k[:1].upper()}{k[1:]}:\n" if k else ""
            parts.append(head + "\n".join(f"- {x}" for x in lines))
    body = "\n".join(parts) if parts else text
    return f"[{short_work_id(doc)}] {blank_contacts(doc.title or '')}\n{body[:chars]}"


def award_view(a: Award) -> str:
    when = " to ".join(day(d) for d in (a.start_date, a.end_date) if d)
    parts = [f"[{a.id}] {a.agency} award {a.award_number}: {a.title}"]
    if a.activity_code:
        parts.append(f"activity code {a.activity_code}")
    if when:
        parts.append(when)
    if a.amount is not None:
        parts.append(f"${a.amount:,.0f}" + (f" ({a.amount_basis})" if a.amount_basis else ""))
    return "; ".join(parts)


def full_view(r: Record) -> str:
    """A record as the grounder reads it: the whole text, a private document blanked."""
    if isinstance(r, Award):
        return award_view(r)
    if isinstance(r, Work) and r.source == "user":
        return f"{r.title}\n{blank_contacts(r.abstract or '')}"
    if isinstance(r, Work):
        return work_view(r, abstract_chars=4000)
    return opportunity_view(r, description_chars=4000) if isinstance(r, Opportunity) else ""


def build_prompt(o: Opportunity, cv: Work | None, docs: list[Work], papers: list[Work],
                 awards: list[Award], context: list[str], system_chars: int
                 ) -> tuple[str, dict[str, Record]]:
    """The user message and the records it shows, keyed as the model cites them. Views
    go in by priority (CV, documents, papers, awards) until the prompt budget is spent;
    a record left out is not given, so it cannot be cited."""
    records: dict[str, Record] = {o.opportunity_number: o}
    head = "Target record:\n" + opportunity_view(o, description_chars=DESCRIPTION_CHARS)
    tail = (f"\n\n{CONTEXT_HEAD}\n" + "\n".join(f"- {x}" for x in context)) if context else ""
    candidates: list[tuple[Record, str]] = []
    if cv is not None:
        candidates.append((cv, cv_view(cv)))
    candidates += [(d, work_view(d, abstract_chars=DOC_CHARS)) for d in docs]
    candidates += [(w, work_view(w, abstract_chars=PAPER_CHARS))
                   for w in [x for x in papers if x.source != "user"][:MAX_PAPERS]]
    candidates += [(a, award_view(a)) for a in awards]
    label = "\n\nApplicant records:\n"
    budget = PROMPT_CHARS - system_chars - len(head) - len(tail) - len(label) - 100
    views = []
    for rec, view in candidates:
        if len(view) + 1 > budget:
            continue
        views.append(view)
        records[record_key(rec)] = rec
        budget -= len(view) + 1
    body = (label + "\n".join(views)) if views else "\n\nApplicant records: none given."
    return head + body + tail, records


def strip_ids(text: str) -> str:
    return " ".join(BRACKETED.sub("", text).split())


# S50 (3c): the live points said "You contributed to ... RTx-303" citing a paper that names
# no role. A role word in a you sentence must stand in a record it cites (the CV says "Led
# ..."); otherwise the point says what the record reports. Decided by words, never a model.
ROLE_RE = re.compile(r"\b(led|contribut\w*|co-?authored|authored|wrote|designed|directed|"
                     r"supervis\w*|managed|founded|organi[sz]ed|mentored|chaired)\b", re.I)


def role_claims(where: str, text: str, cited: list[Record]) -> list[str]:
    body = " ".join(full_view(r) for r in cited).lower()
    errs = []
    for m in ROLE_RE.finditer(text):
        word = m.group(1).lower()
        stem = word[:7] if word.startswith(("contribut", "supervis")) else word
        if not re.search(rf"\b{re.escape(stem)}", body):
            errs.append(f"{where} says {m.group(0)!r}, a role the records it cites do not "
                        "state: say what the record reports (\"Your paper reports ...\")")
    return errs


# A you sentence names the applicant; a paper it cites names its authors ("We found"), so
# MiniCheck flagged "You identified X" against "We identified X". When a point cites papers
# only, layer 2 scores it with the paper as the subject, as the fit skill does ("The paper
# ..."). A CV or document line is the applicant's own, so it is scored as written.
YOU_SUBJECT = re.compile(r"^(?:you|your work|your research)\b", re.I)


def as_record_claim(text: str, cited: list[Record]) -> str:
    if not cited or not all(isinstance(r, Work) and r.source != "user" for r in cited):
        return text
    claim = YOU_SUBJECT.sub("The paper", text.strip(), count=1)
    return re.sub(r"\byou\b", "it", re.sub(r"\byour\b", "its", claim))


def missing_form(where: str, text: str) -> list[str]:
    """The deterministic check of a missing item: it is about the applicant's records
    ("nothing you added shows one"), not a gap in the record ("The record does not specify
    a sub-discipline"). Both are decided by words, never by a model."""
    errs = []
    if not ABOUT_YOU.search(text):
        errs.append(f"{where} ({text!r}) does not say that nothing the applicant added shows "
                    "it: write \"The record asks for X; nothing you added shows it\"")
    if m := RECORD_GAP.search(text):
        errs.append(f"{where} says {m.group(0)!r}, a gap in the record: missing lists what "
                    "the record asks for that the applicant's records do not show, in the "
                    "form \"The record asks for X; nothing you added shows it\"")
    return errs


def record_part(text: str) -> str:
    """The part of a missing item that claims something of the record, before the fixed
    "; nothing you added shows it" clause, which the grounder cannot find in the record."""
    return text.split(";", 1)[0].strip()


def with_context(o: Opportunity, context: list[str]) -> Opportunity:
    """The target record as the checks see it: the code-written context lines ride on
    it, so a number they hold (a GPA rule's 3.50) may be repeated (as loop._with_facts)."""
    if not context:
        return o
    return o.model_copy(update={"description": f"{o.description or ''} {' '.join(context)}"})


# --- the skill ---

def cover_points(o: Opportunity, cv: Work | None, docs: list[Work], papers: list[Work],
                 awards: list[Award], provider: AuditedProvider,
                 grounder: Grounder | None = None, context: list[str] | None = None,
                 audience: str = "researcher") -> tuple[Validated[Points], dict[str, Record]]:
    """The checked points and the records the model was given, by the key it cites."""
    system = INSTRUCTIONS + (STUDENT_LINE if audience == "student" else "")
    context = list(context or [])
    prompt, records = build_prompt(o, cv, docs, papers, awards, context, len(system))
    target = o.opportunity_number
    applicant = {k for k in records if k != target}
    checked = {**records, target: with_context(o, context)}

    def known(i: object) -> str:
        i = str(i).strip("[] ")  # models drop the "user:" prefix of a user document
        return f"user:{i}" if i not in records and f"user:{i}" in records else i

    def generate(feedback: list[str]) -> Points:
        msg = prompt + ("\n\nYour previous answer was rejected: " + "; ".join(feedback)
                        + ". Fix these problems." if feedback else "")
        r = provider.chat([Message("user", msg)], system=system, schema=SCHEMA,
                          max_tokens=4000, cache_system=True)
        d = parse_json(r.text)
        try:
            points = [Point(strip_ids(str(p["asks"])), [known(i) for i in p["asks_ids"]],
                            strip_ids(str(p["you"])), [known(i) for i in p["you_ids"]])
                      for p in d["points"]]
            missing = [strip_ids(str(m)) for m in d.get("missing") or []]
            return Points(points, missing, [known(i) for i in d["cited_ids"]],
                          str(d.get("reasoning") or ""))
        except (KeyError, TypeError, AttributeError) as e:
            raise ValueError(f"missing field: {e}") from e

    attempts = [0]

    def unparseable(errors: list[str]) -> None:
        attempts[0] += 1
        provider.log.validation(provider.last_call_id, SKILL, False, errors, attempts[0])

    def sentence_checks(where: str, text: str, ids: list[str],
                        banned: re.Pattern = BANNED) -> list[str]:
        errs = [f"{where}: {e}" for e in check(text, ids, checked).errors]
        n = sentences(text)
        if not 1 <= n <= MAX_SENTENCES:
            errs.append(f"{where}: write 1 or 2 sentences, got {n}")
        if len(text.split()) < MIN_WORDS:
            errs.append(f"{where} is a fragment ({text!r}): write one full sentence with a "
                        "subject and a verb")
        if m := banned.search(text):
            errs.append(f"{where} says {m.group(0)!r}: describe the record and the "
                        "applicant's records only, never chances or whether to apply")
        return errs

    def validate(p: Points) -> Check:
        attempts[0] += 1
        errors = []
        if not MIN_POINTS <= len(p.points) <= MAX_POINTS:
            errors.append(f"give {MIN_POINTS} to {MAX_POINTS} points, got {len(p.points)}")
        if len(p.missing) > MAX_MISSING:
            errors.append(f"missing holds at most {MAX_MISSING} items, got {len(p.missing)}")
        errors += [f"cited id {c!r} was not in the input" for c in p.cited_ids
                   if c not in records]
        for i, pt in enumerate(p.points, 1):
            if pt.asks_ids != [target]:
                errors.append(f"point {i}: asks_ids must be exactly [{target}], the target "
                              f"record, got {pt.asks_ids}")
            if not pt.you_ids:
                errors.append(f"point {i}: you_ids must name at least one applicant record")
            if bad := [x for x in pt.you_ids if x not in applicant]:
                errors.append(f"point {i}: you_ids names {bad}, which is not an applicant "
                              "record you were given")
            errors += sentence_checks(f"point {i} asks", pt.asks, [target], BANNED_ASKS)
            errors += sentence_checks(f"point {i} you", pt.you,
                                      [x for x in pt.you_ids if x in applicant])
            errors += role_claims(f"point {i} you", pt.you,
                                  [records[x] for x in pt.you_ids if x in applicant])
        for j, m in enumerate(p.missing, 1):
            errors += sentence_checks(f"missing {j}", m, [target], BANNED_ASKS)
            errors += missing_form(f"missing {j}", m)
        provider.log.validation(provider.last_call_id, SKILL, not errors, errors, attempts[0])
        return Check(not errors, errors)

    v = generate_validated(generate, validate, unparseable)
    if v.value and grounder:
        ground(v.value, o, records, grounder, provider)
    return v, records


def ground(p: Points, o: Opportunity, records: dict[str, Record], grounder: Grounder,
           provider: AuditedProvider) -> None:
    """Layer 2: each asks and missing sentence against the target record, each you
    sentence against the applicant records it cites. Flags only."""
    target = opportunity_view(o, description_chars=4000)
    for i, pt in enumerate(p.points, 1):
        s = grounder.support(target, [pt.asks])[0]
        p.support[f"point {i} asks"] = round(s, 3)
        if s <= THRESHOLD:
            p.unsupported.append(pt.asks)
        cited = [records[x] for x in pt.you_ids if x in records]
        doc = "\n\n".join(full_view(r) for r in cited)
        s = grounder.support(doc, [as_record_claim(pt.you, cited)])[0] if doc else 0.0
        p.support[f"point {i} you"] = round(s, 3)
        if s <= THRESHOLD:
            p.unsupported.append(pt.you)
    for j, m in enumerate(p.missing, 1):
        s = grounder.support(target, [record_part(m)])[0]
        p.support[f"missing {j}"] = round(s, 3)
        if s <= THRESHOLD:
            p.unsupported.append(m)
    provider.log.validation(provider.last_call_id, SKILL, not p.unsupported,
                            [f"unsupported: {s}" for s in p.unsupported], 1, layer=2)

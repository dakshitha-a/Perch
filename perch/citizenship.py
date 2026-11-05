"""Citizenship and residency: the optional picks, and a closed-phrase reader for a listing's own
words (S53). Deterministic code only; never a model, and the picks are never shown to one.

A pick is compared with a rule only when the listing's own text states the rule in one of a
few closed phrases. The result is never a "not eligible" verdict: a listing the user does not
meet moves lower in the same list, with a note that quotes the full sentence and names the
field it came from. No phrase, no inference (standing rule 3): the note then says where Perch
looked and that it found no rule.

A sentence that only states a preference ("strong preference given to U.S. citizens") is not
a rule: it is not counted and it does not move a listing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CITIZENSHIP_VALUES = ("us_citizen", "permanent_resident", "international", "prefer_not")
CITIZENSHIP_LABELS = {"us_citizen": "U.S. citizen", "permanent_resident": "Permanent resident",
                      "international": "International", "prefer_not": "Prefer not to say"}
STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
STATE_CODES = tuple(STATES)
_NAME_TO_CODE = {v.lower(): k for k, v in STATES.items()}
_STATE_RE = (r"(?<!West )(?:" + "|".join(sorted((re.escape(n) for n in STATES.values()),
                                                 key=len, reverse=True)) + r")\b")
_STATE_ONLY = re.compile(_STATE_RE, re.I)
_RES_OF = re.compile(r"\b(?:residents?\s+of|resident\s+in)\s+(?:the\s+(?:state|commonwealth)\s+"
                     r"of\s+)?(?:" + _STATE_RE + ")", re.I)
_STATE_RES = re.compile(r"(?:" + _STATE_RE + r")\s+residents?\b", re.I)
_US = re.compile(r"(?<!non-)(?<!non )\b(?:U\.?S\.?|United\s+States)\s+citizens?\b"
                 r"|\bcitizens?\s+(?:or\s+nationals?\s+)?of\s+the\s+United\s+States\b", re.I)
_PR = re.compile(r"\bpermanent\s+residents?\b", re.I)
_INTL = re.compile(r"\binternational\s+students?\b", re.I)
_NEG = re.compile(r"\b(?:not|ineligible|cannot|unable|excluded|non-residents?)\b", re.I)
_POS_INTL = re.compile(r"\b(?:are\s+eligible|may\s+apply|can\s+apply|are\s+welcome|welcome|"
                       r"including\s+international|open\s+to\s+international)\b", re.I)
_PREF = re.compile(r"\b(?:prefer(?:s|red|ence|ences)?|priority|encouraged?|favou?r(?:ed)?)\b",
                   re.I)

# Where a field's text came from, in plain words (the card says it).
FIELD_WORDS = {
    "eligibility.notes": "the award's eligibility notes",
    "field_quotes.eligibility": "the eligibility sentence quoted from the award's page",
    "eligibility.citizenship": "the award's citizenship field",
    "eligibility.residency_state": "the award's residency field",
    "eligibility_notes": "the opportunity's eligibility text",
    "international_ok": "the award's international-students field",
}


@dataclass(frozen=True)
class Rule:
    kind: str  # "citizenship" or "residency"
    mode: str  # "only": must be one of allows; "ok_for": says these may apply; "not_for": not these
    allows: frozenset
    sentence: str
    field: str


@dataclass
class Outcome:
    kind: str
    status: str  # "pass" | "fail" | "none"
    rule: Rule | None = None
    where: str = ""  # plain words for the field, with the source page


def _split(text: str) -> list[str]:
    t = re.sub(r"\bU\.S\.", "U\x01S\x01", " ".join(text.replace("\n", " ; ").split()))
    parts = re.split(r";\s*|(?<=[.!?])\s+(?=[A-Z“\"(])", t)
    return [p.replace("\x01", ".").strip() for p in parts if p.strip()]


def rules_in(text: str | None, field_name: str) -> list[Rule]:
    """Every closed-phrase rule in `text`, each with the full sentence it came from. A
    sentence that only states a preference is not a rule and gives none."""
    out: list[Rule] = []
    for sent in _split(text or ""):
        if _PREF.search(sent):
            continue
        neg = bool(_NEG.search(sent))
        us, pr, intl = _US.search(sent), _PR.search(sent), _INTL.search(sent)
        if (us or pr) and not neg:
            allows = {v for v, hit in (("us_citizen", us), ("permanent_resident", pr),
                                       ("international", intl and _POS_INTL.search(sent)))
                      if hit}
            mode = "ok_for" if (pr and not us) else "only"
            out.append(Rule("citizenship", mode, frozenset(allows), sent, field_name))
        elif pr and neg and not us:
            out.append(Rule("citizenship", "not_for", frozenset({"permanent_resident"}), sent,
                            field_name))
        elif intl:
            if neg:
                out.append(Rule("citizenship", "not_for", frozenset({"international"}), sent,
                                field_name))
            elif _POS_INTL.search(sent):
                out.append(Rule("citizenship", "ok_for", frozenset({"international"}), sent,
                                field_name))
        if not neg and (_RES_OF.search(sent) or _STATE_RES.search(sent)):
            codes = {_NAME_TO_CODE[m.group(0).lower()] for m in _STATE_ONLY.finditer(sent)}
            if codes:
                out.append(Rule("residency", "only", frozenset(codes), sent, field_name))
    return out


def _eval(rules: list[Rule], pick: str) -> tuple[str, Rule | None]:
    first_pass = None
    for r in rules:
        if r.mode == "only":
            if pick in r.allows:
                first_pass = first_pass or r
            else:
                return "fail", r
        elif r.mode == "ok_for" and pick in r.allows:
            first_pass = first_pass or r
        elif r.mode == "not_for" and pick in r.allows:
            return "fail", r
    return ("pass", first_pass) if first_pass else ("none", None)


def quote(sentence: str, n: int = 300) -> str:
    s = sentence.strip().rstrip(".")
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + " …"


def where_words(field_name: str, source: str | None, is_grants: bool = False) -> str:
    base = FIELD_WORDS.get(field_name, "the listing's eligibility text")
    if is_grants or source == "grants_gov":
        return f"{base} on Grants.gov"
    if source == "temple_pages":
        return f"{base} on its Temple page"
    return base


def stated_note(kind_label: str, o: Outcome, you: str) -> str:
    """A rule the pick meets."""
    return (f"{kind_label}: from {o.where}, the listing asks for: “{quote(o.rule.sentence)}”. "
            f"You entered: {you}.")


def demoted_note(o: Outcome, you: str) -> str:
    """A rule the pick does not meet."""
    return (f"From {o.where}, the listing asks for: “{quote(o.rule.sentence)}”. "
            f"You entered: {you}.")


def none_note(has_text: bool, where_all: str) -> str:
    """No rule found: say where Perch looked."""
    if not has_text:
        return ("This listing has no eligibility text for Perch to read; check the award's "
                "page.")
    return f"Perch read {where_all} and found no citizenship or residency rule."


def you_label(kind: str, cit: str | None, res: str | None) -> str:
    return CITIZENSHIP_LABELS[cit or "prefer_not"] if kind == "citizenship" else STATES[res or ""]


def judge(sources: list[tuple[str, str | None]], cit: str | None, res: str | None,
          source: str | None, is_grants: bool = False) -> dict[str, Outcome]:
    """Compare the picks with every rule in `sources` (field name, text). Returns one Outcome
    per pick that was given ("prefer_not" and blank give none). An Outcome of status "none"
    means the text was read and states no such rule."""
    rules: list[Rule] = []
    seen: set[tuple] = set()
    for fname, text in sources:
        for r in rules_in(text, fname):
            k = (r.kind, r.sentence)
            if k not in seen:  # the notes and the quoted sentence repeat each other
                seen.add(k)
                rules.append(r)
    out: dict[str, Outcome] = {}
    picks = (("citizenship", cit if cit in CITIZENSHIP_LABELS and cit != "prefer_not" else None),
             ("residency", res if res in STATES else None))
    for kind, pick in picks:
        if pick is None:
            continue
        status, rule = _eval([r for r in rules if r.kind == kind], pick)
        out[kind] = Outcome(kind, status, rule,
                            where_words(rule.field, source, is_grants) if rule else "")
    return out


def stated(sources: list[tuple[str, str | None]]) -> bool:
    return any(rules_in(t, f) for f, t in sources)


def has_text(sources: list[tuple[str, str | None]]) -> bool:
    return any((t or "").strip() for _, t in sources)


def where_all(source: str | None, is_grants: bool = False) -> str:
    return where_words("eligibility_notes" if is_grants else "eligibility.notes", source,
                       is_grants).replace("the award's eligibility notes", "this listing's "
                                          "eligibility text").replace(
        "the opportunity's eligibility text", "this listing's eligibility text")


def rule_json(outs: dict[str, Outcome], record_id: str, source_url: str, readable: bool
              ) -> dict | None:
    """The provenance the card and the evidence panel show: the rule that decided the outcome
    (a fail first), else the first rule met, else `none`. None when no pick was given."""
    if not outs:
        return None
    pick = (next((o for o in outs.values() if o.status == "fail"), None)
            or next((o for o in outs.values() if o.status == "pass"), None))
    o = pick or next(iter(outs.values()))
    return {"record_id": record_id, "source_url": source_url,
            "field": o.rule.field if o.rule else None,
            "where": o.where if o.rule else None,
            "quote": o.rule.sentence if o.rule else None,
            "outcome": o.status, "has_text": readable}


def student_sources(s) -> list[tuple[str, str | None]]:  # noqa: ANN001 - a Scholarship
    e = s.eligibility
    return [("eligibility.notes", e.notes),
            ("field_quotes.eligibility", s.field_quotes.get("eligibility")),
            ("eligibility.citizenship", e.citizenship)]


def opportunity_sources(o) -> list[tuple[str, str | None]]:  # noqa: ANN001 - an Opportunity
    return [("eligibility_notes", o.eligibility_notes),
            ("field_quotes.eligibility", o.field_quotes.get("eligibility"))]


__all__ = ["CITIZENSHIP_LABELS", "CITIZENSHIP_VALUES", "STATES", "STATE_CODES", "Outcome", "Rule",
           "judge", "rules_in", "stated"]

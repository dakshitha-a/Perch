"""Student mode rules (S18): the CV parse, eligibility by rule, and the gap list.

Deterministic code only; never a model. The rules are the ones written down in
data/synthetic/README.md ("Answer key rules"), so the S19 bench can compare this code
with the hand-written keys:

- Not eligible: the first rule a record breaks, in the order of RULES.
- May be eligible: no rule broken, but the record asks for something the CV cannot
  show (a minimum GPA with no GPA stated, residency, citizenship, a targeted criterion),
  or the CV does not state a fact a rule needs.
- Eligible: no rule broken and nothing unknown.
The app never asks for residency, citizenship or a targeted criterion; it quotes the
record and leaves the judgment to the student.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np

from perch.datefmt import day
from perch.embed import normalise
from perch.profile import Profile, Thread
from perch.schemas import Lead, Opportunity, Scholarship, utcnow
from perch.scholarships import NIH_FELLOWSHIP_LEVEL, sample_records
from perch.score import match_score
from perch.user.cv import sections
from perch.user.inputs import UserDoc

MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november "
    "december".split(), 1)}
YEAR_WORDS = {"first-year": 1, "freshman": 1, "first year": 1, "sophomore": 2,
              "second-year": 2, "second year": 2, "junior": 3, "third-year": 3,
              "third year": 3, "senior": 4, "fourth-year": 4, "fourth year": 4}
RULES = ("deadline", "level", "class_year", "graduation", "major", "gpa", "enrolment")
UNKNOWN = ("listing_only", "nih_rules", "gpa_unstated", "residency", "citizenship", "targeted",
           "level_unstated", "past_cycle_date",
           "class_year_unstated", "graduation_unstated", "major_unstated",
           "enrolment_unstated")
GAP_ORDER = ("transcript", "essay", "interview", "fafsa", "letters", "portfolio", "gpa")


@dataclass
class StudentFacts:
    level: str | None = None  # "bachelor's", "graduate", "associate", "professional", ...
    programme: str | None = None  # the line the level was read from, for display
    class_year: int | None = None  # undergraduates only
    major: str | None = None
    gpa: float | None = None
    enrolment: str | None = None  # "full-time" or "part-time"
    graduation: date | None = None  # expected; the first of the month stated
    degree_year: int | None = None  # year of the last completed degree
    honours: list[str] = field(default_factory=list)
    activities: list[str] = field(default_factory=list)
    posters: list[str] = field(default_factory=list)  # posters and talks
    employment: list[str] = field(default_factory=list)
    referees: int = 0
    portfolio: bool = False

    def summary(self) -> list[tuple[str, str]]:
        """What the parse read, as label and value, for the Profile screen."""
        rows = [("Level of study", self.level), ("Program", self.programme),
                ("Year", f"Year {self.class_year}" if self.class_year else None),
                ("Major", self.major), ("GPA", f"{self.gpa:.2f}" if self.gpa else None),
                ("Enrollment", self.enrolment),
                ("Expected graduation", self.graduation.strftime("%B %Y")
                 if self.graduation else None),
                ("Referees listed", str(self.referees) if self.referees else None)]
        return [(k, v) for k, v in rows if v]


def _level(line: str) -> str | None:
    low = line.lower()
    if re.search(r"\b(ph\.?\s?d|doctoral|doctorate|ed\.?d|dphil)\b", low):
        return "graduate"
    if re.search(r"\b(m\.?d\.?|j\.?d\.?|pharm\.?d|d\.?d\.?s|d\.?m\.?d|d\.?v\.?m|dpt)\b", low) \
            and "candidate" in low:
        return "professional"
    if re.search(r"\b(master|m\.?s\.?|m\.?a\.?|mph|mba|msw|m\.?ed|m\.?eng|mfa)\b", low):
        return "graduate"
    if re.search(r"\b(b\.?s\.?|b\.?a\.?|bachelor|bsn|b\.?f\.?a|undergraduate)\b", low):
        return "bachelor's"
    if re.search(r"\b(associate|a\.?a\.?s?|a\.?s\.?)\b", low):
        return "associate"
    if re.search(r"high school", low):
        return "high school"
    return None


def parse_student_cv(text: str) -> StudentFacts:
    """Read a student CV. Anything not found stays None, and the rules treat it as
    unknown ("may be eligible"), never as a pass."""
    secs = sections(text)
    f = StudentFacts()
    edu = [x for k, v in secs.items() if "education" in k for x in v]
    current = [x for x in edu if re.search(r"candidate|current|expected|in progress|student",
                                           x, re.I)]
    for line in current or edu[:1]:
        if lv := _level(line):
            f.level, f.programme = lv, line
            m = re.search(r",\s*([A-Z][A-Za-z &]+?)(?:\s*\(|,|$)", line)
            if m:
                f.major = m.group(1).strip()
            break
    blob = "\n".join(edu)
    if m := re.search(r"\bGPA\b[^0-9]{0,12}([0-4]\.\d{1,2})", blob, re.I):
        f.gpa = float(m.group(1))
    low = blob.lower()
    if "part-time" in low or "part time" in low:
        f.enrolment = "part-time"
    elif "full-time" in low or "full time" in low:
        f.enrolment = "full-time"
    if f.level == "bachelor's":
        f.class_year = next((n for w, n in YEAR_WORDS.items() if re.search(rf"\b{w}\b", low)),
                            None)
    if m := re.search(r"expected (?:graduation|completion)\W+([A-Za-z]+)\s+(\d{4})", blob,
                      re.I):
        mon = MONTHS.get(m.group(1).lower())
        if mon:
            f.graduation = date(int(m.group(2)), mon, 1)
    done = [int(y) for x in edu if not re.search(r"candida|expected", x, re.I)
            for y in re.findall(r"\b(19[6-9]\d|20\d\d)\b", x)]
    f.degree_year = max(done) if done else None
    pick = lambda *keys: [x for k, v in secs.items() if any(w in k for w in keys) for x in v]  # noqa: E731
    f.honours = pick("honour", "honor", "award")
    f.activities = pick("activit", "service", "volunteer", "leadership")
    f.posters = [x for x in pick("poster", "talk", "presentation", "research")
                 if re.search(r"poster|talk|presentation", x, re.I)]
    f.employment = pick("employment", "work experience", "experience")
    refs = pick("reference", "referee")
    f.referees = len([x for x in refs if not re.search(r"available|request", x, re.I)])
    f.portfolio = bool(pick("portfolio")) or bool(re.search(r"\bportfolio\b", text, re.I))
    return f


@dataclass
class Verdict:
    verdict: str  # "eligible", "may be eligible", "not eligible"
    reason: str | None  # the broken rule, or the first unknown
    lines: list[str] = field(default_factory=list)  # written by code, shown on the card
    unknown: list[str] = field(default_factory=list)
    # Q1 (S50): {"rule", "outcome": "pass"|"fail"|"unknown", "text"} for every rule run
    checks: list[dict[str, str]] = field(default_factory=list)


def _fmt(d: date) -> str:
    return day(d)  # as the cards show dates (U14)


def _major_ok(major: str, wanted: list[str]) -> bool:
    m = major.lower()
    return any(w.lower() in m or m in w.lower() for w in wanted)


# A criterion that opens with one of these reads after "a student who" (R11).
VERBS = {"is", "has", "was", "are", "have", "identifies", "grew", "lives", "lived", "works",
         "worked", "holds", "plans", "comes", "came", "speaks", "attends", "attended",
         "served", "serves", "belongs", "volunteers"}


def for_whom(criterion: str) -> str:
    """The record's targeted criterion as one sentence (R11): "is the first in their
    family..." reads "For a student who is the first...", and a noun phrase such as
    "first-generation college student" reads "For a first-generation college student."."""
    c = criterion.strip().rstrip(".")
    first = c.split(" ", 1)[0].lower()
    if first in VERBS:
        return f"For a student who {c}."
    if first in ("a", "an", "the", "any", "students", "applicants", "those", "people"):
        return f"For {c}."
    return f"For {'an' if first[:1] in 'aeiou' else 'a'} {c}."


def _and(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _levels(levels: list[str]) -> str:
    """G21: "associate degree and bachelor's", not "associate, bachelor's"."""
    return _and([f"{x} degree" if x == "associate" else x for x in levels])


def _years(years: list[int]) -> str:
    """G21: "years 1 and 2", not "year 1, 2"."""
    return (f"year {years[0]}" if len(years) == 1
            else "years " + _and([str(y) for y in years]))


# A Temple page's level tag, when the record has no level_of_study (S49 M2: empty on all
# 284 Temple-page awards). "mixed" sets no rule; "faculty" records are not in the pool.
# A professional-degree student (MD, JD) is a graduate student on these pages.
AUDIENCE_LEVELS: dict[str, list[str]] = {"undergraduate": ["bachelor's"],
                                         "graduate": ["graduate", "professional"]}
TEMPLE_SOURCES = ("temple_pages", "temple_sdfa")
# A Temple page date more than this many days old is from an earlier cycle: most of these
# awards recur yearly, so the verdict is "may be eligible", never "not eligible" (S49 M7,
# decided 2026-11-04). The date is still the page's own; nothing is inferred.
PAST_CYCLE_DAYS = 31


# G1, Q2 (S50): a Temple page that tags an award "mixed" or gives no tag sets no level, so a
# "Graduate Student Research Grant" passed for an undergraduate. The award's own name then
# decides, from the raw name (the bracket in "Film Award Fund (Graduate)" counts). A
# postdoctoral fellowship (F32, F33) is not a student award; an F31 or predoctoral
# fellowship filed under faculty is a graduate one. Training grants stay with faculty.
POSTDOC_NAME = re.compile(r"\bpost-?doctoral\b|\bpostdocs?\b|\bF3[23]\b", re.I)
PREDOC_NAME = re.compile(r"\bF31\b|\bpre-?doctoral fellowship", re.I)
INSTITUTIONAL = re.compile(r"\binstitutional\b|\btraining (?:grants?|awards?)\b", re.I)
UG_NAME = re.compile(r"\bundergraduates?\b", re.I)
GRAD_NAME = re.compile(r"\bgraduate\b|\bdoctoral\b|\bdissertation\b|\bmaster'?s\b|\bph\.?d\b",
                       re.I)


def name_level(name: str) -> str | None:
    """"postdoc", "graduate", "undergraduate" or None, from words in an award's name."""
    if POSTDOC_NAME.search(name):
        return "postdoc"
    if PREDOC_NAME.search(name) and not INSTITUTIONAL.search(name):
        return "graduate"
    ug, grad = UG_NAME.search(name), GRAD_NAME.search(name)
    if ug and grad:
        return None  # "Undergraduate and Graduate ...": open to both, so no rule
    return "undergraduate" if ug else "graduate" if grad else None


def audience_of(s: Scholarship) -> str | None:
    """The audience a Temple-page award is judged for: the page tag, or the award's name
    when the tag is "mixed" or absent (G1), or names a postdoc or F31 fellowship (Q2).
    A record that states its own levels, and every other source, keep the tag as it is."""
    tag = s.audience_level
    if s.source not in TEMPLE_SOURCES or s.level_of_study:
        return tag
    by_name = name_level(s.name)
    if by_name == "postdoc":
        return "postdoc"
    if tag == "faculty" and by_name == "graduate" and PREDOC_NAME.search(s.name):
        return "graduate"
    if tag in (None, "mixed") and by_name:
        return by_name
    return tag


def level_from_name(s: Scholarship) -> bool:
    return not s.level_of_study and audience_of(s) != s.audience_level


def study_levels(s: Scholarship) -> list[str]:
    if s.level_of_study:
        return list(s.level_of_study)
    return AUDIENCE_LEVELS.get(audience_of(s) or "", [])


def level_said(s: Scholarship, levels: list[str]) -> str:
    """The level as the record words it: its levels, the page tag, or the name's word."""
    if s.level_of_study:
        return f"{_levels(levels)} students"
    word = audience_of(s) or ""
    return f"{word} students, by the award's name" if level_from_name(s) else f"{word} students"


def past_cycle(s: Scholarship, as_of: date) -> bool:
    return bool(s.source in TEMPLE_SOURCES and s.deadline
                and (as_of - s.deadline).days > PAST_CYCLE_DAYS)


def past_cycle_line(d: date) -> str:
    return f"The page shows a past date, {_fmt(d)}. Check the page for this year's date."


# Q1, G6 (S50): each rule the check ran, or could not run, as one code-written line with its
# outcome, so a "may be eligible" card says what was checked. The rule keys, in card order.
CHECK_RULES = ("level", "class_year", "school", "citizenship", "residency", "deadline",
               "graduation", "major", "gpa", "enrolment", "targeted", "staff_only")
CHECK_LABELS = {"level": "level", "class_year": "year", "school": "school",
                "citizenship": "citizenship", "residency": "residency", "deadline": "deadline",
                "graduation": "graduation date", "major": "major", "gpa": "GPA",
                "enrolment": "enrollment", "targeted": "who it is for",
                "staff_only": "not a staff award"}
LISTING_TAIL = "The award's own page sets the full rules. Read it before applying."
QUOTE_CHARS = 300


def first_sentence(text: str, n: int = QUOTE_CHARS) -> str:
    """The first sentence of a page's own text, cut at a word past `n` characters."""
    s = re.split(r"(?<=[.!?])\s+", " ".join(text.split()), maxsplit=1)[0]
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + " …"


def check(s: Scholarship, f: StudentFacts, as_of: date) -> Verdict:
    """Eligibility by rule for one record. Every value in a line is copied from the
    record or the parsed CV. `Verdict.checks` holds every rule's outcome (Q1)."""
    e = s.eligibility
    broken: list[tuple[str, str]] = []
    unknown: list[tuple[str, str]] = []
    checks: list[dict[str, str]] = []

    def note(rule: str, outcome: str, text: str) -> None:
        checks.append({"rule": rule, "outcome": outcome, "text": text})

    if s.deadline and s.deadline < as_of:
        if past_cycle(s, as_of):
            unknown.append(("past_cycle_date", past_cycle_line(s.deadline)))
            note("deadline", "unknown", f"Deadline: {past_cycle_line(s.deadline)}")
        else:
            broken.append(("deadline", f"The deadline, {_fmt(s.deadline)}, has passed."))
            note("deadline", "fail", f"Deadline: {_fmt(s.deadline)}, which has passed.")
    elif s.deadline:
        note("deadline", "pass", f"Deadline: {_fmt(s.deadline)}, not yet passed.")
    elif s.deadline_quote:
        note("deadline", "unknown",
             f"Deadline: no date in the listing; the page says “{s.deadline_quote}”.")
    else:
        note("deadline", "unknown", "Deadline: the listing gives no date.")
    levels = study_levels(s)
    if levels:
        said = level_said(s, levels)
        if not f.level:
            unknown.append(("level_unstated", "Your CV does not say your level of study."))
            note("level", "unknown", f"Level: open to {said}; your CV does not say yours.")
        elif f.level not in levels:
            broken.append(("level", f"Open to {said}; your CV says {f.level}."))
            note("level", "fail", f"Level: open to {said}; your CV says {f.level}.")
        else:
            note("level", "pass", f"Level: open to {said}; your CV says {f.level}.")
    else:
        note("level", "unknown", "Level: the listing does not state one.")
    if e.class_year and f.level == "bachelor's":
        years = _years(e.class_year)
        if f.class_year is None:
            unknown.append(("class_year_unstated",
                            f"Open to undergraduate {years}; your CV does not say "
                            "your year."))
            note("class_year", "unknown",
                 f"Year: open to undergraduate {years}; your CV does not say your year.")
        elif f.class_year not in e.class_year:
            broken.append(("class_year", f"Open to undergraduate {years}; your CV says "
                                         f"year {f.class_year}."))
            note("class_year", "fail",
                 f"Year: open to undergraduate {years}; your CV says year {f.class_year}.")
        else:
            note("class_year", "pass",
                 f"Year: open to undergraduate {years}; your CV says year {f.class_year}.")
    if e.graduation_by or e.graduation_after:
        if not f.graduation:
            unknown.append(("graduation_unstated",
                            "The record limits graduation dates; your CV gives none."))
            note("graduation", "unknown",
                 "Graduation date: the record limits it; your CV gives none.")
        elif e.graduation_by and f.graduation > e.graduation_by:
            broken.append(("graduation", f"You must graduate by {_fmt(e.graduation_by)}; your "
                                         f"CV says {f.graduation.strftime('%B %Y')}."))
            note("graduation", "fail", f"Graduation date: {broken[-1][1]}")
        elif e.graduation_after and f.graduation < e.graduation_after:
            broken.append(("graduation", f"You must graduate on or after "
                                         f"{_fmt(e.graduation_after)}; your CV says "
                                         f"{f.graduation.strftime('%B %Y')}."))
            note("graduation", "fail", f"Graduation date: {broken[-1][1]}")
        else:
            note("graduation", "pass", "Graduation date: your CV's date is within the record's "
                                       f"limits ({f.graduation.strftime('%B %Y')}).")
    if e.major:
        majors = ", ".join(e.major)
        if not f.major:
            unknown.append(("major_unstated", f"Open to {majors} majors; your CV "
                                              "does not name a major."))
            note("major", "unknown", f"Major: open to {majors} majors; your CV names none.")
        elif not _major_ok(f.major, e.major):
            broken.append(("major", f"Open to {majors} majors; your CV says {f.major}."))
            note("major", "fail", f"Major: open to {majors} majors; your CV says {f.major}.")
        else:
            note("major", "pass", f"Major: open to {majors} majors; your CV says {f.major}.")
    if e.gpa_min is not None:
        ask = f"asks for at least {e.gpa_min:.2f}"
        if f.gpa is None:
            unknown.append(("gpa_unstated", f"Asks for a GPA of at least {e.gpa_min:.2f}; your "
                                            "CV does not state one."))
            note("gpa", "unknown", f"GPA: {ask}; your CV does not state one.")
        elif f.gpa < e.gpa_min:
            broken.append(("gpa", f"Asks for a GPA of at least {e.gpa_min:.2f}; your CV says "
                                  f"{f.gpa:.2f}."))
            note("gpa", "fail", f"GPA: {ask}; your CV says {f.gpa:.2f}.")
        else:
            note("gpa", "pass", f"GPA: {ask}; your CV says {f.gpa:.2f}.")
    if e.enrolment_status in ("full-time", "part-time"):
        st = e.enrolment_status
        if not f.enrolment:
            unknown.append(("enrolment_unstated", f"Open to {st} students; "
                                                  "your CV does not say which you are."))
            note("enrolment", "unknown",
                 f"Enrollment: open to {st} students; your CV does not say which you are.")
        elif f.enrolment != st:
            broken.append(("enrolment", f"Open to {st} students; your CV says "
                                        f"{f.enrolment}."))
            note("enrolment", "fail", f"Enrollment: open to {st} students; your CV says "
                                      f"{f.enrolment}.")
        else:
            note("enrolment", "pass", f"Enrollment: open to {st} students; your CV says "
                                      f"{f.enrolment}.")
    if e.residency_state:
        unknown.append(("residency", f"For residents of {e.residency_state}. You decide if "
                                     "this applies."))
        note("residency", "unknown",
             f"Residency: for residents of {e.residency_state}. You decide if this applies.")
    if e.citizenship:
        unknown.append(("citizenship", f"Asks for: {e.citizenship}. You decide if this "
                                       "applies."))
        note("citizenship", "unknown",
             f"Citizenship: asks for {e.citizenship}. You decide if this applies.")
    elif s.international_ok is True:
        note("citizenship", "pass", "Citizenship: the listing says international students "
                                    "may apply.")
    elif s.international_ok is False:
        note("citizenship", "unknown", "Citizenship: the listing says international students "
                                       "may not apply. You decide if this applies.")
    elif not e.residency_state:
        note("citizenship", "unknown",
             "Citizenship or residency: the listing states no rule; the award's page may.")
    if e.targeted_criterion:
        unknown.append(("targeted", f"{for_whom(e.targeted_criterion)} You decide if this "
                                    "applies."))
        note("targeted", "unknown",
             f"Who it is for: {for_whom(e.targeted_criterion)} You decide if this applies.")
    if s.source in TEMPLE_SOURCES:
        if s.scope == "school" and s.schools:
            note("school", "unknown", f"School: open to students of {_and(s.schools)}; Perch "
                                      "does not know your school.")
        elif s.scope == "temple_wide":
            note("school", "pass", "School: open across Temple.")
    staff = audience_of(s) in NOT_STUDENTS or norm_name(s.name) in STAFF_AWARDS
    note("staff_only", "fail" if staff else "pass",
         "Staff only: listed for staff or faculty, not students." if staff
         else "Students: not a staff or faculty award.")
    checks.sort(key=lambda c: CHECK_RULES.index(c["rule"]))
    if broken:
        broken.sort(key=lambda b: RULES.index(b[0]))
        return Verdict("not eligible", broken[0][0], [broken[0][1]], checks=checks)
    if unknown:
        return Verdict("may be eligible", unknown[0][0], [u[1] for u in unknown],
                       [u[0] for u in unknown], checks=checks)
    if s.source != "synthetic":  # a public listing names who may apply, not its full rules
        return Verdict("may be eligible", "listing_only", listing_lines(s, checks),
                       ["listing_only"], checks=checks)
    return Verdict("eligible", None, ["Meets every rule Perch checks."], checks=checks)


def listing_lines(s: Scholarship, checks: list[dict[str, str]]) -> list[str]:
    """G6: a listing that rules nothing out says what Perch checked, quotes the listing's
    own eligibility sentence when it has one, and sends the student to the award's page."""
    passed = [CHECK_LABELS[c["rule"]] for c in checks
              if c["outcome"] == "pass" and c["rule"] != "staff_only"]
    lines = [f"Perch checked {_and(passed)}; nothing there rules you out." if passed
             else "The listing states no rule Perch can check against your CV."]
    if s.eligibility.notes:
        lines.append(f"The listing says: “{first_sentence(s.eligibility.notes)}”")
    return [*lines, LISTING_TAIL]


def gaps(s: Scholarship, f: StudentFacts) -> list[tuple[str, str]]:
    """Requirements the CV does not show, as (key, line), in GAP_ORDER."""
    r = s.application_requirements
    out: list[tuple[str, str]] = []
    if r:
        if r.transcript:
            out.append(("transcript", "A transcript"))
        if r.essay:
            out.append(("essay", "An essay"))
        if r.interview:
            out.append(("interview", "An interview"))
        if r.fafsa:
            out.append(("fafsa", "A FAFSA on file"))
        if r.letters_count > f.referees:
            n = r.letters_count
            out.append(("letters", f"{n} letter{'s' if n > 1 else ''} of recommendation; your "
                                   f"CV lists {f.referees} referee"
                                   f"{'' if f.referees == 1 else 's'}"))
        if r.portfolio and not f.portfolio:
            out.append(("portfolio", "A portfolio"))
    if s.eligibility.gpa_min is not None and f.gpa is None:
        out.append(("gpa", f"A GPA of at least {s.eligibility.gpa_min:.2f}; your CV states none"))
    return out


# --- NIH fellowships (public Grants.gov records) under the same rules ---

def nih_as_scholarship(o: Opportunity) -> Scholarship:
    """An NIH F-series graduate listing seen through the student rules: level graduate,
    its close date as the deadline. Only the rule inputs are filled."""
    return Scholarship(id=o.id, source=o.source, source_url=o.source_url,
                       fetched_at=o.fetched_at, name=o.title, sponsor=o.agency,
                       purpose=o.description, level_of_study=["graduate"],
                       award_type="fellowship", deadline=o.close_date)


def check_nih(o: Opportunity, f: StudentFacts, as_of: date) -> Verdict:
    level = NIH_FELLOWSHIP_LEVEL.get(o.activity_code or "")
    if level != "graduate":
        line = f"{o.activity_code} is a {level} fellowship, not one for students."
        return Verdict("not eligible", "level", [line],
                       checks=[{"rule": "level", "outcome": "fail", "text": f"Level: {line}"}])
    v = check(nih_as_scholarship(o), f, as_of)
    from perch.datefmt import closes, no_deadline

    if no_deadline(o, as_of) and o.close_date:  # T17, G8: an expiry or placeholder is no deadline
        v.checks = [c if c["rule"] != "deadline" else
                    {"rule": "deadline", "outcome": "unknown",
                     "text": f"Deadline: none in the notice ({closes(o, as_of)})."}
                    for c in v.checks]
    if v.reason == "listing_only":  # NIH rules (citizenship, sponsor, institution) not read
        return Verdict("may be eligible", "nih_rules",
                       ["Open to graduate students. NIH sets further rules in the notice; "
                        "read it before applying."], ["nih_rules"], checks=v.checks)
    return v


# --- the student brief's stages (moved from perch/private/student.py in S42) ---
#
# A student's input is the CV, an interests note and a list of achievements, all read from
# the user's encrypted rows (or, for a guest, from the SYNTHETIC persona). Each route embeds,
# takes the nearest RETRIEVE by cosine to the query thread, reranks them, then checks every
# one by rule. Leads keep the TOP best that are not ruled out; the ruled-out ones among those
# retrieved are kept too, ranked after, so the student sees why.

STUDENT_STAGES = ("student_profile", "fellowships", "scholarships", "student_explanations")
# 40 until S27: the SYNTHETIC student bench retrieved 23 of 24 planted records at 100, 19 at 40.
RETRIEVE = 100
TOP = 10
SAMPLE_BADGE = "Sample data: an invented record, not a real scholarship"
YOU = "user:you"  # the "researcher" of a brief with no public profile


def achievements(text: str) -> list[str]:
    """The numbered or bulleted items of the achievements note, at most five."""
    items = [m.group(1).strip() for m in re.finditer(
        r"(?ms)^\s*(?:\d+[.)]|[-*•])\s+(.+?)(?=^\s*(?:\d+[.)]|[-*•])\s+|\Z)", text)]
    items = [" ".join(i.split()) for i in items if len(i.split()) >= 3]
    if not items:
        items = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.split()) >= 3][1:]
    return items[:5]


ENTRY_TITLE = "Your entry"
ENTRIES_TITLE = "One of your entries"
INTERESTS_TITLE = "Your interests note"


def achievement_docs(items: list[str], fetched_at: datetime | None = None) -> list[UserDoc]:
    """One citable record per achievement (`user:achievement-a`, ...). `items` are the
    achievements as separate texts, such as a user's entries; `fetched_at` is their time.
    S51 H9: the title the text shows is "Your entry", or "One of your entries" when there
    are several; "Your achievement A" named a letter the student never sees."""
    at = fetched_at or utcnow()
    title = ENTRY_TITLE if len(items[:5]) == 1 else ENTRIES_TITLE
    return [UserDoc(id=f"user:achievement-{chr(97 + i)}", source="user",
                    source_url="perch://user", fetched_at=at,
                    title=title, type="user", abstract=a)
            for i, a in enumerate(items[:5])]


# S51 H4: 43 Temple pages give only an award's name. A model asked about one wrote "The
# record names ... and gives no further detail", which MiniCheck flagged every time. Such a
# listing gets this code-written line instead of a model call.
NAME_ONLY_NOTE = "This listing gives only the award’s name. Read its page for what it funds."
CANARY_TAIL = re.compile(r"\s*SYNTHETIC sample record, canary \S+$")


def name_only(s: Scholarship) -> bool:
    """No purpose (after the canary tail), no eligibility notes and no field of study."""
    return not (CANARY_TAIL.sub("", s.purpose or "").strip() or (s.eligibility.notes or "").strip()
                or s.field_of_study)


def record_text(s: Scholarship) -> str:
    """What is embedded and reranked: name, sponsor, purpose without its canary line,
    fields and the page notes."""
    purpose = CANARY_TAIL.sub("", s.purpose or "")
    parts = [s.name, s.sponsor or "", purpose, ", ".join(s.field_of_study),
             ", ".join(s.level_of_study), s.eligibility.notes or ""]
    return ". ".join(p for p in parts if p)


def short_id(record_id: str) -> str:
    return record_id.split(":", 1)[-1]


def as_opportunity(s: Scholarship) -> Opportunity:
    """A scholarship in the shape skill 2 reads. The citation id is the record's short
    id; amounts and the deadline are copied, so the validator can check them."""
    return Opportunity(id=s.id, source=s.source, source_url=s.source_url,
                       fetched_at=s.fetched_at, opportunity_number=short_id(s.id),
                       title=s.name, agency=s.sponsor or "", close_date=s.deadline,
                       award_ceiling=s.amount_max, award_floor=s.amount_min,
                       deadline_quote=s.deadline_quote, amount_quote=s.amount_quote,
                       details_url=s.details_url, details_fetched_at=s.details_fetched_at,
                       description=record_text(s))


@dataclass
class Scored:
    record: Scholarship
    opp: Opportunity | None  # the NIH listing behind a fellowship, if any
    score: float
    verdict: Verdict
    also_on: list[str] = field(default_factory=list)  # other pages listing the same award


# Awards for staff that Temple's pages file with the student scholarships (S49 M8),
# reviewed by hand on 2026-11-04 from the stored Temple-page records. Normalised names.
STAFF_AWARDS = frozenset({"faculty advisor", "new advisor", "outstanding advising program award",
                          "professional advisor", "michele o connor advising service award"})
NOT_STUDENTS = ("faculty", "postdoc")


def norm_name(name: str) -> str:
    n = name.lower().replace("&", " and ")
    n = re.sub(r"\([^)]*\)", " ", n)
    n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    return " ".join(re.sub(r"^the ", "", n).split())


def _filled(s: Scholarship) -> int:
    return len(s.model_dump(exclude_defaults=True))


# G2 (S50): copies of one award carry names that differ only in a plural, "Program",
# "Scholarship(s)" or a bracket ("Diamond Research Scholars" and "Diamond Research Scholars
# Program"; "Rhodes" and "Rhodes Scholarship"). The key drops those words.
KEY_WORDS = re.compile(r"\b(?:programs?|scholarships?|scholars?|awards?)\b")
# Names whose keys match but which may be different awards, reviewed by hand on 2026-11-05
# from the deploy store's Temple-page records: a Rome-campus programme scholarship and a
# degree-level one; Temple's need-based grant and the tuition-remission page's entry.
DISTINCT_AWARDS = frozenset({"bachelor s degree", "temple university grant"})


def award_key(name: str) -> str:
    k = KEY_WORDS.sub(" ", norm_name(name))
    return " ".join(re.sub(r"s$", "", w) if len(w) > 3 else w for w in k.split())


def _keep(group: list[Scholarship]) -> Scholarship:
    """The copy a merged group shows: the fellowships office's when it lists the award (its
    level and class year are the reviewed ones, G2), else the copy with the most fields, and
    on a tie the broader audience, so a narrow page tag never rules a student out alone."""
    office = [s for s in group if s.source == "temple_sdfa"]
    return max(office or group, key=lambda s: (_filled(s), s.audience_level in (None, "mixed"),
                                               s.id))


def student_pool(records: list[Scholarship]) -> tuple[list[Scholarship], dict[str, list[str]]]:
    """The records a student brief may rank, and {kept id: other pages listing it}.
    Leaves out staff and faculty awards (M8). Copies of one award, on Temple pages or by the
    fellowships office, under names that share `award_key`, are one award (S7, G2): one copy
    is kept (`_keep`) and the others' pages are listed under it. DISTINCT_AWARDS stay apart."""
    pool = [s for s in records if audience_of(s) not in NOT_STUDENTS
            and norm_name(s.name) not in STAFF_AWARDS]
    by_name: dict[str, list[Scholarship]] = {}
    for s in pool:
        if s.source in TEMPLE_SOURCES and (k := award_key(s.name)) not in DISTINCT_AWARDS:
            by_name.setdefault(k, []).append(s)
    drop: set[str] = set()
    also: dict[str, list[str]] = {}
    for group in by_name.values():
        if len(group) < 2:
            continue
        keep = _keep(group)
        others = [s for s in group if s.id != keep.id]
        drop |= {s.id for s in others}
        also[keep.id] = [s.source_url for s in others]
        if (with_amount := _carry_amount(keep, others)) is not keep:
            pool = [with_amount if s.id == keep.id else s for s in pool]
    return [s for s in pool if s.id not in drop], also


def _carry_amount(keep: Scholarship, others: list[Scholarship]) -> Scholarship:
    """S51 H6: the kept copy of a merged award states no amount but the dropped copies agree
    on one: carry it over with its sentence and page, as temple_dedupe.merge does at build
    time. Not when the kept copy already cites another page (its deadline's), since one
    details_url cannot hold both; the record validator still checks the result (rule 3)."""
    if keep.amount_min is not None or keep.amount_max is not None:
        return keep
    have = [s for s in others if s.amount_min is not None or s.amount_max is not None]
    if not have or len({(s.amount_min, s.amount_max) for s in have}) != 1:
        return keep
    src = have[0]
    url = src.details_url or src.source_url
    if keep.details_url and keep.details_url != url:
        return keep
    try:
        return Scholarship.model_validate({
            **keep.model_dump(), "amount_min": src.amount_min, "amount_max": src.amount_max,
            "amount_quote": src.amount_quote, "details_url": url,
            "details_fetched_at": keep.details_fetched_at or src.details_fetched_at
            or src.fetched_at})
    except ValueError:
        return keep


def student_profile(facts: StudentFacts, interests: UserDoc | None, achieved: list[UserDoc],
                    embedder: object, as_of: date) -> Profile:
    """One query thread from the interests note (or the achievements without one); the
    achievements ride on it as records an explanation may cite."""
    query_docs = [interests] if interests else achieved
    text = "\n\n".join(d.abstract or "" for d in query_docs)
    if facts.major:
        text = f"{facts.major}. {text}"
    vec = normalise(embedder.embed_queries([text]).mean(0, keepdims=True))[0]
    ids = [d.id for d in ([interests] if interests else []) + achieved]
    from perch.threads import label

    return Profile(YOU, as_of, getattr(embedder, "name", "embedder"),
                   [Thread(0, vec, ids, 1.0, label(text), [text[:600]])], ids)


def rank(records: list[Scholarship], profile: Profile, embedder: object, reranker: object,
         judge: callable, retrieve: int = RETRIEVE) -> list[Scored]:
    """Cosine to the query thread, the nearest `retrieve` reranked, every one judged.
    Records outside the student pool (staff awards, duplicates) are left out first."""
    records, also = student_pool(records)
    if not records:
        return []
    texts = [record_text(s) for s in records]
    docs = normalise(np.asarray(embedder.embed_documents(texts)))
    sims = docs @ profile.threads[0].vector
    near = list(np.argsort(-sims)[:retrieve])
    scores = reranker.score(profile.threads[0].titles[0], [texts[i] for i in near])
    out = [Scored(records[i], None, float(sc), judge(records[i]), also.get(records[i].id, []))
           for i, sc in zip(near, scores, strict=True)]
    return sorted(out, key=lambda x: -x.score)


RULED_OUT_SHOWN = 5  # S49 S10: every ruled-out record among 100 retrieved was too many


def choose(scored: list[Scored], top: int = TOP, ruled_out: int = RULED_OUT_SHOWN
           ) -> list[Scored]:
    """The best `top` not ruled out, then the best `ruled_out` ruled-out ones, so the
    student sees why."""
    ok = [x for x in scored if x.verdict.verdict != "not eligible"][:top]
    out = [x for x in scored if x.verdict.verdict == "not eligible"][:ruled_out]
    return ok + out


# A guest's brief reads the SYNTHETIC sample student's CV, not the viewer's: its rule lines
# say so (S43 S8, S50 QA). Ordered: the longer phrases first.
SAMPLE_WORDS = [
    (re.compile(r"\byour CV does not say yours\b"), "the sample student's CV does not say theirs"),
    (re.compile(r"\byour CV\b"), "the sample student's CV"),
    (re.compile(r"\bYour CV\b"), "The sample student's CV"),
    (re.compile(r"\byour (year|school|level of study)\b"), r"their \1"),
    (re.compile(r"\bwhich you are\b"), "which they are"),
    (re.compile(r"\brules you out\b"), "rules the sample student out"),
    (re.compile(r"\bOne of your entries\b"), "One of the sample student's entries"),
    (re.compile(r"\bone of your entries\b"), "one of the sample student's entries"),
    (re.compile(r"\bYour entry\b"), "The sample student's entry"),
    (re.compile(r"\bYour interests note\b"), "The sample student's interests note"),
    (re.compile(r"\bYou must graduate\b"), "The sample student must graduate"),
]


def for_sample(text: str) -> str:
    """A rule line reworded for the sample student: "your CV" becomes theirs."""
    for pat, rep in SAMPLE_WORDS:
        text = pat.sub(rep, text)
    return text


def to_leads(brief_id: str, route: str, chosen: list[Scored], facts: StudentFacts,
             start: int = 1, sample: bool = False) -> list[Lead]:
    """`sample`: the facts are the SYNTHETIC sample student's, so the lines name them."""
    say = for_sample if sample else (lambda t: t)
    leads = []
    for i, x in enumerate(chosen, start):
        s, v = x.record, x.verdict
        g = gaps(s, facts) if v.verdict != "not eligible" and not x.opp else []
        src = x.opp or s
        leads.append(Lead(
            id=f"{brief_id}:{route}{i}", source=src.source, source_url=src.source_url,
            fetched_at=src.fetched_at, brief_id=brief_id, route=route, record_id=src.id,
            rank=i, rerank_score=round(x.score, 4), match_score=match_score(x.score),
            verdict=v.verdict,
            verdict_reason=v.reason, verdict_lines=[say(t) for t in v.lines],
            checks=[{**c, "text": say(c["text"])} for c in v.checks],
            gaps=[say(t) for _, t in g],
            gap_keys=[k for k, _ in g], sample=s.synthetic,
            notes=[f"Also listed on {u}" for u in x.also_on]))
    return leads


def judge_for(facts: StudentFacts, as_of: date, nih: dict[str, Opportunity]) -> callable:
    def judge(s: Scholarship) -> Verdict:
        if s.id in nih:
            return check_nih(nih[s.id], facts, as_of)
        return check(s, facts, as_of)
    return judge


def nih_records(repo: object) -> dict[str, tuple[Scholarship, Opportunity]]:
    """NIH F-series listings as rule inputs, keyed by the listing id."""
    out = {}
    for o in repo.list(Opportunity):
        if (o.activity_code or "") not in NIH_FELLOWSHIP_LEVEL or o.status == "forecasted":
            continue  # G13: a forecast is not yet open; Help says forecasts are not shown
        s = Scholarship(id=o.id, source=o.source, source_url=o.source_url,
                        fetched_at=o.fetched_at, name=o.title, sponsor=o.agency,
                        purpose=(o.description or "")[:1500], award_type="fellowship",
                        deadline=o.close_date)
        out[o.id] = (s, o)
    return out


def samples() -> list[Scholarship]:
    """The SYNTHETIC sample scholarships (rule 11): a list of their own, never mixed with
    public records in any count."""
    from perch.scholarships import ensure_samples

    try:
        return sample_records()
    except RuntimeError:  # a worker host that has not loaded the store yet: build it from the file
        ensure_samples()
        return sample_records()

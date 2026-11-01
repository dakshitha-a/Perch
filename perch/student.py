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
from datetime import date

from perch.datefmt import day
from perch.private.cv import sections
from perch.schemas import Opportunity, Scholarship

MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november "
    "december".split(), 1)}
YEAR_WORDS = {"first-year": 1, "freshman": 1, "first year": 1, "sophomore": 2,
              "second-year": 2, "second year": 2, "junior": 3, "third-year": 3,
              "third year": 3, "senior": 4, "fourth-year": 4, "fourth year": 4}
RULES = ("deadline", "level", "class_year", "graduation", "major", "gpa", "enrolment")
UNKNOWN = ("listing_only", "nih_rules", "gpa_unstated", "residency", "citizenship", "targeted",
           "level_unstated",
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
        """What the parse read, as label and value, for the Profile screen (private)."""
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


def check(s: Scholarship, f: StudentFacts, as_of: date) -> Verdict:
    """Eligibility by rule for one record. Every value in a line is copied from the
    record or the parsed CV."""
    e = s.eligibility
    broken: list[tuple[str, str]] = []
    unknown: list[tuple[str, str]] = []
    if s.deadline and s.deadline < as_of:
        broken.append(("deadline", f"The deadline, {_fmt(s.deadline)}, has passed."))
    if s.level_of_study:
        if not f.level:
            unknown.append(("level_unstated", "Your CV does not say your level of study."))
        elif f.level not in s.level_of_study:
            broken.append(("level", f"Open to {_levels(s.level_of_study)} students; your CV "
                                    f"says {f.level}."))
    if e.class_year and f.level == "bachelor's":
        years = _years(e.class_year)
        if f.class_year is None:
            unknown.append(("class_year_unstated",
                            f"Open to undergraduate {years}; your CV does not say "
                            "your year."))
        elif f.class_year not in e.class_year:
            broken.append(("class_year", f"Open to undergraduate {years}; your CV says "
                                         f"year {f.class_year}."))
    if e.graduation_by or e.graduation_after:
        if not f.graduation:
            unknown.append(("graduation_unstated",
                            "The record limits graduation dates; your CV gives none."))
        elif e.graduation_by and f.graduation > e.graduation_by:
            broken.append(("graduation", f"You must graduate by {_fmt(e.graduation_by)}; your "
                                         f"CV says {f.graduation.strftime('%B %Y')}."))
        elif e.graduation_after and f.graduation < e.graduation_after:
            broken.append(("graduation", f"You must graduate on or after "
                                         f"{_fmt(e.graduation_after)}; your CV says "
                                         f"{f.graduation.strftime('%B %Y')}."))
    if e.major:
        if not f.major:
            unknown.append(("major_unstated", f"Open to {', '.join(e.major)} majors; your CV "
                                              "does not name a major."))
        elif not _major_ok(f.major, e.major):
            broken.append(("major", f"Open to {', '.join(e.major)} majors; your CV says "
                                    f"{f.major}."))
    if e.gpa_min is not None:
        if f.gpa is None:
            unknown.append(("gpa_unstated", f"Asks for a GPA of at least {e.gpa_min:.2f}; your "
                                            "CV does not state one."))
        elif f.gpa < e.gpa_min:
            broken.append(("gpa", f"Asks for a GPA of at least {e.gpa_min:.2f}; your CV says "
                                  f"{f.gpa:.2f}."))
    if e.enrolment_status in ("full-time", "part-time"):
        if not f.enrolment:
            unknown.append(("enrolment_unstated", f"Open to {e.enrolment_status} students; "
                                                  "your CV does not say which you are."))
        elif f.enrolment != e.enrolment_status:
            broken.append(("enrolment", f"Open to {e.enrolment_status} students; your CV says "
                                        f"{f.enrolment}."))
    if e.residency_state:
        unknown.append(("residency", f"For residents of {e.residency_state}. You decide if "
                                     "this applies."))
    if e.citizenship:
        unknown.append(("citizenship", f"Asks for: {e.citizenship}. You decide if this "
                                       "applies."))
    if e.targeted_criterion:
        unknown.append(("targeted", f"{for_whom(e.targeted_criterion)} You decide if this "
                                    "applies."))
    if broken:
        broken.sort(key=lambda b: RULES.index(b[0]))
        return Verdict("not eligible", broken[0][0], [broken[0][1]])
    if unknown:
        return Verdict("may be eligible", unknown[0][0], [u[1] for u in unknown],
                       [u[0] for u in unknown])
    if s.source != "synthetic":  # a public listing names who may apply, not its full rules
        return Verdict("may be eligible", "listing_only",
                       ["The listing says who may apply; the award's own page sets the full "
                        "rules. Read it before applying."], ["listing_only"])
    return Verdict("eligible", None, ["Meets every rule Perch checks."])


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
    from perch.scholarships import NIH_FELLOWSHIP_LEVEL

    level = NIH_FELLOWSHIP_LEVEL.get(o.activity_code or "")
    if level != "graduate":
        return Verdict("not eligible", "level",
                       [f"{o.activity_code} is a {level} fellowship, not one for students."])
    v = check(nih_as_scholarship(o), f, as_of)
    if v.reason == "listing_only":  # NIH rules (citizenship, sponsor, institution) not read
        return Verdict("may be eligible", "nih_rules",
                       ["Open to graduate students. NIH sets further rules in the notice; "
                        "read it before applying."], ["nih_rules"])
    return v

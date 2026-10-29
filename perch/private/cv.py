"""Deterministic CV parse for private mode. Never a model.

Reads the doctoral degree year, the current rank, the appointments, the sponsors of
listed funding, and whether a substantial NIH research award is listed. Used for two
rules, both shown on the lead as private and both written by code:

- Career-stage unlock: NIH defines an early-stage investigator as someone within 10
  years of their terminal research degree or the end of post-graduate clinical
  training, whichever is later, who has not competed successfully as PD/PI for a
  substantial NIH independent research award (ESI_URL, read 2026-10-29). The parse
  reads the degree year and NIH awards only. It cannot see clinical training or an
  extension, so a lead is marked "may be eligible", never "eligible".
- Sponsor history: an opportunity from an agency the CV lists as a past sponsor moves up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

ESI_URL = "https://grants.nih.gov/policy-and-compliance/policy-topics/early-stage-investigators"
ESI_YEARS = 10
DOCTORATE = re.compile(r"\b(Ph\.?\s?D|M\.?D|Sc\.?D|DrPH|Dr\.?P\.?H|Ed\.?D|D\.?Phil|PharmD|DVM|"
                       r"DNP|DPT|DDS|DMD|Psy\.?D|J\.?D)\b", re.I)
YEAR = re.compile(r"\b(19[5-9]\d|20\d\d)\b")
RANKS = ["Distinguished Professor", "Associate Professor", "Assistant Professor",
         "Research Professor", "Professor", "Instructor", "Research Scientist",
         "Postdoctoral Fellow", "Postdoctoral Researcher", "Lecturer"]
# NIH activity codes a PD/PI can hold and still be an ESI, copied from NIH's "List of
# Smaller Grants & Awards that Maintain ESI Status" (SMALLER_URL, read 2026-10-29); F and
# K awards are on it as whole series. Any other NIH activity code on the CV counts as
# a possible substantial award, so the unlock is not offered.
SMALLER_URL = ESI_URL + "/list-smaller-grants"
ESI_KEEPS = set("""R00 R03 R15 UA5 R16 R21 R25 R90 RL9 RL5 R34 R36 R41 UT1 R42 UT2 R43 U43 R44
U44 R50 R55 R56 R61 RL2 SB1 SC2 SC3 U09 U34 X01 X02 D71 R38 D43 T32 T34 T35 T90 TL4 C06 G07
G08 G11 G13 G20 R13 U13 S10 S15 S21 S22 UC6 PC1 PC2 OT1 OT2 OT3""".split())
NIH_CODE = re.compile(r"\b([A-Z][A-Z0-9]\d)(?=\b|[A-Z]{2}\d)")  # R01, DP2, R01GM...
SPONSORS = {  # sponsor name as it may appear on a CV -> the agency text used to match
    "NIH": ("nih", "national institutes of health"),
    "NSF": ("nsf", "national science foundation"),
    "DOD": ("dod", "department of defense"),
    "DOE": ("doe", "department of energy"),
    "NASA": ("nasa",),
    "AHRQ": ("ahrq", "agency for healthcare research", "agency for health care research"),
    "CDC": ("cdc", "centers for disease control"),
    "USDA": ("usda", "department of agriculture"),
    "NEH": ("neh", "national endowment for the humanities"),
}
NEGATION = re.compile(r"\b(no|not|never|none)\b", re.I)


@dataclass
class CVFacts:
    degree_year: int | None = None
    rank: str | None = None
    appointments: list[str] = field(default_factory=list)
    sponsors: list[str] = field(default_factory=list)  # keys of SPONSORS
    nih_substantial: list[str] = field(default_factory=list)  # activity codes found
    institutions: list[str] = field(default_factory=list)  # for masking
    names: list[str] = field(default_factory=list)  # for masking

    def esi_possible(self, as_of: date) -> bool:
        return (self.degree_year is not None and as_of.year - self.degree_year <= ESI_YEARS
                and not self.nih_substantial)

    def esi_note(self) -> str:
        return (f"May be eligible as an early-stage investigator per your CV (private): "
                f"doctorate {self.degree_year}, no substantial NIH award listed. NIH's rule "
                f"also counts clinical training and extensions; check {ESI_URL}")


def sections(text: str) -> dict[str, list[str]]:
    """Lines under each heading, keyed by the heading in lower case."""
    out: dict[str, list[str]] = {"": []}
    cur = ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        h = re.match(r"^(#+\s*|)([A-Za-z][A-Za-z &/,-]{2,40}?):?\s*$", s)
        if h and (h.group(1) or s.isupper() or s.endswith(":")):
            cur = h.group(2).strip().lower()
            out.setdefault(cur, [])
            continue
        out[cur].append(s.lstrip("-*• ").strip())
    return out


def _find(secs: dict[str, list[str]], *keys: str) -> list[str]:
    return [x for k, v in secs.items() if any(w in k for w in keys) for x in v]


def parse_cv(text: str) -> CVFacts:
    secs = sections(text)
    f = CVFacts()
    edu = _find(secs, "education", "degree", "training") or [x for v in secs.values() for x in v]
    years = [int(m.group(1)) for line in edu if DOCTORATE.search(line)
             for m in [max(YEAR.finditer(line), key=lambda m: m.start(), default=None)] if m]
    f.degree_year = max(years) if years else None
    f.appointments = _find(secs, "appointment", "position", "employment", "experience")
    for line in f.appointments:
        if re.search(r"present|current|now", line, re.I) or line is f.appointments[0]:
            f.rank = next((r for r in RANKS if r.lower() in line.lower()), f.rank)
            if f.rank:
                break
    funding = _find(secs, "funding", "grant", "support", "award")
    for line in funding:
        if NEGATION.search(line):
            continue
        low = line.lower()
        for key, names in SPONSORS.items():
            if any(re.search(rf"\b{re.escape(n)}\b", low) for n in names) and key not in f.sponsors:
                f.sponsors.append(key)
        f.nih_substantial += [c for c in NIH_CODE.findall(line)
                              if c not in ESI_KEEPS and c[0] not in "FK"
                              and c not in f.nih_substantial]
    for line in [*edu, *f.appointments]:
        for part in re.split(r",", line):
            p = part.strip()
            if re.search(r"\b(University|Institute|College|School|Hospital|Center|Lab)\b", p):
                f.institutions.append(p)
    title = next((line for line in text.splitlines() if line.strip()), "")
    m = re.search(r"(?:Dr\.?\s+)?([A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-z]+)", title.split("—")[-1])
    if m:
        f.names.append(m.group(1))
    return f


def sponsor_match(agency: str, sponsors: list[str]) -> str | None:
    low = agency.lower()
    return next((k for k in sponsors if any(n in low for n in SPONSORS[k])), None)

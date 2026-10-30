"""Deterministic eligibility rules for Route A. Never a model.

Every rule reads record fields only. A candidate that fails any rule is dropped
before rerank, with the reason kept for the evidence panel and for the hand check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from perch.schemas import Opportunity

# Temple's applicant category on Grants.gov is not verified (Q4): it is "state-related".
# Until answered, either higher-education category counts.
APPLICANT_OK = {
    "Public and State controlled institutions of higher education",
    "Private institutions of higher education",
    "Unrestricted (i.e., open to any type of entity above), subject to any clarification in "
    "text field entitled \"Additional Information on Eligibility\"",
}
# An "Others" applicant type defers to the record's eligibility text. It counts when
# that text names universities (61 of 121 open NSF listings on 2026-10-30, among them
# MPS Chemistry) or invites "all responsible sources" (DARPA and NGA announcements).
OTHERS_PREFIX = "Others"
OTHERS_TEXT_OK = re.compile(
    r"institutions? of higher education|\bIHEs?\b|colleges? and universit|universities"
    r"|all responsible sources", re.IGNORECASE)


def applicant_ok(o: Opportunity) -> bool:
    types = set(o.eligible_applicants)
    if APPLICANT_OK & types:
        return True
    return (any(t.startswith(OTHERS_PREFIX) for t in types)
            and bool(OTHERS_TEXT_OK.search(o.eligibility_notes or "")))


# Activity codes outside v1 scope or closed to a university applicant.
EXCLUDED_ACTIVITY = {
    r"F\d\d": "fellowship (students and postdocs are out of scope in v1)",
    r"K99|R00": "postdoctoral transition award (out of scope in v1)",
    r"R36": "dissertation award (out of scope in v1)",
    r"R4[1-4]|U4[34]": "SBIR/STTR (small businesses apply, not universities)",
}


# Restrictions the title states outright. Excluded by default because Perch cannot
# confirm them from public records (career stage needs the CV: private context, S13).
CAREER_STAGE = r"\bearly[- ]career\b|\bearly[- ]stage investigator|\bnew investigator"
TITLE_RESTRICTIONS = {
    r"\blimited competition\b": "limited competition: only named applicants may apply",
    CAREER_STAGE: "restricted by career stage, which public records cannot confirm",
}


def career_stage_restricted(o: Opportunity) -> bool:
    return bool(re.search(CAREER_STAGE, o.title, re.IGNORECASE))


# Grants.gov names an agency by its full name in some records and by its code in others
# ("National Institutes of Health", "HHS-NIH11"), so a filter matches either.
AGENCY_NAMES = {
    "nih": ("national institutes of health", "hhs-nih"),
    "ahrq": ("agency for health care research and quality", "hhs-ahrq"),
    "nsf": ("national science foundation", "nsf"),
}


def agency_matches(agency: str, wanted: str) -> bool:
    a, w = agency.lower(), wanted.lower().strip()
    return w in a or any(n in a for n in AGENCY_NAMES.get(w, ()))


@dataclass
class Constraints:
    as_of: date
    include_forecasted: bool = False
    min_amount: float | None = None  # drop if the record's ceiling is below this
    # Drop if the record's ceiling is above this. A record with no ceiling is kept: the
    # amount is unknown, and Scout says so rather than guess (S10).
    max_amount: float | None = None
    closes_by: date | None = None  # drop if the record closes after this date
    activity_codes: list[str] = field(default_factory=list)  # keep only these, exact
    keywords: list[str] = field(default_factory=list)  # keep if any is in title or description
    exclude_keywords: list[str] = field(default_factory=list)
    agencies: list[str] = field(default_factory=list)  # keep only these (substring match)
    exclude_agencies: list[str] = field(default_factory=list)
    exclude_activity: list[str] = field(default_factory=list)  # extra codes, exact
    include_restricted: bool = False  # keep title-restricted opportunities
    # Keep career-stage-restricted ones only: the CV (private) or the user's own word
    # suggests they may qualify. The lead is labelled by the caller.
    career_stage_ok: bool = False
    check_dates: bool = True  # the back-test sets False and applies its own time window


def date_reasons(o: Opportunity, as_of: date) -> list[str]:
    reasons = []
    if o.open_date and o.open_date > as_of:
        reasons.append(f"opens {o.open_date.isoformat()}, after {as_of.isoformat()}")
    if o.close_date is None and o.status != "forecasted":
        reasons.append("no close date in the record")
    elif o.close_date and o.close_date < as_of:
        reasons.append(f"closed {o.close_date.isoformat()}")
    return reasons


def check(o: Opportunity, c: Constraints) -> list[str]:
    """Reasons the opportunity is ineligible; empty means eligible."""
    reasons = []
    if c.check_dates:
        if o.status == "forecasted" and not c.include_forecasted:
            reasons.append("forecasted, not yet open for applications")
        reasons += date_reasons(o, c.as_of)
    if not o.eligible_applicants:
        reasons.append("no applicant types in the record")
    elif not applicant_ok(o):
        reasons.append("institutions of higher education are not eligible applicants")
    code = o.activity_code or ""
    for pattern, why in EXCLUDED_ACTIVITY.items():
        if code and re.fullmatch(pattern, code):
            reasons.append(f"activity code {code}: {why}")
    if code and code in c.exclude_activity:
        reasons.append(f"activity code {code} excluded by the user")
    if not c.include_restricted:
        for pattern, why in TITLE_RESTRICTIONS.items():
            if pattern == CAREER_STAGE and c.career_stage_ok:
                continue
            if re.search(pattern, o.title, re.IGNORECASE):
                reasons.append(why)
    if c.min_amount is not None and o.award_ceiling is not None and o.award_ceiling < c.min_amount:
        reasons.append(f"award ceiling {o.award_ceiling:,.0f} is below {c.min_amount:,.0f}")
    if c.max_amount is not None and o.award_ceiling is not None and o.award_ceiling > c.max_amount:
        reasons.append(f"award ceiling {o.award_ceiling:,.0f} is above {c.max_amount:,.0f}")
    if c.closes_by and o.close_date and o.close_date > c.closes_by:
        reasons.append(f"closes {o.close_date.isoformat()}, after {c.closes_by.isoformat()}")
    if c.activity_codes and code not in c.activity_codes:
        reasons.append(f"activity code {code or 'none'} not in the chosen codes")
    text = f"{o.title} {o.description or ''}".lower()
    if c.keywords and not any(k.lower() in text for k in c.keywords):
        reasons.append("none of the chosen keywords in the title or description")
    hit = [k for k in c.exclude_keywords if k.lower() in text]
    if hit:
        reasons.append(f"mentions excluded keyword {hit[0]!r}")
    if c.agencies and not any(agency_matches(o.agency, a) for a in c.agencies):
        reasons.append(f"agency {o.agency} not in the chosen agencies")
    if any(agency_matches(o.agency, a) for a in c.exclude_agencies):
        reasons.append(f"agency {o.agency} excluded by the user")
    return reasons


def split(opps: list[Opportunity], c: Constraints
          ) -> tuple[list[Opportunity], dict[str, list[str]]]:
    """(eligible, {id: reasons}) preserving input order."""
    ok, rejected = [], {}
    for o in opps:
        r = check(o, c)
        if r:
            rejected[o.id] = r
        else:
            ok.append(o)
    return ok, rejected

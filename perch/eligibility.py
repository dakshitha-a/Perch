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
# Activity codes outside v1 scope or closed to a university applicant.
EXCLUDED_ACTIVITY = {
    r"F\d\d": "fellowship (students and postdocs are out of scope in v1)",
    r"K99|R00": "postdoctoral transition award (out of scope in v1)",
    r"R36": "dissertation award (out of scope in v1)",
    r"R4[1-4]|U4[34]": "SBIR/STTR (small businesses apply, not universities)",
}


# Restrictions the title states outright. Excluded by default because Perch cannot
# confirm them from public records (career stage needs the CV: private context, S13).
TITLE_RESTRICTIONS = {
    r"\blimited competition\b": "limited competition: only named applicants may apply",
    r"\bearly[- ]career\b|\bearly[- ]stage investigator|\bnew investigator": (
        "restricted by career stage, which public records cannot confirm"),
}


@dataclass
class Constraints:
    as_of: date
    include_forecasted: bool = False
    min_amount: float | None = None  # drop if the record's ceiling is below this
    agencies: list[str] = field(default_factory=list)  # keep only these (substring match)
    exclude_agencies: list[str] = field(default_factory=list)
    exclude_activity: list[str] = field(default_factory=list)  # extra codes, exact
    include_restricted: bool = False  # keep title-restricted opportunities


def check(o: Opportunity, c: Constraints) -> list[str]:
    """Reasons the opportunity is ineligible; empty means eligible."""
    reasons = []
    if o.status == "forecasted" and not c.include_forecasted:
        reasons.append("forecasted, not yet open for applications")
    if o.open_date and o.open_date > c.as_of:
        reasons.append(f"opens {o.open_date.isoformat()}, after {c.as_of.isoformat()}")
    if o.close_date is None and o.status != "forecasted":
        reasons.append("no close date in the record")
    elif o.close_date and o.close_date < c.as_of:
        reasons.append(f"closed {o.close_date.isoformat()}")
    if not o.eligible_applicants:
        reasons.append("no applicant types in the record")
    elif not APPLICANT_OK & set(o.eligible_applicants):
        reasons.append("institutions of higher education are not eligible applicants")
    code = o.activity_code or ""
    for pattern, why in EXCLUDED_ACTIVITY.items():
        if code and re.fullmatch(pattern, code):
            reasons.append(f"activity code {code}: {why}")
    if code and code in c.exclude_activity:
        reasons.append(f"activity code {code} excluded by the user")
    if not c.include_restricted:
        for pattern, why in TITLE_RESTRICTIONS.items():
            if re.search(pattern, o.title, re.IGNORECASE):
                reasons.append(why)
    if c.min_amount is not None and o.award_ceiling is not None and o.award_ceiling < c.min_amount:
        reasons.append(f"award ceiling {o.award_ceiling:,.0f} is below {c.min_amount:,.0f}")
    if c.agencies and not any(a.lower() in o.agency.lower() for a in c.agencies):
        reasons.append(f"agency {o.agency} not in the chosen agencies")
    if any(a.lower() in o.agency.lower() for a in c.exclude_agencies):
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

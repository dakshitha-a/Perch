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
CAREER_STAGE = (r"\bearly[- ]career\b|\bearly[- ]stage investigator|\bearly investigator"
                r"|\bnew investigator"
                r"|\byoung investigator|\byoung faculty")
TITLE_RESTRICTIONS = {
    r"\blimited competition\b": "limited competition: only named applicants may apply",
    CAREER_STAGE: "restricted by career stage, which public records cannot confirm",
    r"\bprimarily undergraduate institution|\bundergraduate[- ]focused institution":
        "for undergraduate-focused institutions; Temple is a doctoral university",
}
# EPSCoR and DEPSCoR are open only in listed states. Pennsylvania is not on NSF's list
# (frozen through FY2027, nsf.gov EPSCoR eligibility page, read 2026-10-30) nor on the
# FY2026 DEPSCoR list in the record itself. A listing that names Pennsylvania is kept.
EPSCOR = re.compile(r"\bD?EPSCoR\b|Established Program to Stimulate Competitive Research",
                    re.IGNORECASE)
HOME_STATE = "Pennsylvania"


# G3 (S50): a notice of intent, a request for information or a sources-sought notice funds
# nothing; in S49 a request for information was a bench's top lead. Always left out, with
# include_restricted too. The acronyms are matched in capitals only.
NOTICE_RE = re.compile(r"(?i:\brequest for information\b|\bnotice of intent\b|\bsources sought\b)"
                       r"|\bRFI\b|\bNOI\b")
NOTICE_REASON = "a notice, not a funding call"


def is_notice(o: Opportunity) -> bool:
    return bool(NOTICE_RE.search(o.title or ""))


def career_stage_restricted(o: Opportunity) -> bool:
    return bool(re.search(CAREER_STAGE, o.title, re.IGNORECASE))


# Grants.gov names an agency by its full name in some records and by its code in others
# ("National Institutes of Health", "HHS-NIH11"), so a filter matches either.
AGENCY_NAMES = {
    "nih": ("national institutes of health", "hhs-nih"),
    "ahrq": ("agency for health care research and quality", "hhs-ahrq"),
    "nsf": ("national science foundation", "nsf"),
    "dod": ("department of defense", "dod"),
    "doe": ("department of energy", "doe"),
    "nasa": ("national aeronautics and space administration", "nasa"),
    "usda": ("department of agriculture", "usda"),
}


def agency_text(o: Opportunity) -> str:
    """Name, department and code together, so "DoD" matches the Air Force Academy."""
    return " ".join(x for x in (o.agency, o.parent_agency, o.agency_code) if x)


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
    closes_after: date | None = None  # drop if the record closes on or before this date (Q14)
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


# A posted call with no close date that says it takes proposals at any time is open (S49
# M1, decided 2026-11-04). It is kept only with a posted date in the last ten years, so a
# listing left up long after its programme ended (Ocean Drilling, posted 2014) stays out.
# The card shows the record's own words as the deadline.
ANYTIME_RE = re.compile(
    r"\b(?:proposals|applications)\s+(?:are\s+)?accepted\s+(?:at\s+)?any\s?time\b"
    r"|\b(?:remains\s+)?open until superseded\b", re.IGNORECASE)
ANYTIME_MAX_AGE_DAYS = 3653


def open_anytime(o: Opportunity, as_of: date) -> bool:
    return (o.close_date is None and o.status == "posted" and o.open_date is not None
            and 0 <= (as_of - o.open_date).days <= ANYTIME_MAX_AGE_DAYS
            and bool(ANYTIME_RE.search(o.close_date_note or "")))


def date_reasons(o: Opportunity, as_of: date) -> list[str]:
    reasons = []
    if o.open_date and o.open_date > as_of:
        reasons.append(f"opens {o.open_date.isoformat()}, after {as_of.isoformat()}")
    if o.close_date is None and o.status != "forecasted" and not open_anytime(o, as_of):
        reasons.append("no close date in the record")
    elif o.close_date and o.close_date < as_of:
        reasons.append(f"closed {o.close_date.isoformat()}")
    return reasons


def check(o: Opportunity, c: Constraints) -> list[str]:
    """Reasons the opportunity is ineligible; empty means eligible."""
    if is_notice(o):  # G3: nothing else about a notice matters
        return [NOTICE_REASON]
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
        text_all = f"{o.title} {o.eligibility_notes or ''} {o.description or ''}"
        if EPSCOR.search(o.title) and HOME_STATE not in text_all:
            reasons.append(f"EPSCoR: open only in listed states, and {HOME_STATE} is not one")
    if c.min_amount is not None and o.award_ceiling is not None and o.award_ceiling < c.min_amount:
        reasons.append(f"award ceiling {o.award_ceiling:,.0f} is below {c.min_amount:,.0f}")
    if c.max_amount is not None and o.award_ceiling is not None and o.award_ceiling > c.max_amount:
        reasons.append(f"award ceiling {o.award_ceiling:,.0f} is above {c.max_amount:,.0f}")
    if c.closes_by and o.close_date and o.close_date > c.closes_by:
        reasons.append(f"closes {o.close_date.isoformat()}, after {c.closes_by.isoformat()}")
    if c.closes_after and o.close_date and o.close_date <= c.closes_after:
        reasons.append(f"closes {o.close_date.isoformat()}, not after "
                       f"{c.closes_after.isoformat()}")
    if c.activity_codes and code not in c.activity_codes:
        reasons.append(f"activity code {code or 'none'} not in the chosen codes")
    text = f"{o.title} {o.description or ''}".lower()
    if c.keywords and not any(k.lower() in text for k in c.keywords):
        reasons.append("none of the chosen keywords in the title or description")
    hit = [k for k in c.exclude_keywords if k.lower() in text]
    if hit:
        reasons.append(f"mentions excluded keyword {hit[0]!r}")
    if c.agencies and not any(agency_matches(agency_text(o), a) for a in c.agencies):
        reasons.append(f"agency {o.agency} not in the chosen agencies")
    if any(agency_matches(agency_text(o), a) for a in c.exclude_agencies):
        reasons.append(f"agency {o.agency} excluded by the user")
    return reasons


# --- Temple internal funding (S49 M9, decided 2026-11-04) ---
#
# Temple's own faculty funding pages (source temple_pages) name no Grants.gov applicant type:
# the applicant is a Temple researcher by definition. They get their own rules and their own
# group in the brief, never mixed with the federal leads. A page date more than a month old is
# from an earlier cycle: the lead stays, with a code-written line, and the date is the page's.
TEMPLE_INTERNAL_SOURCE = "temple_pages"
TEMPLE_INTERNAL_AUDIENCES = (None, "faculty", "postdoc", "mixed")
PAST_CYCLE_DAYS = 31
# G5 (S50): a page date more than about 13 months old is not last year's cycle but a page
# left up (6 of 26 pages carried dates from 2021 to 2024): the page is left out, with
# "page last dated X" as its reason. A page named for an NIH mechanism (K01, K08) describes
# federal money, and a page named for students is not researcher funding.
PAST_CYCLE_MAX_DAYS = 396
NIH_CODE = re.compile(r"\b[DFKPRTU]\d{2}\b")
STUDENT_WORDS = re.compile(r"\bstudents?\b|\bhonors\b", re.I)


def past_cycle_line(d: date) -> str:
    from perch.datefmt import day

    return f"The page shows a past date, {day(d)}. Check the page for this year's date."


def check_temple_internal(o: Opportunity, c: Constraints) -> tuple[list[str], list[str]]:
    """(reasons it is left out, code-written notes) for one Temple internal opportunity."""
    reasons: list[str] = []
    notes: list[str] = []
    if o.source != TEMPLE_INTERNAL_SOURCE:
        return ["not a Temple internal funding page"], []
    if o.audience_level not in TEMPLE_INTERNAL_AUDIENCES:
        reasons.append(f"the page lists it for {o.audience_level} students, not researchers")
    if NIH_CODE.search(o.title):
        reasons.append("the page describes an NIH mechanism, not Temple funding")
    if STUDENT_WORDS.search(o.title):
        reasons.append("the page names a student award, not researcher funding")
    if c.check_dates and o.close_date and o.close_date < c.as_of:
        age = (c.as_of - o.close_date).days
        if age > PAST_CYCLE_MAX_DAYS:
            from perch.datefmt import day

            reasons.append(f"page last dated {day(o.close_date)}")
        elif age > PAST_CYCLE_DAYS:
            notes.append(past_cycle_line(o.close_date))
        else:
            reasons.append(f"closed {o.close_date.isoformat()}")
    if c.min_amount is not None and o.award_ceiling is not None and o.award_ceiling < c.min_amount:
        reasons.append(f"award ceiling {o.award_ceiling:,.0f} is below {c.min_amount:,.0f}")
    text = f"{o.title} {o.description or ''}".lower()
    hit = [k for k in c.exclude_keywords if k.lower() in text]
    if hit:
        reasons.append(f"mentions excluded keyword {hit[0]!r}")
    return reasons, notes


# --- what a brief hid, and why (S49 F2) ---
#
# Every reason `check` writes falls in one of these groups, matched in this order. The counts
# are of records, each in the group of its first reason, so they add up to the hidden total.
HIDDEN_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("notice", "notices and requests for information, not funding calls", r"^a notice, "),
    ("closed", "closed or no close date", r"^closed |no close date|^opens "),
    ("forecast", "forecast, not open yet", r"^forecasted"),
    ("applicant", "not open to universities", r"applicant types|higher education are not"),
    ("small_business", "for small businesses", r"SBIR/STTR"),
    ("career_stage", "limited by career stage", r"career stage|fellowship \(students|"
     r"postdoctoral transition|dissertation award"),
    ("restricted", "limited to named applicants, institutions or states",
     r"limited competition|undergraduate-focused|EPSCoR"),
    ("your_filters", "outside your filters", r"^closes |award ceiling|keyword"
     r"|activity code .* (?:excluded|not in)|agency .* (?:not in|excluded)"),
)


def hidden_counts(rejected: dict[str, list[str]]) -> list[dict[str, object]]:
    """[{key, label, count, record_ids}] for each group with at least one record, in
    HIDDEN_GROUPS order, then "other" for any reason no group names. Written by code from the
    reasons `check` gave; nothing here is a model's."""
    ids: dict[str, list[str]] = {}
    for rid, reasons in rejected.items():
        key = "other"
        for k, _, rx in HIDDEN_GROUPS:
            if any(re.search(rx, r) for r in reasons):
                key = k
                break
        ids.setdefault(key, []).append(rid)
    labels = {k: label for k, label, _ in HIDDEN_GROUPS} | {"other": "other reasons"}
    order = [k for k, _, _ in HIDDEN_GROUPS] + ["other"]
    return [{"key": k, "label": labels[k], "count": len(ids[k]), "record_ids": ids[k]}
            for k in order if k in ids]


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

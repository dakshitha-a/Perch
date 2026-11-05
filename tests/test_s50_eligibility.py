"""S50 round 2: research-side rules (G3 notices, G5 Temple internal pages). SYNTHETIC records."""

from datetime import UTC, date, datetime

from perch.eligibility import Constraints, check, check_temple_internal, hidden_counts

T = datetime(2026, 11, 1, tzinfo=UTC)
AS_OF = date(2026, 11, 6)
UNI = ["Public and State controlled institutions of higher education"]


def opp(title: str, **kw):
    from perch.schemas import Opportunity

    n = kw.pop("n", "SYN-1")
    base = dict(id=f"grants_gov:{n}", source="grants_gov", fetched_at=T,
                source_url=f"https://example.gov/SYNTHETIC/{n}", opportunity_number=n,
                title=title, agency="SYNTHETIC Agency", status="posted",
                close_date=date(2027, 1, 15), eligible_applicants=UNI)
    return Opportunity(**{**base, **kw})


# --- G3: a notice funds nothing ---

def test_notices_are_left_out_even_with_restrictions_allowed():
    c = Constraints(as_of=AS_OF, include_restricted=True)
    for t in ("Notice of Intent to Issue NOFO SYN-2: Research Infrastructure",
              "NOI: SYNTHETIC Program for Specialized Education",
              "Request for Information - Gauging Interest in a SYNTHETIC Technology",
              "RFI - SYNTHETIC Infrastructure Scope", "Sources Sought: SYNTHETIC Lab Services"):
        reasons = check(opp(t), c)
        assert reasons == ["a notice, not a funding call"], t


def test_a_notice_counts_in_its_own_hidden_group():
    rows = hidden_counts({"grants_gov:SYN-1": ["a notice, not a funding call"]})
    assert [r["key"] for r in rows] == ["notice"]


def test_a_funding_call_is_not_a_notice():
    c = Constraints(as_of=AS_OF)
    assert check(opp("SYNTHETIC Research Program on RFID Sensing (R01)"), c) == []
    assert check(opp("SYNTHETIC Notice-Free Innovation Awards"), c) == []


# --- G5: Temple internal pages ---

def page(title: str, close: date | None = None, audience: str = "faculty", n: str = "p1"):
    from perch.schemas import Opportunity

    return Opportunity(id=f"temple_pages:{n}", source="temple_pages", fetched_at=T,
                       source_url=f"https://example.edu/SYNTHETIC/{n}", opportunity_number=n,
                       title=title, agency="Temple University", close_date=close,
                       audience_level=audience,
                       **({"deadline_quote": "SYNTHETIC deadline sentence.",
                           "details_url": f"https://example.edu/SYNTHETIC/{n}"} if close else {}))


def test_a_page_dated_more_than_13_months_ago_is_hidden_with_its_date():
    c = Constraints(as_of=AS_OF)
    why, notes = check_temple_internal(page("SYNTHETIC Faculty Research Award",
                                            date(2021, 3, 25)), c)
    assert why == ["page last dated 25 Mar 2021"] and notes == []


def test_a_page_from_last_cycle_stays_with_its_line():
    c = Constraints(as_of=AS_OF)
    why, notes = check_temple_internal(page("SYNTHETIC Faculty Fellows", date(2025, 11, 15)), c)
    assert why == [] and "15 Nov 2025" in notes[0]


def test_nih_mechanism_and_student_pages_are_not_temple_faculty_funding():
    c = Constraints(as_of=AS_OF)
    for t in ("Mentored Research Scientist Development Award (K01)",
              "Independent Scientist Award (K02)"):
        assert check_temple_internal(page(t), c)[0], t
    for t, aud in (("Graduate Student Fellowships", "mixed"),
                   ("Undergraduate Honors Senior Project Grants", "faculty")):
        assert check_temple_internal(page(t, audience=aud), c)[0], t
    # A faculty fellowship about graduate education is faculty funding.
    assert check_temple_internal(page("Faculty Fellow in Graduate Education"), c) == ([], [])


def test_temple_group_keeps_one_copy_of_a_page_title():
    from perch.brief import dedupe_titles

    a, b = page("Innovation Fund", n="a"), page("Innovation Fund", n="b")
    assert [o.id for o in dedupe_titles([b, a])] == ["temple_pages:a"]

"""S50 round 2: research-side rules (G3 notices, G5 Temple internal pages). SYNTHETIC records."""

from datetime import UTC, date, datetime

from perch.eligibility import Constraints, check, hidden_counts

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

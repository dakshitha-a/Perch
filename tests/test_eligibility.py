from datetime import UTC, date, datetime

from perch.eligibility import Constraints, check, split
from perch.schemas import Opportunity

T = datetime(2026, 10, 28, tzinfo=UTC)
HE = ["Private institutions of higher education", "Small businesses"]


def opp(**kw):
    base = dict(id="grants_gov:X", opportunity_number="X", title="SYNTHETIC (R01)", agency="NIH",
                source="grants_gov", source_url="https://www.grants.gov/x", fetched_at=T,
                status="posted", open_date=date(2026, 1, 1), close_date=date(2027, 1, 1),
                eligible_applicants=HE, activity_code="R01")
    base.update(kw)
    return Opportunity(**base)


C = Constraints(as_of=date(2026, 10, 28))


def test_open_r01_for_universities_is_eligible():
    assert check(opp(), C) == []


def test_dates():
    assert "closed 2026-10-01" in check(opp(close_date=date(2026, 10, 1)), C)
    assert any("opens" in r for r in check(opp(open_date=date(2026, 12, 1)), C))
    assert "no close date in the record" in check(opp(close_date=None), C)
    assert check(opp(status="forecasted", close_date=None), C) == [
        "forecasted, not yet open for applications"]
    assert check(opp(status="forecasted", close_date=None),
                 Constraints(as_of=C.as_of, include_forecasted=True)) == []


def test_applicants_and_activity_codes():
    assert check(opp(eligible_applicants=["Small businesses"]), C) == [
        "institutions of higher education are not eligible applicants"]
    assert check(opp(eligible_applicants=[]), C) == ["no applicant types in the record"]
    for code in ("F32", "K99", "R00", "R36", "R43", "R44", "U44"):
        assert check(opp(activity_code=code), C), code
    for code in ("R01", "R21", "K01", "U01", "T32", None):
        assert check(opp(activity_code=code), C) == [], code


def test_user_constraints():
    c = Constraints(as_of=C.as_of, min_amount=500_000, agencies=["NIH"], exclude_activity=["R21"])
    assert check(opp(award_ceiling=250_000), c) == ["award ceiling 250,000 is below 500,000"]
    assert check(opp(award_ceiling=None), c) == []  # no ceiling in the record: not excluded
    assert check(opp(agency="NSF"), c) == ["agency NSF not in the chosen agencies"]
    assert check(opp(activity_code="R21"), c) == ["activity code R21 excluded by the user"]


def test_agency_filter_matches_names_and_codes():
    c = Constraints(as_of=C.as_of, agencies=["NIH"])
    assert check(opp(agency="National Institutes of Health"), c) == []
    assert check(opp(agency="HHS-NIH11"), c) == []
    assert check(opp(agency="HHS-AHRQ"), c) == ["agency HHS-AHRQ not in the chosen agencies"]
    assert check(opp(agency="HHS-NIH11"), Constraints(as_of=C.as_of, exclude_agencies=["nih"]))


def test_follow_up_constraints():
    c = Constraints(as_of=C.as_of, max_amount=200_000, closes_by=date(2026, 12, 31),
                    activity_codes=["R21", "R03"], keywords=["imaging"],
                    exclude_keywords=["clinical trial"])
    good = dict(activity_code="R21", award_ceiling=150_000, close_date=date(2026, 12, 1),
                title="SYNTHETIC imaging methods (R21)")
    assert check(opp(**good), c) == []
    assert check(opp(**{**good, "award_ceiling": None}), c) == []  # unknown amount: kept
    assert check(opp(**{**good, "award_ceiling": 250_000}), c) == [
        "award ceiling 250,000 is above 200,000"]
    assert check(opp(**{**good, "close_date": date(2027, 2, 5)}), c) == [
        "closes 2027-02-05, after 2026-12-31"]
    assert check(opp(**{**good, "activity_code": "R01"}), c) == [
        "activity code R01 not in the chosen codes"]
    assert check(opp(**{**good, "title": "SYNTHETIC genomics (R21)"}), c) == [
        "none of the chosen keywords in the title or description"]
    assert check(opp(**{**good, "description": "Clinical Trial Required"}), c) == [
        "mentions excluded keyword 'clinical trial'"]


def test_split_keeps_order_and_reasons():
    a, b = opp(id="a"), opp(id="b", close_date=date(2020, 1, 1))
    ok, rejected = split([a, b], C)
    assert [o.id for o in ok] == ["a"] and list(rejected) == ["b"]


def test_title_restrictions():
    lim = opp(title="Limited Competition: Small Grant Program for K01 Recipients (R03)")
    assert check(lim, C) == ["limited competition: only named applicants may apply"]
    early = opp(title="Supporting Talented Early Career Researchers in Genomics (R01)")
    assert check(early, C) == ["restricted by career stage, which public records cannot confirm"]
    assert check(lim, Constraints(as_of=C.as_of, include_restricted=True)) == []


def test_others_counts_when_the_text_names_universities():
    # NSF MPS Chemistry (26-519): applicant type "Others", universities named in the text.
    import json
    from pathlib import Path

    from perch.sources import grants_gov as gg

    raw = json.loads((Path(__file__).parent / "fixtures/grants_gov/fetch_opportunity_nsf.json")
                     .read_text(encoding="utf-8"))
    o = gg.parse_opportunity(raw["data"], datetime(2026, 10, 30, tzinfo=UTC), "posted")
    assert o.eligible_applicants[0].startswith("Others")
    assert check(o, Constraints(as_of=date(2026, 10, 30))) == []
    other = o.model_copy(update={"eligibility_notes": "Only tribal governments may apply."})
    assert "institutions of higher education are not eligible applicants" in check(
        other, Constraints(as_of=date(2026, 10, 30)))


def test_agency_filter_reaches_the_department_and_code():
    o = opp(agency="Air Force Academy", agency_code="DOD-USAFA",
            parent_agency="Department of Defense")
    c = Constraints(as_of=date(2026, 10, 30), check_dates=False)
    for wanted in ("DoD", "Department of Defense", "DOD-USAFA", "Air Force"):
        c.agencies = [wanted]
        assert not any("not in the chosen agencies" in r for r in check(o, c)), wanted
    c.agencies = ["NIH"]
    assert any("not in the chosen agencies" in r for r in check(o, c))


def test_institution_type_young_investigator_and_epscor():
    c = Constraints(as_of=date(2026, 10, 30), check_dates=False)
    for title, why in [
        ("ONR FY27 NOFO for Young Investigator Program", "career stage"),
        ("Young Faculty Award (YFA) 2027", "career stage"),
        ("Parkinson's, Early Investigator Research Award", "career stage"),
        ("Facilitating Research at Primarily Undergraduate Institutions (RUI)", "undergraduate"),
        ("Academic Research Enhancement Award (AREA) for Undergraduate-Focused Institutions "
         "(R15)", "undergraduate"),
        ("EPSCoR Research Infrastructure Improvement Program", "EPSCoR"),
        ("FY26 DEFENSE ESTABLISHED PROGRAM TO STIMULATE COMPETITIVE RESEARCH (DEPSCoR)",
         "EPSCoR"),
    ]:
        assert any(why in r for r in check(opp(title=f"SYNTHETIC {title}"), c)), title
    named = opp(title="SYNTHETIC EPSCoR Workshops", eligibility_notes="Pennsylvania and others")
    assert not any("EPSCoR" in r for r in check(named, c))
    c.include_restricted = True
    assert not check(opp(title="SYNTHETIC EPSCoR Workshops"), c)

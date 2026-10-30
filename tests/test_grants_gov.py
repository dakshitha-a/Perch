"""Grants.gov parser and client, against real (contact-redacted) responses saved 2026-10-28."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from perch.sources import grants_gov as gg

FIX = Path(__file__).parent / "fixtures" / "grants_gov"
T = datetime(2026, 10, 28, tzinfo=UTC)


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_parse_fetch_fixture():
    o = gg.parse_opportunity(load("fetch_opportunity.json")["data"], T, "posted")
    assert o.id == "grants_gov:PAR-25-268"
    assert o.source == "grants_gov"
    assert o.source_url == "https://www.grants.gov/search-results-detail/357303"
    assert o.opportunity_number == "PAR-25-268"
    assert o.open_date == date(2024, 11, 21)
    assert o.close_date == date(2026, 11, 17)
    assert o.archive_date == date(2026, 12, 23)
    assert o.award_ceiling is None and o.award_floor is None  # the record says "none"
    assert o.activity_code == "R01"
    assert o.assistance_listings == ["93.213"]
    assert "Grant" in o.funding_instruments
    assert o.eligible_applicants and o.eligibility_notes
    assert o.description and "<p>" not in o.description
    assert o.status == "posted"


def test_dates_and_money():
    assert gg._date("Nov 17, 2026 12:00:00 AM EST") == date(2026, 11, 17)
    assert gg._date("Jan 5, 2026 12:00:00 AM EST") == date(2026, 1, 5)
    assert gg._date("11/17/2026") == date(2026, 11, 17)
    assert gg._date("") is None
    assert gg._money("none") is None and gg._money("250,000") == 250000.0
    assert gg._money(0) is None


def test_fixtures_hold_no_contacts():
    for f in FIX.glob("*.json"):
        assert "@" not in f.read_text(encoding="utf-8"), f.name


def test_client_searches_then_fetches_each_hit():
    calls = []
    search, detail = load("search2_nih_posted.json"), load("fetch_opportunity.json")

    def handler(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path.endswith("/search2"):
            return httpx.Response(200, json=search)
        return httpx.Response(200, json=detail)

    with gg.GrantsGovClient(transport=httpx.MockTransport(handler), min_interval=0) as c:
        opps = list(c.iter_opportunities(agencies="HHS-NIH11", limit=2))
    assert len(opps) == 2
    paths = [p for p, _ in calls]
    assert paths[0].endswith("/search2") and paths.count("/v1/api/fetchOpportunity") == 2
    assert calls[0][1]["oppStatuses"] == "forecasted|posted"


def test_error_code_raises():
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"errorcode": 1, "msg": "bad"}))
    with gg.GrantsGovClient(transport=t, min_interval=0) as c:
        try:
            c.search()
        except RuntimeError as e:
            assert "bad" in str(e)
        else:
            raise AssertionError("expected RuntimeError")


def test_archived_record_and_parent_activity_code():
    o = gg.parse_opportunity(load("fetch_opportunity_archived.json")["data"], T, "archived")
    assert o.opportunity_number == "PA-11-260"
    assert o.open_date == date(2011, 7, 22) and o.close_date == date(2013, 9, 7)
    assert o.activity_code == "R01"  # from "(Parent R01)"
    assert o.description


def test_list_fields_are_order_independent():
    d1 = load("fetch_opportunity.json")["data"]
    d2 = json.loads(json.dumps(d1))
    d2["synopsis"]["applicantTypes"].reverse()
    assert gg.parse_opportunity(d1, T) == gg.parse_opportunity(d2, T)


def test_title_entities_and_two_letter_codes():
    d = load("fetch_opportunity.json")["data"]
    d["opportunityTitle"] = "High Priority HIV Research (RM1 Clinical Trial Optional) and&nbsp;more"
    o = gg.parse_opportunity(d, T)
    assert o.activity_code == "RM1" and o.title.endswith("and more")
    d["opportunityTitle"] = "Avant Garde Awards (DP1 Clinical Trial Optional)"
    assert gg.parse_opportunity(d, T).activity_code == "DP1"
    d["opportunityTitle"] = "Institutional Network Award (U2C - Clinical Trial Not Allowed)"
    assert gg.parse_opportunity(d, T).activity_code == "U2C"


def test_agency_comes_from_agency_details_not_the_contact():
    # On DoD and DOE records the synopsis agencyName is a contact's name and role.
    dod = gg.parse_opportunity(load("fetch_opportunity_dod.json")["data"], T, "posted")
    assert dod.agency == "Air Force Academy"
    assert dod.agency_code == "DOD-USAFA" and dod.parent_agency == "Department of Defense"
    nsf = gg.parse_opportunity(load("fetch_opportunity_nsf.json")["data"], T, "posted")
    assert nsf.agency == "U.S. National Science Foundation" and nsf.parent_agency is None
    assert nsf.close_date == date(2076, 10, 7)
    assert nsf.close_date_note == "Proposals accepted anytime"
    nih = gg.parse_opportunity(load("fetch_opportunity.json")["data"], T, "posted")
    assert nih.agency == "National Institutes of Health"


def test_redaction_drops_contact_agency_name_and_contact_info():
    data = {"synopsis": {"agencyName": "A Person\nGrantor", "contactInfo": "A Person",
                         "agencyDetails": {"agencyName": "Air Force Academy"}}}
    out = gg.redact_contacts(data)["synopsis"]
    assert out["agencyName"] == "[redacted]" and out["contactInfo"] == "[redacted]"
    assert out["agencyDetails"]["agencyName"] == "Air Force Academy"


def test_deadline_note_drops_placeholders():
    assert gg.deadline_note("Proposals accepted anytime") == "Proposals accepted anytime"
    for junk in ("undefined", "No Explanation", "", None, "none."):
        assert gg.deadline_note(junk) is None

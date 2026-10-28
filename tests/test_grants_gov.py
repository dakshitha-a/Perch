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

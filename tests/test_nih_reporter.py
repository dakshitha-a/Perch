"""NIH RePORTER parser and client, against a real response saved on 2026-10-28."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from perch.sources import nih_reporter as nih

FIX = Path(__file__).parent / "fixtures" / "nih_reporter" / "projects_search_pi.json"
T = datetime(2026, 10, 28, tzinfo=UTC)


def load():
    return json.loads(FIX.read_text(encoding="utf-8"))


def test_parse_fixture_fields():
    awards = [nih.parse_project(r, T) for r in load()["results"]]
    assert len(awards) == 11
    a = awards[0]
    assert a.id == "nih:11401474"
    assert a.source == "nih_reporter"
    assert a.source_url == "https://reporter.nih.gov/project-details/11401474"
    assert a.award_number == "R01DK134630"
    assert a.fiscal_year == 2026
    assert a.start_date == date(2023, 6, 5) and a.end_date == date(2027, 5, 31)
    assert a.opportunity_number == "PA-20-183"
    assert a.activity_code == "R01"
    assert a.amount == 595366 and a.amount_basis == "fiscal year"
    assert a.institution == "TEMPLE UNIV OF THE COMMONWEALTH"
    assert a.agency == "NIDDK"
    assert {x.agency for x in awards} >= {"NIDDK", "AHRQ"}  # RePORTER is wider than NIH
    pi = load()["results"][0]["principal_investigators"][0]
    assert pi["full_name"] in a.pi_names


def test_end_date_can_move_between_fiscal_years():
    awards = [nih.parse_project(r, T) for r in load()["results"]]
    ends = {a.end_date for a in awards if a.award_number == "R01DK131016"}
    assert ends == {date(2025, 4, 30), date(2027, 4, 30)}  # extension recorded in FY2024


def test_client_pages_and_spaces_requests():
    bodies = []
    page = load()

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        out = dict(page)
        out["meta"] = {**page["meta"], "total": 13}
        out["results"] = page["results"] if body["offset"] == 0 else page["results"][:2]
        return httpx.Response(200, json=out)

    with nih.NIHReporterClient(transport=httpx.MockTransport(handler), min_interval=0) as c:
        pi = page["results"][0]["principal_investigators"][0]
        awards = c.awards_for_pi(pi["first_name"], pi["last_name"])
    assert len(awards) == 13
    assert [b["offset"] for b in bodies] == [0, 11]
    assert bodies[0]["criteria"] == {
        "org_names": ["TEMPLE UNIV"],
        "pi_names": [{"first_name": pi["first_name"], "last_name": pi["last_name"]}],
    }


def test_default_spacing_is_one_second():
    assert nih.NIHReporterClient().min_interval == 1.0

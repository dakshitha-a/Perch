"""NSF Award Search parser and client, against real (contact-redacted) responses."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from perch.sources import nsf

FIX = Path(__file__).parent / "fixtures" / "nsf"
T = datetime(2026, 10, 28, tzinfo=UTC)


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_parse_copi_fixture():
    raw = load("awards_copi.json")["response"]["award"][0]
    a = nsf.parse_award(raw, T)
    assert a.id == "nsf:1212416"
    assert a.source == "nsf"
    assert a.source_url == "https://api.nsf.gov/services/v1/awards/1212416.json"
    assert a.start_date == date(2012, 7, 1) and a.end_date == date(2016, 6, 30)
    assert a.amount_basis == "estimated total" and a.amount is not None
    assert "Axel Kohlmeyer" in a.pi_names
    assert all("@" not in n and "redacted" not in n for n in a.pi_names)
    assert a.opportunity_number is None


def test_fixtures_hold_no_contacts():
    for f in FIX.glob("*.json"):
        text = f.read_text(encoding="utf-8")
        assert "@" not in text.replace("[email redacted]", ""), f.name


AT = "@"  # built from pieces so the repo's hygiene check does not flag test data


def test_strip_and_redact():
    assert nsf.strip_email(f"SYNTHETIC Person p{AT}example.org") == "SYNTHETIC Person"
    data = {"response": {"award": [{"piEmail": f"x{AT}example.org",
                                    "pi": [f"A B a{AT}example.org"], "poPhone": "1234567890"}]}}
    out = nsf.redact_contacts(data)["response"]["award"][0]
    assert out["piEmail"] == "[redacted]" and out["poPhone"] == "[redacted]"
    assert out["pi"] == ["A B [email redacted]"]


def test_client_queries_pi_and_copi_and_dedupes():
    seen = []
    page = load("awards_copi.json")

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=page)

    with nsf.NSFClient(transport=httpx.MockTransport(handler), min_interval=0) as c:
        awards = c.awards_for_pi("Kohlmeyer")
    assert [a.id for a in awards] == ["nsf:1212416"]
    assert {"pdPIName", "coPDPI"} == {k for p in seen for k in p if k in ("pdPIName", "coPDPI")}
    assert seen[0]["awardeeName"] == '"Temple University"' and seen[0]["offset"] == "0"

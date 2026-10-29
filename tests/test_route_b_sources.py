"""Route B fetchers, against real responses saved on 2026-10-29."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from perch.sources import nih_reporter as nr
from perch.sources import openalex as oa

FIX = Path(__file__).parent / "fixtures"
T = datetime(2026, 10, 29, tzinfo=UTC)


def load(path):
    return json.loads((FIX / path).read_text(encoding="utf-8"))


def test_companies_on_reads_company_institutions_only():
    raw = load("openalex/company_works_topics.json")["results"][0]
    orgs = oa.companies_on(raw, T)
    assert [o.name for o in orgs] == ["Merck KGaA, Darmstadt (Germany)",
                                      "Merck Healthcare KGaA, Darmstadt (Germany)"]
    o = orgs[0]
    assert o.type == "company" and o.country == "DE"
    assert o.source_url.startswith("https://api.openalex.org/institutions/I")
    assert o.institution_ids == [o.id]


def test_company_works_citing_chunks_ids_at_the_or_ceiling():
    seen: list[str] = []
    page = load("openalex/company_works_citing.json")

    def handler(req: httpx.Request) -> httpx.Response:
        f = req.url.params["filter"]
        seen.append(f)
        assert f.endswith(",authorships.institutions.type:company")
        return httpx.Response(200, json=page)

    ids = [f"https://openalex.org/W{i}" for i in range(150)]
    with oa.OpenAlexClient(transport=httpx.MockTransport(handler), min_interval=0) as c:
        got = c.company_works_citing(ids)
    assert len(seen) == 2  # 100 ids, then 50; one page each (count 19 < 100)
    assert seen[0].count("|") == 99 and seen[1].count("|") == 49
    assert len(got) == 3  # same three works in both chunks, kept once
    w, orgs = got[0]
    assert w.publication_date == date(2025, 9, 23)
    assert orgs and all(o.type == "company" for o in orgs)


def test_company_works_in_topics_filters_dates_and_topics():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.params["filter"])
        return httpx.Response(200, json=load("openalex/company_works_topics.json"))

    with oa.OpenAlexClient(transport=httpx.MockTransport(handler), min_interval=0) as c:
        got = c.company_works_in_topics(["https://openalex.org/T10123", "T11215"],
                                        date(2023, 10, 29), date(2026, 10, 29), max_pages=1)
    assert seen == ["primary_topic.id:T10123|T11215,from_publication_date:2023-10-29,"
                    "to_publication_date:2026-10-29,authorships.institutions.type:company"]
    assert len(got) == 3


def test_sbir_sttr_parses_firm_awards():
    bodies = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json=load("nih_reporter/sbir_sttr_search.json"))

    with nr.NIHReporterClient(transport=httpx.MockTransport(handler), min_interval=0) as c:
        awards = c.sbir_sttr("PARP inhibition DNA repair", [2024, 2025, 2026], limit=50)
    crit = bodies[0]["criteria"]
    assert crit["activity_codes"] == nr.SBIR_STTR_CODES
    assert crit["advanced_text_search"]["search_text"] == "PARP inhibition DNA repair"
    assert [a.activity_code for a in awards] == ["R43", "R44", "R44"]
    assert awards[0].institution == "BLACKSMITH MEDICINES, INC."
    assert awards[0].source_url.startswith("https://reporter.nih.gov/")

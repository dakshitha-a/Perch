"""OpenAlex parser and client, against real responses saved on 2026-10-28."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from perch.sources import openalex as oa

FIX = Path(__file__).parent / "fixtures" / "openalex"
T = datetime(2026, 10, 28, tzinfo=UTC)
AUTHOR = "https://openalex.org/A5026494099"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_parse_author_from_orcid_fixture():
    r = oa.parse_author(load("author_orcid.json"), T)
    assert r.id == AUTHOR
    assert r.source == "openalex"
    assert r.source_url == "https://api.openalex.org/authors/A5026494099"
    assert r.orcid == "https://orcid.org/0000-0001-6204-6475"
    assert "Temple University" in r.institutions
    assert r.topics and r.topics[0].display_name


def test_parse_works_page_fixture():
    works = [oa.parse_work(w, T) for w in load("works_page.json")["results"]]
    assert len(works) == 5
    w = works[0]
    assert w.id == "https://openalex.org/W7166556526"
    assert w.source_url == "https://api.openalex.org/works/W7166556526"
    assert w.publication_date == date(2026, 10, 23)
    assert w.venue == "The Journal of Open Source Software"
    assert w.doi == "https://doi.org/10.21105/joss.11185"
    assert AUTHOR in w.author_ids
    assert oa.TEMPLE_INSTITUTION_ID in w.institution_ids
    assert all(AUTHOR in x.author_ids for x in works)
    assert any(x.abstract for x in works)


def test_reconstruct_abstract_orders_by_position():
    assert oa.reconstruct_abstract({"world": [1], "hello": [0], "again": [3], "hello,": [2]}) == (
        "hello world hello, again"
    )
    assert oa.reconstruct_abstract(None) is None


def test_id_parsing():
    assert oa.parse_orcid("https://orcid.org/0000-0001-6204-6475") == "0000-0001-6204-6475"
    assert oa.parse_orcid("0000-0002-1825-009X") == "0000-0002-1825-009X"
    assert oa.parse_orcid("Axel Kohlmeyer") is None
    assert oa.parse_author_id(AUTHOR) == "A5026494099"
    assert oa.parse_author_id("A5026494099") == "A5026494099"


def fixture_transport(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if path == "/authors":
            return httpx.Response(200, json=load("authors_search.json"))
        if path.startswith("/authors/"):  # by ORCID or by id: same author
            return httpx.Response(200, json=load("author_orcid.json"))
        if path == "/works":
            page = load("works_page.json")
            page["meta"]["count"] = 7
            if request.url.params["page"] != "1":
                page["results"] = page["results"][:2]
            return httpx.Response(200, json=page)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_client_resolve_and_page_works():
    calls = []
    with oa.OpenAlexClient(transport=fixture_transport(calls), min_interval=0) as c:
        found = c.resolve_by_name("Axel Kohlmeyer")
        assert [r.id for r in found] == [AUTHOR]
        assert c.resolve_by_orcid("0000-0001-6204-6475").id == AUTHOR
        works = list(c.iter_works(AUTHOR, per_page=5))
    assert len(works) == 7  # 5 on the first page, 2 on the second
    assert [r.url.params["page"] for r in calls if r.url.path == "/works"] == ["1", "2"]
    search = calls[0].url.params
    assert search["filter"] == "last_known_institutions.id:I84392919"
    assert "authorization" not in calls[0].headers


def test_api_key_goes_in_header_not_url():
    calls = []
    with oa.OpenAlexClient(api_key="k" * 16, transport=fixture_transport(calls),
                           min_interval=0) as c:
        c.resolve_by_orcid("0000-0001-6204-6475")
    assert calls[0].headers["authorization"] == "Bearer " + "k" * 16
    assert "k" * 16 not in str(calls[0].url)


def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(oa.time, "sleep", lambda s: None)
    responses = iter([httpx.Response(429, headers={"Retry-After": "1"}),
                      httpx.Response(200, json=load("author_orcid.json"))])
    transport = httpx.MockTransport(lambda req: next(responses))
    with oa.OpenAlexClient(transport=transport, min_interval=0) as c:
        assert c.get_author("A5026494099").id == AUTHOR


def test_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(oa.time, "sleep", lambda s: None)
    transport = httpx.MockTransport(lambda req: httpx.Response(503))
    with oa.OpenAlexClient(transport=transport, retries=1, min_interval=0) as c:
        with pytest.raises(httpx.HTTPStatusError):
            c.get_author("A5026494099")


def test_queried_author_kept_when_authorships_are_truncated():
    page = load("works_page.json")
    page["results"] = page["results"][:1]
    page["results"][0]["authorships"] = page["results"][0]["authorships"][1:]  # drop the author
    page["meta"]["count"] = 1
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=page))
    with oa.OpenAlexClient(transport=transport, min_interval=0) as c:
        (w,) = list(c.iter_works(AUTHOR))
    assert AUTHOR in w.author_ids

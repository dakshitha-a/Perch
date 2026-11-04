"""Browse routes: /awards, /opportunities, /filters, /samples (S43). SYNTHETIC records only.

Run on SQLite and on Postgres (skips without PERCH_TEST_DATABASE_URL). The rate-limit test
needs PERCH_TEST_REDIS_URL.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from perch.schemas import Opportunity, Scholarship
from tests.test_api import make
from tests.test_store import T, opp, temple_trio

REDIS_URL = os.environ.get("PERCH_TEST_REDIS_URL", "")


@pytest.fixture(params=["sqlite", "postgres"])
def client(request, tmp_path):
    c, service = make(tmp_path)
    with service.repo() as r:  # make() stores one real grants.gov record; these tests count
        r.conn.execute("DELETE FROM records")
        r.conn.commit()
    if request.param == "postgres":
        pg = request.getfixturevalue("pg_clean")
        from perch.store.postgres import PostgresRepository

        service.repo_factory = lambda: PostgresRepository(pg.worker, role="worker")
    return c, service


def records():
    a, b, c = temple_trio()
    fox = a.model_copy(update={"id": "temple_pages:d", "name": "SYNTHETIC Fox Prize",
                               "schools": ["Fox School of Business"]})
    outside = a.model_copy(update={"id": "other:e", "name": "SYNTHETIC Outside Prize",
                                   "source": "other_source", "schools": [], "scope": None,
                                   "page_owner": None})
    temple_opp = Opportunity(id="temple_pages:o1", opportunity_number="temple_pages:o1",
                             title="SYNTHETIC Seed Grant", agency="SYNTHETIC OVPR",
                             source="temple_pages", source_url="https://x.example/ovpr",
                             fetched_at=T)
    return [a, b, c, fox, outside, temple_opp, opp("O9", "SYNTHETIC External Grant")]


@pytest.fixture
def loaded(client):
    c, service = client
    with service.repo() as r:
        r.upsert(records())
    return c


def ids(group):
    return [i["id"] for i in group["items"]]


def test_awards_lists_public_records_with_provenance_and_nulls(loaded):
    body = loaded.get("/awards").json()
    (g,) = body["groups"]
    assert body["kind"] == "scholarship" and g["key"] == "all" and g["total"] == 5
    assert sorted(ids(g)) == ["other:e", "temple_pages:a", "temple_pages:b", "temple_pages:c",
                              "temple_pages:d"]  # the list itself is in name order (S43)
    assert not any(i.startswith("sample:") for i in ids(g))
    for it in g["items"]:  # rule 4
        assert it["source"] and it["source_url"] and it["fetched_at"] and it["sample"] is False
    b = next(i for i in g["items"] if i["id"] == "temple_pages:b")
    assert b["amount_max"] is None and b["deadline"] is None and b["schools"] == []
    assert b["scope"] == "unstated" and b["scope_not_stated"] is True
    a = next(i for i in g["items"] if i["id"] == "temple_pages:a")
    assert a["scope"] == "school" and a["schools"] == ["CST"] and a["scope_not_stated"] is False


def test_temple_only_keeps_records_listed_on_temple_pages(loaded):
    (g,) = loaded.get("/awards", params={"temple_only": "true"}).json()["groups"]
    assert sorted(ids(g)) == [f"temple_pages:{k}" for k in "abcd"]
    (g,) = loaded.get("/opportunities", params={"temple_only": "true"}).json()["groups"]
    assert ids(g) == ["temple_pages:o1"]
    (g,) = loaded.get("/opportunities").json()["groups"]
    assert ids(g) == ["O9", "temple_pages:o1"]


def test_all_temple_chip_is_the_scope_filter(loaded):
    (g,) = loaded.get("/awards", params={"scope": "temple_wide,unstated"}).json()["groups"]
    assert ids(g) == ["temple_pages:b", "temple_pages:c"]


def test_school_view_has_two_labelled_groups_never_mixed(loaded):
    body = loaded.get("/awards", params={"school": "CST", "temple_only": "true"}).json()
    own, wide = body["groups"]
    assert (own["key"], own["label"]) == ("school", "CST")
    assert (wide["key"], wide["label"]) == ("open", "Open across Temple")
    assert ids(own) == ["temple_pages:a"] and own["total"] == 1
    assert ids(wide) == ["temple_pages:b", "temple_pages:c"]  # temple_wide and unstated
    assert not set(ids(own)) & set(ids(wide))


def test_school_group_paging_and_exclusion(client):
    c, service = client
    a, _, wide = temple_trio()
    named = wide.model_copy(update={"id": "temple_pages:w", "schools": ["CST"]})
    extra = [wide.model_copy(update={"id": f"temple_pages:x{n}"}) for n in range(3)]
    with service.repo() as r:
        r.upsert([a, wide, named, *extra])
    body = c.get("/awards", params={"school": "CST", "limit": 2}).json()
    own, open_ = body["groups"]
    assert ids(own) == ["temple_pages:a", "temple_pages:w"]  # the wide record naming CST is here
    assert "temple_pages:w" not in ids(open_)  # ... and only here
    assert open_["total"] == 4 and len(open_["items"]) == 2 and open_["next_cursor"]
    more = c.get("/awards", params={"school": "CST", "limit": 2, "group": "open",
                                    "cursor": open_["next_cursor"]}).json()
    (g,) = more["groups"]
    assert g["key"] == "open" and len(ids(g)) == 2
    assert not set(ids(g)) & set(ids(open_))
    assert c.get("/awards", params={"school": "CST", "group": "nope"}).status_code == 422
    assert c.get("/awards", params={"cursor": "gA=="}).status_code == 422


def test_search_and_level_filters(loaded):
    (g,) = loaded.get("/awards", params={"q": "harbor"}).json()["groups"]
    assert ids(g) == ["temple_pages:b"]
    (g,) = loaded.get("/awards", params={"level": "graduate"}).json()["groups"]
    assert g["items"] == []


def test_filters_counts_come_from_the_store(loaded):
    f = loaded.get("/filters").json()
    assert f["total"] == 5 and f["temple_total"] == 4
    assert f["schools"] == [{"name": "CST", "count": 1},
                            {"name": "Fox School of Business", "count": 1}]
    assert f["levels"] == []
    r = loaded.get("/filters", params={"audience": "researcher"}).json()
    assert r["total"] == 2 and r["temple_total"] == 1 and r["schools"] == []
    assert loaded.get("/filters", params={"audience": "x"}).status_code == 422


def test_filters_count_a_record_under_each_of_its_schools(client):
    c, service = client
    two = temple_trio()[0].model_copy(update={"schools": ["CST", "CEHD"]})
    with service.repo() as r:
        r.upsert([two, two.model_copy(update={"id": "temple_pages:z", "schools": ["CST"]})])
    f = c.get("/filters").json()
    assert f["schools"] == [{"name": "CST", "count": 2}, {"name": "CEHD", "count": 1}]


def test_samples_are_synthetic_badged_and_never_in_public_lists(loaded):
    s = loaded.get("/samples").json()
    assert s["sample"] is True and s["notice"] and s["total"] >= 50 and s["items"]
    for it in s["items"]:
        assert it["id"].startswith("sample:") and it["source"] == "synthetic"
        assert it["sample"] is True
    nxt = loaded.get("/samples", params={"cursor": s["next_cursor"], "limit": 5}).json()
    assert nxt["items"] and nxt["items"][0]["id"] > s["items"][-1]["id"]
    public = {i["id"] for g in loaded.get("/awards").json()["groups"] for i in g["items"]}
    assert not public & {i["id"] for i in s["items"]}
    assert loaded.get("/samples", params={"audience": "researcher"}).json()["items"] == []


def test_a_sample_in_the_public_store_never_reaches_awards(client):
    from perch.scholarships import read_samples

    c, service = client
    with service.repo() as r:
        r.upsert([*records()[:1], read_samples()[0]])
    (g,) = c.get("/awards").json()["groups"]
    assert ids(g) == ["temple_pages:a"]
    assert c.get("/filters").json()["total"] == 1


def test_browse_needs_no_session(loaded):
    for path in ("/awards", "/opportunities", "/filters", "/samples"):
        assert loaded.get(path).status_code == 200


@pytest.mark.skipif(not REDIS_URL, reason="PERCH_TEST_REDIS_URL is not set")
def test_reads_are_rate_limited_per_address(tmp_path, monkeypatch):
    import redis

    c, _ = make(tmp_path)
    r = redis.Redis.from_url(REDIS_URL)
    r.flushdb()
    c.app.state.sessions = SimpleNamespace(r=r)
    monkeypatch.setenv("PERCH_RATE_LIMITS", '{"api_read": [2, 60]}')
    assert [c.get("/filters").status_code for _ in range(3)] == [200, 200, 429]
    over = c.get("/awards")
    assert over.status_code == 429 and over.json()["detail"] == {"error": "rate_limited"}
    assert int(over.headers["retry-after"]) >= 1
    r.flushdb()


def test_scholarship_and_opportunity_item_keys_are_stable():
    from perch.browse.routes import item

    it = item(Scholarship(id="sample:sch-9999", name="SYNTHETIC", source="synthetic",
                          source_url="synthetic://x", fetched_at=T, canary="C"))
    assert {"id", "kind", "source", "source_url", "fetched_at", "scope", "scope_not_stated",
            "schools", "levels", "deadline", "amount_max", "sample"} <= set(it)

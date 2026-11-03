from datetime import UTC, date, datetime

import pytest

from perch.schemas import Opportunity, Researcher, Scholarship, Work
from perch.store.sqlite import SQLiteRepository

T = datetime(2026, 10, 28, tzinfo=UTC)


@pytest.fixture(params=["sqlite", "postgres"])
def repo(request, tmp_path):
    """The same tests run on both backends. Postgres skips without PERCH_TEST_DATABASE_URL."""
    if request.param == "sqlite":
        with SQLiteRepository(tmp_path / "x.db") as r:
            yield r
        return
    pg = request.getfixturevalue("pg_clean")
    from perch.store.postgres import PostgresRepository

    with PostgresRepository(pg.worker, role="worker") as r:
        yield r


def work(id, authors, day):
    return Work(id=id, title=f"SYNTHETIC {id}", author_ids=authors, publication_date=day,
                source="openalex", source_url=f"https://api.openalex.org/works/{id}", fetched_at=T)


def opp(id, title, close=None):
    return Opportunity(id=id, opportunity_number=id, title=title, agency="SYNTHETIC Agency",
                       close_date=close, source="grants_gov",
                       source_url=f"https://example.invalid/{id}", fetched_at=T)


def sample_sch(n):
    return Scholarship(id=f"sample:sch-{n:04d}", name=f"SYNTHETIC Prize {n}", source="synthetic",
                       source_url="https://example.invalid/sample", fetched_at=T,
                       canary=f"CANARY-{n}")


def test_round_trip_keeps_provenance(repo):
    r = Researcher(id="A1", display_name="SYNTHETIC Person", source="openalex",
                   source_url="https://api.openalex.org/authors/A1", fetched_at=T)
    assert repo.upsert([r]) == 1
    got = repo.get(Researcher, "A1")
    assert got == r
    assert repo.get(Work, "A1") is None  # kinds do not collide
    assert repo.get_any("A1") == r
    assert repo.get_any("nope") is None


def test_upsert_replaces_and_works_by_author_orders_newest_first(repo):
    repo.upsert([work("W1", ["A1"], date(2020, 1, 1)), work("W2", ["A1", "A2"], date(2023, 5, 1)),
                 work("W3", ["A2"], date(2024, 1, 1))])
    repo.upsert([work("W1", ["A1"], date(2021, 1, 1))])
    assert [w.id for w in repo.works_by_author("A1")] == ["W2", "W1"]
    assert repo.get(Work, "W1").publication_date == date(2021, 1, 1)
    assert len(repo.list(Work)) == 3


def test_list_is_ordered_by_id_and_hides_samples_by_default(repo):
    repo.upsert([sample_sch(2), sample_sch(1)])
    real = Scholarship(id="temple:b", name="SYNTHETIC Public B", source="temple_sdfa",
                       source_url="https://example.invalid/b", fetched_at=T)
    real2 = real.model_copy(update={"id": "Temple:a"})
    repo.upsert([real, real2])
    assert [s.id for s in repo.list(Scholarship)] == ["Temple:a", "temple:b"]  # byte order
    both = repo.list(Scholarship, include_samples=True)
    assert [s.id for s in both] == ["Temple:a", "sample:sch-0001", "sample:sch-0002", "temple:b"]


def test_browse_filters_and_pages(repo):
    repo.upsert([opp("O1", "Kidney research", date(2027, 1, 1)),
                 opp("O2", "Quantum sensing", date(2026, 1, 1)),
                 opp("O3", "Kidney transplant", None),
                 opp("O4", "Kidney imaging", date(2028, 1, 1))])
    page = repo.browse(Opportunity, limit=2)
    assert [o.id for o in page.items] == ["O1", "O2"] and page.total == 4
    assert page.next_cursor is not None
    nxt = repo.browse(Opportunity, limit=2, cursor=page.next_cursor)
    assert [o.id for o in nxt.items] == ["O3", "O4"] and nxt.next_cursor is None
    kid = repo.browse(Opportunity, q="kidney")
    assert [o.id for o in kid.items] == ["O1", "O3", "O4"] and kid.total == 3
    late = repo.browse(Opportunity, closes_after=date(2027, 6, 1))
    assert [o.id for o in late.items] == ["O4"]
    assert repo.browse(Opportunity, temple_only=True).items == []


def test_browse_never_returns_samples(repo):
    repo.upsert([sample_sch(1)])
    assert repo.browse(Scholarship).items == []


def test_epoch_bumps(repo):
    assert repo.epoch() == 0
    assert repo.bump_epoch() == 1
    assert repo.bump_epoch() == 2
    assert repo.epoch() == 2

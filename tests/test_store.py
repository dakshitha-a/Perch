from datetime import UTC, date, datetime

from perch.schemas import Researcher, Work
from perch.store.sqlite import SQLiteRepository

T = datetime(2026, 10, 28, tzinfo=UTC)


def work(id, authors, day):
    return Work(id=id, title=f"SYNTHETIC {id}", author_ids=authors, publication_date=day,
                source="openalex", source_url=f"https://api.openalex.org/works/{id}", fetched_at=T)


def test_round_trip_keeps_provenance(tmp_path):
    with SQLiteRepository(tmp_path / "x.db") as repo:
        r = Researcher(id="A1", display_name="SYNTHETIC Person", source="openalex",
                       source_url="https://api.openalex.org/authors/A1", fetched_at=T)
        assert repo.upsert([r]) == 1
        got = repo.get(Researcher, "A1")
        assert got == r
        assert repo.get(Work, "A1") is None  # kinds do not collide


def test_upsert_replaces_and_works_by_author_orders_newest_first():
    repo = SQLiteRepository()
    repo.upsert([work("W1", ["A1"], date(2020, 1, 1)), work("W2", ["A1", "A2"], date(2023, 5, 1)),
                 work("W3", ["A2"], date(2024, 1, 1))])
    repo.upsert([work("W1", ["A1"], date(2021, 1, 1))])
    assert [w.id for w in repo.works_by_author("A1")] == ["W2", "W1"]
    assert repo.get(Work, "W1").publication_date == date(2021, 1, 1)
    assert len(repo.list(Work)) == 3

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
    # Name order, case-folded (S43 S6): imaging, research, transplant, then Quantum.
    assert [o.id for o in page.items] == ["O4", "O1"] and page.total == 4
    assert page.next_cursor is not None
    nxt = repo.browse(Opportunity, limit=2, cursor=page.next_cursor)
    assert [o.id for o in nxt.items] == ["O3", "O2"] and nxt.next_cursor is None
    kid = repo.browse(Opportunity, q="kidney")
    assert [o.id for o in kid.items] == ["O4", "O1", "O3"] and kid.total == 3
    late = repo.browse(Opportunity, closes_after=date(2027, 6, 1))
    assert [o.id for o in late.items] == ["O4"]
    assert repo.browse(Opportunity, temple_only=True).items == []


def test_browse_orders_by_name_ignoring_case_with_id_tie_break(repo):
    repo.upsert([opp("Z1", "banana grant"), opp("Z2", "Apple grant"), opp("Z3", "apple grant"),
                 opp("Z4", "Cherry grant")])
    first = repo.browse(Opportunity, limit=3)
    assert [o.id for o in first.items] == ["Z2", "Z3", "Z1"]  # Apple = apple, id breaks the tie
    rest = repo.browse(Opportunity, limit=3, cursor=first.next_cursor)
    assert [o.id for o in rest.items] == ["Z4"]


def test_browse_never_returns_samples(repo):
    repo.upsert([sample_sch(1)])
    assert repo.browse(Scholarship).items == []


def test_epoch_bumps(repo):
    assert repo.epoch() == 0
    assert repo.bump_epoch() == 1
    assert repo.bump_epoch() == 2
    assert repo.epoch() == 2


# --- Temple filters (S43 forks F1 and F2) ---

def temple_trio():
    """A school scholarship, one with no stated scope, one listed as university-wide. SYNTHETIC."""
    from tests.test_temple_dedupe import sch

    one = sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/cst")
    none = sch("temple_pages:b", "SYNTHETIC Harbor Prize", "SDFA", "https://x.example/sdfa")
    wide = none.model_copy(update={"id": "temple_pages:c", "name": "SYNTHETIC Wide Prize",
                                   "scope": "temple_wide"})
    return one, none, wide


def test_temple_only_means_listed_on_a_temple_page_not_temple_funded(repo):
    one, none, wide = temple_trio()
    assert one.temple_funded is None  # nothing says Temple pays: the filter must not need it
    repo.upsert([one, none, wide, opp("O1", "SYNTHETIC grant"), sample_sch(1)])
    got = repo.browse(Scholarship, temple_only=True)
    assert sorted(r.id for r in got.items) == ["temple_pages:a", "temple_pages:b", "temple_pages:c"]
    assert got.total == 3
    assert repo.browse(Opportunity, temple_only=True).items == []
    assert [o.id for o in repo.browse(Opportunity).items] == ["O1"]


def test_temple_sdfa_source_counts_as_a_temple_page(repo):
    one, *_ = temple_trio()
    repo.upsert([one.model_copy(update={"id": "temple:sdfa-1", "source": "temple_sdfa"})])
    assert [r.id for r in repo.browse(Scholarship, temple_only=True).items] == ["temple:sdfa-1"]


def test_unstated_scope_stays_inside_temple_and_schools_are_kept(repo):
    from perch.store.denorm import columns

    one, none, wide = temple_trio()
    assert columns(one).scope == "school" and columns(one).schools == ["CST"]
    assert columns(none).scope == "unstated"  # SDFA is not a school page: no scope, no school
    assert columns(wide).scope == "temple_wide"
    # a school named on a record with another scope is kept, not cleared
    both = wide.model_copy(update={"schools": ["Fox School of Business", "CST"]})
    assert columns(both).scope == "temple_wide"
    assert columns(both).schools == ["CST", "Fox School of Business"]
    # a school scope with no school named is not a stated scope
    assert columns(one.model_copy(update={"schools": []})).scope == "unstated"
    # outside Temple, a missing scope is external
    assert columns(opp("O1", "x")).scope == "external"
    repo.upsert([one, none, both])
    assert [r.id for r in repo.browse(Scholarship, schools=["CST"]).items] == [
        "temple_pages:a", "temple_pages:c"]
    assert repo.browse(Scholarship, temple_only=True).total == 3

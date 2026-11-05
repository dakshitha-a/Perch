"""Browse sort and open-only (S49 V1). SYNTHETIC records; runs on SQLite and on Postgres."""

from __future__ import annotations

from datetime import date

import pytest

from perch.schemas import Scholarship
from tests.test_store import T, repo  # noqa: F401 - the two-backend fixture

TODAY = date(2026, 11, 4)


def sch(id: str, name: str, deadline: date | None, amount: float | None) -> Scholarship:
    return Scholarship(id=f"temple_pages:{id}", name=name, source="temple_pages",
                       source_url="https://example.invalid/" + id, fetched_at=T,
                       deadline=deadline, amount_max=amount,
                       deadline_quote=(f"Due {deadline.day} {deadline.year}" if deadline else None),
                       amount_quote=(f"Up to {int(amount)} dollars" if amount else None),
                       details_url="https://example.invalid/" + id + "/d", details_fetched_at=T)


RECORDS = [
    sch("a", "SYNTHETIC Alder", date(2026, 12, 1), 500),
    sch("b", "SYNTHETIC Birch", None, 9000),
    sch("c", "SYNTHETIC Cedar", date(2026, 11, 4), None),    # today counts as open
    sch("d", "SYNTHETIC Dogwood", date(2026, 3, 1), 500),    # past
    sch("e", "SYNTHETIC Elm", date(2026, 9, 1), None),       # past, newer than d
    sch("f", "SYNTHETIC Fir", date(2027, 1, 15), 100),
    sch("g", "SYNTHETIC Ginkgo", None, None),
]


def ids(page) -> list[str]:
    return [r.id.split(":")[1] for r in page.items]


@pytest.fixture
def loaded(repo):  # noqa: F811
    repo.upsert(RECORDS)
    return repo


def test_name_is_the_default_order(loaded):
    assert ids(loaded.browse(Scholarship, today=TODAY)) == list("abcdefg")


def test_closing_order_upcoming_then_past_newest_first_then_no_date(loaded):
    got = loaded.browse(Scholarship, sort="closing", today=TODAY)
    assert ids(got) == ["c", "a", "f", "e", "d", "b", "g"]
    assert got.total == 7


def test_amount_order_largest_first_nulls_last_ties_by_name(loaded):
    got = loaded.browse(Scholarship, sort="amount", today=TODAY)
    assert ids(got) == ["b", "a", "d", "f", "c", "e", "g"]


def test_open_only_keeps_null_and_today_and_drops_past(loaded):
    got = loaded.browse(Scholarship, open_only=True, today=TODAY)
    assert ids(got) == ["a", "b", "c", "f", "g"] and got.total == 5
    both = loaded.browse(Scholarship, open_only=True, sort="closing", today=TODAY)
    assert ids(both) == ["c", "a", "f", "b", "g"]


@pytest.mark.parametrize("sort", ["closing", "amount"])
def test_pages_join_into_the_same_order_as_one_page(loaded, sort):
    whole = ids(loaded.browse(Scholarship, sort=sort, today=TODAY))
    seen, cursor = [], None
    for _ in range(10):
        page = loaded.browse(Scholarship, sort=sort, today=TODAY, limit=2, cursor=cursor)
        seen += ids(page)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == whole and len(seen) == 7


def test_a_name_cursor_is_not_an_offset_cursor(loaded):
    page = loaded.browse(Scholarship, limit=2, today=TODAY)
    with pytest.raises(ValueError):
        loaded.browse(Scholarship, sort="closing", today=TODAY, cursor=page.next_cursor)


def test_route_passes_sort_and_open_only_and_reports_the_sort(tmp_path):
    from tests.test_api import make

    c, service = make(tmp_path)
    with service.repo() as r:
        r.conn.execute("DELETE FROM records")
        r.conn.commit()
        r.upsert(RECORDS)
    got = c.get("/awards?sort=amount&limit=3").json()
    assert got["sort"] == "amount"
    assert [i["id"][-1] for i in got["groups"][0]["items"]] == ["b", "a", "d"]
    assert c.get("/awards").json()["sort"] == "name"
    assert c.get("/awards?sort=nope").status_code == 422
    opened = c.get("/awards?open_only=true").json()["groups"][0]
    # the server's own date decides which dates are past
    assert opened["total"] == sum(r.deadline is None or r.deadline >= date.today()
                                  for r in RECORDS)

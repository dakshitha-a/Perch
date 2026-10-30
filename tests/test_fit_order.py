"""One score and one order (S27): the 0-100 fit orders the candidates; the best `top` stay."""

from datetime import UTC, datetime

from perch.schemas import Lead
from perch.service import by_fit, candidates

T = datetime(2026, 10, 30, tzinfo=UTC)


def lead(i, fit, status="new"):
    return Lead(id=f"b:{i}", source="grants_gov", source_url="https://www.grants.gov/x",
                fetched_at=T, brief_id="b", route="A", record_id=f"grants_gov:SYNTHETIC-{i}",
                rank=i, fit_score=fit, status=status)


def test_fit_orders_and_the_best_stay():
    leads = [lead(1, 40), lead(2, None), lead(3, 90), lead(4, 90), lead(5, 10, "kept"),
             lead(6, 5, "dismissed")]
    out = by_fit(leads, top=2)
    # 90 and 90 (ranking order breaks the tie), then the kept and dismissed leads stay.
    assert [x.id for x in out] == ["b:3", "b:4", "b:5", "b:6"]
    assert [x.rank for x in out] == [1, 2, 3, 4]
    # No fit sorts last.
    assert [x.id for x in by_fit(leads[:3], top=3)] == ["b:3", "b:1", "b:2"]


def test_twenty_candidates_only_when_explained():
    assert candidates({"top": 10, "explain": True}) == 20
    assert candidates({"top": 10, "explain": False}) == 10
    assert candidates({"top": 25, "explain": True}) == 25

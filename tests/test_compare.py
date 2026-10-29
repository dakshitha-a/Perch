"""Compare cells are copied from records or computed from them by code. SYNTHETIC."""

from datetime import UTC, date, datetime

from perch.compare import NONE, closes, money
from perch.schemas import Opportunity

T = datetime(2026, 10, 29, tzinfo=UTC)


def opp(**kw):
    return Opportunity(id="grants_gov:SYN-1", source="grants_gov", source_url="u", fetched_at=T,
                       opportunity_number="SYN-1", title="SYNTHETIC", agency="X", **kw)


def test_money_copies_floor_and_ceiling():
    assert money(opp(award_floor=50000, award_ceiling=250000)).text == "$50,000 to $250,000"
    assert money(opp(award_ceiling=250000)).text == "Up to $250,000"
    assert money(opp()).text == NONE and money(opp()).sort is None


def test_closes_counts_days_from_the_brief_date():
    c = closes(opp(close_date=date(2026, 11, 28)), date(2026, 10, 29))
    assert c.text == "2026-11-28" and c.note == "30 days after the brief date"
    assert closes(opp(close_date=date(2026, 10, 1)), date(2026, 10, 29)).note \
        == "on or before the brief date"
    gone = closes(opp(status="forecasted"), date(2026, 10, 29))
    assert gone.text == NONE and gone.note == "listed as forecasted"


def test_research_compare_offers_only_research_offices():
    """S22, audit M1: the student offices showed on a PI's hand-off as "no kept undefined"."""
    from perch.compare import rows_json

    routes = {o["route"] for o in rows_json([])["offices"]}
    assert routes == {"A", "B"}

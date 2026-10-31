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


def test_a_placeholder_close_date_reads_as_the_record_says():
    """U3: NSF dates open-anytime programmes decades out. Past ten years, as on the card,
    Compare shows the record's own words and no day count; it still sorts by the date."""
    far = opp(close_date=date(2076, 10, 7), close_date_note="Proposals accepted anytime")
    c = closes(far, date(2026, 10, 29))
    assert c.text == "Proposals accepted anytime" and "days" not in (c.note or "")
    assert c.sort == "2076-10-07"
    near = opp(close_date=date(2027, 1, 7), close_date_note="Proposals accepted anytime")
    assert closes(near, date(2026, 10, 29)).text == "2027-01-07"
    assert closes(opp(close_date=date(2076, 10, 7)), date(2026, 10, 29)).text == "2076-10-07"


def test_research_compare_offers_only_research_offices():
    """S22, audit M1: the student offices showed on a PI's hand-off as "no kept undefined"."""
    from perch.compare import rows_json

    routes = {o["route"] for o in rows_json([])["offices"]}
    assert routes == {"A", "B"}


def test_compare_and_scout_show_the_cards_match():
    """U6: one number for one lead. Compare's evidence cell and Scout's explain step show
    the card's Match, not the rank or the model's own fit number."""
    from perch.compare import route_a_row
    from perch.schemas import Lead
    from perch.scout.loop import summarise

    lead = Lead(id="b:1", source="grants_gov", source_url="u", fetched_at=T, brief_id="b",
                route="A", record_id="grants_gov:SYN-1", rank=1, match_score=67,
                cited_ids=["W1"])
    cell = route_a_row(lead, opp(), date(2026, 10, 29)).cells["evidence"]
    assert cell.text.startswith("Match 67 (good)") and "order" not in cell.text
    assert summarise("explain_fit", {"fit": 85, "match_on_card": 67}) \
        == "explained; the card says Match 67 (good)"
    assert "85" not in summarise("explain_fit", {"fit": 85, "match_on_card": None})

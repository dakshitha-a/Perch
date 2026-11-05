"""S50 G8: a placeholder close date (NSF's 2076, a 2099 with no note) is never shown as a
date: the record's own words, or a fixed line when it has none. SYNTHETIC records."""

from datetime import UTC, date, datetime

from perch import datefmt
from perch.schemas import Opportunity

T = datetime(2026, 11, 1, tzinfo=UTC)
AS_OF = date(2026, 11, 6)


def opp(close: date | None, note: str | None = None, n: str = "SYN-1") -> Opportunity:
    return Opportunity(id=f"grants_gov:{n}", source="grants_gov", fetched_at=T,
                       source_url=f"https://example.gov/SYNTHETIC/{n}", opportunity_number=n,
                       title="SYNTHETIC Core Programs", agency="SYNTHETIC Agency",
                       status="posted", close_date=close, close_date_note=note,
                       eligible_applicants=["Private institutions of higher education"])


ANYTIME = opp(date(2076, 10, 5), "Proposals accepted anytime")
BARE = opp(date(2099, 1, 1), n="SYN-2")


def test_far_dates_read_as_words_in_every_text_helper():
    for o, words in ((ANYTIME, "Proposals accepted anytime"), (BARE, datefmt.FAR_TEXT)):
        assert datefmt.closes(o, AS_OF) == words
        assert datefmt.deadline(o, AS_OF) == words
        assert datefmt.no_deadline(o, AS_OF)
        assert "2076" not in datefmt.deadline(o, AS_OF) and "2099" not in words


def test_a_real_date_is_still_a_date():
    o = opp(date(2027, 2, 15), n="SYN-3")
    assert datefmt.closes(o, AS_OF) == "15 Feb 2027"
    assert not datefmt.no_deadline(o, AS_OF)


def test_browse_item_hides_the_placeholder_date():
    from perch.browse.routes import item

    for o in (ANYTIME, BARE):
        d = item(o)
        assert d["close_date"] is None and d["deadline"] is None
        assert d["placeholder_close_date"] == o.close_date.isoformat()
        assert d["close_text"] == datefmt.closes(o)
    d = item(opp(date(2027, 2, 15), n="SYN-3"))
    assert d["close_date"] == "2027-02-15" and d["close_text"] == "15 Feb 2027"
    assert "placeholder_close_date" not in d


def test_model_view_and_scout_facts_carry_no_placeholder_date():
    from perch.scout.student_tools import facts_of
    from perch.skills import opportunity_view

    for o in (ANYTIME, BARE):
        assert str(o.close_date.year) not in opportunity_view(o)
        assert str(o.close_date.year) not in str(facts_of(o))

"""S49 function review, must-fix and should-fix items (docs/design/S49_FUNCTION_REVIEW.md).

No spend, no network. Every record here is SYNTHETIC.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from perch.schemas import Opportunity, Scholarship
from perch.scout import answer as ans
from perch.scout.read_tools import facts

T = datetime(2026, 11, 1, tzinfo=UTC)
AS_OF = date(2026, 11, 4)


def sch(**kw) -> Scholarship:
    base = dict(id="temple_pages:s1", source="temple_pages", fetched_at=T,
                source_url="https://example.temple.edu/s1", name="SYNTHETIC Quillfen Award")
    return Scholarship(**(base | kw))


def opp(**kw) -> Opportunity:
    base = dict(id="grants_gov:SYN-1", source="grants_gov", fetched_at=T,
                source_url="https://www.grants.gov/x", opportunity_number="SYN-1",
                title="SYNTHETIC Program", agency="National Science Foundation",
                status="posted")
    return Opportunity(**(base | kw))


# --- M3: the page's deadline words are a deadline ---

def test_m3_facts_quote_the_page_words_when_there_is_no_date():
    s = sch(deadline_quote="Due Date: April 16", details_url="https://example.temple.edu/s1",
            details_fetched_at=T)
    f = facts(s, AS_OF)
    assert "April 16" in f["deadline"] and "not stated" not in f["deadline"]
    o = opp(close_date_note="Proposals accepted anytime")
    assert "Proposals accepted anytime" in facts(o, AS_OF)["deadline"]


def test_m3_code_check_rejects_a_false_no_deadline_claim():
    s = sch(deadline_quote="Due Date: April 16", details_url="https://example.temple.edu/s1",
            details_fetched_at=T)
    seen = {s.id: s}
    assert ans.code_check(f"The record gives no deadline [{s.id}].", [s.id], seen, None,
                          AS_OF) is False
    bare = sch(id="temple_pages:s2")
    assert ans.code_check(f"The record gives no deadline [{bare.id}].", [bare.id],
                          {bare.id: bare}, None, AS_OF) is True


# --- M1: open-anytime calls with a recent posted date stay in the brief ---

UNI = ["Unrestricted (i.e., open to any type of entity above), subject to any clarification in "
       "text field entitled \"Additional Information on Eligibility\""]


def test_m1_open_anytime_with_a_recent_posted_date_is_eligible():
    from perch.eligibility import Constraints, check

    c = Constraints(as_of=AS_OF)
    o = opp(open_date=date(2024, 2, 17), close_date_note="Proposals accepted anytime",
            eligible_applicants=UNI)
    assert check(o, c) == []
    # No note: still no close date.
    assert "no close date in the record" in check(o.model_copy(update={"close_date_note": None}),
                                                  c)
    # The same words on a listing posted more than ten years ago: left out.
    old = o.model_copy(update={"open_date": date(2014, 4, 18)})
    assert "no close date in the record" in check(old, c)
    # A continuing-basis notice is not an anytime call.
    eda = o.model_copy(update={"close_date_note": "Applications are accepted on a continuing "
                               "basis and processed as received."})
    assert "no close date in the record" in check(eda, c)
    # A forecast is still a forecast.
    assert check(o.model_copy(update={"status": "forecasted"}), c)

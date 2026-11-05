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


# --- student rules: M2 level from the page tag, M7 past-cycle dates ---

def _facts(level: str):
    from perch.student import StudentFacts

    return StudentFacts(level=level)


def test_m2_the_page_level_tag_sets_the_level_rule():
    from perch.student import check

    ug = sch(audience_level="undergraduate")
    grad = sch(audience_level="graduate")
    mixed = sch(audience_level="mixed")
    v = check(ug, _facts("graduate"), AS_OF)
    assert v.verdict == "not eligible" and v.reason == "level"
    assert v.lines == ["Open to undergraduate students; your CV says graduate."]
    assert check(grad, _facts("bachelor's"), AS_OF).verdict == "not eligible"
    assert check(grad, _facts("graduate"), AS_OF).verdict == "may be eligible"
    assert check(grad, _facts("professional"), AS_OF).verdict == "may be eligible"
    assert check(ug, _facts("bachelor's"), AS_OF).verdict == "may be eligible"
    assert check(mixed, _facts("graduate"), AS_OF).reason != "level"
    # level_of_study, when set, still wins.
    both = sch(audience_level="undergraduate", level_of_study=["graduate"])
    assert check(both, _facts("graduate"), AS_OF).reason != "level"


def test_m7_a_past_cycle_temple_date_is_may_be_eligible_with_the_line():
    from perch.student import check

    kw = dict(deadline_quote="Applications are due February 13, 2026.",
              details_url="https://example.temple.edu/s1", details_fetched_at=T)
    old = sch(deadline=date(2026, 2, 13), **kw)
    v = check(old, _facts("bachelor's"), AS_OF)
    assert v.verdict == "may be eligible" and v.reason == "past_cycle_date"
    assert v.lines[0] == ("The page shows a past date, 13 Feb 2026. Check the page for this "
                          "year's date.")
    # A date that passed within the month is this cycle's: closed.
    recent = sch(deadline=date(2026, 10, 20),
                 **(kw | {"deadline_quote": "Applications are due October 20, 2026."}))
    assert check(recent, _facts("bachelor's"), AS_OF).reason == "deadline"
    # Synthetic and NIH records keep the plain deadline rule.
    smp = Scholarship(id="sample:x", source="synthetic", source_url="perch://sample",
                      fetched_at=T, name="SYNTHETIC Sample", canary="CANARY-x",
                      deadline=date(2026, 2, 13))
    assert check(smp, _facts("bachelor's"), AS_OF).reason == "deadline"


# --- the student pool: M8 staff awards out, S7 one copy per award ---

def test_m8_staff_and_faculty_awards_are_not_in_the_student_pool():
    from perch.student import student_pool

    recs = [sch(id="temple_pages:a", name="Professional Advisor", audience_level="undergraduate"),
            sch(id="temple_pages:b", name="The Michele O'Connor Advising Service Award"),
            sch(id="temple_pages:c", name="SYNTHETIC Faculty Thing", audience_level="faculty"),
            sch(id="temple_pages:d", name="SYNTHETIC Student Award")]
    pool, _ = student_pool(recs)
    assert [s.id for s in pool] == ["temple_pages:d"]


def test_s7_an_award_on_both_temple_lists_appears_once():
    from perch.student import student_pool

    a = sch(id="temple_pages:g", name="SYNTHETIC Gillfen Scholarship",
            source_url="https://example.temple.edu/g")
    b = Scholarship(id="temple_sdfa:g", source="temple_sdfa", fetched_at=T,
                    source_url="https://example.temple.edu/sdfa/g",
                    name="SYNTHETIC Gillfen Scholarship", sponsor="SYNTHETIC Sponsor",
                    level_of_study=["bachelor's"])
    other = sch(id="temple_pages:h", name="SYNTHETIC Other Award")
    pool, also = student_pool([a, b, other])
    assert {s.id for s in pool} == {"temple_sdfa:g", "temple_pages:h"}
    assert also == {"temple_sdfa:g": ["https://example.temple.edu/g"]}
    # Two copies on one list are left alone here.
    same = sch(id="temple_pages:g2", name="SYNTHETIC Gillfen Scholarship")
    assert len(student_pool([a, same])[0]) == 2


def test_s10_ruled_out_records_are_capped_at_five():
    from perch.student import Scored, Verdict, choose

    def sc(i, v):
        return Scored(sch(id=f"temple_pages:{i}"), None, -i, Verdict(v, None))

    xs = [sc(i, "not eligible") for i in range(8)] + [sc(10 + i, "may be eligible")
                                                     for i in range(3)]
    got = choose(xs, top=10)
    assert sum(x.verdict.verdict == "not eligible" for x in got) == 5
    assert len(got) == 8

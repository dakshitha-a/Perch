"""S51 H5: the validator reads a record's nested fields (a scholarship's eligibility) and the
numbers in its lists. Every value still comes from a record field (rule 3). SYNTHETIC."""

from datetime import UTC, date, datetime

from perch.schemas import Scholarship, ScholarshipEligibility
from perch.validate import check, evidence

T = datetime(2026, 11, 1, tzinfo=UTC)


def rec(**kw) -> Scholarship:
    return Scholarship(id="temple_pages:s1", source="temple_pages", fetched_at=T,
                       source_url="https://example.temple.edu/s1", name="SYNTHETIC Award",
                       eligibility=ScholarshipEligibility(**kw))


def test_a_nested_gpa_is_an_allowed_number():
    s = rec(gpa_min=3.5)
    assert check("It asks for a GPA of 3.50.", [s.id], {s.id: s}).ok


def test_class_years_in_a_nested_list_are_allowed_numbers():
    s = rec(class_year=[1, 2, 3])
    assert check("The record lists class years 1, 2 and 3.", [s.id], {s.id: s}).ok


def test_a_nested_date_and_text_count_and_a_wrong_number_still_fails():
    s = rec(graduation_by=date(2027, 5, 31), citizenship="SYNTHETIC citizen of Quillfen")
    e = evidence(s)
    assert date(2027, 5, 31) in e.dates and "Quillfen" in e.text
    assert not check("It asks for a GPA of 3.9.", [s.id], {s.id: s}).ok


def test_the_digits_of_a_nested_url_or_a_timing_are_not_allowed_numbers():
    from perch.schemas import Brief, Opportunity

    o = Opportunity(id="temple_pages:o1", source="temple_pages", fetched_at=T,
                    source_url="https://example.temple.edu/o1", title="SYNTHETIC Seed Grant",
                    opportunity_number="O1", agency="SYNTHETIC Office",
                    field_sources={"amount_max": "https://example.temple.edu/page/48213"})
    assert "48213" not in evidence(o).numbers
    b = Brief(id="b", source="perch", source_url="perch://b", fetched_at=T,
              researcher_id="A1", timings_ms={"route_a": 7731.0})
    assert "7731" not in evidence(b).numbers

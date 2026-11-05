"""S51 E5: Scout's get_record never shows "None (the record's own words)". A far-off
placeholder close date with no note reads as the record stating no closing date.
SYNTHETIC records."""

import json
from datetime import UTC, date, datetime

from perch.schemas import Opportunity
from perch.scout.tools import TOOLS
from tests.test_scout import ctx, service  # noqa: F401 - the fixture


def test_a_placeholder_date_with_no_note_says_the_record_states_no_closing_date(service):  # noqa: F811
    far = Opportunity(id="grants_gov:SYN-99-1", source="grants_gov", source_url="u",
                      fetched_at=datetime(2026, 10, 29, tzinfo=UTC), opportunity_number="SYN-99-1",
                      title="SYNTHETIC standing programme", agency="NSF",
                      close_date=date(2099, 1, 1))
    with service.repo() as r:
        r.upsert([far])
    got = TOOLS["get_record"][1](ctx(service), id=far.id)["record"]
    text = json.dumps(got)
    assert "None" not in text and "2099" not in text
    assert got["deadline"] == "The record states no closing date."

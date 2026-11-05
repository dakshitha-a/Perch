"""S50 Q3: a kept Temple internal call never goes into the Research Development draft. Its
own page names its contact, and a code-written line says so. SYNTHETIC records."""

import pytest

from perch.offices import OFFICES
from perch.schemas import Lead, Opportunity
from perch.skills.handoff import TEMPLE_OWN_CONTACT, draft_handoff
from tests.test_skills import T, _handoff_inputs, audited, handoff_reply

PAGE = Opportunity(id="temple_pages:syn-fund", source="temple_pages", fetched_at=T,
                   source_url="https://example.edu/SYNTHETIC/fund", opportunity_number="syn-fund",
                   title="SYNTHETIC Seed Fund", agency="Temple University")
INTERNAL = Lead(id="b:t1", source="temple_pages", source_url=PAGE.source_url, fetched_at=T,
                brief_id="b", route="A", record_id=PAGE.id, rank=1, status="kept",
                group="temple_internal")


def test_internal_calls_are_left_out_with_a_code_line():
    res, items, papers = _handoff_inputs()
    p, _ = audited([handoff_reply(
        "My work studies living kidney donor communication [W1]. I would like to discuss "
        "SYNTHETIC ELSI [PAR-1], which funds research on these questions.")])
    d = draft_handoff(OFFICES["research_development"], res, [*items, (INTERNAL, PAGE)],
                      papers, p)
    assert "SYNTHETIC Seed Fund" not in d.body and "syn-fund" not in d.body
    assert d.lead_ids == ["b:1"] and d.left_out == ["b:t1"]
    assert d.left_out_note == TEMPLE_OWN_CONTACT
    assert d.subject == "Request to discuss 1 funding opportunity"


def test_only_internal_calls_is_no_draft():
    res, _, papers = _handoff_inputs()
    with pytest.raises(LookupError, match="contact"):
        draft_handoff(OFFICES["research_development"], res, [(INTERNAL, PAGE)], papers, None)

"""Egress filter (private mode, "Leaving the app"). All text is SYNTHETIC and built at
test time; no private text is in the repo (standing rule 1)."""

import json
from datetime import UTC, datetime

from perch import egress
from perch.schemas import Lead, Researcher, Work

T = datetime(2026, 10, 29, tzinfo=UTC)
CANARY = "zqx" + "canary" + "77"
EMAIL = "a.b" + "@" + "example.org"  # built at run time: the repo carries no addresses


def test_private_text_is_withheld_by_default_and_public_text_passes():
    assert egress.release("Public sentence [W1].", ["W1"]) == "Public sentence [W1]."
    assert egress.release(f"From my aims {CANARY}.", ["private:aims#1"]) == egress.WITHHELD
    w = Work(id="private:aims#1", source="private", source_url="-", fetched_at=T, title="x")
    pub = Work(id="https://openalex.org/W1", source="openalex", source_url="u",
               fetched_at=T, title="y")
    assert egress.public_only([w, pub]) == [pub]


def test_masking_is_consistent_and_unmasks_from_the_in_memory_key():
    person, inst = "Dr SYNTHETIC Quill", "SYNTHETIC Institute of Owls"
    private = f"We will map {CANARY} owl perch networks in winter roosts across the city."
    public = "Owl perch networks are studied in many places."
    m = egress.Masker([private], [public], terms={"PERSON": [person],
                                                  "INSTITUTION": [inst]})
    text = (f"{person} at {inst} ({EMAIL}, 215-555-0100, 0000-0002-1825-0097, "
            f"R01CA123456) plans to map {CANARY} owl perch networks in winter roosts. "
            f"{person} again.")
    masked = m.mask(text)
    assert person not in masked and inst not in masked and CANARY not in masked
    assert "example.org" not in masked and "555" not in masked and "R01CA123456" not in masked
    assert masked.count("[PERSON-1]") == 2 and "[INSTITUTION-1]" in masked
    assert "[EMAIL-1]" in masked and "[PHONE-1]" in masked and "[ORCID-1]" in masked
    assert "[AWARD-1]" in masked and "[PRIVATE-PHRASE-1]" in masked
    assert m.unmask(masked) == text
    assert "research direction" in egress.WARNING


def test_handoff_paragraph_citing_a_private_record_falls_back(tmp_path):
    from perch.llm.audit import AuditedProvider, AuditLog
    from perch.llm.fake import FakeProvider
    from perch.offices import OFFICES
    from perch.skills.handoff import FALLBACK, draft_handoff

    res = Researcher(id="https://openalex.org/A1", display_name="SYNTHETIC Researcher",
                     source="openalex", source_url="u", fetched_at=T)
    lead = Lead(id="b:B1", source="openalex", source_url="u", fetched_at=T, brief_id="b",
                route="B", record_id="https://openalex.org/I1", explanation="SYNTHETIC.")
    reply = json.dumps({"paragraph": f"I plan {CANARY} work. I would like to discuss B1.",
                        "cited_ids": ["B1"]})
    d = draft_handoff(OFFICES["technology_commercialization"], res, [(lead, None)], [],
                      AuditedProvider(FakeProvider([reply]), AuditLog(None), "x"))
    assert CANARY in d.body  # cites no private record: released as written
    reply2 = json.dumps({"paragraph": f"I plan {CANARY} work. I would like to discuss B1.",
                         "cited_ids": ["B1", "private:aims#1"]})
    p2 = AuditedProvider(FakeProvider([reply2, reply2]), AuditLog(None), "x")
    d2 = draft_handoff(OFFICES["technology_commercialization"], res, [(lead, None)], [], p2)
    # Until S13 adds session records, the validator rejects a private citation; the
    # egress check in draft_handoff is the second line. Either way the canary stays in.
    assert CANARY not in d2.body and FALLBACK in d2.body and d2.flagged


def test_a_masked_phrase_takes_the_rest_of_its_clause():
    """T11: the student export read "one of your achievements [PRIVATE-PHRASE-3] creek."
    The model retold "outfalls along a SYNTHETIC creek" as "outfalls along a creek", so the
    last private n-gram ended at "a". Words of the documents left between a masked run and
    the clause's end join it; a public word after the clause does not."""
    from perch.egress import Masker

    ach = ("SYNTHETIC achievement. Built a QGIS map of storm drain outfalls along a SYNTHETIC "
           "creek that a local volunteer group now uses (invented).")
    m = Masker([ach], ["A public listing on stream ecology and research."])
    text = ("Cited work: one of your achievements built a QGIS map of storm drain outfalls "
            "along a creek [achievement-c]. It fits stream ecology research.")
    out = m.mask(text)
    assert "creek" not in out and "outfalls" not in out
    assert out.startswith("Cited work: one of your achievements [PRIVATE-PHRASE-1] [achievement-c]")
    assert "It fits stream ecology research." in out
    assert m.unmask(out) == text

import json
from datetime import UTC, date, datetime

import numpy as np

from perch.llm.audit import AuditedProvider, AuditLog
from perch.llm.fake import FakeProvider
from perch.profile import Profile, Thread
from perch.schemas import Opportunity, Work
from perch.skills.fit import explain_leads
from perch.skills.summary import summarise_profile

T = datetime(2026, 10, 28, tzinfo=UTC)


def work(i, title):
    return Work(id=f"https://openalex.org/W{i}", title=f"SYNTHETIC {title}", publication_year=2021,
                publication_date=date(2021, 1, 1), author_ids=["A"], source="openalex",
                source_url=f"https://api.openalex.org/works/W{i}", fetched_at=T)


WORKS = {w.id: w for w in [work(1, "living kidney donor communication"),
                           work(2, "kidney transplant waitlist networks"),
                           work(3, "organ donation attitudes")]}
PROFILE = Profile("A", date(2026, 10, 28), "fake",
                  [Thread(0, np.zeros(2), list(WORKS), 1.0, "kidney, donor", [])], list(WORKS))
OPP = Opportunity(id="grants_gov:PAR-1", opportunity_number="PAR-1", title="SYNTHETIC ELSI (R01)",
                  agency="NIH", close_date=date(2026, 11, 18), source="grants_gov",
                  source_url="https://www.grants.gov/x", fetched_at=T)


def audited(replies):
    log = AuditLog(None)
    return AuditedProvider(FakeProvider(replies), log, "x"), log


def fit_reply(explanation, cited=("PAR-1", "W1"), finding_id="W1"):
    first, _, rest = explanation.partition(". ")
    return json.dumps({"reasoning": "r", "fit": 80, "opportunity_sentence": first + ".",
                       "research_findings": [{"paper_id": finding_id, "finding": rest}],
                       "link_sentence": "Both concern donation.", "cited_ids": list(cited)})


GOOD = "PAR-1 funds research on ethics of donation. studied living kidney donor communication."


def test_fit_passes_first_time_and_is_logged():
    p, log = audited([fit_reply(GOOD)])
    (v,) = explain_leads([OPP], PROFILE, WORKS, p)
    assert not v.flagged and v.value.fit == 80 and v.attempts == 1
    assert log.rejection_rate("fit_explainer") == (0, 1)
    assert sum(e["kind"] == "call" for e in log.events) == 1


def test_invented_number_is_regenerated_then_passes():
    bad = GOOD + " It pays $2,000,000."
    p, log = audited([fit_reply(bad), fit_reply(GOOD)])
    (v,) = explain_leads([OPP], PROFILE, WORKS, p)
    assert v.attempts == 2 and not v.flagged
    assert "number '2000000'" in p.inner.calls[1]["messages"][0].content  # errors fed back
    assert log.rejection_rate("fit_explainer") == (1, 2)


def test_twice_bad_is_flagged_without_explanation():
    p, log = audited([fit_reply(GOOD, cited=("W1",)), fit_reply(GOOD, cited=("PAR-1", "W9"))])
    (v,) = explain_leads([OPP], PROFILE, WORKS, p)
    assert v.flagged and v.value is None
    assert any("W9" in e for e in v.errors)


def test_summary_skill_validates_topics_and_two_sentences():
    reply = json.dumps({"topics": [{"label": "living donation", "work_ids": ["W1"]},
                                   {"label": "waitlist networks", "work_ids": ["W2"]},
                                   {"label": "donation attitudes", "work_ids": ["W3"]}],
                        "summary": "Studies kidney donation. Focus on communication.",
                        "cited_ids": ["W1", "W2", "W3"]})
    p, log = audited([reply])
    v = summarise_profile(PROFILE, WORKS, p)
    assert not v.flagged and len(v.value.topics) == 3
    one_sentence = json.loads(reply)
    one_sentence["summary"] = "Only one sentence."
    p, log = audited([json.dumps(one_sentence)] * 2)
    assert summarise_profile(PROFILE, WORKS, p).flagged


def test_layer2_flags_unsupported_factual_sentence_only():
    from perch.grounding import FakeGrounder

    reply = json.dumps({"reasoning": "r", "fit": 70,
                        "opportunity_sentence": "PAR-1 funds deep ocean volcano drilling.",
                        "research_findings": [{
                            "paper_id": "W1",
                            "finding": "studied living kidney donor communication"}],
                        "link_sentence": "The fit is weak overall.", "cited_ids": ["PAR-1", "W1"]})
    p, log = audited([reply])
    (v,) = explain_leads([OPP], PROFILE, WORKS, p, grounder=FakeGrounder())
    assert v.value.unsupported == ["PAR-1 funds deep ocean volcano drilling."]
    assert set(v.value.support) == {"opportunity_sentence", "W1"}
    assert v.value.research_sentence == "Cited work: W1 studied living kidney donor communication."
    assert log.rejection_rate("fit_explainer", layer=2) == (1, 1)


def test_finding_must_name_a_given_and_cited_paper():
    p, log = audited([fit_reply(GOOD, finding_id="W9"), fit_reply(GOOD, finding_id="W2")])
    (v,) = explain_leads([OPP], PROFILE, WORKS, p)
    assert v.flagged
    assert any("W9" in e for e in log.events[1]["errors"])


# --- skill 3, hand-off drafter (SYNTHETIC records) ---

def _handoff_inputs():
    from perch.schemas import Lead, Researcher
    res = Researcher(id="https://openalex.org/A1", display_name="SYNTHETIC Researcher",
                     source="openalex", source_url="u", fetched_at=T)
    opp = OPP.model_copy(update={"award_ceiling": 250000.0})
    lead = Lead(id="b:1", source="grants_gov", source_url="u", fetched_at=T, brief_id="b",
                route="A", record_id=opp.id, rank=1, cited_ids=["PAR-1", "W1"], status="kept")
    return res, [(lead, opp)], [WORKS["https://openalex.org/W1"]]


def handoff_reply(paragraph, cited=("PAR-1", "W1")):
    return json.dumps({"paragraph": paragraph, "cited_ids": list(cited)})


def test_handoff_model_writes_the_paragraph_and_code_writes_the_numbers():
    from perch.offices import OFFICES
    from perch.skills.handoff import draft_handoff
    res, items, papers = _handoff_inputs()
    p, log = audited([handoff_reply(
        "My work studies living kidney donor communication [W1]. I would like to discuss "
        "SYNTHETIC ELSI [PAR-1], which funds research on these questions.")])
    d = draft_handoff(OFFICES["research_development"], res, items, papers, p)
    assert not d.flagged and d.cited_ids == ["PAR-1", "W1"]
    assert d.body.startswith("Dear Research Development team,\n\nMy work studies")
    assert "PAR-1: SYNTHETIC ELSI (R01). NIH; closes 18 Nov 2026; award size up to $250,000." \
        in d.body
    assert d.body.endswith("Best regards,\nSYNTHETIC Researcher")
    assert d.subject == "Request to discuss 1 funding opportunity"
    assert [e["passed"] for e in log.events if e["kind"] == "validation"] == [True]


def test_handoff_advice_or_invented_numbers_fall_back_to_code_text():
    from perch.offices import OFFICES
    from perch.skills.handoff import FALLBACK, draft_handoff
    res, items, papers = _handoff_inputs()
    p, _ = audited([
        handoff_reply("My work studies donors [W1]. I should apply to SYNTHETIC ELSI [PAR-1]."),
        handoff_reply("My work studies donors [W1]. SYNTHETIC ELSI [PAR-1] gives $900,000."),
    ])
    d = draft_handoff(OFFICES["research_development"], res, items, papers, p)
    assert d.flagged and FALLBACK in d.body and "$900,000" not in d.body
    assert any("900000" in e for e in d.errors)


def test_student_fit_prompt_never_says_researcher() -> None:
    """S22, audit M5: a student's explanation must not call them the researcher."""
    from perch.skills.fit import INSTRUCTIONS, STUDENT_INSTRUCTIONS

    assert STUDENT_INSTRUCTIONS != INSTRUCTIONS
    assert "for the student" in STUDENT_INSTRUCTIONS
    assert "a researcher's published work" not in STUDENT_INSTRUCTIONS
    assert "never \"the researcher\"" in STUDENT_INSTRUCTIONS


def test_sentence_count_ignores_abbreviations():
    from perch.skills import sentences

    assert sentences("The U.S. National Science Foundation funds SYNTHETIC work [X].") == 1
    assert sentences("It funds catalysis, e.g. SYNTHETIC catalysts, and more.") == 1
    assert sentences("Work by Smith et al. shows X. Then Y.") == 2
    assert sentences("Funds DNA. Also RNA.") == 2


def test_handoff_opening_carries_no_citation_keys_and_a_private_researcher_signs_it():
    """Q23: "[26-519]" and "[private:proposal]" stayed in the email's opening, since the
    old pattern wanted a leading letter. Q26: "Best regards, You (private)"."""
    from perch.offices import OFFICES
    from perch.schemas import Researcher
    from perch.skills.handoff import draft_handoff, plain_citations

    res, items, papers = _handoff_inputs()
    p, _ = audited([handoff_reply(
        "My work studies living kidney donor communication [W1]. I would like to discuss "
        "SYNTHETIC ELSI [PAR-1], which funds research on these questions.")])
    d = draft_handoff(OFFICES["research_development"], res, items, papers, p)
    opening = d.body.split("\n\n")[1]
    assert "[" not in opening and "communication. I would" in opening
    recs = {"26-519": items[0][1], "W1": papers[0]}
    assert plain_citations("Chemistry [26-519] and more [private:proposal, W1].", recs,
                           {"W1"}) == "Chemistry (PAR-1) and more."
    assert plain_citations("A note [sic].", recs, set()) == "A note [sic]."
    you = Researcher(id="private:you", display_name="You (private)", source="private",
                     source_url="private://session", fetched_at=T)
    d = draft_handoff(OFFICES["research_development"], you, items, papers, None)
    assert d.body.endswith("Best regards,\n") and "(private)" not in d.body


# --- skill 4, cover points (S33; SYNTHETIC text only) ---

CV_TEXT = """SYNTHETIC CV, an invented person. Canary PERCH-CANARY-TEST-CV

## Contact
lab.vale""" + "@" + """example.invalid, 215-555-0100, https://example.invalid/vale

## Education
- PhD, Biomedical Engineering, SYNTHETIC Institute, 2021

## Appointments
- Assistant Professor, SYNTHETIC Department of Bioengineering, 2023 to present

## Funding
- SYNTHETIC seed grant SEED-0000-01, insole force sensing, $40,000

## Skills
- Wearable sensor design; gait analysis
"""


def _cover_inputs():
    from perch.private.inputs import make_doc
    from perch.schemas import Award

    cv = make_doc("cv", CV_TEXT)
    proposal = make_doc("proposal", "SYNTHETIC draft aims: a shoe-worn sensor that records "
                        "ground reaction force at home for people with gait change.")
    opp = OPP.model_copy(update={"description": "SYNTHETIC announcement: supports early-career "
                                 "investigators developing wearable sensing for movement "
                                 "disorders. Applicants describe prior sensor work and a "
                                 "mentoring plan."})
    award = Award(id="nih:1", source="nih_reporter", source_url="https://example.invalid/a",
                  fetched_at=T, agency="NIH", award_number="R03SYN000001",
                  title="SYNTHETIC pilot award on insole sensors", activity_code="R03",
                  start_date=date(2022, 1, 1), end_date=date(2023, 12, 31), amount=50000.0)
    return opp, cv, [proposal], list(WORKS.values()), [award]


def cover_reply(points=None, missing=None, cited=None):
    points = points if points is not None else [
        {"asks": "The announcement supports wearable sensing for movement disorders.",
         "asks_ids": ["PAR-1"], "you": "You proposed a shoe-worn sensor that records ground "
         "reaction force at home.", "you_ids": ["proposal"]},
        {"asks": "It asks applicants to describe prior sensor work.", "asks_ids": ["PAR-1"],
         "you": "You hold a SYNTHETIC seed grant on insole force sensing.",
         "you_ids": ["private:cv"]},
        {"asks": "It supports early-career investigators.", "asks_ids": ["PAR-1"],
         "you": "You are an Assistant Professor since 2023 [private:cv].",
         "you_ids": ["private:cv", "nih:1"]}]
    return json.dumps({"reasoning": "r", "points": points,
                       "missing": missing if missing is not None else
                       ["The announcement asks for a mentoring plan."],
                       "cited_ids": cited or ["PAR-1", "private:cv", "proposal", "nih:1"]})


def test_cover_points_pass_cite_the_target_and_applicant_records_and_show_no_contacts():
    from perch.skills.cover import cover_points

    opp, cv, docs, papers, awards = _cover_inputs()
    p, log = audited([cover_reply()])
    v, records = cover_points(opp, cv, docs, papers, awards, p)
    assert not v.flagged and v.attempts == 1, v.errors
    pts = v.value.points
    assert [x.asks_ids for x in pts] == [["PAR-1"]] * 3
    assert pts[0].you_ids == ["private:proposal"]  # the dropped prefix is put back
    assert pts[2].you == "You are an Assistant Professor since 2023."  # inline ids go
    assert v.value.missing == ["The announcement asks for a mentoring plan."]
    assert set(records) == {"PAR-1", "private:cv", "private:proposal", "W1", "W2", "W3",
                            "nih:1"}
    sent = p.inner.calls[0]
    text = sent["system"] + sent["messages"][0].content
    assert "lab.vale" not in text and "215-555-0100" not in text and "https://" not in text
    assert "[contact removed]" in text and "Education:" in text and "SEED-0000-01" in text
    assert "[nih:1] NIH award R03SYN000001" in text and "[W1]" in text
    assert log.rejection_rate("cover_points") == (0, 1)


def test_cover_points_regenerate_on_a_bad_id_or_an_invented_number_then_withhold():
    from perch.skills.cover import cover_points

    opp, cv, docs, papers, awards = _cover_inputs()
    bad = cover_reply(points=[{"asks": "It supports wearable sensing.", "asks_ids": ["PAR-1"],
                               "you": "You built sensors.", "you_ids": ["W9"]}] * 3)
    p, log = audited([bad, cover_reply()])
    v, _ = cover_points(opp, cv, docs, papers, awards, p)
    assert v.attempts == 2 and not v.flagged
    fed = p.inner.calls[1]["messages"][0].content
    assert "rejected" in fed and "W9" in fed
    # a point whose asks cites a paper, a you that judges odds, an invented amount: twice
    odds = cover_reply(points=[
        {"asks": "It supports wearable sensing.", "asks_ids": ["W1"],
         "you": "You are a strong candidate with good odds.", "you_ids": ["private:cv"]},
        {"asks": "It pays $900,000.", "asks_ids": ["PAR-1"], "you": "You built sensors.",
         "you_ids": ["private:cv"]},
        {"asks": "It asks for prior sensor work.", "asks_ids": ["PAR-1"],
         "you": "You should apply.", "you_ids": []}])
    p, log = audited([odds, odds])
    v, _ = cover_points(opp, cv, docs, papers, awards, p)
    assert v.flagged and v.value is None
    joined = " ".join(v.errors)
    for word in ("asks_ids must be exactly [PAR-1]", "'strong candidate'", "900000", "at least one",
                 "'should apply'"):
        assert word in joined, word
    assert log.rejection_rate("cover_points") == (2, 2)


def test_cover_points_grounder_flags_without_withholding_and_the_prompt_fits_the_model():
    from perch.grounding import FakeGrounder
    from perch.private.inputs import make_doc
    from perch.skills.cover import PROMPT_CHARS, cover_points

    opp, cv, docs, papers, awards = _cover_inputs()
    pts = json.loads(cover_reply())["points"]
    pts[1]["you"] = "You trained dolphins underwater."  # nothing in the CV says so
    p, log = audited([cover_reply(points=pts)])
    v, _ = cover_points(opp, cv, docs, papers, awards, p, grounder=FakeGrounder())
    assert not v.flagged and v.value.unsupported == ["You trained dolphins underwater."]
    assert set(v.value.support) >= {"point 1 asks", "point 1 you", "missing 1"}
    assert log.rejection_rate("cover_points", layer=2) == (1, 1)
    # the worst case: a long CV, every document kind, six long papers and awards
    big_cv = make_doc("cv", CV_TEXT + "\n## Publications\n" + "- SYNTHETIC paper line\n" * 400)
    big_docs = [make_doc(k, f"SYNTHETIC {k} text. " * 400)
                for k in ("proposal", "direction", "manuscript", "interests")]
    from perch.private.student import achievement_docs
    big_docs += achievement_docs("\n".join(f"{i}. SYNTHETIC achievement {i} " + "words " * 200
                                           for i in range(1, 6)))
    long_papers = [w.model_copy(update={"abstract": "SYNTHETIC abstract words. " * 200})
                   for w in papers] * 3
    p, _ = audited([cover_reply(), cover_reply()])
    v, records = cover_points(opp, big_cv, big_docs, long_papers, awards * 4, p,
                              context=["Open to year 4; your CV says 3."])
    sent = p.inner.calls[0]
    assert len(sent["system"]) + len(sent["messages"][0].content) < PROMPT_CHARS
    assert "Rule check, written by code:\n- Open to year 4" in sent["messages"][0].content
    assert "private:cv" in records and len([k for k in records if k.startswith("W")]) <= 6

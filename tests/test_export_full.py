"""Full exports (S42, ported from the private-mode tests): the brief is the user's own, so an
export prints everything it holds: summary, topics, explanations and the CV values in rule
lines. SYNTHETIC records only."""

from datetime import date

from perch import export as ex
from perch.schemas import Lead

from .test_export import KW, _inputs, _student_inputs


def test_the_documents_note_appears_only_when_the_brief_read_documents():
    brief, leads, opps, works = _inputs()
    plain = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, []))
    assert ex.DOCUMENTS_NOTE not in plain
    held = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, [], documents=True))
    assert f"> {ex.DOCUMENTS_NOTE}" in held
    assert held.index(ex.DOCUMENTS_NOTE) < held.index("## Research profile")
    s_brief, s_leads, recs = _student_inputs()
    md = ex.to_markdown(ex.student_blocks(s_brief, s_leads, recs))
    assert f"> {ex.DOCUMENTS_NOTE}" in md  # a student brief always reads the CV
    s_brief.options["sample"] = "SYNTHETIC persona-ug"  # a guest's sample persona is not theirs
    assert ex.DOCUMENTS_NOTE not in ex.to_markdown(ex.student_blocks(s_brief, s_leads, recs))


def test_a_student_export_prints_cv_values_in_rule_lines_plainly():
    brief, leads, recs = _student_inputs()
    md = ex.to_markdown(ex.student_blocks(brief, leads, recs))
    assert "Asks for a GPA of at least 3.50; your CV says 3.40." in md
    assert "2 letters of recommendation; your CV lists 1 referee" in md.replace("Still needed: ",
                                                                                  "")
    assert "withheld" not in md.replace("The explanation was withheld", "")


def test_the_higher_education_rule_is_the_screens():
    rows = ["State governments", "Private institutions of higher education",
            "Nonprofits having a 501(c)(3) status with the IRS, other than institutions of "
            "higher education", "Public and State controlled Institutions of Higher Education"]
    assert ex.higher_ed_rows(rows) == [rows[1], rows[3]]
    assert ex.higher_ed_rows(None) == [] and ex.higher_ed_rows(["Small businesses"]) == []


def test_the_excerpt_cuts_at_a_sentence_end_or_a_word():
    assert ex.excerpt(None) is None and ex.excerpt("  \n ") is None
    assert ex.excerpt("Short  text\nhere.") == "Short text here."
    sentence = "This program funds SYNTHETIC work in a lab. "
    cut = ex.excerpt(sentence * 30)  # 1,290 characters, sentences end every 43
    assert cut.endswith("lab.") and len(cut) <= 600 and not cut.endswith("…")
    assert cut == (sentence * 30)[:cut.rfind(".") + 1]
    nostop = ex.excerpt("word " * 200)  # no sentence end
    assert nostop.endswith("word…") and len(nostop) <= 601
    assert ex.excerpt("<p>A &amp; B</p> <b>done</b>.") == "A & B done ."


def test_a_researcher_export_carries_the_record_facts():
    from perch.export import Block  # noqa: F401 - the blocks module under test

    brief, leads, opps, works = _inputs()
    o = opps["grants_gov:SYN-1"]
    o.status = "forecasted"
    o.eligible_applicants = ["State governments", "Private institutions of higher education",
                             "Nonprofits having a 501(c)(3) status with the IRS, other than "
                             "institutions of higher education"]
    o.description = ("This SYNTHETIC program funds new work.  It also funds " + "x " * 400)
    leads[0].match_score = 67
    leads[0].notes = ["The announcement asks for a PhD.", "Your CV lists a PhD."]
    leads[0].explanation = leads[0].inference = None
    md = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, [], documents=True))
    sec = md[md.index("### 1. SYN-1"):md.index("### 2. SYN-3")]
    facts = sec.splitlines()
    assert facts[2] == "- Match 67 (good)" and facts[3] == "- Status: Forecast"
    assert "- Rule: The announcement asks for a PhD." in sec
    assert "- From your CV: Your CV lists a PhD." in sec
    assert "Eligible applicants include:" in sec
    assert "- Private institutions of higher education" in sec
    assert "- State governments" not in sec and "other than institutions" not in sec
    assert "From the record: This SYNTHETIC program funds new work.\n" in sec
    assert sec.index("From the record:") < sec.index("[Record: Grants.gov SYN-1]")
    # no description, no match, a posted status, no higher-education row: none of the lines
    plain = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, []))
    other = plain[plain.index("### 2. SYN-3"):]
    assert "Match" not in other and "Status:" not in other and "From the record" not in other
    assert "Eligible applicants" not in other
    o.status = "archived"
    assert ex._status_line(o) == "Status: archived"
    o.status = "posted"
    assert ex._status_line(o) is None


def test_a_student_export_names_the_agency_and_excerpts_the_record():
    from perch.schemas import Opportunity, Scholarship

    brief, leads, recs = _student_inputs()
    recs["sample:sch-0001"] = recs["sample:sch-0001"].model_copy(update={
        "purpose": "This SYNTHETIC award supports invented study. It is not real."})
    leads[0].match_score = 40
    opp = Opportunity(id="grants_gov:SYN-9", opportunity_number="SYN-9", title="SYNTHETIC call",
                      agency="NSF", parent_agency="SYNTHETIC Department",
                      close_date=date(2027, 1, 5),
                      description="A SYNTHETIC call for students. More text follows.", **KW)
    recs["temple_sdfa:f1"] = opp
    md = ex.to_markdown(ex.student_blocks(brief, leads, recs))
    assert "- Match 40 (partial)" in md and "- Agency: NSF (SYNTHETIC Department)" in md
    assert "From the record: A SYNTHETIC call for students. More text follows." in md
    assert "From the record: This SYNTHETIC award supports invented study. It is not real." in md
    assert "SAMPLE DATA" in md and "\\[SAMPLE\\]" in md  # the sample keeps its badge and banner
    assert isinstance(recs["sample:sch-0001"], Scholarship) and isinstance(leads[0], Lead)

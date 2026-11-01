"""Exports say what the screen says (QA cycle 1: Q10, Q11, Q21, Q24). SYNTHETIC records."""

from datetime import UTC, date, datetime

from perch import egress
from perch import export as ex
from perch.schemas import Brief, Lead, Opportunity, Work

T = datetime(2026, 10, 29, tzinfo=UTC)
KW = {"source": "grants_gov", "source_url": "https://www.grants.gov/x", "fetched_at": T}


def _inputs():
    brief = Brief(id="b", researcher_id="https://openalex.org/A1",
                  options={"as_of": "2026-10-31"}, award_horizon=date(2016, 6, 30),
                  topics=["SYNTHETIC topic"], **KW)
    opps = {f"grants_gov:SYN-{i}": Opportunity(
        id=f"grants_gov:SYN-{i}", opportunity_number=f"SYN-{i}", title=f"SYNTHETIC grant {i}",
        agency="NSF", close_date=date(2027, 9, 30), **KW) for i in (1, 2, 3)}
    work = Work(id="https://openalex.org/W1234567", title="A SYNTHETIC paper",
                publication_year=2024, **{**KW, "source": "openalex"})
    leads = [Lead(id=f"b:{i}", brief_id="b", route="A", record_id=f"grants_gov:SYN-{i}",
                  rank=i, status="dismissed" if i == 2 else "new",
                  explanation=("The program funds SYNTHETIC work [SYN-1]. Cited work: W1234567 "
                               "developed a SYNTHETIC tool.") if i == 1 else None,
                  inference="The tool fits [W1234567]." if i == 1 else None,
                  cited_ids=["SYN-1", "W1234567"] if i == 1 else [], **KW)
             for i in (1, 2, 3)]
    return brief, leads, opps, {work.id: work}


def test_export_names_papers_numbers_without_gaps_and_writes_dates_as_the_screen():
    brief, leads, opps, works = _inputs()
    md = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, []))
    # Q10: the paper by its title and year, never by its OpenAlex id in the sentence
    assert "Cited work: “A SYNTHETIC paper” (2024) developed" in md
    assert "Cited work: W1234567" not in md and "Inference: The tool fits" in md
    # Q11: shown leads numbered 1 to n; the dismissed one is counted, not skipped silently
    assert "### 1. SYN-1" in md and "### 2. SYN-3" in md and "SYN-2" not in md
    assert "1 dismissed lead is left out." in md and "0 kept, 2 shown, 1 dismissed." in md
    # Q21: dates as the screen writes them
    assert "Brief as of 31 Oct 2026." in md and "Closes: 30 Sep 2027" in md
    assert "last public award): 30 Jun 2016" in md and "2026-10-31" not in md


def test_a_documents_export_says_withheld_once_per_line_and_where_it_came_from():
    """Q24: "Topics withheld: Withheld: ..." and "Inference: Withheld: ..." said it
    twice, and the header said public records only."""
    brief, leads, opps, works = _inputs()
    md = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, [], documents=True))
    assert "Built by Perch from your documents and public records." in md
    assert "Built from public records" not in md
    for line in md.splitlines():
        assert line.count("ithheld") <= 1, line
    assert "Topics withheld: this text draws on private documents" in md
    assert "Inference withheld: this text draws on private documents" in md
    masked = egress.Masker()
    md = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, [], masker=masked,
                                  documents=True))
    assert "Inference: The tool fits" in md and "(2024)" in md


def test_the_kept_leads_table_writes_closes_as_the_screen():
    """R1 (regression of Q21): /compare gives the close date as ISO text; the export's
    Kept leads compared table wrote it as it came, beside "Closes: 30 Sep 2027" below."""
    from perch.compare import route_a_row

    brief, leads, opps, works = _inputs()
    leads[0].status = "kept"
    rows = [route_a_row(leads[0], opps[leads[0].record_id], date(2026, 10, 31))]
    md = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, rows))
    table = [x for x in md.splitlines() if x.startswith("| Grant: SYN-1")]
    assert table and "| 30 Sep 2027 (" not in table[0] and "30 Sep 2027" in table[0]
    assert "2027-09-30" not in md
    page = ex.to_html(ex.blocks(brief, None, leads, opps, {}, works, rows), "t")
    assert "2027-09-30" not in page and "<td>30 Sep 2027</td>" in page


def _student_inputs():
    """A SYNTHETIC student brief: three fellowships (the second dismissed) and one sample."""
    from perch.schemas import Scholarship, ScholarshipEligibility

    brief = Brief(id="s", researcher_id="private:student", options={"as_of": "2026-10-31",
                                                                     "student": True}, **KW)
    pub = {"source": "temple_sdfa", "source_url": "https://undergraduate.temple.edu/x",
           "fetched_at": T}
    recs = {f"temple_sdfa:f{i}": Scholarship(id=f"temple_sdfa:f{i}", name=f"SYNTHETIC "
                                             f"fellowship {i}", **pub) for i in (1, 2, 3)}
    recs["sample:sch-0001"] = Scholarship(
        id="sample:sch-0001", name="Quillfen SYNTHETIC Award", source="synthetic",
        source_url="synthetic://sample/sch-0001", fetched_at=T, canary="PERCH-SAMPLE-TEST",
        eligibility=ScholarshipEligibility(gpa_min=3.5))
    leads = [Lead(id=f"s:F{i}", brief_id="s", route="F", record_id=f"temple_sdfa:f{i}",
                  rank=i, status="dismissed" if i == 2 else "kept" if i == 3 else "new",
                  verdict="may be eligible", verdict_lines=["The listing says who may apply."],
                  **pub) for i in (1, 2, 3)]
    leads.append(Lead(id="s:S1", brief_id="s", route="S", record_id="sample:sch-0001", rank=1,
                      sample=True, verdict="not eligible",
                      verdict_lines=["Asks for a GPA of at least 3.50; your CV says 3.40."],
                      gaps=["2 letters of recommendation; your CV lists 1 referee", "An essay"],
                      explanation="[sch-0001] supports undergraduates. Cited work: "
                      "private:achievement-a led a SYNTHETIC survey [achievement-a].",
                      cited_ids=["sample:sch-0001", "private:achievement-a"],
                      source="synthetic", source_url="synthetic://sample/sch-0001",
                      fetched_at=T))
    return brief, leads, recs


def test_the_student_export_numbers_without_gaps_and_counts_dismissed():
    """R8: the student export ran 1, 2, 4, 5 with no line about the dismissed option, and
    its footer said only how many were shown (Q11's fix covered researchers only)."""
    brief, leads, recs = _student_inputs()
    md = ex.to_markdown(ex.student_blocks(brief, leads, recs))
    assert "### 1. SYNTHETIC fellowship 1" in md and "### 2. SYNTHETIC fellowship 3 (kept)" in md
    assert "fellowship 2" not in md and "1 dismissed option is left out." in md
    assert "1 kept, 3 shown, 1 dismissed." in md


def test_student_exports_keep_the_rule_and_drop_the_cv_value():
    """Q42: a rule line in a student export keeps the rule and drops the value the rule
    read from the CV; with masking chosen the value is masked, with its key in memory."""
    brief, leads, recs = _student_inputs()
    md = ex.to_markdown(ex.student_blocks(brief, leads, recs))
    assert "Asks for a GPA of at least 3.50; your CV value is withheld." in md
    assert "2 letters of recommendation; your CV value is withheld" in md
    assert "3.40" not in md and "1 referee" not in md and "Still needed: An essay" in md
    m = egress.Masker()
    md = ex.to_markdown(ex.student_blocks(brief, leads, recs, masker=m))
    assert "your CV says \\[CV-VALUE-1\\]." in md and "3.40" not in md
    assert m.unmask("[CV-VALUE-1]") == "3.40"
    assert egress.release_cv_line("Your CV does not say your level of study.") == \
        "Your CV does not say your level of study."


def test_student_record_links_name_their_source_not_the_url():
    """R19: student record links read "[Record: https://...](https://...)"."""
    brief, leads, recs = _student_inputs()
    for r in list(recs.values())[:3]:
        r.source = "temple_sdfa"
    md = ex.to_markdown(ex.student_blocks(brief, leads, recs))
    assert "[Record: Temple Scholar Development and Fellowships Advising list](https://" in md
    assert "[Record: https://" not in md


def test_exports_render_citations_as_the_screen_with_no_raw_ids():
    """R9: the profile summary kept "[W7166556526, ...]", a documents export kept
    "[private:manuscript]" and "[HT942526PRPIIRA, proposal, manuscript]", and a masked
    student export kept "[sch-0001] supports ..." and "private:achievement-a [...]"."""
    import re

    brief, leads, opps, works = _inputs()
    brief.summary = "The researcher builds SYNTHETIC tools [W1234567, W7654321]."
    leads[0].explanation = ("The program funds SYNTHETIC work [SYN-1]. Cited work: W1234567 "
                            "developed a SYNTHETIC tool [W1234567].")
    md = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, []))
    assert "SYNTHETIC tools (“A SYNTHETIC paper”, 2024; a paper on file)." in md
    assert "The program funds SYNTHETIC work. Cited work: “A SYNTHETIC paper” (2024) " \
        "developed a SYNTHETIC tool." in md  # its own number and the repeat go, as on the card
    assert not re.search(r"\bW\d{5,}|private:", md)
    text = ex.name_papers("Fits [HT942526PRPIIRA, proposal, manuscript] and "
                          "[private:manuscript].", works)
    assert text == "Fits (HT942526PRPIIRA; your draft proposal; your unpublished work) and " \
        "(your unpublished work)."
    m = egress.Masker()
    md = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, [], masker=m,
                                  documents=True))
    assert not re.search(r"\bW\d{5,}|private:", md)
    s_brief, s_leads, recs = _student_inputs()
    m = egress.Masker()
    md = ex.to_markdown(ex.student_blocks(s_brief, s_leads, recs, masker=m))
    assert "Quillfen SYNTHETIC Award (sample) supports undergraduates." in md
    assert "Cited work: one of your achievements led a SYNTHETIC survey." in md
    model = "\n".join(x for x in md.splitlines() if x.startswith("> **Model:**"))
    assert not re.search(r"\bsch-\d|private:|\[achievement", model)
    assert ex.name_papers("A [PRIVATE-PHRASE-1] phrase.", {}) == "A [PRIVATE-PHRASE-1] phrase."

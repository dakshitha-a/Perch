"""Exports are the full brief; "Mask my ongoing research" masks only research phrases
(2026-11-02). Hand-off drafts keep their own withholding and masking. SYNTHETIC text only."""

import json
from datetime import date

from perch import egress
from perch import export as ex
from perch.schemas import Lead

from .test_export import KW, _inputs, _student_inputs
from .test_private import FILES, PARAPHRASE, PERSONA, private_app, public_paraphrase_reply

# SYNTHETIC research direction: a phrase found in no public record and in no other document.
DIRECTION = ("SYNTHETIC research direction. We study zebrafish lantern oscillation under "
             "tidal stress in coastal tanks.")
RESEARCH_PHRASE = "zebrafish lantern oscillation under tidal stress"
CV_ONLY_PHRASE = "Shoe-worn force sensing for early gait change"  # persona-1's CV only
CV_NAME = "Rowan Vale"  # persona-1's SYNTHETIC fictional CV name


def direction_reply(messages, system, schema):
    """A valid fit explanation whose finding retells the direction and the CV."""
    if schema and "fit" in schema.get("properties", {}):
        return json.dumps({
            "reasoning": "r", "fit": 70,
            "opportunity_sentence": "The announcement funds research projects [PAR-25-268].",
            "research_findings": [{"paper_id": "private:proposal",
                                   "finding": f"studied {RESEARCH_PHRASE}, as {CV_NAME} lists "
                                              f"under {CV_ONLY_PHRASE}"}],
            "link_sentence": "The proposal fits the announcement.",
            "cited_ids": ["PAR-25-268", "private:proposal"]})
    return ""


def session_with_direction(tmp_path, monkeypatch, responder=direction_reply, author=None):
    """The persona's CV and proposal, plus a SYNTHETIC direction document."""
    c, _ = private_app(tmp_path, monkeypatch, responder=responder)
    tok = c.post("/private/session").json()["token"]
    h = {"X-Perch-Private": tok}
    for kind, text in (("cv", (PERSONA / FILES["cv"]).read_text()),
                       ("proposal", (PERSONA / FILES["proposal"]).read_text()),
                       ("direction", DIRECTION)):
        assert c.post("/private/documents", headers=h,
                      json={"kind": kind, "text": text}).status_code == 201
    c.post("/private/brief", headers=h, json={"as_of": "2026-10-28", "author_id": author})
    lead = next(x for x in c.get("/private/brief", headers=h).json()["leads"]
                if x["route"] == "A")
    c.post(f"/private/leads/{lead['id']}/keep", headers=h)
    return c, h, lead


def test_a_default_export_gives_summary_topics_and_explanations_in_full(tmp_path, monkeypatch):
    """SYNTHETIC session: nothing is withheld in md, html or json."""
    c, h, lead = session_with_direction(tmp_path, monkeypatch)
    on_screen = lead["explanation"]
    assert RESEARCH_PHRASE in on_screen
    got = c.get("/private/brief", headers=h).json()["brief"]
    for ext in ("md", "html", "json"):
        text = c.get(f"/private/export.{ext}", headers=h).text
        assert RESEARCH_PHRASE in text and CV_ONLY_PHRASE in text, ext
        assert egress.WITHHELD not in text, ext
    exp = c.get("/private/export.json", headers=h).json()
    assert exp["brief"]["summary"] == got["summary"] and exp["brief"]["topics"] == got["topics"]
    assert exp["leads"][0]["explanation"] == on_screen
    assert "withheld" not in exp and exp["masked"] is False
    assert "masked_note" not in exp


def test_mask_masks_research_phrases_only_and_unmask_restores_them(tmp_path, monkeypatch):
    c, h, lead = session_with_direction(tmp_path, monkeypatch)
    for ext in ("md", "html", "json"):
        text = c.get(f"/private/export.{ext}", headers=h, params={"mask": True}).text
        assert RESEARCH_PHRASE not in text and "[PRIVATE-PHRASE-" in text, ext
        assert CV_NAME in text and CV_ONLY_PHRASE in text, ext  # the CV is not masked
        assert "[PERSON-" not in text and "[INSTITUTION-" not in text, ext
        assert ex.MASKED_NOTE in text or ext == "json", ext
    masked = c.get("/private/export.json", headers=h, params={"mask": True}).json()
    assert masked["masked"] is True and masked["masked_note"] == ex.MASKED_NOTE
    text = masked["leads"][0]["explanation"]
    back = c.post("/private/unmask", headers=h, json={"text": text}).json()["text"]
    assert back == lead["explanation"]  # the unmask key covers the export's placeholders
    # A hand-off masked afterwards numbers its placeholders on the same key.
    d = c.post("/private/handoff", headers=h, json={"office": "research_development",
                                                    "mask": True}).json()
    assert c.post("/private/unmask", headers=h, json={"text": d["body"]}).status_code == 200
    again = c.post("/private/unmask", headers=h, json={"text": text}).json()["text"]
    assert again == lead["explanation"]


def test_mask_without_a_research_document_changes_nothing(tmp_path, monkeypatch):
    """A CV alone: "mask my ongoing research" has nothing to mask and says nothing masked."""
    c, _ = private_app(tmp_path, monkeypatch)
    tok = c.post("/private/session").json()["token"]
    h = {"X-Perch-Private": tok}
    c.post("/private/documents", headers=h, json={"kind": "cv",
                                                  "text": (PERSONA / FILES["cv"]).read_text()})
    c.post("/private/brief", headers=h, json={"author_id": "A5026494099",
                                              "as_of": "2026-10-28"})
    plain = c.get("/private/export.md", headers=h).text
    assert c.get("/private/export.md", headers=h, params={"mask": True}).text == plain
    assert ex.DOCUMENTS_NOTE in plain and ex.MASKED_NOTE not in plain
    assert c.get("/private/export.json", headers=h, params={"mask": True}).json()["masked"] is False
    assert c.post("/private/unmask", headers=h, json={"text": "x"}).status_code == 409


def test_handoff_drafts_keep_default_withholding_and_their_own_mask(tmp_path, monkeypatch):
    """The hand-off is unchanged: withheld by default, masked on its own option (all
    documents), whatever the export does."""
    c, h, _ = session_with_direction(tmp_path, monkeypatch,
                                     responder=public_paraphrase_reply,
                                     author="A5026494099")
    office = {"office": "research_development"}
    d = c.post("/private/handoff", headers=h, json=office).json()
    assert PARAPHRASE not in d["body"] and "this session holds documents" in d["withheld"]
    dm = c.post("/private/handoff", headers=h, json={**office, "mask": True}).json()
    assert PARAPHRASE not in dm["body"] and "[PRIVATE-PHRASE-" in dm["body"]
    # an export, full or masked, leaves the hand-off as it was
    c.get("/private/export.md", headers=h, params={"mask": True})
    d2 = c.post("/private/handoff", headers=h, json=office).json()
    assert d2["body"] == d["body"] and d2["withheld"] == d["withheld"]
    # the hand-off's mask still masks the CV's names and terms, which the export's does not
    masker = egress.Masker([DIRECTION], [], {"PERSON": [CV_NAME]})
    assert "[PERSON-1]" in masker.mask(f"{CV_NAME} wrote this")


def test_the_documents_note_appears_only_when_documents_are_held(tmp_path, monkeypatch):
    brief, leads, opps, works = _inputs()
    plain = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, []))
    assert ex.DOCUMENTS_NOTE not in plain
    full = egress.ResearchMasker([])
    held = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, [], masker=full,
                                    documents=True))
    assert f"> {ex.DOCUMENTS_NOTE}" in held and ex.MASKED_NOTE not in held
    assert held.index(ex.DOCUMENTS_NOTE) < held.index("## Research profile")
    masked = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, [],
                                      masker=egress.ResearchMasker([DIRECTION]),
                                      documents=True))
    assert f"> {ex.MASKED_NOTE}" in masked
    assert ex.DOCUMENTS_NOTE == ("This brief includes text drawn from your documents. The file "
                                 "stays on your computer after the session ends.")
    assert ex.MASKED_NOTE == ("Phrases from your ongoing research are masked. Masking cannot "
                              "hide what the work is about.")
    s_brief, s_leads, recs = _student_inputs()
    md = ex.to_markdown(ex.student_blocks(s_brief, s_leads, recs, masker=full))
    assert f"> {ex.DOCUMENTS_NOTE}" in md


def test_a_student_export_prints_cv_values_in_rule_lines_plainly():
    brief, leads, recs = _student_inputs()
    md = ex.to_markdown(ex.student_blocks(brief, leads, recs, masker=egress.ResearchMasker([])))
    assert "Asks for a GPA of at least 3.50; your CV says 3.40." in md
    assert "2 letters of recommendation; your CV lists 1 referee" in md.replace("Still needed: ",
                                                                                  "")
    assert egress.CV_WITHHELD not in md and "[CV-VALUE" not in md
    # the hand-off style of release still withholds the value
    held = ex.to_markdown(ex.student_blocks(brief, leads, recs))
    assert egress.CV_WITHHELD in held


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
    leads[0].notes = ["The announcement asks for a PhD.", "Your CV lists a PhD (private)."]
    leads[0].explanation = leads[0].inference = None
    md = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, [],
                                  masker=egress.ResearchMasker([]), documents=True))
    sec = md[md.index("### 1. SYN-1"):md.index("### 2. SYN-3")]
    facts = sec.splitlines()
    assert facts[2] == "- Match 67 (good)" and facts[3] == "- Status: Forecast"
    assert "- Rule: The announcement asks for a PhD." in sec
    assert "- Private: Your CV lists a PhD (private)." in sec
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
    md = ex.to_markdown(ex.student_blocks(brief, leads, recs, masker=egress.ResearchMasker([])))
    assert "- Match 40 (partial)" in md and "- Agency: NSF (SYNTHETIC Department)" in md
    assert "From the record: A SYNTHETIC call for students. More text follows." in md
    assert "From the record: This SYNTHETIC award supports invented study. It is not real." in md
    assert "SAMPLE DATA" in md and "\\[SAMPLE\\]" in md  # the sample keeps its badge and banner
    assert isinstance(recs["sample:sch-0001"], Scholarship) and isinstance(leads[0], Lead)

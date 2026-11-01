"""QA round 5 (docs/design/qa/CYCLE_5.md, G1 to G23): one test per finding that code can
check offline. SYNTHETIC records and fake models only."""

import json
import shutil
import subprocess
from datetime import date

import pytest

from perch.llm.fake import FakeProvider
from perch.schemas import Opportunity
from perch.scout.loop import Scout
from perch.scout.tools import TOOLS, ScoutContext

from .test_export import KW
from .test_scout import AS_OF, AUTHOR, _ranked_brief, call, service  # noqa: F401

WEB = __import__("pathlib").Path(__file__).resolve().parents[1] / "web"


def _node(script: str) -> object:
    r = subprocess.run(["node", "--input-type=module", "-e",
                        script.replace("MODULE", (WEB / "format.js").as_uri())],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# --- G1: a documents brief's cards show no raw citation keys ---

@pytest.mark.skipif(not shutil.which("node"), reason="Node not installed")
def test_document_keys_render_as_document_citations():
    """G1: the fit model cites a document as [proposal]; the brief's cited_ids hold
    private:proposal. The bracket group stayed as text, and each finding kept its own
    trailing key, so a card read "...gait change [proposal]."."""
    segs, parsed = _node("""
import * as f from "MODULE";
const k = new Set(["HT1", "private:proposal", "private:manuscript"]);
console.log(JSON.stringify([
  f.segments("aligns with research [HT1, proposal, manuscript].", k, new Set(["HT1"])),
  f.parseExplanation("The award supports work [HT1]. Cited work: private:proposal proposed "
    + "insole sensing [proposal]; private:manuscript recorded plantar force [manuscript].",
    [...k], new Set(["HT1"]))]));
""")
    assert segs == ["aligns with research ", {"cite": "HT1"}, {"cite": "private:proposal"},
                    {"cite": "private:manuscript"}, "."]
    assert parsed["findings"] == [
        {"paper": "private:proposal", "text": "proposed insole sensing"},
        {"paper": "private:manuscript", "text": "recorded plantar force"}]
    app = (WEB / "app.js").read_text()
    assert "From your documents" in app and '"your documents"' in app


# --- G2, G12, G19: the largest award, what pays most, the top three ---

def _amounts(svc, leads, amounts):
    """Give the ranked brief's grants (floor, ceiling) pairs."""
    with svc.repo() as r:
        r.upsert([r.get(Opportunity, x.record_id).model_copy(update={
            "award_floor": lo, "award_ceiling": hi})
            for x, (lo, hi) in zip(leads, amounts, strict=True)])


def test_a_ceiling_sort_ranks_only_stated_ceilings_and_cuts_to_top(service):  # noqa: F811
    """G2: sorted by ceiling, the brief's search listed a floor-only record last, the model
    named it as the largest ("from $15,000,000"), and top 1 was ignored."""
    b, leads = _ranked_brief(service, 3)
    _amounts(service, leads, [(15_000_000, None), (600_000, 12_000_000), (None, 10_000_000)])
    c = ScoutContext(service, AS_OF, researcher_id=AUTHOR, brief_id=b.id)
    out = TOOLS["search_opportunities"][1](c, route="A", scope="brief", sort="award_ceiling",
                                           top=1)
    assert [x["id"] for x in out["leads"]] == [leads[1].record_id]
    assert out["leads"][0]["award_ceiling"] == "$12,000,000"
    assert out["leads"][0]["award_floor"] == "$600,000"
    assert out["no_ceiling_stated"] == [{"id": leads[0].record_id,
                                         "title": "SYNTHETIC grant 1", "brief_rank": 1}]
    assert "never call one of them the largest" in out["note"]


def test_largest_and_pays_most_are_sorted_searches_on_the_brief(service):  # noqa: F811
    """G2, G12: "which one pays most" compared the kept two; "largest award ceiling" named
    a floor-only record. Code sets the sort and scope, refuses compare, and the validator
    rejects a floor-only record called the largest."""
    b, leads = _ranked_brief(service, 3)
    _amounts(service, leads, [(15_000_000, None), (600_000, 12_000_000), (None, 10_000_000)])
    c = ScoutContext(service, AS_OF, researcher_id=AUTHOR, brief_id=b.id)
    bad = (f"The lead with the largest award ceiling is SYNTHETIC grant 1 "
           f"[{leads[0].record_id}], from $15,000,000.")
    good = f"SYNTHETIC grant 2 has the largest ceiling, up to $12,000,000 [{leads[1].record_id}]."
    fake = FakeProvider([call("compare"), call("search_opportunities", route="A"), bad, good])
    s = Scout(fake, c).start("which one pays most")
    assert [x.status for x in s.cards] == ["refused", "done"]
    assert s.cards[1].arguments["sort"] == "award_ceiling"
    assert s.cards[1].arguments["scope"] == "brief"
    assert s.answer == good and not s.flagged
    assert "states no award ceiling" in fake.calls[3]["messages"][-1].content


def test_top_three_compares_the_briefs_first_three(service):  # noqa: F811
    """G19: with two kept, "What are my top three leads and why?" compared the two kept, so
    the read-as block said 2 leads under a question about 3."""
    b, leads = _ranked_brief(service, 5)
    for x in leads[-2:]:
        service.set_lead_status(b.id, x.id, "kept")
    c = ScoutContext(service, AS_OF, researcher_id=AUTHOR, brief_id=b.id)
    fake = FakeProvider([call("compare"), "Done."])
    s = Scout(fake, c).start("What are my top three leads and why?")
    assert s.cards[0].arguments["ids"] == [x.record_id for x in leads[:3]]
    assert s.cards[0].detail == "3 leads side by side"
    assert s.cards[0].result["note"].startswith("These rows are the brief's top 3 leads")
    fake2 = FakeProvider([call("compare"), "Done."])
    s2 = Scout(fake2, c).start("Compare my kept leads")
    assert "ids" not in s2.cards[0].arguments  # the kept ones, as asked


# --- G3: an expiry is never a deadline, in the record view or the answer ---

def _parent(n="PA-SYN-31", short="Parent F31"):
    return Opportunity(id=f"grants_gov:{n}", opportunity_number=n,
                       title=f"SYNTHETIC Predoctoral Fellowship ({short})", agency="NIH",
                       close_date=date(2028, 5, 7), **KW)


def test_get_record_gives_an_expiry_as_no_deadline_and_the_check_rejects_one(service):  # noqa: F811
    from perch.scout.loop import expiry_as_deadline

    o = _parent()
    with service.repo() as r:
        r.upsert([o])
    got = TOOLS["get_record"][1](ScoutContext(service, AS_OF, researcher_id=AUTHOR), id=o.id)
    rec = got["record"]
    assert "close_date" not in rec
    assert rec["deadline"] == "no deadline in the record; the announcement expires 7 May 2028"
    seen = {o.id: o}
    assert expiry_as_deadline(f"The deadline for F31 is 7 May 2028 [{o.id}].", seen)
    assert expiry_as_deadline(f"The soonest deadline is 7 May 2028 for F31 [{o.id}].", seen)
    table = (f"| Feature | F31 [{o.id}] |\n| :--- | :--- |\n| **Deadline** | 7 May 2028 |")
    assert expiry_as_deadline(table, seen)
    assert not expiry_as_deadline(f"The record states no deadline; the announcement expires "
                                  f"7 May 2028 [{o.id}].", seen)
    assert not expiry_as_deadline(f"The announcement expires on 7 May 2028 [{o.id}].", seen)
    assert not expiry_as_deadline(table.replace("| 7 May", "| Expires 7 May"), seen)


# --- G4: a short student follow-up with a code is sent back with the exact call ---

def test_a_code_follow_up_is_sent_back_naming_the_call(service):  # noqa: F811
    from perch.scout.student_tools import STUDENT_RULES, STUDENT_TOOLS

    c = ScoutContext(service, AS_OF, researcher_id=AUTHOR)
    refusal = "I cannot fulfill this request."
    for q, want, args in (("f31?", 'words "F31"', {"words": "F31"}),
                          ("whats the deadline for the f31", 'words "F31"', {"words": "F31"}),
                          ("drop the samples", 'route "F"', {"route": "F"}),
                          ("how many of my options are samples", 'route "S"', {"route": "S"})):
        fake = FakeProvider([refusal, refusal, "No student brief here."])
        s = Scout(fake, c, table=STUDENT_TOOLS, rules=STUDENT_RULES, who="a student").start(q)
        assert s.exchanges[-1]["nudged"]
        assert want in fake.calls[1]["messages"][-1].content, q
        # refused twice in a long conversation (C12S turns 6 and 13): code makes the call
        assert [(x.tool, x.arguments) for x in s.cards] == [("search_options", args)], q


# --- G7: each line cites its own record ---

def test_a_line_naming_another_records_short_name_is_rejected():
    from perch.scout.loop import crossed_rows

    f31, f33 = _parent(), _parent("PA-SYN-33", "Parent F33")
    seen = {f31.id: f31, f33.id: f33}
    bad = f"* Senior Fellowship (Parent F33): F33 is a senior fellowship [{f31.id}]."
    errs = crossed_rows(bad, seen)
    assert errs and "PA-SYN-33" in errs[0]
    assert not crossed_rows(bad.replace(f31.id, f33.id), seen)


# --- G9: start over, said any short way, on the server too ---

def test_start_over_phrases_reset_the_conversation_by_code(service):  # noqa: F811
    from perch.scout.loop import START_OVER_ANSWER, START_OVER_RE

    for q in ("can we start over", "lets start over pls", "start over", "Please start again."):
        assert START_OVER_RE.match(q), q
    for q in ("Is there a grant to restart my lab?", "start over with NIH only"):
        assert not START_OVER_RE.match(q), q
    fake = FakeProvider(["One answer."])
    sc = Scout(fake, ScoutContext(service, AS_OF, researcher_id=AUTHOR))
    s = sc.start("Hello")
    n = len(fake.calls)
    sc.ask(s, "can we start over")
    assert s.answer == START_OVER_ANSWER and s.exchanges[-1]["answer_by"] == "code"
    assert s.messages == [] and len(fake.calls) == n  # no model call


# --- G10: "befor june" is the next June ---

def test_a_misspelt_month_and_a_past_date_mean_the_next_one(service):  # noqa: F811
    from perch.scout.loop import month_dates

    as_of = date(2026, 11, 1)
    for q in ("anythng from nsf closing befor june", "b4 june", "untill june"):
        assert [d.isoformat() for _, d, _ in month_dates(q, as_of)] == ["2027-06-01"], q
    b, _ = _ranked_brief(service, 2)
    c = ScoutContext(service, as_of, researcher_id=AUTHOR, brief_id=b.id)
    fake = FakeProvider([call("search_opportunities", route="A", closes_by="2026-06-01"),
                         "None of the brief's leads closes by then."])
    s = Scout(fake, c).start("anything from nsf closing before then")
    assert s.cards[0].arguments["closes_by"] == "2027-06-01"


# --- G11: the first grant named, if off the brief, is called a further lead ---

def test_an_answer_that_opens_with_a_store_lead_must_call_it_further(service):  # noqa: F811
    from perch.scout.loop import further_first

    b, leads = _ranked_brief(service, 2)
    c = ScoutContext(service, AS_OF, researcher_id=AUTHOR, brief_id=b.id)
    other = Opportunity(id="grants_gov:SYN-X", opportunity_number="SYN-X", title="Other",
                        agency="NSF", **KW)
    c.seen[other.id] = other
    assert further_first(f"The next NSF deadline is Other [{other.id}].", c)
    assert not further_first(f"A further lead, not on your brief: Other [{other.id}].", c)
    assert not further_first(f"None of these is on your brief. Other [{other.id}] is weak.", c)
    with service.repo() as r:
        c.seen[leads[0].record_id] = r.get(Opportunity, leads[0].record_id)
    assert not further_first(f"Grant 1 [{leads[0].record_id}] closes first.", c)


@pytest.mark.skipif(not shutil.which("node"), reason="Node not installed")
def test_the_page_reads_start_over_as_the_server_does():
    """G9: the page's pattern was anchored to the bare phrase, so "can we start over"
    reached the model, which refused."""
    import re

    from perch.scout.loop import START_OVER_RE

    src = re.search(r"const START_OVER = (/.+/i);", (WEB / "scout.js").read_text()).group(1)
    phrases = ["can we start over", "lets start over pls", "start over", "new chat please",
               "Is there a grant to restart my lab?", "start over with NIH only"]
    r = subprocess.run(["node", "-e", f"const R = {src}; console.log(JSON.stringify("
                        f"{json.dumps(phrases)}.map((q) => R.test(q))))"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [bool(START_OVER_RE.match(q)) for q in phrases]
    assert json.loads(r.stdout)[:4] == [True] * 4


# --- G13 to G17, G21, G22: exports and student options ---

def test_student_mode_leaves_out_forecasted_nih_fellowships():
    """G13: a forecast (FOR-NS-25-004) showed as "may be eligible"; Help says forecasts
    are not shown."""
    from perch.private.student import nih_records
    from perch.scholarships import nih_fellowships

    mk = lambda n, status: Opportunity(id=f"grants_gov:{n}", opportunity_number=n,  # noqa: E731
                                       title=f"SYNTHETIC {n}", agency="NIH", activity_code="F31",
                                       status=status, **KW)

    class Repo:
        def list(self, kind):
            return [mk("PA-SYN-1", "posted"), mk("FOR-SYN-2", "forecasted")]

    assert [o.opportunity_number for o in nih_fellowships(Repo())] == ["PA-SYN-1"]
    assert list(nih_records(Repo())) == ["grants_gov:PA-SYN-1"]  # the path a brief takes


def test_student_export_one_line_not_eligible_withheld_note_and_announcement_label():
    """G14: about 1,100 of 1,391 lines were the not-eligible lists. G15: a withheld
    explanation had no note. G17: an expiry read "Deadline: Expires 7 May 2028". G21: two
    capitalised "Still needed" bullets and "(Parent F31) (kept)"."""
    from perch import export as ex

    from .test_export import _student_inputs

    brief, leads, recs = _student_inputs()
    f31 = _parent()
    recs[f31.id] = f31
    leads.append(leads[0].model_copy(update={
        "id": "s:F31", "record_id": f31.id, "rank": 9, "status": "kept", "flagged": True,
        "verdict": "may be eligible", "explanation": None, "gaps": ["A transcript", "An essay"]}))
    leads.append(leads[0].model_copy(update={
        "id": "s:F9", "record_id": "temple_sdfa:f1", "rank": 10, "verdict": "not eligible",
        "verdict_lines": ["Open to undergraduate years 1 and 2; your CV says year 4."],
        "match_score": 35, "status": "kept"}))
    md = ex.to_markdown(ex.student_blocks(brief, leads, recs))
    part = md[md.index("### 3. SYNTHETIC Predoctoral"):]
    assert part.startswith("### 3. SYNTHETIC Predoctoral Fellowship (Parent F31), kept")
    assert "- Announcement: Expires 7 May 2028" in part and "Deadline: Expires" not in md
    assert "- Still needed: a transcript; an essay" in part
    assert "> The explanation was withheld: it failed the checks twice." in part
    assert "One line each: the option, the rule it does not meet, and its Match." in md
    assert ("- SYNTHETIC fellowship 1, kept: Open to undergraduate years 1 and 2; your CV "
            "value is withheld. Match 35 (weak).") in md


def test_rule_lines_join_years_and_levels_in_words():
    from perch.student import _levels, _years

    assert _years([1, 2]) == "years 1 and 2" and _years([4]) == "year 4"
    assert _levels(["associate"]) == "associate degree"
    assert _levels(["bachelor's", "graduate"]) == "bachelor's and graduate"


def test_a_documents_export_has_no_bare_record_line_or_award_horizon():
    """G16: persona-1's export held "Public award horizon: no public award found", from a
    search that never ran, and a bare "Researcher record (private)" line."""
    from perch import export as ex
    from perch.schemas import Researcher

    from .test_export import _inputs

    brief, leads, opps, works = _inputs()
    brief.researcher_id, brief.topics = "private:you", []
    you = Researcher(id="private:you", display_name="You (private)",
                     **{**KW, "source": "private", "source_url": "private://session"})
    md = ex.to_markdown(ex.blocks(brief, you, leads, opps, {}, works, [], documents=True))
    assert "award horizon" not in md and "Researcher record" not in md
    assert "## Research profile" not in md
    b2, l2, o2, w2 = _inputs()
    md = ex.to_markdown(ex.blocks(b2, None, l2, o2, {}, w2, []))
    assert "Public award horizon" in md and "## Research profile" in md


def test_a_paper_is_named_in_full_once_per_lead_and_bare_masked_findings_go():
    """G21: every PI-4 grant named the same two papers by full title in the Model text and
    the Inference; masked student descriptions all ended "Cited work: one of your
    achievements [PRIVATE-PHRASE-1]; ..."."""
    from perch import export as ex

    from .test_export import _inputs

    brief, leads, opps, works = _inputs()
    works["https://openalex.org/W1234567"].title = "A SYNTHETIC paper on six word titles"
    md = ex.to_markdown(ex.blocks(brief, None, leads, opps, {}, works, []))
    assert md.count("“A SYNTHETIC paper on six word titles”") == 1
    assert "Inference: The tool fits (“A SYNTHETIC paper on six…”)." in md
    assert ex.bare_findings_out("X funds work. Cited work: one of your achievements "
                                "[PRIVATE-PHRASE-1]; your CV [PRIVATE-PHRASE-2].") == \
        "X funds work."
    assert ex.bare_findings_out("X. Cited work: one of your achievements led a survey.") == \
        "X. Cited work: one of your achievements led a survey."


# --- G18: a follow-up's filters, by kind ---

def test_a_follow_up_replaces_a_filter_of_the_same_kind_and_keeps_the_rest():
    """G18: "Leave out Department of Defense grants" after an NSF question ran with NSF and
    "not DOD" together and found nothing."""
    from perch.scout.loop import carry_filters

    before = {"agencies": ["NSF"], "closes_by": "2027-03-01", "max_amount": 200000}
    got = carry_filters({"route": "A", "agencies": ["NSF"], "exclude_agencies": ["DOD"],
                         "closes_by": "2027-03-01", "max_amount": 200000}, before,
                        "Leave out Department of Defense grants")
    assert got == {"route": "A", "exclude_agencies": ["DOD"], "closes_by": "2027-03-01",
                   "max_amount": 200000}
    assert carry_filters({"route": "A", "agencies": ["NSF"], "closes_by": "2027-03-01"},
                         before, "any agency is fine") == {"route": "A",
                                                           "closes_by": "2027-03-01"}
    assert carry_filters({"route": "A", "agencies": ["NSF"]}, before, "show me everything") \
        == {"route": "A"}
    assert "money(v)" in (WEB / "scout.js").read_text()  # the chip reads $200,000


# --- G23: "what can i apply for" is the brief's order, not the kept options ---

def test_a_student_question_not_about_kept_options_does_not_compare_them(service):  # noqa: F811
    from perch.scout.student_tools import STUDENT_RULES, STUDENT_TOOLS

    c = ScoutContext(service, AS_OF, researcher_id=AUTHOR)
    fake = FakeProvider([call("compare_options"), "No options here."])
    s = Scout(fake, c, table=STUDENT_TOOLS, rules=STUDENT_RULES,
              who="a student").start("what can i apply for")
    assert s.cards[0].status == "refused" and "search_options" in s.cards[0].result["error"]
    fake = FakeProvider([call("compare_options"), "Done."])
    s = Scout(fake, c, table=STUDENT_TOOLS, rules=STUDENT_RULES,
              who="a student").start("Compare my kept options")
    assert s.cards[0].status != "refused"


def test_shared_suffixes_and_place_names_are_not_short_names():
    """The bench after G7: "(R01 Clinical Trial Required)" and a company's "(United
    Kingdom)" were read as one record's short name, and two good answers were withheld."""
    from perch.schemas import Organisation
    from perch.scout.loop import crossed_rows

    a = _parent("PAR-SYN-1", "R01 Clinical Trial Required")
    b = _parent("PAR-SYN-2", "R01 Clinical Trial Optional")
    org = Organisation(id="I1", name="SYNTHETIC Co (United Kingdom)", **KW)
    seen = {a.id: a, b.id: b, org.id: org}
    assert not crossed_rows(f"A grant (R01 Clinical Trial Required) [{b.id}].", seen)
    assert not crossed_rows("SYNTHETIC Co (United Kingdom) cites you [B1].", seen)

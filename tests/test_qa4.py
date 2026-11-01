"""QA round 4 (docs/design/qa/CYCLE_4.md, F1 to F27): one test per finding that code can
check offline. SYNTHETIC records and fake models only."""

import json
import shutil
import subprocess
import time
from datetime import date

import pytest

from perch import datefmt, egress
from perch import export as ex
from perch.llm import ToolCall
from perch.llm.fake import FakeProvider
from perch.schemas import Lead, Opportunity, Scholarship
from perch.scout.loop import Scout, floor_as_ceiling, question_scope
from perch.scout.tools import TOOLS, ScoutContext, fit_sentence, second_person

from .test_export import KW, T, _inputs, _student_inputs
from .test_scout import AS_OF, AUTHOR, _ranked_brief, call, service  # noqa: F401

WEB = __import__("pathlib").Path(__file__).resolve().parents[1] / "web"


# --- F2, F12: the fit sentence ends as a sentence and speaks to the researcher ---

def test_own_citation_as_a_noun_reads_this_opportunity_everywhere():
    """F2: "...the theoretical physics aims of [26-523]." lost its own citation and read
    "aims of." on the card, in the export and in Scout's demo question 1."""
    own = {"26-523", "grants_gov:26-523"}
    assert ex.own_in_place("aligns with the theoretical physics aims of [26-523].", own) == \
        "aligns with the theoretical physics aims of this opportunity."
    assert ex.own_in_place("the STEM focus of the [sch-0001].", {"sch-0001"}) == \
        "the STEM focus of this opportunity."
    assert ex.own_in_place("the agenda required by [26-525, W1].", {"26-525"}) == \
        "the agenda required by this opportunity [W1]."
    kept = "aligns with dynamics [26-519, W1]."  # not a noun's place: dropped as before
    assert ex.own_in_place(kept, {"26-519"}) == kept
    assert ex.name_papers("It fits the aims of [26-523].", {}, skip=own) == \
        "It fits the aims of this opportunity."
    lead = Lead(id="b:A3", brief_id="b", route="A", record_id="grants_gov:26-523", rank=3,
                inference="The researcher's development of methods aligns with the "
                "theoretical physics aims of [26-523].", **KW)
    assert fit_sentence(lead) == ("Your development of methods aligns with the theoretical "
                                  "physics aims of this opportunity.")


def test_fit_sentences_reach_scout_in_the_second_person():
    """F12: 15 of 16 answers to demo question 1 said "the researcher's development of..."
    to the researcher who asked."""
    assert second_person("The researcher's focus fits.") == "Your focus fits."
    assert second_person("It suits the researcher develops tools") == "It suits you develop tools"
    assert second_person("The researcher focuses on X and the researcher has Y.") == \
        "You focus on X and you have Y."


@pytest.mark.skipif(not shutil.which("node"), reason="Node not installed")
def test_cards_render_an_own_citation_as_a_noun_the_same_way():
    script = """
import * as f from "MODULE";
console.log(JSON.stringify([
  f.ownInPlace("aims of [26-523].", new Set(["26-523"])),
  f.ownInPlace("the focus of the [sch-1].", new Set(["sch-1"])),
  f.ownInPlace("fits dynamics [26-519, W1].", new Set(["26-519"])),
  f.segments("aims of [26-523].", null, new Set(["26-523"]))]));
""".replace("MODULE", (WEB / "format.js").as_uri())
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    a, b, c, segs = json.loads(r.stdout)
    assert a == "aims of this opportunity." and b == "the focus of this opportunity."
    assert c == "fits dynamics [26-519, W1]." and segs == ["aims of this opportunity."]


# --- F1, F10: "these" are the brief's leads; others carry their band ---

def test_these_and_my_leads_search_the_brief_only(service):  # noqa: F811
    """F1: "Which of these close before March?" named the brief's one lead, then nine
    records from the whole store. Code reads the question's scope, and a brief-scoped
    search filters the brief's own leads by the same rules."""
    assert question_scope("Which of these close before March?") == "brief"
    assert question_scope("Which of my NSF leads close by 1 Mar 2027?") == "brief"
    assert question_scope("Any other grants that close before March?") == "all"
    assert question_scope("Only show NIH grants") is None
    b, leads = _ranked_brief(service, 4)  # close 1 to 4 Mar 2027
    c = ScoutContext(service, AS_OF, researcher_id=AUTHOR, brief_id=b.id)
    out = TOOLS["search_opportunities"][1](c, route="A", closes_by="2027-03-02", scope="brief")
    assert [x["id"] for x in out["leads"]] == [leads[0].record_id, leads[1].record_id]
    assert out["scope"] == "brief" and out["removed_by_filters"] == 2
    assert out["leads"][0]["brief_rank"] == 1 and out["leads"][0]["deadline"] == \
        "closes 1 Mar 2027"
    fake = FakeProvider([call("search_opportunities", route="A", closes_by="2027-03-01"),
                         f"[{leads[0].record_id}] closes 1 Mar 2027."])
    s = Scout(fake, c).start("Which of these close before March?")
    assert s.cards[0].arguments["scope"] == "brief"  # set by code, shown on the card
    assert s.cards[0].detail.startswith("1 of your brief's leads")
    with pytest.raises(Exception, match="scope brief needs a brief"):
        TOOLS["search_opportunities"][1](ScoutContext(service, AS_OF, researcher_id=AUTHOR),
                                         route="A", scope="brief")


def test_store_wide_rows_say_their_band_and_whether_the_brief_holds_them(service):  # noqa: F811
    """F10: "r01?" listed cancer R01s with nothing to say none was in the brief."""
    c = ScoutContext(service, AS_OF, researcher_id=AUTHOR)
    out = TOOLS["search_opportunities"][1](c, route="A", top=5)
    assert out["leads"] and all(x["match_band"].endswith(" match") for x in out["leads"])
    assert "match" not in out["leads"][0]  # no score as a number
    assert out["note"].startswith("None of these is on the user's brief: say so first")


# --- F3, F22: one clause for every deadline ---

def _parent():
    return Opportunity(id="grants_gov:PA-SYN-1", opportunity_number="PA-SYN-1",
                       title="SYNTHETIC Predoctoral Fellowship (Parent F31)", agency="NIH",
                       close_date=date(2028, 5, 7), **KW)


def test_a_parent_announcement_expires_everywhere_and_is_no_deadline():
    """F3 (T17 again): the card read "Expires 7 May 2028", but the export read "Closes:",
    the note "deadline Expires", and Scout "has a deadline of 7 May 2028"."""
    from perch.compare import closes
    from perch.scout.student_tools import facts_of, write_note

    o = _parent()
    assert datefmt.deadline(o) == "no deadline in the record; the announcement expires 7 May 2028"
    assert closes(o, date(2026, 11, 1)).text == "Expires 7 May 2028"
    f = facts_of(o)
    assert "deadline" not in f and f["announcement_expires"] == "7 May 2028"
    lead = Lead(id="s:F1", brief_id="s", route="F", record_id=o.id, rank=1,
                verdict="may be eligible", **KW)
    body = write_note("F", [(lead, f)])["body"]
    assert "announcement expires 7 May 2028" in body and "deadline Expires" not in body
    anytime = o.model_copy(update={"title": "SYNTHETIC program", "close_date": date(2099, 1, 1),
                                   "close_date_note": "Proposals accepted anytime"})
    assert datefmt.deadline(anytime, date(2026, 11, 1)) == "Proposals accepted anytime"  # F22
    brief, leads, opps, works = _inputs()
    opps["grants_gov:SYN-1"] = o.model_copy(update={"id": "grants_gov:SYN-1"})
    assert "Closes: Expires 7 May 2028" in ex.to_markdown(
        ex.blocks(brief, None, leads, opps, {}, works, []))
    s_brief, s_leads, recs = _student_inputs()
    recs["temple_sdfa:f1"] = o.model_copy(update={"id": "temple_sdfa:f1"})
    assert "Deadline: Expires 7 May 2028" in ex.to_markdown(
        ex.student_blocks(s_brief, s_leads, recs))


def test_the_hand_off_list_never_calls_an_expiry_a_close_date():
    from perch.skills.handoff import lead_lines

    lead = Lead(id="b:A1", brief_id="b", route="A", record_id="grants_gov:PA-SYN-1", rank=1,
                **KW)
    line = lead_lines([(lead, _parent())])[0]
    assert "the announcement expires 7 May 2028" in line and "closes 7 May 2028" not in line


# --- F4, F17, F27: the student export follows the screen ---

def test_the_student_export_groups_as_the_screen_and_names_no_own_record():
    """F4: "...supports students (Boren Fellowship)." and no fit sentence exported. F17:
    the 50 not-eligible options mixed in, the shared lines repeated on every card. F27:
    "Fellowships (public) (59)"."""
    brief, leads, recs = _student_inputs()
    leads.append(leads[0].model_copy(update={"id": "s:F4", "record_id": "temple_sdfa:f4",
                                             "verdict": "not eligible", "rank": 4}))
    recs["temple_sdfa:f4"] = recs["temple_sdfa:f1"].model_copy(update={
        "id": "temple_sdfa:f4", "name": "SYNTHETIC fellowship 4"})
    leads.append(leads[0].model_copy(update={"id": "s:F5", "record_id": "temple_sdfa:f5",
                                             "rank": 5}))
    recs["temple_sdfa:f5"] = recs["temple_sdfa:f1"].model_copy(update={
        "id": "temple_sdfa:f5", "name": "SYNTHETIC fellowship 5"})
    for x in (y for y in leads if y.route == "F"):
        x.explanation = f"The fellowship funds SYNTHETIC study [{x.record_id.split(':')[1]}]."
        x.inference = f"It suits your survey work, the focus of [{x.record_id.split(':')[1]}]."
        x.match_score = 50
        x.status = "new"
    m = egress.Masker()
    md = ex.to_markdown(ex.student_blocks(brief, leads, recs, masker=m))
    assert "## Fellowships, public (4)" in md and "(public) (" not in md
    assert "## Fellowships, public: not eligible by rule (1)" in md
    assert md.index("SYNTHETIC fellowship 5") < md.index("not eligible by rule")
    assert md.index("not eligible by rule") < md.index("SYNTHETIC fellowship 4")
    assert "Unless an option says otherwise:" in md
    open_part = md[:md.index("not eligible by rule")]
    assert open_part.count("The listing states no deadline or amount.") == 1
    assert open_part.count("The listing says who may apply.") == 1  # once, above the list
    assert "(SYNTHETIC fellowship 1)" not in md  # F4: no own-record parenthesis
    assert "Why it may fit: It suits your survey work, the focus of this opportunity." in md
    plain = ex.to_markdown(ex.student_blocks(brief, leads, recs))
    n = plain.count("Why it may fit withheld:")
    assert n == 5  # four options you may apply for, one not eligible: counted in the banner
    assert f"> {egress.withheld_note(plain.count(egress.WITHHELD) + n)}" in plain


def test_a_documents_brief_is_titled_your_documents(tmp_path, monkeypatch):
    from .test_private import open_with_persona, private_app

    c, _ = private_app(tmp_path, monkeypatch)
    h = open_with_persona(c)
    c.post("/private/brief", headers=h, json={"as_of": "2026-10-28"})
    md = c.get("/private/export.md", headers=h).text
    assert md.startswith("# Perch brief: your documents") and "You (private)" not in md
    assert "<title>Perch brief: your documents</title>" in c.get("/private/export.html",
                                                                  headers=h).text


# --- F5, F11: counts from compare and the signals; compare reads as the card ---

def test_a_count_code_wrote_into_a_compare_row_backs_the_answer(service):  # noqa: F811
    """F5: "How many of my papers does each kept lead cite?" ran get_org_signals and
    the answers lost their numbers."""
    b, leads = _ranked_brief(service, 2)
    with service.repo() as r:
        r.upsert([x.model_copy(update={"cited_ids": ["W1", "W2", "W3"], "status": "kept",
                                       "inference": "It fits [W1].", "match_score": 30})
                  for x in leads])
    c = ScoutContext(service, AS_OF, researcher_id=AUTHOR, brief_id=b.id)
    fake = FakeProvider([call("compare"), f"[{leads[0].record_id}] cites 3 of your papers."])
    s = Scout(fake, c).start("How many of my papers does each kept lead cite?")
    assert s.answer and not s.flagged, s.errors
    row = s.cards[0].result["rows"][0]
    assert row["your_papers_cited"] == 3 and row["kind"] == "grant" and "route" not in row
    assert row["Evidence"] == "weak match, cites 3 of your papers"  # F11: no score, no codes
    assert "how_it_relates" in row  # F11, T15: the weak band's label
    from perch.scout.loop import GRANT_Q_RE, ORG_Q_RE

    q = "Which of my kept grants cites more of my papers?"
    assert ORG_Q_RE.search(q) and GRANT_Q_RE.search(q)  # so no nudge to get_org_signals
    assert "kept lead or grant cites is in compare's rows" in __import__(
        "perch.scout.loop", fromlist=["RULES"]).RULES


def test_a_floor_named_after_its_amount_is_not_called_a_ceiling():
    """F16: compare's Money cell reads "from $15,000,000 (award floor)"; an answer that
    copied it into a ceiling sentence was withheld twice."""
    o = Opportunity(id="grants_gov:SYN-FL", opportunity_number="SYN-FL", title="SYNTHETIC",
                    agency="NSF", award_floor=15_000_000, **KW)
    seen = {o.id: o}
    ok = f"The largest award ceiling is unstated; [{o.id}] is from $15,000,000 (award floor)."
    assert floor_as_ceiling(ok, seen) == []
    assert floor_as_ceiling(f"The largest ceiling is $15,000,000 [{o.id}].", seen)


# --- F6: student reasons come with the search ---

def test_not_eligible_options_carry_their_rule_reason_and_one_explain_per_question(
        service):  # noqa: F811
    """F6 (T10 again): "Which ones am I not eligible for, and why?" ran explain_verdict seven
    times and stopped at the cap with no answer."""
    from perch.schemas import Brief
    from perch.scout.student_tools import STUDENT_RULES, STUDENT_TOOLS, search_options

    brief, leads, recs = _student_inputs()
    for x in leads:
        x.verdict, x.status = "not eligible", "new"
        x.verdict_lines = ["Open to year 4; your CV says 3."]
    with service.repo() as r:
        r.upsert([*recs.values(), *leads, Brief(**{**brief.model_dump(), "lead_ids":
                                                    [x.id for x in leads]})])
    ctx = ScoutContext(service, AS_OF, brief_id="s", researcher_id="private:student")
    out = search_options(ctx, verdict="not eligible")
    rows = [*out.get("options", []), *out.get("fellowships", []),
            *out.get("sample_scholarships", [])]
    assert rows and all(r["why"] == ["Open to year 4; your CV says 3."] for r in rows)
    assert "each with its reason in why" in STUDENT_RULES
    fake = FakeProvider([call("explain_verdict", option_id=rows[0]["id"]),
                         call("explain_verdict", option_id=rows[1]["id"]),
                         f"[{rows[0]['id']}] is open to year 4; your CV says 3."])
    s = Scout(fake, ctx, table=STUDENT_TOOLS, rules=STUDENT_RULES).start("why not?")
    assert [x.status for x in s.cards] == ["done", "refused"]
    assert s.answer and not s.flagged, s.errors  # the rule line's numbers back it


# --- F7, F8, F19: the hand-off on a documents brief ---

def test_scouts_hand_off_on_a_documents_brief_opens_by_code(tmp_path, monkeypatch):
    """F7: Scout's draft opened "My published research focuses on ... my recent papers []"
    under a Code label, though the brief has no public papers and the aims are on gait."""
    from .test_private import fit_reply, open_with_persona, private_app

    asked = []

    def reply(messages, system, schema):
        if system and system.startswith("You are Scout"):
            opp = __import__("re").search(r"\n1\. \[([^\]]+)\]", system).group(1)
            return [ToolCall("c1", "draft_handoff", {"ids": [opp]})]
        if system and system.startswith("You draft the opening"):
            asked.append(system)
        return fit_reply(messages, system, schema)

    c, _ = private_app(tmp_path, monkeypatch, responder=reply)
    h = open_with_persona(c)
    c.post("/private/brief", headers=h, json={"as_of": "2026-10-28"})
    v = c.post("/private/scout", headers=h,
               json={"question": "Draft the hand-off for my top lead"}).json()
    for _ in range(100):
        v = c.get(f"/private/scout/{v['id']}", headers=h).json()
        if not v["busy"] and v["status"] != "running":
            break
        time.sleep(0.1)
    d = v["exchanges"][0]["cards"][0]["draft"]
    opening = d["body"].split("\n\n")[1]
    assert d["opening_by"] == "code" and not asked  # no model ran for the opening
    assert opening.startswith("I would like to talk with your team about ")
    assert "my CV" in opening and "[" not in d["body"]
    assert "These are the leads I would like to discuss:" in d["body"]  # F8: none kept
    assert "Perch drafted this from your documents and public records." in d["body"]  # F19


def test_the_hand_off_validator_rejects_empty_and_placeholder_citations():
    from perch.offices import OFFICES
    from perch.schemas import Researcher
    from perch.skills.handoff import draft_handoff

    o = Opportunity(id="grants_gov:SYN-1", opportunity_number="SYN-1", title="SYNTHETIC",
                    agency="NSF", close_date=date(2027, 1, 1), **KW)
    lead = Lead(id="b:A1", brief_id="b", route="A", record_id=o.id, rank=1, status="kept",
                **KW)
    res = Researcher(id="https://openalex.org/A1", display_name="SYNTHETIC Person", **KW)
    bad = json.dumps({"paragraph": "My work is on SYNTHETIC topics [No papers provided]. I "
                      "would like to discuss SYNTHETIC [].", "cited_ids": ["SYN-1"]})
    fake = FakeProvider([bad, bad])
    from perch.llm.audit import AuditedProvider, AuditLog

    d = draft_handoff(OFFICES["research_development"], res, [(lead, o)], [],
                      AuditedProvider(fake, AuditLog(None), "handoff"))
    assert d.flagged and d.opening_by == "code"
    assert any("No papers provided" in e or "[]" in e for e in d.errors)
    assert "These are the leads I kept in Perch:" in d.body  # F8: every listed lead kept
    good = json.dumps({"paragraph": "My work builds SYNTHETIC tools. I would like to discuss "
                       "SYNTHETIC with your team.", "cited_ids": ["SYN-1"]})
    d = draft_handoff(OFFICES["research_development"], res, [(lead, o)], [],
                      AuditedProvider(FakeProvider([good]), AuditLog(None), "handoff"))
    assert d.opening_by == "model" and not d.flagged


# --- F15: the last list ---

def test_follow_ups_see_the_last_list(service):  # noqa: F811
    b, leads = _ranked_brief(service, 3)
    c = ScoutContext(service, AS_OF, researcher_id=AUTHOR, brief_id=b.id)
    fake = FakeProvider([call("search_opportunities", route="A", top=3), "Listed.",
                         "The first one."])
    scout = Scout(fake, c)
    s = scout.start("Only show NSF grants")
    assert s.last_list
    scout.ask(s, "whats the deadline for the first one")
    assert "The last list you gave, in order: [" in fake.calls[-1]["system"]


# --- F25 ---

def test_an_empty_find_is_refused_with_a_hint(tmp_path):
    from .test_api import make

    c, _ = make(tmp_path)
    for q in ("", "   "):
        r = c.get("/authors/resolve", params={"q": q})
        assert r.status_code == 422 and r.json()["detail"] == \
            "Type a name, ORCID iD or OpenAlex ID."


def test_scholarship_amount_sort_exists():
    """F15: "Which option pays the most?" can sort by amount."""
    from perch.scout.student_tools import STUDENT_TOOLS

    assert "amount" in STUDENT_TOOLS["search_options"][0].parameters["properties"]["sort"][
        "enum"]
    assert Scholarship  # imported for the student fixtures
    assert T

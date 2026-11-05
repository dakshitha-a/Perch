"""S53: the optional citizenship and state picks, compared with a listing's own quoted rule.

Records are SYNTHETIC stand-ins: the sentences are shaped like the ones on Temple's pages, the
names and ids are invented. Nothing is copied from a real record."""

from datetime import UTC, date, datetime

from perch.citizenship import rules_in
from perch.schemas import Opportunity, Scholarship, ScholarshipEligibility
from perch.student import (
    Scored,
    StudentFacts,
    check,
    choose,
    for_sample,
    to_leads,
)

T = datetime(2026, 11, 1, tzinfo=UTC)
AS_OF = date(2026, 11, 6)


def facts(cit=None, res=None) -> StudentFacts:
    return StudentFacts(level="bachelor's", class_year=3, major="Biology",
                        citizenship=cit, residency_state=res)


def sch(notes: str | None = None, quote: str | None = None, sid: str = "a",
        source: str = "temple_pages", **kw) -> Scholarship:
    return Scholarship(id=f"{source}:{sid}", source=source, fetched_at=T,
                       source_url=f"https://example.edu/SYNTHETIC/{sid}",
                       name="SYNTHETIC Undergraduate Research Award", audience_level="mixed",
                       eligibility=ScholarshipEligibility(notes=notes),
                       field_quotes={"eligibility": quote} if quote else {}, **kw)


US_ONLY = "Applicants must be U.S. citizens who are full time students."
BOTH = "Open to U.S. citizens and permanent residents; apply by the deadline."


def line(v) -> str:
    return next(c["text"] for c in v.checks if c["rule"] == "citizenship")


# --- the phrase matcher ---

def test_matcher_reads_a_closed_phrase_and_quotes_the_full_sentence():
    rs = rules_in("Be enrolled full time; U.S. citizens who study biology are eligible; apply "
                  "online.", "eligibility.notes")
    assert [r.sentence for r in rs] == ["U.S. citizens who study biology are eligible"]
    assert rs[0].field == "eligibility.notes"
    assert rs[0].allows == {"us_citizen"}


def test_matcher_finds_nothing_without_a_phrase():
    assert rules_in("Open to resident doctoral students in the humanities. Apply online.",
                    "eligibility.notes") == []
    assert rules_in("Students at Temple University may apply.", "eligibility.notes") == []


def test_matcher_reads_other_closed_forms():
    assert rules_in("A citizen of the United States", "x")[0].allows == {"us_citizen"}
    assert rules_in("Citizens or nationals of the United States", "x")[0].allows == {"us_citizen"}
    r = rules_in("Be a Pennsylvania resident", "x")[0]
    assert (r.kind, r.allows) == ("residency", {"PA"})
    r = rules_in("Residents of West Virginia only", "x")[0]
    assert r.allows == {"WV"}


def test_a_preference_is_not_a_rule():
    assert rules_in("Strong preference given to U.S. citizens and permanent resident students.",
                    "x") == []


def test_permanent_residents_not_eligible_reads_as_a_negative():
    r = rules_in("Permanent residents are not eligible.", "x")[0]
    assert (r.mode, r.allows) == ("not_for", {"permanent_resident"})


def test_international_direction_only_when_the_sentence_says_so():
    assert rules_in("International students are not eligible.", "x")[0].mode == "not_for"
    assert rules_in("All students will be considered, including international students.",
                    "x")[0].mode == "ok_for"
    assert rules_in("International students attend Temple.", "x") == []


# --- check(): pass, demote, unknown ---

def test_pick_that_meets_the_rule_passes_with_the_quoted_sentence():
    v = check(sch(US_ONLY), facts("us_citizen"), AS_OF)
    assert not v.demoted
    c = next(c for c in v.checks if c["rule"] == "citizenship")
    assert c["outcome"] == "pass"
    assert "Applicants must be U.S. citizens who are full time students" in c["text"]
    assert "eligibility notes on its Temple page" in c["text"]
    assert "You entered: U.S. citizen." in c["text"]
    assert v.rule["outcome"] == "pass" and v.rule["field"] == "eligibility.notes"


def test_pick_that_misses_the_rule_demotes_and_never_rules_out():
    v = check(sch(US_ONLY), facts("international"), AS_OF)
    assert v.verdict == "may be eligible"
    assert v.demoted is True
    assert all(c["outcome"] != "fail" for c in v.checks)
    assert v.lines[0].startswith("From the award's eligibility notes on its Temple page, the "
                                 "listing asks for: “Applicants must be U.S. citizens")
    assert "You entered: International." in v.lines[0]
    assert v.rule["outcome"] == "fail"
    assert v.rule["quote"].startswith("Applicants must be U.S. citizens")
    assert v.rule["source_url"] == "https://example.edu/SYNTHETIC/a"
    assert v.rule["record_id"] == "temple_pages:a"


def test_permanent_resident_meets_both_forms_only_where_listed():
    assert not check(sch(BOTH), facts("permanent_resident"), AS_OF).demoted
    assert check(sch(US_ONLY), facts("permanent_resident"), AS_OF).demoted
    assert not check(sch(BOTH), facts("us_citizen"), AS_OF).demoted
    assert check(sch(BOTH), facts("international"), AS_OF).demoted


def test_the_quoted_eligibility_sentence_is_read_too():
    v = check(sch(None, quote=US_ONLY), facts("international"), AS_OF)
    assert v.demoted and v.rule["field"] == "field_quotes.eligibility"
    assert "eligibility sentence quoted from the award's page" in v.lines[0]


def test_residency_pass_and_demote():
    s = sch("Be a Pennsylvania resident; file the FAFSA")
    ok = check(s, facts(res="PA"), AS_OF)
    assert not ok.demoted
    assert next(c for c in ok.checks if c["rule"] == "residency")["outcome"] == "pass"
    bad = check(s, facts(res="NJ"), AS_OF)
    assert bad.demoted and "You entered: New Jersey." in bad.lines[0]


def test_blank_and_prefer_not_leave_the_verdict_exactly_as_before():
    s = sch(US_ONLY)
    base = check(s, facts(), AS_OF)
    for pick in (None, "prefer_not"):
        v = check(s, facts(pick), AS_OF)
        assert (v.verdict, v.reason, v.lines, v.checks, v.demoted, v.rule) == (
            base.verdict, base.reason, base.lines, base.checks, False, None)
    assert "states no rule" in line(base)


def test_no_phrase_says_where_perch_looked():
    v = check(sch("Students at Temple may apply."), facts("us_citizen"), AS_OF)
    assert not v.demoted
    assert line(v) == ("Perch found no rule it can compare with your answer. Read the "
                       "eligibility text.")
    assert v.rule["outcome"] == "none" and v.rule["quote"] is None
    assert v.rule["has_text"] is True


def test_no_eligibility_text_at_all_is_said():
    v = check(sch(), facts("us_citizen"), AS_OF)
    assert line(v) == ("This listing has no eligibility text for Perch to read; check the "
                       "award's page.")
    assert v.rule["has_text"] is False and v.rule["outcome"] == "none"


def test_the_sample_student_line_reads_the_sample_student_entered():
    v = check(sch(US_ONLY), facts("international"), AS_OF)
    assert for_sample(v.lines[0]).endswith("The sample student entered: International.")


# --- ordering ---

def scored(sid: str, score: float, notes: str | None, cit: str) -> Scored:
    s = sch(notes, sid=sid)
    return Scored(s, None, score, check(s, facts(cit), AS_OF))


def test_demoted_listings_come_last_stay_in_the_list_and_do_not_use_the_ruled_out_cap():
    top = [scored("a", 0.9, US_ONLY, "international"),        # demoted, best score
           scored("b", 0.8, None, "international"),
           scored("c", 0.7, "Open to all.", "international")]
    out = choose(top, top=10, ruled_out=0)
    assert [x.record.id.split(":")[1] for x in out] == ["b", "c", "a"]
    assert out[-1].verdict.demoted and out[-1].verdict.verdict == "may be eligible"
    # the cut is made first; demoted ones go last inside the shown set, none is dropped
    out = choose(top, top=2, ruled_out=5)
    assert [x.record.id.split(":")[1] for x in out] == ["b", "a"]


def test_leads_carry_the_flag_and_the_rule():
    x = scored("a", 0.9, US_ONLY, "international")
    lead = to_leads("b1", "F", [x], facts("international"))[0]
    assert lead.demoted is True
    assert lead.citizenship_rule["outcome"] == "fail"
    assert lead.verdict == "may be eligible"


# --- researcher side ---

def opp(notes: str | None, source: str = "grants_gov") -> Opportunity:
    return Opportunity(id="opp:1", source=source, source_url="https://example.gov/SYNTHETIC/1",
                       fetched_at=T, opportunity_number="SYN-1", title="SYNTHETIC call",
                       agency="Invented Agency", eligibility_notes=notes)


def test_researcher_demotion_note_names_grants_gov():
    from perch.service import grant_demotion

    note, prov = grant_demotion(opp(US_ONLY), "international", None)
    assert note.startswith("From the opportunity's eligibility text on Grants.gov, the listing "
                           "asks for: “Applicants must be U.S. citizens")
    assert prov["outcome"] == "fail" and prov["field"] == "eligibility_notes"
    assert prov["source_url"] == "https://example.gov/SYNTHETIC/1"
    note, prov = grant_demotion(opp(US_ONLY), "us_citizen", None)
    assert prov["outcome"] == "pass" and "You entered: U.S. citizen." in note
    note, prov = grant_demotion(opp("Open to universities."), "us_citizen", None)
    assert prov["outcome"] == "none"
    assert note is None  # said once above the list, not on every card
    note, prov = grant_demotion(opp(None), "us_citizen", None)
    assert note is None and prov["has_text"] is False
    assert grant_demotion(opp(US_ONLY), None, None) == (None, None)
    assert grant_demotion(opp(US_ONLY), "prefer_not", None) == (None, None)


def test_citizenship_counts_skip_samples_and_industry():
    from perch.api import citizenship_counts

    leads = [{"route": "A", "opportunity": {"eligibility_notes": US_ONLY}},
             {"route": "A", "opportunity": {"eligibility_notes": "Open."}},
             {"route": "S", "sample": True, "record": {"eligibility": {"notes": US_ONLY}}},
             {"route": "B", "organisation": {}},
             {"route": "F", "record": {"eligibility": {"notes": BOTH}}}]
    assert citizenship_counts(leads) == {"stated": 2, "total": 3}


def test_guest_persona_is_international_and_has_no_state():
    from perch.user.briefs import persona_inputs

    p = persona_inputs("persona-ug")
    assert (p.citizenship, p.residency_state) == ("international", None)


def test_scout_student_tool_output_holds_no_pick_value():
    """The lines the comparison wrote name the user's answer, so every Scout path that reads a
    lead's lines or notes goes through `without_picks`, and a pick line never gets through."""
    import re
    from pathlib import Path

    from perch.citizenship import without_picks

    v = check(sch(US_ONLY), facts("international"), AS_OF)
    lead = to_leads("b1", "F", [Scored(sch(US_ONLY), None, 0.5, v)], facts("international"))[0]
    assert any("You entered" in x for x in lead.verdict_lines)
    cleaned = without_picks(lead.verdict_lines)
    assert not any("International" in x or "entered" in x for x in cleaned)
    none_line = line(check(sch("Open to all."), facts("us_citizen"), AS_OF))
    assert without_picks([none_line, "Deadline: not yet passed."]) == ["Deadline: not yet passed."]
    root = Path(__file__).resolve().parents[1] / "perch" / "scout"
    for f in root.glob("*.py"):
        for n, src in enumerate(f.read_text().splitlines(), 1):
            if re.search(r"\.(verdict_lines|notes)\b", src) and "e.notes" not in src \
                    and "eligibility" not in src and "rec.notes" not in src:
                assert "without_picks(" in src, f"{f.name}:{n} reads lead lines unscrubbed"


def test_eligible_noncitizen_lets_permanent_residents_apply():
    # The federal aid phrase; SYNTHETIC wording shaped like it.
    s = "Be a U.S. citizen or Eligible Noncitizen."
    (r,) = rules_in(s, "eligibility.notes")
    assert r.allows == frozenset({"us_citizen", "permanent_resident"})
    from perch.citizenship import judge

    src = [("eligibility.notes", s)]
    assert judge(src, "permanent_resident", None, "temple_pages")["citizenship"].status == "pass"
    assert judge(src, "international", None, "temple_pages")["citizenship"].status == "fail"


def test_fafsa_sentences_are_not_rules():
    assert rules_in("You must be eligible to file the FAFSA as a U.S. citizen.",
                    "eligibility.notes") == []
    assert rules_in("Complete the FAFSA; U.S. citizens only.", "eligibility.notes")[0].sentence \
        == "U.S. citizens only."


def test_pipe_splits_clauses_so_a_not_cannot_cancel_a_rule():
    rs = rules_in("U.S. citizens only | Not open to staff", "eligibility.notes")
    assert [r.mode for r in rs] == ["only"]


def test_residency_note_is_not_quoted_as_the_listings_words():
    from perch.citizenship import judge, stated_note

    outs = judge([("eligibility.residency_state", "For residents of Pennsylvania")], None, "NJ",
                 "temple_pages")
    from perch.citizenship import demoted_note

    n = demoted_note(outs["residency"], "New Jersey")
    assert n == "The award's residency field says: Pennsylvania. You entered: New Jersey."
    assert "“" not in n
    outs = judge([("eligibility.residency_state", "For residents of Pennsylvania")], None, "PA",
                 "temple_pages")
    assert "“" not in stated_note("Residency", outs["residency"], "Pennsylvania")


def test_choose_cuts_first_then_puts_demoted_last():
    from types import SimpleNamespace as NS

    def sc(i, demoted):
        return NS(i=i, verdict=NS(verdict="may be eligible", demoted=demoted))

    items = [sc(0, True), sc(1, False), sc(2, False), sc(3, False)]
    out = choose(items, top=3, ruled_out=0)
    assert [x.i for x in out] == [1, 2, 0]  # the demoted one is still shown, last
    assert {x.i for x in out} == {0, 1, 2}


def test_export_notes_keep_the_rule_and_drop_the_pick():
    from perch.citizenship import strip_entered

    got = strip_entered([
        "From the award's eligibility notes, the listing asks for: “U.S. citizens only”. "
        "You entered: U.S. citizen.",
        "Perch found no rule it can compare with your answer. Read the eligibility text.",
        "Your CV lists a past award from X."])
    assert got == ["From the award's eligibility notes, the listing asks for: “U.S. citizens "
                   "only”.", "Your CV lists a past award from X."]


def test_student_export_drops_the_users_pick_s54():
    """S54: a student may forward the export to an office, so it never carries the pick."""
    from perch.citizenship import strip_entered

    line = ('Citizenship: the listing asks for: "SYNTHETIC U.S. citizens only." '
            "You entered: International.")
    out = " ".join(strip_entered([line]))
    assert "International" not in out and "U.S. citizens" in out

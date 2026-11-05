"""S50 round 2: student rules on Temple-page awards (G1, G2, Q1/G6, Q2).

Records are SYNTHETIC stand-ins shaped like the stored Temple-page awards: the names are
generic award names, the ids and URLs are invented, and no record text is copied."""

from datetime import UTC, date, datetime

from perch.schemas import Scholarship, ScholarshipEligibility
from perch.student import StudentFacts, check, student_pool

T = datetime(2026, 11, 1, tzinfo=UTC)
AS_OF = date(2026, 11, 6)
UG = StudentFacts(level="bachelor's", class_year=3, major="Biology")
PHD = StudentFacts(level="graduate", major="Chemistry")


def sch(name: str, source: str = "temple_pages", audience: str | None = "mixed",
        sid: str | None = None, **kw) -> Scholarship:
    sid = sid or name.lower().replace(" ", "-")[:30]
    return Scholarship(id=f"{source}:{sid}", source=source, fetched_at=T,
                       source_url=f"https://example.edu/SYNTHETIC/{sid}", name=name,
                       audience_level=audience, **kw)


# --- G1, Q2: the level comes from the award's own name when the page tag says "mixed" ---

def test_graduate_names_rule_out_an_undergraduate():
    for name in ("Graduate Student Research Grants", "SYNTHETIC Masters Scholarship",
                 "Film Award Fund (Graduate)", "Dissertation Completion Grant"):
        v = check(sch(name), UG, AS_OF)
        assert v.verdict == "not eligible", name
        assert v.reason == "level"
        assert "mixed" not in v.lines[0]
        assert "award's name" in v.lines[0]


def test_undergraduate_name_is_open_to_an_undergraduate_and_not_to_a_phd():
    s = sch("SYNTHETIC Undergraduate Research Award")
    assert check(s, UG, AS_OF).verdict != "not eligible"
    assert check(s, PHD, AS_OF).verdict == "not eligible"


def test_a_name_with_both_levels_sets_no_rule():
    s = sch("SYNTHETIC Undergraduate and Graduate Travel Award")
    assert check(s, UG, AS_OF).verdict != "not eligible"
    assert check(s, PHD, AS_OF).verdict != "not eligible"


def test_postdoctoral_fellowships_leave_the_student_pool():
    recs = [sch("NRSA Individual Postdoctoral Fellowship (F32)", sid="f32"),
            sch("NRSA Senior Postdoctoral Fellowship (F33)", sid="f33"),
            sch("SYNTHETIC Undergraduate Research Award", sid="ura")]
    pool, _ = student_pool(recs)
    assert [s.id for s in pool] == ["temple_pages:ura"]


def test_predoctoral_fellowship_filed_under_faculty_reaches_a_phd_student():
    f31 = sch("NRSA Individual Predoctoral Fellowship (F31)", audience="faculty", sid="f31")
    t32 = sch("NRSA Institutional Training Award (T32)", audience="faculty", sid="t32")
    pool, _ = student_pool([f31, t32])
    assert [s.id for s in pool] == ["temple_pages:f31"]
    assert check(f31, PHD, AS_OF).verdict != "not eligible"
    assert check(f31, UG, AS_OF).verdict == "not eligible"


def test_the_records_own_levels_still_decide():
    s = sch("SYNTHETIC Graduate Prize", source="temple_sdfa", audience=None,
            level_of_study=["bachelor's"])
    assert check(s, UG, AS_OF).verdict != "not eligible"


def test_samples_keep_their_own_rules():
    s = Scholarship(id="sample:sch-9999", source="synthetic", fetched_at=T,
                    source_url="https://example.edu/SYNTHETIC/sample", name="Graduate Example",
                    canary="PERCH-CANARY-S50-TEST", eligibility=ScholarshipEligibility())
    assert check(s, UG, AS_OF).verdict == "eligible"


# --- G2: one award listed on several pages is one card ---

def test_looser_name_key_merges_copies_across_and_within_sources():
    office = sch("Rhodes", source="temple_sdfa", audience=None, sid="rhodes",
                 level_of_study=["bachelor's"],
                 eligibility=ScholarshipEligibility(class_year=[4]))
    page = sch("Rhodes Scholarships", audience="graduate", sid="rhodes-scholarships-1")
    a = sch("Diamond Research Scholars", audience="undergraduate", sid="drs-1")
    b = sch("Diamond Research Scholars Program", audience="undergraduate", sid="drs-2")
    pool, also = student_pool([office, page, a, b])
    ids = [s.id for s in pool]
    assert ids.count("temple_sdfa:rhodes") == 1 and "temple_pages:rhodes-scholarships-1" not in ids
    assert also["temple_sdfa:rhodes"] == [page.source_url]  # the office copy keeps its level
    assert len([i for i in ids if "drs" in i]) == 1
    v = check(next(s for s in pool if s.id == "temple_sdfa:rhodes"), UG, AS_OF)
    assert v.verdict == "not eligible" and v.reason == "class_year"  # one verdict, not two


def test_reviewed_look_alike_names_stay_apart():
    a = sch("Temple University Grant", audience="undergraduate", sid="tug-1")
    b = sch("Temple University Grant (TUG)", audience="mixed", sid="tug-2")
    pool, _ = student_pool([a, b])
    assert len(pool) == 2


def test_different_names_are_not_merged():
    a = sch("SYNTHETIC Peer Teachers", audience="undergraduate", sid="pt")
    b = sch("SYNTHETIC Peer Mentors", audience="undergraduate", sid="pm")
    assert len(student_pool([a, b])[0]) == 2


# --- Q1, G6: every card says what the rules checked ---

FIXED = ("The listing says who may apply; the award's own page sets the full rules. Read it "
         "before applying.")


def test_listing_only_card_says_what_was_checked_and_quotes_the_listing():
    s = sch("SYNTHETIC Research Scholars", audience="undergraduate", sid="rs",
            scope="temple_wide", deadline=date(2027, 2, 15), details_fetched_at=T,
            details_url="https://example.edu/SYNTHETIC/rs-details",
            deadline_quote="Applications are due February 15, 2027.",
            eligibility=ScholarshipEligibility(notes="For first-year students, sophomores, or "
                                                     "juniors. Apply with a mentor."))
    v = check(s, UG, AS_OF)
    assert v.verdict == "may be eligible" and v.reason == "listing_only"
    assert FIXED not in v.lines
    assert v.lines[0] == "Perch checked level, school and deadline; nothing there rules you out."
    assert v.lines[1] == ("The listing says: “For first-year students, sophomores, or "
                          "juniors.”")
    rules = {c["rule"]: c["outcome"] for c in v.checks}
    assert rules == {"level": "pass", "school": "pass", "deadline": "pass",
                     "citizenship": "unknown", "staff_only": "pass"}
    assert all(set(c) == {"rule", "outcome", "text"} for c in v.checks)


def test_a_ruled_out_card_still_lists_every_rule():
    s = sch("SYNTHETIC Graduate Travel Grants", sid="gt", scope="school",
            schools=["SYNTHETIC School"], eligibility=ScholarshipEligibility(citizenship="U.S. "
                                                                             "citizen"))
    v = check(s, UG, AS_OF)
    assert v.verdict == "not eligible"
    by = {c["rule"]: c for c in v.checks}
    assert by["level"]["outcome"] == "fail" and "your CV says bachelor's" in by["level"]["text"]
    assert by["school"]["outcome"] == "unknown" and "SYNTHETIC School" in by["school"]["text"]
    assert by["citizenship"]["text"] == ("Citizenship: asks for U.S. citizen. You decide if "
                                         "this applies.")
    assert by["deadline"] == {"rule": "deadline", "outcome": "unknown",
                              "text": "Deadline: the listing gives no date."}


def test_leads_carry_the_checks():
    from perch.schemas import Lead
    from perch.student import Scored, to_leads

    s = sch("SYNTHETIC Undergraduate Prize", sid="up")
    leads = to_leads("b1", "S", [Scored(s, None, 1.0, check(s, UG, AS_OF))], UG)
    d = Lead.model_validate(leads[0].model_dump(mode="json")).model_dump(mode="json")
    assert d["checks"][0] == {"rule": "level", "outcome": "pass",
                              "text": "Level: open to undergraduate students, by the award's "
                                      "name; your CV says bachelor's."}


def test_a_sample_brief_names_the_sample_students_cv():
    """A guest's sample brief reads the SYNTHETIC sample student's CV, so no rule line,
    verdict line or gap says "your CV" (S50 QA, the walk's sample_brief_not_your_cv)."""
    from perch.student import Scored, to_leads

    s = sch("SYNTHETIC Graduate Award", sid="ga", schools=["SYNTHETIC School"], scope="school",
            eligibility=ScholarshipEligibility(gpa_min=3.5, enrolment_status="full-time"))
    f = StudentFacts(level="bachelor's", class_year=3, major="Biology")
    mine = to_leads("b1", "S", [Scored(s, None, 1.0, check(s, f, AS_OF))], f)[0]
    theirs = to_leads("b1", "S", [Scored(s, None, 1.0, check(s, f, AS_OF))], f,
                      sample=True)[0]
    assert any("your CV" in c.text for c in mine.checks)
    text = " ".join([*(c.text for c in theirs.checks), *theirs.verdict_lines, *theirs.gaps])
    assert "your" not in text.lower().replace("you decide", "")
    assert "the sample student's CV says bachelor's" in text
    assert [c.outcome for c in theirs.checks] == [c.outcome for c in mine.checks]

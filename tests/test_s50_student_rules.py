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

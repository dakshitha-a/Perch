from datetime import UTC, date, datetime

from perch import awards as aw
from perch.schemas import Award, Researcher

T = datetime(2026, 10, 28, tzinfo=UTC)


def award(id, number, pis, end, fy, start=date(2020, 1, 1), source="nih_reporter", foa=None):
    return Award(id=id, source=source, source_url=f"https://example.org/{id}", fetched_at=T,
                 agency="NIH", award_number=number, title=f"SYNTHETIC {number}", pi_names=pis,
                 start_date=start, end_date=end, fiscal_year=fy, opportunity_number=foa)


R = Researcher(id="https://openalex.org/A1", display_name="Jane Q. Doe", source="openalex",
               source_url="https://api.openalex.org/authors/A1", fetched_at=T)


def test_name_matching():
    assert aw.same_person("Jane Q. Doe", "JANE QUINN DOE")
    assert aw.same_person("Jane Doe", "J Doe")
    assert aw.same_person("José Núñez", "Jose Nunez")
    assert aw.same_person("Jane Doe Jr.", "Jane Doe")
    assert not aw.same_person("Jane Doe", "John Doe")
    assert not aw.same_person("Jane Doe", "Jane Roe")
    assert aw.search_name("Tomasz Skórski") == ("Tomasz", "Skorski")
    assert aw.search_name("Heather M. Gardiner") == ("Heather", "Gardiner")


def test_link_respects_overrides(tmp_path):
    csv = tmp_path / "o.csv"
    csv.write_text("author_id,kind,value,note\n"
                   "A1,exclude_award,nih_reporter:R01X,different person\n"
                   "A1,include_award,nsf:999,listed under a maiden name\n"
                   "https://openalex.org/A1,query_name,Jane Roe,earlier name\n"
                   "A2,exclude_award,nih_reporter:R01Y,other author\n")
    ov = aw.load_overrides(R.id, csv)
    assert ov.query_names == ["Jane Roe"]
    recs = [award("1", "R01X", ["Jane Doe"], date(2030, 1, 1), 2025),
            award("2", "R01Y", ["Jane Doe"], date(2027, 1, 1), 2025),
            award("3", "999", ["Someone Else"], date(2026, 1, 1), None, source="nsf"),
            award("4", "R01Z", ["Jane Roe"], date(2025, 1, 1), 2024),
            award("5", "R01W", ["Jim Doe"], date(2031, 1, 1), 2025)]
    linked = {a.award_number for a in aw.link_awards(R, recs, ov)}
    assert linked == {"R01Y", "999", "R01Z"}


def test_summary_uses_latest_end_and_horizon():
    recs = [award("a", "R01A", ["Jane Doe"], date(2025, 4, 30), 2023, foa="PA-1"),
            award("b", "R01A", ["Jane Doe"], date(2027, 4, 30), 2024, foa="PA-1"),
            award("c", "R01B", ["Jane Doe"], date(2026, 8, 31), 2025, start=date(2021, 9, 1))]
    s = aw.summarise(recs)
    assert [x.award_number for x in s] == ["R01A", "R01B"]
    assert s[0].end_date == date(2027, 4, 30) and s[0].end_record.id == "b"
    assert s[0].opportunity_numbers == ["PA-1"]
    h = aw.award_horizon(s)
    assert h.award_number == "R01A" and h.end_date == date(2027, 4, 30)
    assert aw.award_horizon([]) is None

"""Temple STTR partner matcher (S12 task 7). SYNTHETIC awards."""

from datetime import UTC, date, datetime

from perch import sttr
from perch.schemas import Award

T = datetime(2026, 10, 29, tzinfo=UTC)


def award(title, start=date(2020, 1, 1)):
    return Award(id=f"x:{title}", source="x", source_url="u", fetched_at=T, agency="X",
                 award_number="1", title=title, start_date=start)


def test_title_needs_two_topic_stems_or_the_only_one():
    topics = {"T1": ("PARP inhibition in cancer therapy", 0.3), "T2": ("HIV Research", 0.2)}
    hits = sttr.matching([award("SYNTHETIC inhibitors for breast cancer"),
                          award("SYNTHETIC cancer imaging"),
                          award("SYNTHETIC HIV-1 assay"), award("N/A")], topics)
    assert [a.title for a in hits] == ["SYNTHETIC inhibitors for breast cancer",
                                       "SYNTHETIC HIV-1 assay"]


def test_the_committed_table_loads_without_contact_fields():
    rows = sttr.load()
    assert len(rows) == 41 and all(a.source_url == sttr.SOURCE_URL for a in rows)
    header = sttr.TABLE.read_text().splitlines()[0].lower()
    assert "email" not in header and "phone" not in header and "contact" not in header

"""S51 W7: compare wording. A lead with no explanation after the explanation stage ended has
"no written reason", not "no explanation yet"; the instrument row is left out when every
column is a grant. SYNTHETIC records."""

from __future__ import annotations

from datetime import UTC, date, datetime

from perch.schemas import Brief, Lead, Opportunity, Organisation, Stage

T = datetime(2026, 11, 1, tzinfo=UTC)
AS_OF = date(2026, 11, 4)


def opp(i: str) -> Opportunity:
    return Opportunity(id=f"grants_gov:SYN-{i}", source="grants_gov", fetched_at=T,
                       source_url="https://www.grants.gov/x", opportunity_number=f"SYN-{i}",
                       title=f"SYNTHETIC Program {i}", agency="NIH", activity_code="R01",
                       close_date=date(2026, 12, 1), status="posted",
                       funding_instruments=["Grant"])


A1, A2 = opp("1"), opp("2")
ORG = Organisation(id="org:1", source="openalex", fetched_at=T, source_url="https://x.invalid",
                   name="SYNTHETIC Quillfen Labs")


def lead(rid: str, rank: int, route: str = "A") -> Lead:
    return Lead(id=f"b:{rank}{route}", source="grants_gov", source_url="u", fetched_at=T,
                brief_id="b", route=route, record_id=rid, rank=rank, status="kept")


class Repo:
    def get(self, cls, i):
        return {A1.id: A1, A2.id: A2, ORG.id: ORG}.get(i)


def brief(status: str | None) -> Brief:
    stages = [Stage(name="explanations", status=status)] if status else []
    return Brief(id="b", source="perch", source_url="perch://b", fetched_at=T,
                 researcher_id="A1", options={"as_of": AS_OF.isoformat()}, stages=stages)


def test_no_written_reason_once_the_explanation_stage_is_over():
    from perch.compare import compare

    leads = [lead(A1.id, 1)]
    for status, want in (("done", "no written reason"), ("skipped", "no written reason"),
                         ("running", "no explanation yet")):
        (row,) = compare(brief(status), leads, Repo())
        assert row.cells["evidence"].note == want, status


def test_the_instrument_row_is_left_out_when_every_column_is_a_grant():
    from perch.compare import compare, rows_json

    grants = rows_json(compare(brief("done"), [lead(A1.id, 1), lead(A2.id, 2)], Repo()))
    assert "kind" not in [c["key"] for c in grants["columns"]]
    mixed = rows_json(compare(brief("done"), [lead(A1.id, 1), lead(ORG.id, 1, "B")], Repo()))
    assert "kind" in [c["key"] for c in mixed["columns"]]

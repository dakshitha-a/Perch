"""S51 H7: centre and programme grants (P30, P01, P50, U54) get their own group on route A.
Rank, Match and the explanation stay as they were; every reader of the main list keeps them.
SYNTHETIC records; fake models; no network."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, date, datetime

from perch.schemas import Brief, Lead, Opportunity

T = datetime(2026, 11, 1, tzinfo=UTC)
AS_OF = date(2026, 11, 4)
NOTE = ("Centre or programme grant (activity code P30). An institution applies for these "
        "for a centre or a group of projects, so Perch lists them below the single-lab grants.")


def opp(i: str, code: str | None) -> Opportunity:
    return Opportunity(id=f"grants_gov:SYN-{i}", source="grants_gov", fetched_at=T,
                       source_url="https://www.grants.gov/x", opportunity_number=f"SYN-{i}",
                       title=f"SYNTHETIC Program {i}", agency="NIH", activity_code=code,
                       close_date=date(2026, 12, 1), status="posted")


def lead(o: Opportunity, rank: int, group: str | None = None) -> Lead:
    return Lead(id=f"b:{rank}{group or ''}", source="grants_gov", source_url="u", fetched_at=T,
                brief_id="b", route="A", record_id=o.id, rank=rank, match_score=80,
                group=group)


def test_the_centre_codes_are_exactly_the_four_in_the_spec():
    from perch.eligibility import CENTRE_CODES, centre_note

    assert frozenset({"P30", "P01", "P50", "U54"}) == CENTRE_CODES
    assert centre_note(opp("1", "P30")) == NOTE
    assert centre_note(opp("2", "R01")) is None
    assert centre_note(opp("3", None)) is None


def test_a_centre_lead_gets_the_group_and_the_note_and_keeps_its_rank_and_explanation(
        tmp_path, monkeypatch):
    from tests.test_api import make

    c, svc = make(tmp_path)
    r = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28"})
    plain = c.get(f"/briefs/{r.json()['id']}").json()["leads"][0]
    code = plain["opportunity"]["activity_code"]
    assert "group" not in plain or plain["group"] is None  # its own code is not a centre one

    monkeypatch.setattr("perch.eligibility.CENTRE_CODES", frozenset({code}))
    c2, _ = make(tmp_path / "b")
    r2 = c2.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28"})
    got = c2.get(f"/briefs/{r2.json()['id']}").json()["leads"][0]
    assert got["group"] == "centre"
    assert got["notes"][-1].startswith(f"Centre or programme grant (activity code {code}).")
    assert got["rank"] == plain["rank"] and got["match_score"] == plain["match_score"]
    # the explanation stage still ran on it: the fake model returns nothing usable
    assert got["flagged"] is plain["flagged"] is True


def test_compare_keeps_centre_leads_with_the_grants_before_temple_internal():
    from perch.compare import compare

    a, p, t = opp("A", "R01"), opp("P", "P30"), opp("T", None)
    leads = [lead(t, 1, "temple_internal"), lead(p, 2, "centre"), lead(a, 1)]
    for x in leads:
        x.status = "kept"

    class Repo:
        def get(self, cls, i):
            return {a.id: a, p.id: p, t.id: t}.get(i)

    b = Brief(id="b", source="perch", source_url="perch://b", fetched_at=T, researcher_id="A1",
              options={"as_of": AS_OF.isoformat()})
    rows = compare(b, leads, Repo())
    assert [r.record_id for r in rows] == [a.id, p.id, t.id]


def test_the_export_lists_centre_leads_among_the_grants():
    from perch.export import brief_blocks

    a, p = opp("A", "R01"), opp("P", "P30")
    b = Brief(id="b", source="perch", source_url="perch://b", fetched_at=T, researcher_id="A1",
              options={"as_of": AS_OF.isoformat()})
    blocks = brief_blocks(b, [lead(a, 1), lead(p, 2, "centre")], opps={a.id: a, p.id: p})
    heads = [x.text for x in blocks if x.kind in ("h2", "h3")]
    assert "Grants (2)" in heads


def test_scout_reads_centre_leads_with_the_ranked_leads():
    from perch.scout.read_tools import ReadTools, ScoutData

    a, p = opp("A", "R01"), opp("P", "P30")
    x = lead(p, 2, "centre")
    x.notes = [NOTE]

    class Repo:
        def get_any(self, i):
            return {a.id: a, p.id: p}.get(i)

    b = Brief(id="b", source="perch", source_url="perch://b", fetched_at=T, researcher_id="A1")
    t = ReadTools(ScoutData(repo=lambda: nullcontext(Repo()), as_of=AS_OF,
                            brief=lambda: (b, [lead(a, 1), x])))
    out = t.read_brief()
    assert [r["id"] for r in out["leads"]] == [a.id, p.id]
    assert out["leads"][1]["notes"] == [NOTE]

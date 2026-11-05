"""S51 student items: name-only listings get no model call (H4); entry labels (H9).
SYNTHETIC records; fake models; no network, no database server."""

from __future__ import annotations

from datetime import UTC, datetime

from perch.schemas import Brief, Lead, Scholarship

T = datetime(2026, 11, 1, tzinfo=UTC)
NAME_ONLY = "This listing gives only the award’s name. Read its page for what it funds."


def sch(i: str, **kw) -> Scholarship:
    base = dict(id=f"temple_pages:{i}", source="temple_pages", fetched_at=T,
                source_url=f"https://example.temple.edu/{i}", name=f"SYNTHETIC Quillfen {i}")
    return Scholarship(**(base | kw))


def test_a_name_only_listing_makes_no_model_call_and_gets_the_note(tmp_path, monkeypatch):
    from perch.skills.fit import Fit
    from perch.validate import Validated
    from tests.test_api import make

    _, svc = make(tmp_path)
    bare = sch("bare")
    canary = sch("can", purpose="SYNTHETIC sample record, canary CANARY-0000")
    full = sch("full", purpose="Supports SYNTHETIC research in marsh ecology.")
    field = sch("field", field_of_study=["Biology"])
    recs = [bare, canary, full, field]
    leads = [Lead(id=f"b:{i}", source="temple_pages", source_url="u", fetched_at=T,
                  brief_id="b", route="F", record_id=s.id, rank=i)
             for i, s in enumerate(recs, 1)]
    with svc.repo() as r:
        r.upsert([*recs, *leads])
    b = Brief(id="b", source="perch", source_url="perch://b", fetched_at=T, researcher_id="x",
              options={"explain": True}, lead_ids=[x.id for x in leads])
    svc._ctx[b.id] = {"achieved": [], "profile": None}
    asked: list[str] = []

    def explain(opps, profile, works, provider, grounder=None, on_result=None, audience=""):
        asked.extend(o.id for o in opps)
        out = []
        for i, _ in enumerate(opps):
            v = Validated(Fit(None, "S.", [], "", [], ""), 1, False, [])
            on_result(i, v)
            out.append(v)
        return out

    monkeypatch.setattr("perch.service.explain_leads", explain)
    detail, skipped = svc._run_student_explanations(b)
    assert sorted(asked) == sorted([full.id, field.id])  # the two name-only ones: no call
    assert detail == "2 explained, 0 withheld, 2 name only" and not skipped
    with svc.repo() as r:
        got = {x.record_id: x for x in (r.get(Lead, i) for i in b.lead_ids)}
    for s in (bare, canary):
        assert got[s.id].notes[-1] == NAME_ONLY
        assert got[s.id].explanation is None and got[s.id].inference is None
    assert NAME_ONLY not in got[full.id].notes and got[full.id].explanation

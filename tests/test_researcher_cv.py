"""The researcher brief with the user's own documents and CV (S42: moved from the private
session into BriefService). SYNTHETIC persona-1 text; fake models; no database: the inputs come
from a MemoryBriefStore set with `using_store`, as the worker sets the account's store."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from perch.user.briefs import MemoryBriefStore, using_store
from perch.user.cv import parse_cv
from perch.user.inputs import make_doc
from tests.test_api import make

PERSONA = Path(__file__).resolve().parent.parent / "data/synthetic/persona-1"
AS_OF = date(2026, 10, 28)


def run(svc, store, **opts):
    with using_store(store):
        b = svc.create("A5026494099", as_of=AS_OF, brief_id="r1", **opts)
        assert svc.run(b.id) == "done", store.view()[0].error
        return store.view()


def test_documents_take_their_share_beside_the_public_threads(tmp_path):
    """Q13, Q21: the added threads take 0.6 of the weight, proposal and manuscript split it
    0.5 : 0.2, and the public threads keep the other 0.4."""
    _, svc = make(tmp_path)
    store = MemoryBriefStore(docs=[
        make_doc("proposal", (PERSONA / "specific_aims_draft.md").read_text()),
        make_doc("manuscript", (PERSONA / "unpublished_manuscript.md").read_text())])
    b, _ = run(svc, store, explain=False)
    mine = [t["weight"] for t in b.threads if str(t["work_ids"][0]).startswith("user:")]
    public = [t["weight"] for t in b.threads if not str(t["work_ids"][0]).startswith("user:")]
    assert public and len(mine) == 2
    assert abs(sum(mine) - 0.6) < 1e-3 and abs(sum(public) - 0.4) < 1e-3
    assert abs(mine[0] / mine[1] - 0.5 / 0.2) < 1e-2  # proposal : manuscript
    # nothing the user wrote reached the public store
    with svc.repo() as r:
        assert not any(w.source == "user" for w in r.works_by_author(b.researcher_id))


def test_a_cv_unlocks_early_stage_leads_and_moves_a_past_sponsor_up(tmp_path, monkeypatch):
    """The CV's degree year makes the researcher an early-stage investigator, so a lead
    restricted by career stage is kept and says why; a sponsor the CV lists moves up."""
    cv = (PERSONA / "cv.md").read_text() + "\n## Funding\n- NIH K23 AG000000, 2023 to 2028\n"
    facts = parse_cv(cv)
    assert facts.esi_possible(AS_OF) and facts.sponsors
    _, svc = make(tmp_path)
    monkeypatch.setattr("perch.service.career_stage_restricted", lambda o: True)
    with_cv = run(svc, MemoryBriefStore(cv=cv), explain=False)
    notes = [n for x in with_cv[1] for n in x.notes]
    assert any("early-stage investigator per your CV" in n for n in notes), notes
    assert all("(private)" not in n for n in notes)
    # the same brief without a CV carries no CV note
    _, svc2 = make(tmp_path / "b")
    without = run(svc2, MemoryBriefStore(), explain=False)
    assert not any("your CV" in n for x in without[1] for n in x.notes)
    # a past sponsor's programme moves up and says so
    sponsor = facts.sponsors[0]
    _, svc3 = make(tmp_path / "c")
    spons = run(svc3, MemoryBriefStore(cv=cv), explain=False)
    assert any(f"past award from {sponsor}" in n for x in spons[1] for n in x.notes)


def test_two_attempts_of_one_brief_do_not_share_their_run_state(tmp_path):
    """S50 C20 (B22): the profile lived in a dict keyed by brief id. When a lost lease let a
    second attempt run beside the first, whichever finished first removed the entry and the
    other failed with a KeyError. Each run now has its own state."""
    import threading

    _, svc = make(tmp_path)
    b = svc.create("A5026494099", as_of=AS_OF, brief_id="twin")
    real = svc._run_route_a
    inside, go = threading.Event(), threading.Event()

    def slow_route_a(brief):
        if threading.current_thread().name == "first-attempt":
            inside.set()
            go.wait(30)
        return real(brief)

    svc._run_route_a = slow_route_a
    out = {}
    first = threading.Thread(target=lambda: out.update(first=svc.run(b.id)),
                             name="first-attempt")
    first.start()
    assert inside.wait(30)
    out["second"] = svc.run(b.id)  # the second attempt runs to the end meanwhile
    go.set()
    first.join(60)
    assert out == {"first": "done", "second": "done"}

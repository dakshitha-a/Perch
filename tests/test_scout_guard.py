"""S49 Q1: every sentence in Scout's guard set is removed, whatever Q49 loosens. SYNTHETIC."""

from __future__ import annotations

from bench.scout_guard import CASES, leaks


def test_the_guard_set_is_big_enough():
    assert len(CASES) >= 15


def test_no_guard_sentence_leaks():
    assert leaks() == []


def _grade(text):
    from bench import scout_guard as sg
    from perch.scout import answer as ans

    t = sg.tools()
    return ans.grade(text, t.seen, ans.name_index([sg.OPP, sg.OPP2, sg.SMP]), sg.AS_OF, None, t)


def test_q4_to_q11_shapes_now_pass():
    """Each shape the s45g replay removed and Q49 allows. All SYNTHETIC."""
    from bench.scout_guard import C1, C2

    ok = [
        f"What the record asks for\n- It closes 17 Nov 2026 {C1}.",  # Q4: no colon
        f"**1. SYNTHETIC Kidney Repair Program**\n- It closes 17 Nov 2026 {C1}.",  # Q5
        f"**1. SYNTHETIC Kidney Repair Program** {C1}",  # Q5: the number is a list mark
        "Perch does not confirm personal eligibility, so check with the sponsor or a Temple "
        "office.",  # Q6
        f"## Differences\n- It closes 17 Nov 2026 {C1}.",  # Q9
        "Would you like me to read the SYNTHETIC Marsh Ecology Program record in full?",  # Q10
        "Or should I compare either record with your CV?",  # Q10
        "You have no entries to add context [user:entries].",  # Q11
        f"Rank 1 is the SYNTHETIC Kidney Repair Program {C1}.",  # Q7: the brief's own rank
        f"It closes 17 Nov 2026 {C1}. It supports kidney repair research.",  # Q3
        f"The SYNTHETIC Kidney Repair Program closes 17 Nov 2026 {C1}.\nIts sponsor is the "
        "National Institutes of Health.",  # Q3: from the prose line above
        "Your brief has 2 leads [user:brief].",  # Q2: the brief as a record
    ]
    for text in ok:
        g = _grade(text)
        assert g.ok, (text, g.removed(detail=True))
    long = ("SYNTHETIC Kidney Repair Program For Very Long Titles That Run On Past The Usual "
            "Word Limit Of A Heading")
    from bench import scout_guard as sg
    from perch.scout import answer as ans

    opp = sg.OPP.model_copy(update={"title": long})
    t = sg.tools()
    t.seen[opp.id] = opp
    g = ans.grade(f"**{long}**\n- It closes 17 Nov 2026 {C1}.", t.seen, set(), sg.AS_OF, None, t)
    assert g.ok, g.removed(detail=True)  # Q5: a bold record title of any length
    assert not _grade(f"**{long}**\n- It closes 9 Dec 2026 {C2}.").ok  # not the cited record


def test_replay_regrades_a_stored_draft_with_no_model(tmp_path):
    """Q0: the replay rebuilds `seen` from the brief and the cited ids, then re-grades."""
    import json

    from bench.scout_guard import OPP, OPP2
    from bench.scout_replay import replay, summary

    good = f"The SYNTHETIC Kidney Repair Program closes 17 Nov 2026 [{OPP.id}]."
    bad = "It pays $9."
    rows = [{"id": "i05", "kind": "lookup", "attempt": 1, "shown": True, "draft": good + " " + bad,
             "removed": [{"part": "grounded", "sentence_index": 1, "reason": "no_citation"}]}]
    (tmp_path / "drafts.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    from datetime import date

    t = replay(tmp_path, [OPP, OPP2], date(2026, 11, 4))
    s = summary(t)
    assert s["removed_rows"] == 1 and s["drafts_differing_from_stored"] == 0
    assert s["reasons"] == {"layer1_number": 1} and s["guard_leaks"] == 0  # Q3: inherited


def test_q15_bench_reads_a_stored_brief_and_spreads_the_shortlist(tmp_path):
    import json
    from datetime import date

    from bench.scout_guard import OPP, OPP2, T
    from bench.scout_open import load_brief, shortlist
    from bench.scout_replay import MemRepo, _Service
    from perch.schemas import Brief, Lead

    b = Brief(id="b", source="perch", source_url="perch://b", fetched_at=T, researcher_id="A1")
    lead = Lead(id="b:1", source="grants_gov", source_url="u", fetched_at=T, brief_id="b",
                route="A", record_id=OPP.id, rank=1)
    doc = {"brief": b.model_dump(mode="json"),  # the shape of GET /briefs/{id}
           "leads": [lead.model_dump(mode="json") | {"opportunity": OPP.model_dump(mode="json")}]}
    (tmp_path / "b.json").write_text(json.dumps(doc))
    got_b, got_leads = load_brief(tmp_path / "b.json")
    assert got_b.id == "b" and [x.record_id for x in got_leads] == [OPP.id]
    same = OPP.model_copy(update={"id": "grants_gov:SYN-GUARD-3"})
    svc = _Service(MemRepo([OPP, same, OPP2]))
    _, leads = shortlist(svc, "researcher", date(2026, 11, 4), spread=True)
    assert len(leads) == 2  # one record per close date
    assert len(shortlist(svc, "researcher", date(2026, 11, 4), spread=False)[1]) == 3

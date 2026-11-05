"""S49 Q1: every sentence in Scout's guard set is removed, whatever Q49 loosens. SYNTHETIC."""

from __future__ import annotations

from bench.scout_guard import CASES, leaks


def test_the_guard_set_is_big_enough():
    assert len(CASES) >= 15


def test_no_guard_sentence_leaks():
    assert leaks() == []


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
    assert s["reasons"] == {"no_citation": 1} and s["guard_leaks"] == 0

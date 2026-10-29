from datetime import date

import numpy as np

from perch.profile import Profile, Thread
from perch.rerank import FakeReranker, RerankCache, rerank
from perch.retrieve import Candidate

from .test_retrieve import opp


def profile():
    t = Thread(0, np.zeros(4), ["W1"], 1.0, "kidney, donor", ["SYNTHETIC living kidney donor"])
    return Profile("A", date(2026, 1, 1), "fake", [t], ["W1"])


def test_rerank_orders_by_score_caches_and_cuts(tmp_path):
    opps = {o.id: o for o in [opp("PA-1", "astronomy telescope"),
                              opp("PA-2", "living kidney donor research"),
                              opp("PA-3", "kidney disease")]}
    cands = [Candidate(i, 1.0, 0) for i in opps]  # retrieval order PA-1, PA-2, PA-3
    cache = RerankCache(tmp_path / "r.db")
    ranked, hits = rerank(cands, opps, profile(), FakeReranker(), cache, top=2)
    assert [r.opportunity.opportunity_number for r in ranked] == ["PA-2", "PA-3"]
    assert hits == 0
    again, hits = rerank(cands, opps, profile(), FakeReranker(), cache, top=2)
    assert hits == 3 and [r.rerank_score for r in again] == [r.rerank_score for r in ranked]

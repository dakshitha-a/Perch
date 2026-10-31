from datetime import UTC, date, datetime

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


def test_query_carries_thread_topics_and_cache_key_carries_query_version():
    from perch.profile import thread_topics
    from perch.retrieve import QUERY_VERSION, thread_query
    from perch.schemas import Topic, Work

    def work(i, topic):
        return Work(id=f"W{i}", source="openalex", source_url="https://openalex.org/W1",
                    fetched_at=datetime(2026, 10, 30, tzinfo=UTC), title=f"SYNTHETIC {i}",
                    topics=[Topic(id="T", display_name=topic)])

    ws = [work(1, "Quantum Chemistry"), work(2, "Quantum Chemistry"), work(3, "Photonics")]
    assert thread_topics(ws) == ["Quantum Chemistry", "Photonics"]
    t = Thread(0, np.zeros(2), ["W1"], 1.0, "excited, states", ["SYNTHETIC title"],
               ["Quantum Chemistry"])
    assert thread_query(t) == "Quantum Chemistry excited  states SYNTHETIC title"
    p = Profile("A1", date(2026, 10, 30), "fake", [t], ["W1"])
    cache = RerankCache(":memory:")
    rerank([Candidate("grants_gov:X", 1.0, 0)], {"grants_gov:X": opp("X", "Quantum")}, p,
           FakeReranker(), cache)
    # P6: keyed by the thread's query (with its version), not by the whole profile
    from perch.rerank import thread_key

    assert thread_key(t).endswith(f":{QUERY_VERSION}")
    assert cache.get("fake-overlap", thread_key(t), "grants_gov:X") is not None
    assert cache.get("fake-overlap", f"{p.hash}:{QUERY_VERSION}", "grants_gov:X") is None
    # a thread the caller marks uncacheable (from documents) is neither read nor written
    cache2 = RerankCache(":memory:")
    rerank([Candidate("grants_gov:X", 1.0, 0)], {"grants_gov:X": opp("X", "Quantum")}, p,
           FakeReranker(), cache2, cacheable=lambda t: False)
    assert cache2.get("fake-overlap", thread_key(t), "grants_gov:X") is None

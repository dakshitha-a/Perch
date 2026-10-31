"""Route A brief, deterministic: threads, retrieval, eligibility, rerank. No model output.

Pipeline: research threads, then hybrid retrieval (top 200), then the eligibility
filter, then the 100 best eligible go to the reranker, which keeps 10. Every stage
is timed; timings are appended to data/logs/brief_timings.jsonl.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from perch.eligibility import Constraints, split
from perch.embed import Embedder
from perch.profile import Profile, Thread, build_threads
from perch.rerank import Ranked, RerankCache, Reranker, rerank
from perch.retrieve import index_opportunities, retrieve
from perch.schemas import Opportunity, Researcher
from perch.store.base import Repository, VectorIndex

RETRIEVE_K = 200
RERANK_IN = 100  # 50 until S27; 100 with topic queries raised back-test MRR 0.067 to 0.149
TIMINGS_LOG = Path("data/logs/brief_timings.jsonl")


@dataclass
class RouteABrief:
    researcher: Researcher
    profile: Profile
    leads: list[Ranked]
    retrieved: int
    rejected: dict[str, list[str]]
    timings_ms: dict[str, float] = field(default_factory=dict)
    rerank_cache_hits: int = 0


def route_a(researcher: Researcher, repo: Repository, index: VectorIndex, embedder: Embedder,
            reranker: Reranker, constraints: Constraints | None = None,
            cache: RerankCache | None = None, top: int = 10,
            timings_log: Path | None = TIMINGS_LOG, profile: Profile | None = None,
            index_new: bool = True,
            cacheable: Callable[[Thread], bool] = lambda t: True) -> RouteABrief:
    """`profile` replaces the threads built from the stored works (added threads);
    `index_new=False` skips indexing, so a private session writes nothing."""
    c = constraints or Constraints(as_of=date.today())
    t: dict[str, float] = {}

    def lap(name: str, start: float) -> float:
        now = time.perf_counter()
        t[name] = round((now - start) * 1000, 1)
        return now

    s = time.perf_counter()
    profile = profile or build_threads(researcher.id, repo.works_by_author(researcher.id),
                                       embedder, c.as_of)
    s = lap("threads", s)
    if index_new:
        index_opportunities(repo, index, embedder)
    s = lap("index", s)
    r = retrieve(profile, index, k=RETRIEVE_K)
    t.update({f"retrieve_{k}": v for k, v in r.timings_ms.items()})
    s = lap("retrieve", s)
    opps = {o.id: o for o in (repo.get(Opportunity, x.record_id) for x in r.candidates) if o}
    eligible, rejected = split([opps[x.record_id] for x in r.candidates if x.record_id in opps], c)
    ok = {o.id for o in eligible}
    pool = [x for x in r.candidates if x.record_id in ok][:RERANK_IN]
    s = lap("eligibility", s)
    leads, hits = rerank(pool, opps, profile, reranker, cache, top=top, cacheable=cacheable)
    lap("rerank", s)
    t["total"] = round(sum(v for k, v in t.items() if not k.startswith("retrieve_")), 1)
    brief = RouteABrief(researcher, profile, leads, len(r.candidates), rejected, t, hits)
    if timings_log:
        timings_log.parent.mkdir(parents=True, exist_ok=True)
        with timings_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now(UTC).isoformat(), "researcher": researcher.id,
                                "as_of": c.as_of.isoformat(), "embedder": embedder.name,
                                "reranker": reranker.name, "candidates": len(r.candidates),
                                "eligible": len(eligible), "rerank_cache_hits": hits,
                                "timings_ms": t}) + "\n")
    return brief

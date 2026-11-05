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

import numpy as np

from perch import profiles
from perch.eligibility import TEMPLE_INTERNAL_SOURCE, Constraints, check_temple_internal, split
from perch.embed import Embedder, normalise
from perch.profile import Profile, Thread, build_threads
from perch.rerank import Ranked, RerankCache, Reranker, rerank
from perch.retrieve import Candidate, index_opportunities, opportunity_text, retrieve
from perch.schemas import Opportunity, Researcher
from perch.store.base import Repository, VectorIndex

RETRIEVE_K = 200
RERANK_IN = 100  # 50 until S27; 100 with topic queries raised back-test MRR 0.067 to 0.149
TEMPLE_TOP = 3  # Temple internal leads shown in their own group (S49 M9)
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
    # Temple internal funding (S49 M9): its own group, never in `leads`. None when not run
    # (a brief from the nightly pre-cache); the caller then runs `temple_internal`.
    temple: list[Ranked] | None = None
    temple_notes: dict[str, list[str]] = field(default_factory=dict)  # id -> code notes


def temple_records(repo: Repository) -> list[Opportunity]:
    """The Temple internal funding pages in the store."""
    try:
        items = repo.browse(Opportunity, temple_only=True, limit=500).items
    except (AttributeError, NotImplementedError):
        items = repo.list(Opportunity)
    return [o for o in items if o.source == TEMPLE_INTERNAL_SOURCE]


def temple_internal(profile: Profile, repo: Repository, embedder: Embedder, reranker: Reranker,
                    c: Constraints, cache: RerankCache | None = None, top: int = TEMPLE_TOP,
                    cacheable: Callable[[Thread], bool] = lambda t: True
                    ) -> tuple[list[Ranked], dict[str, list[str]]]:
    """The best `top` Temple internal opportunities for this profile, by their own rules
    (eligibility.check_temple_internal) and the same reranker as the federal leads. Every
    page that passes is scored, so the group does not depend on the federal retrieval: each
    record goes to the thread its embedding is nearest, then the reranker scores it there."""
    opps = {}
    notes: dict[str, list[str]] = {}
    for o in temple_records(repo):
        why, n = check_temple_internal(o, c)
        if not why:
            opps[o.id] = o
            if n:
                notes[o.id] = n
    if not opps or not profile.threads:
        return [], {}
    ids = list(opps)
    docs = normalise(np.asarray(embedder.embed_documents([opportunity_text(opps[i])
                                                          for i in ids])))
    tv = np.stack([t.vector for t in profile.threads])
    sims = docs @ tv.T
    cands = [Candidate(i, float(sims[k].max()), profile.threads[int(sims[k].argmax())].index)
             for k, i in enumerate(ids)]
    cands.sort(key=lambda x: (-x.score, x.record_id))
    ranked, _ = rerank(cands, opps, profile, reranker, cache, top=top, cacheable=cacheable)
    return ranked, {x.opportunity.id: notes[x.opportunity.id] for x in ranked
                    if x.opportunity.id in notes}


def route_a(researcher: Researcher, repo: Repository, index: VectorIndex, embedder: Embedder,
            reranker: Reranker, constraints: Constraints | None = None,
            cache: RerankCache | None = None, top: int = 10,
            timings_log: Path | None = TIMINGS_LOG, profile: Profile | None = None,
            index_new: bool = True,
            cacheable: Callable[[Thread], bool] = lambda t: True,
            rerank_in: int = RERANK_IN) -> RouteABrief:
    """`profile` replaces the threads built from the stored works (added threads);
    `index_new=False` skips indexing, so a brief that reads user text writes nothing public."""
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
    r = retrieve(profile, index, k=RETRIEVE_K, mode=profiles.current().retrieval)
    t.update({f"retrieve_{k}": v for k, v in r.timings_ms.items()})
    s = lap("retrieve", s)
    # Temple internal pages are left out here: they have their own group (S49 M9).
    opps = {o.id: o for o in (repo.get(Opportunity, x.record_id) for x in r.candidates)
            if o and o.source != TEMPLE_INTERNAL_SOURCE}
    eligible, rejected = split([opps[x.record_id] for x in r.candidates if x.record_id in opps], c)
    ok = {o.id for o in eligible}
    pool = [x for x in r.candidates if x.record_id in ok][:rerank_in]
    s = lap("eligibility", s)
    leads, hits = rerank(pool, opps, profile, reranker, cache, top=top, cacheable=cacheable)
    s = lap("rerank", s)
    temple, temple_notes = temple_internal(profile, repo, embedder, reranker, c, cache,
                                           cacheable=cacheable)
    lap("temple_internal", s)
    t["total"] = round(sum(v for k, v in t.items() if not k.startswith("retrieve_")), 1)
    brief = RouteABrief(researcher, profile, leads, len(r.candidates), rejected, t, hits,
                        temple, temple_notes)
    if timings_log:
        timings_log.parent.mkdir(parents=True, exist_ok=True)
        with timings_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now(UTC).isoformat(), "researcher": researcher.id,
                                "as_of": c.as_of.isoformat(), "embedder": embedder.name,
                                "reranker": reranker.name, "candidates": len(r.candidates),
                                "eligible": len(eligible), "rerank_cache_hits": hits,
                                "timings_ms": t}) + "\n")
    return brief

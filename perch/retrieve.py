"""Route A retrieval: per-thread hybrid search (dense + BM25) fused with RRF.

Deterministic given the index, the embedder and the profile. Each thread runs a
dense search with its vector and a BM25 search with its label terms and top paper
titles; the two lists are fused with reciprocal rank fusion (k=60). Threads are
merged by RRF weighted by each thread's share of the profile. `mode` keeps one
list only ("dense" or "bm25"); the back-test uses it for the bench matrix and the
keyword-only baseline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from perch.embed import Embedder
from perch.profile import Profile, Thread
from perch.schemas import Opportunity
from perch.store.base import Repository, VectorIndex

RRF_K = 60
PER_LIST = 100
TOP_K = 50
DOC_CHARS = 4000


def opportunity_text(o: Opportunity) -> str:
    parts = [o.title, o.activity_code or "", o.description or ""]
    return " ".join(p for p in parts if p)[:DOC_CHARS]


def index_opportunities(repo: Repository, index: VectorIndex, embedder: Embedder) -> int:
    """Embed and index every stored opportunity (cached by content hash)."""
    opps = repo.list(Opportunity)
    texts = [opportunity_text(o) for o in opps]
    vecs = embedder.embed_documents(texts)
    return index.upsert([o.id for o in opps], texts, vecs.tolist())


# Bumped when thread_query changes, so cached rerank scores for the old query are not reused.
QUERY_VERSION = "topics-1"


def thread_query(t: Thread) -> str:
    """Topic names, label terms and top titles. Topics added in S27: on the NIH back-test
    they raised MRR from 0.067 to 0.109 alone, and to 0.149 with 100 candidates reranked."""
    return " ".join([*t.topics, t.label.replace(",", " "), *t.titles])


@dataclass
class Candidate:
    record_id: str
    score: float
    best_thread: int
    ranks: dict[str, int] = field(default_factory=dict)  # e.g. {"t0.dense": 3, "t0.bm25": 12}


@dataclass
class Retrieval:
    candidates: list[Candidate]
    timings_ms: dict[str, float]


def rrf(ranked: list[str]) -> dict[str, float]:
    return {rid: 1.0 / (RRF_K + r) for r, rid in enumerate(ranked, start=1)}


MODES = ("hybrid", "dense", "bm25")


def retrieve(profile: Profile, index: VectorIndex, k: int = TOP_K,
             per_list: int = PER_LIST, mode: str = "hybrid") -> Retrieval:
    if mode not in MODES:
        raise ValueError(f"retrieval mode must be one of {MODES}: {mode!r}")
    timings: dict[str, float] = {"dense": 0.0, "bm25": 0.0}
    total: dict[str, float] = {}
    best: dict[str, tuple[float, int]] = {}
    ranks: dict[str, dict[str, int]] = {}
    for t in profile.threads:
        t0 = time.perf_counter()
        dense = ([rid for rid, _ in index.dense(t.vector.tolist(), per_list)]
                 if mode != "bm25" else [])
        t1 = time.perf_counter()
        sparse = ([rid for rid, _ in index.bm25(thread_query(t), per_list)]
                  if mode != "dense" else [])
        t2 = time.perf_counter()
        timings["dense"] += (t1 - t0) * 1000
        timings["bm25"] += (t2 - t1) * 1000
        fused: dict[str, float] = {}
        for name, lst in (("dense", dense), ("bm25", sparse)):
            for rid, s in rrf(lst).items():
                fused[rid] = fused.get(rid, 0.0) + s
            for r, rid in enumerate(lst, start=1):
                ranks.setdefault(rid, {})[f"t{t.index}.{name}"] = r
        for rid, s in fused.items():
            total[rid] = total.get(rid, 0.0) + t.weight * s
            if rid not in best or s > best[rid][0]:
                best[rid] = (s, t.index)
    order = sorted(total, key=lambda rid: (-total[rid], rid))[:k]
    cands = [Candidate(rid, total[rid], best[rid][1], ranks[rid]) for rid in order]
    timings["total"] = timings["dense"] + timings["bm25"]
    return Retrieval(cands, {k_: round(v, 1) for k_, v in timings.items()})

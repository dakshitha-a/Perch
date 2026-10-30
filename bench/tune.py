"""Route A tuning harness (S27): score ranking variants on the NIH back-test.

Each variant changes one knob of the production ranking and is scored on the same
rows as bench/backtest.py (papers before the award start, pool open in the window).
Knobs:
  - query:   "label" (production: thread label + top titles) or "topics" (adds the
             thread's most common OpenAlex topic names), for BM25 and the reranker
  - fuse:    weight of the reranker score in the final order; 1.0 is production
             (rerank alone), lower values blend in the retrieval score (RRF, scaled
             to the row's best)
  - rerank_in, per_list: how many candidates reach the reranker, and list depth
Rerank scores are cached per (query kind, profile, record), so later rounds are fast.
The keyword-only baseline (BM25, no rerank) is reported with every round.

  uv run --extra ml python -m bench.tune --device cuda
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import perch.retrieve as R
from bench.backtest import (BENCH_DB, PIS, WINDOW_MONTHS, PoolIndex, coverage, in_window,
                            load_rows, slug, works_for)
from perch.config import env, load_dotenv
from perch.eligibility import Constraints, check
from perch.embed import get_embedder
from perch.profile import Profile, Thread, build_threads
from perch.rerank import DEFAULT_MODEL, CrossEncoderReranker, RerankCache
from perch.retrieve import opportunity_text, retrieve
from perch.schemas import Opportunity, Work
from perch.sources.openalex import OpenAlexClient
from perch.store.lance import LanceIndex
from perch.store.sqlite import SQLiteRepository

OUT = Path("bench/results/tune")
PRODUCTION_QUERY = R.thread_query


@dataclass(frozen=True)
class Variant:
    name: str
    query: str = "label"
    fuse: float = 1.0
    rerank_in: int = 50
    per_list: int = 100
    rerank: bool = True
    mode: str = "hybrid"


def topic_terms(t: Thread, works: dict[str, Work], n: int = 3) -> list[str]:
    c = Counter(tp.display_name for wid in t.work_ids for tp in works[wid].topics[:1]
                if wid in works)
    return [name for name, _ in c.most_common(n)]


def make_query(kind: str, works: dict[str, Work]):
    def q(t: Thread) -> str:
        base = " ".join([t.label.replace(",", " "), *t.titles])
        return base if kind == "label" else " ".join([*topic_terms(t, works), base])
    return q


def order_for(v: Variant, profile: Profile, works: dict[str, Work], index, opps, reranker,
              cache: RerankCache) -> list[str]:
    qf = make_query(v.query, works)
    R.thread_query = qf  # retrieve() builds its BM25 query through this name
    try:
        cands = retrieve(profile, index, k=200, per_list=v.per_list, mode=v.mode).candidates
    finally:
        R.thread_query = PRODUCTION_QUERY
    if not v.rerank or not cands:
        return [c.record_id for c in cands]
    head, tail = cands[: v.rerank_in], cands[v.rerank_in:]
    threads = {t.index: t for t in profile.threads}
    key = f"{reranker.name}|{v.query}"
    scores: dict[str, float] = {}
    todo: dict[int, list] = {}
    for c in head:
        s = cache.get(key, profile.hash, c.record_id)
        if s is None:
            todo.setdefault(c.best_thread, []).append(c)
        else:
            scores[c.record_id] = s
    for ti, group in todo.items():
        docs = [opportunity_text(opps[c.record_id])[:2000] for c in group]
        for c, s in zip(group, reranker.score(qf(threads[ti]), docs), strict=True):
            scores[c.record_id] = s
            cache.put(key, profile.hash, c.record_id, s)
    top = max(c.score for c in head)
    fused = {c.record_id: v.fuse * scores[c.record_id] + (1 - v.fuse) * c.score / top
             for c in head}
    pos = {c.record_id: i for i, c in enumerate(head)}
    ranked = sorted(fused, key=lambda r: (-fused[r], pos[r]))
    return ranked + [c.record_id for c in tail]


def metrics(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks) or 1
    return {"n": len(ranks),
            "hit@5": round(sum(bool(r and r <= 5) for r in ranks) / n, 3),
            "hit@10": round(sum(bool(r and r <= 10) for r in ranks) / n, 3),
            "mrr": round(sum(1 / r for r in ranks if r) / n, 3)}


def run(variants: list[Variant], device: str | None, strata=("targeted",)) -> dict:
    load_dotenv()
    rows = [r for r in load_rows(PIS) if r["stratum"] in strata]
    embedder = get_embedder("Qwen/Qwen3-Embedding-0.6B", cache=Path("data/cache/embeddings.db"),
                            device=device)
    reranker = CrossEncoderReranker(DEFAULT_MODEL, device=device)
    cache = RerankCache(Path("data/bench/cache/rerank_tune.db"))
    out: dict[str, list[int | None]] = {v.name: [] for v in variants}
    with SQLiteRepository(BENCH_DB) as repo, OpenAlexClient(env("OPENALEX_API_KEY")) as oa:
        opps = {o.id: o for o in repo.list(Opportunity)}
        cov = coverage(rows, {o.opportunity_number for o in opps.values()}, WINDOW_MONTHS)
        rows = [r for r in rows if cov[r["alias"] + r["stratum"]] >= 1.0]
        base = LanceIndex(Path("data/bench/lance") / slug(embedder.name))
        for r in rows:
            start = date.fromisoformat(r["award_start"])
            as_of = start - timedelta(days=1)
            wl = works_for(repo, r["openalex_id"], oa)
            works = {w.id: w for w in wl}
            profile = build_threads(f"https://openalex.org/{r['openalex_id']}", wl, embedder,
                                    as_of)
            pool = {i for i, o in opps.items()
                    if in_window(o.open_date, o.close_date, start, WINDOW_MONTHS)}
            c = Constraints(as_of=as_of, check_dates=False)
            index = PoolIndex(base, {i for i in pool if not check(opps[i], c)}, len(opps))
            truth = f"grants_gov:{r['opportunity_number']}"
            for v in variants:
                order = order_for(v, profile, works, index, opps, reranker, cache)
                out[v.name].append(order.index(truth) + 1 if truth in order else None)
    return {name: {**metrics(ranks), "ranks": ranks} for name, ranks in out.items()}


VARIANTS = {
    "keyword-only": Variant("keyword-only", mode="bm25", rerank=False),
    "R0 production": Variant("R0 production"),
    "R1 fuse 0.7": Variant("R1 fuse 0.7", fuse=0.7),
    "R1 fuse 0.5": Variant("R1 fuse 0.5", fuse=0.5),
    "R1 fuse 0.3": Variant("R1 fuse 0.3", fuse=0.3),
    "R2 topics": Variant("R2 topics", query="topics"),
    "R2 topics fuse 0.5": Variant("R2 topics fuse 0.5", query="topics", fuse=0.5),
    "R3 rerank 100": Variant("R3 rerank 100", rerank_in=100),
    "R3 per_list 200": Variant("R3 per_list 200", per_list=200),
    "R4 topics rerank 100": Variant("R4 topics rerank 100", query="topics", rerank_in=100),
    "R4 rerank 150": Variant("R4 rerank 150", rerank_in=150),
    "R4 topics rerank 150": Variant("R4 topics rerank 150", query="topics", rerank_in=150),
    "R4 topics rerank 200": Variant("R4 topics rerank 200", query="topics", rerank_in=200),
}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--device")
    ap.add_argument("--only", nargs="*", help="variant names (default: all)")
    ap.add_argument("--strata", nargs="*", default=["targeted"])
    a = ap.parse_args(argv)
    vs = [VARIANTS[n] for n in (a.only or VARIANTS)]
    t = time.perf_counter()
    res = run(vs, a.device, tuple(a.strata))
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M")
    (OUT / f"tune_{stamp}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    for name, m in res.items():
        print(f"{name:24s} n={m['n']} hit@5={m['hit@5']} hit@10={m['hit@10']} mrr={m['mrr']}")
    print(f"{time.perf_counter() - t:.0f} s")


if __name__ == "__main__":
    main()

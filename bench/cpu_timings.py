"""S38 task 2: CPU timings for the embedder, reranker and MiniCheck, on public data only.

Reads the migrated Postgres database (perch_dev), never writes. No GPU, no cloud call.

    CUDA_VISIBLE_DEVICES= PERCH_E2E_DSN=postgresql://.../perch_dev \
        uv run python bench/cpu_timings.py --run 1

Measures, per run:
  embed_query   one query embedding at a time, n=10 thread queries of real researchers
  rerank_50     `rerank()` over the top 50 eligible candidates of each researcher (one
                value per researcher, up to 5), no score cache
  rerank_100    the same with 100 candidates, the shipped RERANK_IN
  minicheck     MiniCheck on one (document, sentence) pair at a time, n=25, document
                text from public works and opportunities in the database
Appends rows to bench/results/s38_cpu/timings.csv and prints median and p95 per stage.
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import time
from datetime import date
from pathlib import Path

from perch.compute import configure_torch, usable_cores
from perch.eligibility import Constraints, split
from perch.grounding import MiniCheckGrounder, split_sentences
from perch.profile import build_threads
from perch.profiles import current
from perch.rerank import make_reranker, rerank
from perch.retrieve import retrieve, thread_query
from perch.schemas import Opportunity, Researcher
from perch.skills import opportunity_view, work_view
from perch.store.hybrid import HybridRepository
from perch.store.postgres import PgVectorIndex, make_pool

DSN = os.environ.get("PERCH_E2E_DSN", "postgresql://postgres:perchtest@127.0.0.1:55432/perch_dev")
OUT = Path("bench/results/s38_cpu/timings.csv")
FIELDS = ["run", "stage", "item", "n_in", "ms", "cores", "torch_threads", "load_before"]


def pct(vals: list[float], q: float) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--shrink-sweep", action="store_true",
                    help="also time rerank at 10, 20, 30, 40 candidates")
    ap.add_argument("--sizes", type=int, nargs="+", default=None,
                    help="rerank candidate counts to time instead of 50 and 100 (the fine "
                    "sweep for the shrink rule); embed and MiniCheck are skipped")
    args = ap.parse_args()
    threads = configure_torch()
    load_before = os.getloadavg()[0]
    prof = current()
    pool = make_pool(DSN)
    repo = HybridRepository(pool, "/tmp/perch-cpu-timings-scratch.db")
    index = PgVectorIndex(index_name="opportunities", embedder=prof.embedder, pool=pool)

    from perch.embed import get_embedder

    t = time.perf_counter()
    emb = get_embedder(prof.embedder, cache=None, device="cpu")
    print(f"embedder loaded in {time.perf_counter() - t:.1f}s")
    t = time.perf_counter()
    rr = make_reranker(prof.reranker, device="cpu")
    print(f"reranker loaded in {time.perf_counter() - t:.1f}s")
    t = time.perf_counter()
    mc = MiniCheckGrounder(device="cpu")
    print(f"minicheck loaded in {time.perf_counter() - t:.1f}s")

    rows: list[dict] = []

    def add(stage: str, item: str, n_in: int, ms: float) -> None:
        rows.append({"run": args.run, "stage": stage, "item": item, "n_in": n_in,
                     "ms": round(ms, 1), "cores": usable_cores(), "torch_threads": threads,
                     "load_before": round(load_before, 1)})

    as_of = date.today()
    cons = Constraints(as_of=as_of)
    researchers = sorted(repo.list(Researcher), key=lambda r: r.id)[:5]
    queries: list[str] = []
    pools: dict[str, tuple] = {}
    for r in researchers:
        works = repo.works_by_author(r.id)
        profile = build_threads(r.id, works, emb, as_of)
        queries += [thread_query(th) for th in profile.threads]
        ret = retrieve(profile, index, k=200)
        opps = {o.id: o for o in (repo.get(Opportunity, c.record_id) for c in ret.candidates) if o}
        eligible, _ = split([opps[c.record_id] for c in ret.candidates if c.record_id in opps],
                            cons)
        ok = {o.id for o in eligible}
        pools[r.id] = (profile, opps, [c for c in ret.candidates if c.record_id in ok])
    print(f"{len(researchers)} researchers, {len(queries)} thread queries")

    # query embed, n=20, one at a time (cycle if fewer)
    qs = [queries[i % len(queries)] for i in range(10)]
    emb.embed_queries([qs[0]])  # warm-up, not counted
    for i, q in enumerate(qs):
        s = time.perf_counter()
        emb.embed_queries([q])
        add("embed_query", str(i), 1, (time.perf_counter() - s) * 1000)

    # rerank
    first = next(iter(pools.values()))
    rerank(first[2][:4], first[1], first[0], rr, None, top=4)  # warm-up
    sizes = args.sizes or [50, 100] + ([10, 20, 30, 40] if args.shrink_sweep else [])
    for n in sizes:
        for rid, (profile, opps, cands) in pools.items():
            pool_n = cands[:n]
            s = time.perf_counter()
            rerank(pool_n, opps, profile, rr, None, top=10)
            add(f"rerank_{n}", rid.rsplit("/", 1)[-1], len(pool_n),
                (time.perf_counter() - s) * 1000)

    # MiniCheck: 50 (document, sentence) pairs from public works and opportunities
    pairs: list[tuple[str, str]] = []
    for r in researchers:
        for w in repo.works_by_author(r.id):
            sents = split_sentences(w.abstract or "")
            if len(sents) >= 2:
                pairs.append((work_view(w, abstract_chars=2000), sents[1]))
        if len(pairs) >= 15:
            break
    for _oid, (_, opps, _c) in list(pools.items()):
        for o in list(opps.values())[:3]:
            sents = split_sentences(o.description or "")
            if len(sents) >= 2:
                pairs.append((opportunity_view(o, description_chars=4000), sents[0]))
    pairs = pairs[:25]
    assert len(pairs) == 25, len(pairs)
    mc.support(pairs[0][0], [pairs[0][1]])  # warm-up
    for i, (d, c) in enumerate(pairs):
        s = time.perf_counter()
        mc.support(d, [c])
        add("minicheck", str(i), 1, (time.perf_counter() - s) * 1000)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    new = not OUT.exists()
    with OUT.open("a", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    load_after = os.getloadavg()[0]
    print(f"cores={usable_cores()} torch_threads={threads} load_before={load_before:.1f} "
          f"load_after={load_after:.1f}")
    for stage in dict.fromkeys(r["stage"] for r in rows):
        v = [r["ms"] for r in rows if r["stage"] == stage]
        print(f"run {args.run} {stage:12s} n={len(v):3d} median={statistics.median(v):9.1f} ms "
              f"p95={pct(v, 0.95):9.1f} ms")
    pool.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

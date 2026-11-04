"""S38 GPU timings for the embedder, reranker (0.6B and 4B) and MiniCheck, on public data only.

Reads the migrated Postgres database (perch_dev), never writes. Run it only through the limiter:

    PERCH_LIMIT_GPU=3 scripts/run_limited.sh .venv/bin/python bench/gpu_timings.py \
        --run 1 --reranker Qwen/Qwen3-Reranker-0.6B

Per run: embed, the chosen reranker and MiniCheck are all loaded together on the one GPU, so
VRAM is the combined footprint. Stages (rows go to bench/results/s38_gpu/timings.csv):
  embed_query    one query at a time, n=10
  rerank_<N>     `rerank()` over the top N eligible candidates of each researcher (N = 14, 50,
                 100; one value per researcher, up to 10), no score cache
  rerank_sat     saturated throughput: the rerank pairs of all researchers at 100 candidates
                 scored in one stream at batch sizes 2 to 64 (column pairs_per_s)
  minicheck_1    one (document, sentence) pair at a time, n=25, as the validator calls it
  minicheck_b    the same documents with 8 claims each, scored at forward batch 8 and 32
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import subprocess
import time
from datetime import date
from pathlib import Path

from perch.eligibility import Constraints, split
from perch.embed import get_embedder
from perch.grounding import MiniCheckGrounder, split_sentences
from perch.profile import build_threads
from perch.rerank import make_reranker, rerank
from perch.retrieve import opportunity_text, retrieve, thread_query
from perch.schemas import Opportunity, Researcher
from perch.skills import opportunity_view, work_view
from perch.store.hybrid import HybridRepository
from perch.store.postgres import PgVectorIndex, make_pool

DSN = os.environ.get("PERCH_E2E_DSN", "postgresql://postgres:perchtest@127.0.0.1:55432/perch_dev")
OUT = Path("bench/results/s38_gpu/timings.csv")
FIELDS = ["run", "reranker", "stage", "item", "n_in", "ms", "pairs_per_s", "batch", "extra"]
EMBEDDER = "Qwen/Qwen3-Embedding-0.6B"


def pct(vals: list[float], q: float) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def smi_used() -> int:
    """MiB used on the one GPU this job may see, from nvidia-smi (all processes on it)."""
    idx = os.environ.get("PERCH_LIMIT_GPU", "0")
    out = subprocess.run(["nvidia-smi", "-i", idx, "--query-gpu=memory.used",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True)
    return int(out.stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--reranker", default="Qwen/Qwen3-Reranker-0.6B")
    ap.add_argument("--researchers", type=int, default=10)
    args = ap.parse_args()
    import torch

    assert torch.cuda.is_available() and torch.cuda.device_count() == 1, "run via run_limited GPU"
    print("gpu:", torch.cuda.get_device_name(0), "| load:", os.getloadavg()[0])
    mib = 1024 * 1024
    rows: list[dict] = []
    rname = args.reranker.rsplit("/", 1)[-1]

    def add(stage: str, item: str, n_in: int, ms: float, pps: float | None = None,
            batch: int | None = None, extra: str = "") -> None:
        rows.append({"run": args.run, "reranker": rname, "stage": stage, "item": item,
                     "n_in": n_in, "ms": round(ms, 1),
                     "pairs_per_s": round(pps, 2) if pps else "",
                     "batch": batch or "", "extra": extra})

    prof_mem: dict[str, float] = {}
    base = torch.cuda.memory_allocated()
    t = time.perf_counter()
    emb = get_embedder(EMBEDDER, cache=None, device="cuda")
    prof_mem["embed_weights_mib"] = (torch.cuda.memory_allocated() - base) / mib
    print(f"embedder loaded in {time.perf_counter() - t:.1f}s")
    b = torch.cuda.memory_allocated()
    t = time.perf_counter()
    rr = make_reranker(args.reranker, device="cuda")
    prof_mem["rerank_weights_mib"] = (torch.cuda.memory_allocated() - b) / mib
    print(f"reranker loaded in {time.perf_counter() - t:.1f}s")
    b = torch.cuda.memory_allocated()
    t = time.perf_counter()
    mc = MiniCheckGrounder(device="cuda")
    prof_mem["minicheck_weights_mib"] = (torch.cuda.memory_allocated() - b) / mib
    print(f"minicheck loaded in {time.perf_counter() - t:.1f}s")
    dtypes = {"embed": str(next(emb.model.parameters()).dtype),
              "rerank": str(next(rr.model.model.parameters()).dtype),
              "minicheck": str(next(mc.model.parameters()).dtype)}
    print("dtypes", dtypes)
    add("dtypes", "-", 0, 0, extra=str(dtypes))

    pool = make_pool(DSN)
    scratch = Path(os.environ.get("TMPDIR", "/tmp")) / "perch-gpu-timings-scratch.db"
    repo = HybridRepository(pool, str(scratch))
    index = PgVectorIndex(index_name="opportunities", embedder=EMBEDDER, pool=pool)
    as_of = date.today()
    cons = Constraints(as_of=as_of)
    researchers = sorted(repo.list(Researcher), key=lambda r: r.id)[:args.researchers]
    queries: list[str] = []
    pools: dict[str, tuple] = {}
    for r in researchers:
        works = repo.works_by_author(r.id)
        torch.cuda.synchronize()
        s = time.perf_counter()
        profile = build_threads(r.id, works, emb, as_of)  # embeds the papers, no cache
        torch.cuda.synchronize()
        add("threads", r.id.rsplit("/", 1)[-1], len(works), (time.perf_counter() - s) * 1000)
        queries += [thread_query(th) for th in profile.threads]
        ret = retrieve(profile, index, k=200)
        opps = {o.id: o for o in (repo.get(Opportunity, c.record_id) for c in ret.candidates) if o}
        eligible, _ = split([opps[c.record_id] for c in ret.candidates if c.record_id in opps],
                            cons)
        ok = {o.id for o in eligible}
        pools[r.id] = (profile, opps, [c for c in ret.candidates if c.record_id in ok])
    print(f"{len(researchers)} researchers, {len(queries)} thread queries; eligible pool sizes",
          [len(p[2]) for p in pools.values()])

    torch.cuda.reset_peak_memory_stats()
    qs = [queries[i % len(queries)] for i in range(10)]
    emb.embed_queries([qs[0]])
    torch.cuda.synchronize()
    for i, q in enumerate(qs):
        s = time.perf_counter()
        emb.embed_queries([q])
        torch.cuda.synchronize()
        add("embed_query", str(i), 1, (time.perf_counter() - s) * 1000)

    first = next(iter(pools.values()))
    rerank(first[2][:4], first[1], first[0], rr, None, top=4)  # warm-up
    for n in (14, 50, 100):
        for rid, (profile, opps, cands) in pools.items():
            pool_n = cands[:n]
            torch.cuda.synchronize()
            s = time.perf_counter()
            rerank(pool_n, opps, profile, rr, None, top=10)
            torch.cuda.synchronize()
            add(f"rerank_{n}", rid.rsplit("/", 1)[-1], len(pool_n),
                (time.perf_counter() - s) * 1000)
    prof_mem["peak_alloc_after_rerank_mib"] = torch.cuda.max_memory_allocated() / mib

    # saturated: every (thread query, doc) pair of the 100-candidate pools in one stream
    sat: list[tuple[str, str]] = []
    for _rid, (profile, opps, cands) in pools.items():
        th = {t.index: t for t in profile.threads}
        for c in cands[:100]:
            sat.append((thread_query(th[c.best_thread]),
                        opportunity_text(opps[c.record_id])[:2000]))
    sat = sat[:400]
    print("saturation pairs:", len(sat))
    for bs in (2, 4, 8, 16, 32, 64):
        try:
            torch.cuda.reset_peak_memory_stats()
            rr.model.predict(sat[:bs], batch_size=bs, show_progress_bar=False)  # warm
            for rep in range(2):
                torch.cuda.synchronize()
                s = time.perf_counter()
                rr.model.predict(sat, batch_size=bs, show_progress_bar=False)
                torch.cuda.synchronize()
                dt = time.perf_counter() - s
                add("rerank_sat", str(rep), len(sat), dt * 1000, len(sat) / dt, bs,
                    f"peak_mib={torch.cuda.max_memory_allocated() / mib:.0f}")
                print(f"  sat batch {bs} rep {rep}: {len(sat) / dt:.1f} pairs/s")
        except torch.cuda.OutOfMemoryError:
            add("rerank_sat", "oom", len(sat), 0, None, bs, "OOM")
            torch.cuda.empty_cache()
            print(f"  batch {bs} OOM")

    pairs: list[tuple[str, str]] = []
    for r in researchers:
        for w in repo.works_by_author(r.id):
            sents = split_sentences(w.abstract or "")
            if len(sents) >= 2:
                pairs.append((work_view(w, abstract_chars=2000), sents[1]))
        if len(pairs) >= 15:
            break
    for _rid, (_, opps, _c) in list(pools.items()):
        for o in list(opps.values())[:3]:
            sents = split_sentences(o.description or "")
            if len(sents) >= 2:
                pairs.append((opportunity_view(o, description_chars=4000), sents[0]))
    pairs = pairs[:25]
    assert len(pairs) == 25, len(pairs)
    torch.cuda.reset_peak_memory_stats()
    mc.support(pairs[0][0], [pairs[0][1]])
    for i, (d, c) in enumerate(pairs):
        torch.cuda.synchronize()
        s = time.perf_counter()
        mc.support(d, [c])
        torch.cuda.synchronize()
        add("minicheck_1", str(i), 1, (time.perf_counter() - s) * 1000)
    # batched: a document with 8 claims, the way a brief checks several sentences of one record
    for bs in (8, 32):
        mc.batch_size = bs
        for rep in range(2):
            torch.cuda.synchronize()
            s = time.perf_counter()
            for d, c in pairs:
                mc.support(d, [c] * 8)
            torch.cuda.synchronize()
            dt = time.perf_counter() - s
            add("minicheck_b", str(rep), 25 * 8, dt * 1000, 25 * 8 / dt, bs)
            print(f"  minicheck 8 claims/doc batch {bs}: {25 * 8 / dt:.1f} sentences/s")
    prof_mem["peak_alloc_after_minicheck_mib"] = torch.cuda.max_memory_allocated() / mib
    prof_mem["nvidia_smi_used_mib_all_loaded"] = smi_used()
    prof_mem["torch_reserved_mib"] = torch.cuda.memory_reserved() / mib
    for k, v in prof_mem.items():
        add("vram", k, 0, 0, extra=f"{v:.0f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    new = not OUT.exists()
    with OUT.open("a", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    for stage in dict.fromkeys(r["stage"] for r in rows if r["stage"] not in ("vram", "dtypes")):
        v = [r["ms"] for r in rows if r["stage"] == stage]
        extra = ""
        if stage in ("rerank_sat", "minicheck_b"):
            for bs in dict.fromkeys(r["batch"] for r in rows if r["stage"] == stage):
                p = [r["pairs_per_s"] for r in rows if r["stage"] == stage and r["batch"] == bs
                     and r["pairs_per_s"] != ""]
                extra += f" b{bs}={statistics.mean(p):.1f}/s" if p else ""
        print(f"run {args.run} {rname} {stage:12s} n={len(v):3d} median={statistics.median(v):9.1f}"
              f" ms p95={pct(v, 0.95):9.1f} ms{extra}")
    print("vram", {k: round(v) for k, v in prof_mem.items()})
    pool.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

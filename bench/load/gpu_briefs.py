"""S47 task 3: concurrent brief jobs on ONE GPU, cloud-gpu profile, fake provider with measured
Sonnet latencies injected (bench/load/worker_main.py), against the e2e Postgres.

    PERCH_LIMIT_GPU=3 scripts/run_limited.sh uv run --extra ml python bench/load/gpu_briefs.py \
        --levels 1,2,4,8,16 --rounds 3 --out bench/results/s47_load

Closed loop: at concurrency N the worker runs `--concurrency N` and N client threads each submit
`rounds` briefs back to back (distinct researchers cycle through the 10 that have works; caches
are switched off in the worker, so every brief does the full work). One warm-up brief per level
loads the models and is not counted. Briefs a minute = briefs / (last finish - first submit).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics as st
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import psycopg  # noqa: E402

from perch.jobs import PostgresRunner  # noqa: E402
from perch.schemas import Brief, Stage  # noqa: E402
from perch.service import STAGES, BriefService, Clients  # noqa: E402
from perch.store.sqlite import SQLiteRepository  # noqa: E402

DSN = os.environ.get("PERCH_E2E_DSN", "postgresql://postgres:perchtest@127.0.0.1:55432/perch_dev")
GPU_INDEX = "3"
SERVICE = "per-job"  # set by --service: "cached" keeps one BriefService per worker


def latencies(out: Path) -> Path:
    """Measured Anthropic latencies from the audit logs (kind=call rows with latency_ms)."""
    rows: dict[str, list[float]] = {"fit": [], "summary": []}
    for f in ("data/logs/model_calls.jsonl", "data/logs/bench_model_calls.jsonl"):
        for line in (ROOT / f).read_text("utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if (r.get("kind") == "call" and r.get("provider") == "anthropic"
                    and r.get("model") == "claude-sonnet-5-5" and r.get("latency_ms")):
                if r.get("role") == "fit_explainer":
                    rows["fit"].append(r["latency_ms"] / 1000)
                elif r.get("role") == "profile_summary":
                    rows["summary"].append(r["latency_ms"] / 1000)
    p = out / "latencies.json"
    p.write_text(json.dumps(rows, indent=1), "utf-8")
    return p


def researchers() -> list[str]:
    with psycopg.connect(DSN) as c:
        return [r[0] for r in c.execute(
            "SELECT r.id FROM records r WHERE r.kind = 'researcher' AND NOT r.sample AND EXISTS "
            "(SELECT 1 FROM records w WHERE w.kind = 'work' AND w.data->'author_ids' @> "
            "to_jsonb(r.id)) ORDER BY r.id").fetchall()]


class Gpu(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak, self.stop_ev, self.samples = 0, threading.Event(), []

    def run(self) -> None:
        while not self.stop_ev.is_set():
            o = subprocess.run(["nvidia-smi", "-i", GPU_INDEX, "--query-gpu=memory.used",
                                "--format=csv,noheader,nounits"], capture_output=True, text=True)
            try:
                v = int(o.stdout.strip())
                self.peak = max(self.peak, v)
                self.samples.append((time.time(), v))
            except ValueError:
                pass
            self.stop_ev.wait(0.5)


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def run_level(n: int, rounds: int, rids: list[str], lat: Path, out: Path) -> dict:
    runner = PostgresRunner(DSN, pool_size=4 * n + 8)
    d = Path(tempfile.mkdtemp(prefix=f"perch-gpuload{n}-"))
    stats = d / "stats.jsonl"
    db = d / "perch.db"
    env = {**os.environ, "PERCH_DATABASE_URL": DSN, "PERCH_PROFILE": "cloud-gpu",
           "PERCH_LLM_DEFAULT": "fake:fake-1", "PERCH_LOAD_STATS": str(stats),
           "PERCH_LOAD_LATENCIES": str(lat),
           "PERCH_LOAD_CACHE_SERVICE": "1" if SERVICE == "cached" else "0"}
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("PERCH_REDIS_URL", None)
    proc = subprocess.Popen([sys.executable, str(ROOT / "bench/load/worker_main.py"), "--db",
                             str(db), "worker", "--concurrency", str(n), "--kinds", "brief"],
                            env=env)
    svc = BriefService(db, None, Clients(openalex=lambda: None))  # type: ignore[arg-type]
    total = 1 + n * rounds
    ids = []
    with SQLiteRepository(str(d / "briefs.db")) as r:
        for i in range(total):
            b = svc.create(rids[i % len(rids)].rsplit("/", 1)[-1], explain=True,
                           as_of=date.today())
            b.stages = [Stage(name=s) for s in STAGES if s != "route_b"]
            r.upsert([b])
            ids.append(b.id)
    result = {"concurrency": n}
    try:
        w = ids[0]
        job = runner.submit("brief", {"brief_id": w}, None, f"load:{w}")
        ws = runner.wait(job, timeout=1800)
        print(f"  level {n}: warm-up {ws.state}", flush=True)
        t_start = time.time()
        gpu = Gpu()
        gpu.start()
        per: list[tuple[str, str, float, float]] = []  # brief id, state, submit, finish
        lk = threading.Lock()
        work = ids[1:]

        def client(k: int) -> None:
            for j in range(rounds):
                bid = work[k * rounds + j]
                t0 = time.time()
                job = runner.submit("brief", {"brief_id": bid}, None, f"load:{bid}")
                s = runner.wait(job, timeout=1800)
                with lk:
                    per.append((bid, s.state, t0, time.time()))

        ts = [threading.Thread(target=client, args=(k,)) for k in range(n)]
        _t0 = time.time()
        [t.start() for t in ts]
        [t.join() for t in ts]
        wall = max(p[3] for p in per) - min(p[2] for p in per)
        gpu.stop_ev.set()
        gpu.join()
        secs = [p[3] - p[2] for p in per if p[1] == "succeeded"]
        errs = sum(p[1] != "succeeded" for p in per)
        # Stage times from the briefs, and the route_a timings the pipeline stores.
        stage_s: dict[str, list[float]] = {}
        tim: dict[str, list[float]] = {}
        with SQLiteRepository(str(d / "briefs.db")) as r:
            for bid, *_ in per:
                b = r.get(Brief, bid)
                if not b:
                    continue
                for s in b.stages:
                    if s.started_at and s.finished_at:
                        stage_s.setdefault(s.name, []).append(
                            (s.finished_at - s.started_at).total_seconds())
                for k, v in (b.timings_ms or {}).items():
                    tim.setdefault(k, []).append(v / 1000)
        agg: dict[str, list[float]] = {}
        calls: dict[str, int] = {}
        for line in stats.read_text("utf-8").splitlines():
            x = json.loads(line)
            if x["t"] < t_start:
                continue
            if x["k"].startswith("model_calls_"):
                calls[x["k"]] = calls.get(x["k"], 0) + 1
            else:
                agg.setdefault(x["k"], []).append(x["s"])
        nb = len(per)
        result.update(
            briefs=nb, errors=errs, wall_s=round(wall, 2),
            briefs_per_min=round(len(secs) / wall * 60, 2),
            p50_s=round(pct(secs, .5), 2), p95_s=round(pct(secs, .95), 2),
            max_s=round(max(secs), 2) if secs else None,
            gpu_mem_peak_mib=gpu.peak, model_calls=calls,
            # per-brief averages of summed seconds (stage means overlap; they are not additive)
            per_brief_s={k: round(sum(v) / nb, 3) for k, v in agg.items()},
            counts={k: len(v) for k, v in agg.items()},
            stage_mean_s={k: round(st.mean(v), 2) for k, v in stage_s.items()},
            route_a_ms_mean={k: round(st.mean(v) * 1000, 1) for k, v in tim.items()},
        )
        return result
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        runner.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="1,2,4,8,16")
    ap.add_argument("--service", choices=["per-job", "cached"], default="per-job")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--out", default="bench/results/s47_load")
    a = ap.parse_args()
    global SERVICE
    SERVICE = a.service
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    lat = latencies(out)
    rids = researchers()
    print(f"researchers: {len(rids)}", flush=True)
    results = []
    for n in [int(x) for x in a.levels.split(",")]:
        r = run_level(n, a.rounds, rids, lat, out)
        print(json.dumps(r), flush=True)
        results.append(r)
        (out / f"gpu_levels_{SERVICE}.json").write_text(json.dumps(results, indent=1), "utf-8")
    with open(out / f"gpu_levels_{SERVICE}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["concurrency", "briefs", "errors", "wall_s", "briefs_per_min", "p50_s",
                    "p95_s", "max_s", "gpu_mem_peak_mib"])
        for r in results:
            w.writerow([r[k] for k in ("concurrency", "briefs", "errors", "wall_s",
                                       "briefs_per_min", "p50_s", "p95_s", "max_s",
                                       "gpu_mem_peak_mib")])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

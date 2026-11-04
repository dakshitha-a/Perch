"""Phase 2 and 3 done-when: a brief job runs on a worker from the queue, with and without a
pre-cache.

Submits `brief` jobs for public researchers in the migrated Postgres database, starts
`perch worker` against it with the cloud-cpu profile (CPU embedder, reranker and MiniCheck)
and the fake LLM provider (no cloud spend), waits for each job and prints job id, state,
number of leads and seconds. Leads come from the pgvector index.

    scripts/run_limited.sh uv run python scripts/e2e_brief_job.py            # one brief
    scripts/run_limited.sh uv run python scripts/e2e_brief_job.py --compare  # cold vs pre-cached

`--compare` runs two phases, each on a fresh worker and a fresh scratch directory (so the
local embedding cache starts empty) and reports the seconds of the measured brief only:
  cold    a warm-up brief for a second researcher (loads the models), then the measured brief
  warm    a `precache` job for the measured researcher on one worker; then, on a second fresh
          worker, the same warm-up brief and the measured brief
The measured brief in the warm phase reads the stored retrieval, rules and rerank result.
Set PERCH_E2E_DSN to a copy of the database: the run writes jobs and `public_cache` rows.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import psycopg

from perch.jobs import PostgresRunner
from perch.schemas import Brief, Lead, Stage
from perch.service import STAGES, BriefService, Clients
from perch.store.sqlite import SQLiteRepository

DSN = os.environ.get("PERCH_E2E_DSN", "postgresql://postgres:perchtest@127.0.0.1:55432/perch_dev")
TIMEOUT = float(os.environ.get("PERCH_E2E_TIMEOUT", "1800"))


def pick_researchers(n: int) -> list[str]:
    with psycopg.connect(DSN) as c:
        rows = c.execute(
            "SELECT r.id FROM records r WHERE r.kind = 'researcher' AND NOT r.sample AND EXISTS "
            "(SELECT 1 FROM records w WHERE w.kind = 'work' AND w.data->'author_ids' @> "
            "to_jsonb(r.id)) ORDER BY r.id LIMIT %s", (n,)).fetchall()
    if len(rows) < n:
        sys.exit("not enough researchers with works in the database")
    return [r[0] for r in rows]


class Worker:
    """A `perch worker` subprocess with its own scratch directory."""

    def __init__(self, runner: PostgresRunner, kinds: str) -> None:
        self.runner = runner
        self.dir = Path(tempfile.mkdtemp(prefix="perch-e2e-"))
        self.db = self.dir / "perch.db"
        env = {**os.environ, "PERCH_DATABASE_URL": DSN, "PERCH_LLM_DEFAULT": "fake:fake-1"}
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("PERCH_REDIS_URL", None)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "perch.cli", "--db", str(self.db), "worker",
             "--concurrency", "2", "--kinds", kinds], env=env)

    def brief(self, rid: str) -> tuple[str, int, float]:
        """Create and run one brief; returns (state, leads, seconds)."""
        # route_b needs the network, so it is left out of this run's stages.
        svc = BriefService(self.db, None, Clients(openalex=lambda: None))  # type: ignore[arg-type]
        b = svc.create(rid.rsplit("/", 1)[-1], explain=True, as_of=date.today())
        b.stages = [Stage(name=n) for n in STAGES if n != "route_b"]
        with SQLiteRepository(str(self.dir / "briefs.db")) as r:
            r.upsert([b])
        t0 = time.monotonic()
        job = self.runner.submit("brief", {"brief_id": b.id}, None, f"e2e:{b.id}")
        st = self.runner.wait(job, timeout=TIMEOUT)
        secs = time.monotonic() - t0
        with SQLiteRepository(str(self.dir / "briefs.db")) as r:
            got = r.get(Brief, b.id)
            leads = [x for x in (r.get(Lead, i) for i in (got.lead_ids if got else [])) if x]
        stages = "; ".join(f"{s.name}={s.status}" for s in got.stages) if got else ""
        print(f"  brief researcher={rid} job={job} state={st.state} leads={len(leads)} "
              f"seconds={secs:.1f}\n  stages: {stages}", flush=True)
        return st.state, len(leads), secs

    def precache(self, rid: str) -> tuple[str, float]:
        t0 = time.monotonic()
        job = self.runner.submit("precache", {"author_id": rid}, None,
                                 f"e2e-precache:{rid}:{time.time()}")
        st = self.runner.wait(job, timeout=TIMEOUT)
        secs = time.monotonic() - t0
        print(f"  precache researcher={rid} job={job} state={st.state} seconds={secs:.1f}",
              flush=True)
        return st.state, secs

    def stop(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=60)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", action="store_true", help="cold vs pre-cached, see the docstring")
    args = ap.parse_args()
    runner = PostgresRunner(DSN)
    try:
        if not args.compare:
            (rid,) = pick_researchers(1)
            w = Worker(runner, "brief")
            try:
                state, leads, secs = w.brief(rid)
            finally:
                w.stop()
            print(f"researcher={rid}\nstate={state}\nleads={leads}\nseconds={secs:.1f}")
            return 0 if state == "succeeded" and leads else 1
        measured, warmup = pick_researchers(2)
        print("phase cold")
        w = Worker(runner, "brief")
        try:
            w.brief(warmup)
            c_state, c_leads, cold = w.brief(measured)
        finally:
            w.stop()
        print("phase warm: precache on one worker")
        w = Worker(runner, "precache")
        try:
            p_state, pre_secs = w.precache(measured)
        finally:
            w.stop()
        print("phase warm: brief on a fresh worker")
        w = Worker(runner, "brief")
        try:
            w.brief(warmup)
            h_state, h_leads, warm = w.brief(measured)
        finally:
            w.stop()
        print(f"cold_seconds={cold:.1f} precache_seconds={pre_secs:.1f} warm_seconds={warm:.1f}")
        ok = all(s == "succeeded" for s in (c_state, p_state, h_state)) and c_leads and h_leads
        return 0 if ok else 1
    finally:
        runner.close()


if __name__ == "__main__":
    raise SystemExit(main())

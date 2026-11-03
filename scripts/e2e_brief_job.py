"""Phase 2 done-when: a brief job runs on a worker from the queue.

Submits a `brief` job for one public researcher in the migrated Postgres database, starts
`perch worker` against it with the fake LLM provider (no cloud spend), waits for the job and
prints job id, state, number of leads and seconds. Leads come from the pgvector index.

    PERCH_E2E_DSN=postgresql://.../perch_dev uv run python scripts/e2e_brief_job.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg

from perch.jobs import PostgresRunner
from perch.schemas import Brief, Lead, Stage
from perch.service import STAGES, BriefService, Clients
from perch.store.sqlite import SQLiteRepository

DSN = os.environ.get("PERCH_E2E_DSN", "postgresql://postgres:perchtest@127.0.0.1:55432/perch_dev")
TIMEOUT = float(os.environ.get("PERCH_E2E_TIMEOUT", "900"))


def pick_researcher() -> str:
    with psycopg.connect(DSN) as c:
        row = c.execute(
            "SELECT r.id FROM records r WHERE r.kind = 'researcher' AND NOT r.sample AND EXISTS "
            "(SELECT 1 FROM records w WHERE w.kind = 'work' AND w.data->'author_ids' @> "
            "to_jsonb(r.id)) ORDER BY r.id LIMIT 1").fetchone()
    if not row:
        sys.exit("no researcher with works in the database")
    return row[0]


def main() -> int:
    rid = pick_researcher()
    work = Path(tempfile.mkdtemp(prefix="perch-e2e-"))
    db = work / "perch.db"
    # The brief row goes in the worker's scratch store; route_b needs the network, so it is
    # left out of this run's stages.
    svc = BriefService(db, None, Clients(openalex=lambda: None))  # type: ignore[arg-type]
    brief = svc.create(rid.rsplit("/", 1)[-1], explain=True)
    brief.stages = [Stage(name=n) for n in STAGES if n != "route_b"]
    with SQLiteRepository(str(work / "briefs.db")) as r:
        r.upsert([brief])

    env = {**os.environ, "PERCH_DATABASE_URL": DSN, "PERCH_LLM_DEFAULT": "fake:fake-1"}
    env.pop("ANTHROPIC_API_KEY", None)
    runner = PostgresRunner(DSN)
    t0 = time.monotonic()
    job = runner.submit("brief", {"brief_id": brief.id}, None, f"e2e:{brief.id}")
    w = subprocess.Popen([sys.executable, "-m", "perch.cli", "--db", str(db), "worker",
                          "--concurrency", "2"], env=env)
    try:
        st = runner.wait(job, timeout=TIMEOUT)
    finally:
        w.terminate()
        w.wait(timeout=30)
        runner.close()
    secs = time.monotonic() - t0
    with SQLiteRepository(str(work / "briefs.db")) as r:
        b = r.get(Brief, brief.id)
        leads = [x for x in (r.get(Lead, i) for i in (b.lead_ids if b else [])) if x]
    print(f"researcher={rid}\njob={job}\nstate={st.state}\nbrief_status={b.status if b else None}"
          f"\nleads={len(leads)}\nseconds={secs:.1f}")
    if b:
        print("stages: " + "; ".join(f"{s.name}={s.status}" for s in b.stages))
    return 0 if st.state == "succeeded" and leads else 1


if __name__ == "__main__":
    raise SystemExit(main())

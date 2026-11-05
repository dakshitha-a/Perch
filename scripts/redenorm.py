"""Re-write every stored public record so its filter columns are computed again (S49).

The filter columns of `records` (scope, schools, audience level, deadline, amount, status) are
computed by `perch.store.denorm.columns` when a record is written. After a change to that
code, run this once against each Postgres store. The record data itself is written back
unchanged, `fetched_at` included.

  uv run python scripts/redenorm.py              # the store in PERCH_DATABASE_URL (.env)
  uv run python scripts/redenorm.py --dsn-env PERCH_WORKER_DATABASE_URL
"""

from __future__ import annotations

import argparse
import os

from perch.config import load_dotenv
from perch.schemas import Opportunity, Scholarship
from perch.store.postgres import PostgresRepository


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn-env", default="PERCH_DATABASE_URL",
                    help="the environment variable that holds the worker-role DSN")
    a = ap.parse_args()
    load_dotenv()
    dsn = os.environ.get(a.dsn_env)
    if not dsn:
        raise SystemExit(f"{a.dsn_env} is not set")
    repo = PostgresRepository(dsn, role="worker")
    for cls in (Scholarship, Opportunity):
        recs = repo.list(cls, include_samples=True)
        n = repo.upsert(recs)
        print(f"{cls.kind}: {n} rewritten")


if __name__ == "__main__":
    main()

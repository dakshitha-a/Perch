"""Refresh the v1 deploy's Grants.gov records from a fresh pull, index them, bust caches (G4).

The pull itself is `perch fetch opportunities` into a scratch SQLite store (the CLI writes
SQLite only). This script then works on the Postgres store in four phases:

  plan     compare the pull with Postgres; look up, by number, each posted or forecasted
           record the pull no longer lists (it has closed or been archived) and add the
           looked-up record to the scratch store. Writes nothing to Postgres.
  apply    upsert every pulled and looked-up record (new `fetched_at`), so closed calls get
           their new status. A record the lookup cannot find is left as it is and listed.
  vectors  embed only the opportunities whose index text changed or is missing (GPU).
  epoch    bump the ingest epoch in Postgres and copy it to Redis, so cached lists go stale.

  S=/path/to/scratch; scripts/run_limited.sh .venv/bin/perch --db $S/gg.db fetch opportunities
  .venv/bin/python scripts/refresh_v1.py plan  --sqlite $S/gg.db
  .venv/bin/python scripts/refresh_v1.py apply --sqlite $S/gg.db
  PERCH_LIMIT_GPU=3 scripts/run_limited.sh .venv/bin/python scripts/refresh_v1.py vectors
  .venv/bin/python scripts/redenorm.py --dsn-env PERCH_WORKER_DATABASE_URL
  .venv/bin/python scripts/refresh_v1.py epoch

The DSN comes from PERCH_WORKER_DATABASE_URL (`--dsn-env` to change it). The archived records
kept for the back-test are never in "missing": only posted and forecasted records are.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from pathlib import Path

from perch.schemas import Opportunity
from perch.store.postgres import PostgresRepository
from perch.store.sqlite import SQLiteRepository

SOURCE = "grants_gov"
OPEN = ("posted", "forecasted")
MAX_MISSING = 200  # more than this many open records gone from one pull means the pull broke


def same_content(a: Opportunity, b: Opportunity) -> bool:
    return a.model_dump(exclude={"fetched_at"}) == b.model_dump(exclude={"fetched_at"})


def pulled(path: Path) -> dict[str, Opportunity]:
    with SQLiteRepository(path) as s:
        return {o.id: o for o in s.list(Opportunity) if o.source == SOURCE}


def diff(pull: dict[str, Opportunity], have: dict[str, Opportunity]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"new": [], "changed": [], "unchanged": [], "missing": []}
    for i, o in pull.items():
        old = have.get(i)
        key = "new" if old is None else "unchanged" if same_content(old, o) else "changed"
        out[key].append(i)
    out["missing"] = sorted(i for i, o in have.items() if o.status in OPEN and i not in pull)
    return out


def lookup_missing(path: Path, have: dict[str, Opportunity], missing: list[str]) -> list[str]:
    """Fetch each missing record by number into the scratch store; return the ids not found."""
    from perch.sources.grants_gov import GrantsGovClient

    not_found = []
    with SQLiteRepository(path) as s, GrantsGovClient() as gg:
        for i in missing:
            number = have[i].opportunity_number
            hits = gg.search(statuses="forecasted|posted|closed|archived", keyword="", rows=5,
                             opp_num=number).get("oppHits") or []
            hits = [h for h in hits if h["number"] == number]
            if not hits:
                not_found.append(i)
                continue
            o = gg.fetch(hits[0]["id"], hits[0].get("oppStatus"))
            if o.id != i:
                not_found.append(i)
                continue
            s.upsert([o])
    return not_found


def report(d: dict[str, list[str]], pull: dict[str, Opportunity],
           have: dict[str, Opportunity]) -> None:
    print(" ".join(f"{k} {len(v)}" for k, v in d.items()))
    moves = Counter(f"{have[i].status}->{pull[i].status}" for i in d["changed"]
                    if have[i].status != pull[i].status)
    print("status changes:", dict(moves) or "none")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["plan", "apply", "vectors", "epoch"])
    ap.add_argument("--sqlite", type=Path, help="the scratch store the pull wrote (plan, apply)")
    ap.add_argument("--dsn-env", default="PERCH_WORKER_DATABASE_URL")
    a = ap.parse_args()
    dsn = os.environ.get(a.dsn_env)
    if not dsn:
        raise SystemExit(f"{a.dsn_env} is not set")
    repo = PostgresRepository(dsn, role="worker")
    try:
        if a.phase in ("plan", "apply"):
            if not a.sqlite or not a.sqlite.exists():
                raise SystemExit("--sqlite must name the scratch store of the pull")
            have = {o.id: o for o in repo.list(Opportunity) if o.source == SOURCE}
            pull = pulled(a.sqlite)
            d = diff(pull, have)
            if a.phase == "plan":
                if len(d["missing"]) > MAX_MISSING:
                    raise SystemExit(f"{len(d['missing'])} open records missing from the pull; "
                                     "stopping, check the pull")
                not_found = lookup_missing(a.sqlite, have, d["missing"])
                pull = pulled(a.sqlite)
                d = diff(pull, have)
                print("after the lookups:")
            report(d, pull, have)
            if d["missing"]:
                print("still listed as open, not found by number (left as is):",
                      ", ".join(d["missing"]))
            if a.phase == "plan":
                print(f"lookups not found: {len(not_found)}")
                return
            n = repo.upsert(pull.values())
            print(f"upserted {n} records")
        elif a.phase == "vectors":
            vectors(repo, dsn)
        else:
            from perch import redisx

            n = repo.bump_epoch()
            redisx.set_epoch(redisx.get_client(), n)
            print(f"ingest epoch now {n} (Postgres and Redis)")
    finally:
        repo.close()


def vectors(repo: PostgresRepository, dsn: str) -> None:
    """Embed only records whose index text or embedder differs from what is stored."""
    from perch.embed import DEFAULT_MODEL, get_embedder
    from perch.retrieve import opportunity_text
    from perch.store.postgres import PgVectorIndex

    opps = [o for o in repo.list(Opportunity) if o.source == SOURCE]
    with repo.pool.connection() as conn:
        stored = {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT record_id, text, embedder FROM record_vectors "
            "WHERE index_name = 'opportunities'")}
    todo = [(o.id, opportunity_text(o)) for o in opps]
    todo = [(i, t) for i, t in todo if stored.get(i) != (t, DEFAULT_MODEL)]
    print(f"{len(opps)} records, {len(todo)} to embed")
    if not todo:
        return
    emb = get_embedder(DEFAULT_MODEL, cache=None, device="cuda")
    vecs = emb.embed_documents([t for _, t in todo]).tolist()
    idx = PgVectorIndex(index_name="opportunities", pool=repo.pool)
    print(f"wrote {idx.upsert([i for i, _ in todo], [t for _, t in todo], vecs)} vectors")


if __name__ == "__main__":
    main()

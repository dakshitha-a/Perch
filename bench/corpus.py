"""Back-test corpus: every NIH opportunity on Grants.gov (posted, closed, archived).

Writes to a separate bench store (data/bench/perch.db), never the demo store, so
closed announcements cannot reach a live brief. Resumable: records already stored
are skipped. At most one request starts per second (self-imposed; Grants.gov
publishes no limit); a response takes about 2.5 s, so up to WORKERS are in flight.
Opportunity numbers given with --first are fetched first, so the ground-truth
announcements are available before the full pull finishes.

  uv run python -m bench.corpus --first data/backtest/pis.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

from perch.schemas import Opportunity
from perch.sources.grants_gov import GrantsGovClient, _date, parse_opportunity
from perch.store.sqlite import SQLiteRepository

BENCH_DB = Path("data/bench/perch.db")
HITS = Path("data/bench/grants_gov_hits.json")
STATUSES = "posted|closed|archived"
AGENCY = "HHS-NIH11"
# Earliest back-test award starts in FY 2015; announcements that closed before 2012
# cannot be open in any back-test window.
MIN_CLOSE = date(2012, 1, 1)
WORKERS = 3


class StartLimiter:
    """At most one start per `interval` seconds, shared across threads."""

    def __init__(self, interval: float = 1.0) -> None:
        self.interval, self.lock, self.next = interval, threading.Lock(), 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next - now)
            self.next = max(now, self.next) + self.interval
        time.sleep(delay)


def load_hits(c: GrantsGovClient, refresh: bool = False) -> list[dict]:
    if HITS.exists() and not refresh:
        return json.loads(HITS.read_text(encoding="utf-8"))
    hits = list(c.iter_hits(statuses=STATUSES, agencies=AGENCY))
    HITS.parent.mkdir(parents=True, exist_ok=True)
    HITS.write_text(json.dumps(hits), encoding="utf-8")
    return hits


def first_numbers(path: Path | None) -> list[str]:
    if not path or not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [r["opportunity_number"] for r in csv.DictReader(f) if r.get("opportunity_number")]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--first", type=Path, help="CSV with an opportunity_number column")
    ap.add_argument("--refresh-hits", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    with GrantsGovClient() as c, SQLiteRepository(BENCH_DB) as repo:
        hits = load_hits(c, a.refresh_hits)
        have = {o.opportunity_number for o in repo.list(Opportunity)}
        firsts = set(first_numbers(a.first))
        keep = [h for h in hits if h["number"] in firsts
                or (_date(h.get("closeDate")) or date.max) >= MIN_CLOSE]
        # Ground truth first, then no close date (open in every window), then newest close.
        keep.sort(key=lambda h: (h["number"] in firsts, not h.get("closeDate"),
                                 h.get("closeDate", "")[-4:]), reverse=True)
        todo = [h for h in keep if h["number"] not in have][: a.limit]
        print(f"{len(hits)} hits, {len(keep)} in range, {len(have)} stored, {len(todo)} to fetch",
              flush=True)
    limiter, lock = StartLimiter(), threading.Lock()
    local = threading.local()
    t0, n = time.monotonic(), {"done": 0, "failed": 0}

    def fetch(h: dict) -> Opportunity | None:
        if not hasattr(local, "c"):
            local.c = GrantsGovClient(min_interval=0.0)
        limiter.wait()
        try:
            data = local.c.post("/fetchOpportunity", {"opportunityId": int(h["id"])})["data"]
            return parse_opportunity(data, datetime.now(UTC), h.get("oppStatus"))
        except Exception as e:  # one bad record must not stop a long pull
            print(f"failed {h['number']}: {type(e).__name__}: {e}", flush=True)
            return None

    with SQLiteRepository(BENCH_DB) as repo, ThreadPoolExecutor(WORKERS) as pool:
        for o in pool.map(fetch, todo):
            with lock:
                n["done" if o else "failed"] += 1
                if o:
                    repo.upsert([o])
                if sum(n.values()) % 250 == 0:
                    rate = sum(n.values()) / (time.monotonic() - t0)
                    print(f"{n['done']} fetched, {n['failed']} failed, {rate:.2f}/s", flush=True)
    print(f"finished: {n['done']} fetched, {n['failed']} failed", flush=True)


if __name__ == "__main__":
    main()

"""Clear the guest limits on a deploy before a demo or a filming run (S52).

Rehearsals, smoke runs and filming all come from one address, so they use up that address's
guest model budget and its rate windows. This clears, in the deploy's Redis:

- every rate-limit window (`perch:rl:*`), for every scope and subject;
- the guest model budgets for today: per guest session (`perch:q:gs:*`), per address
  (`perch:q:ga:*`) and the guests' daily total (`perch:q:gglobal:*`), with their in-flight
  reservations.

It never touches sessions, signed-in users' budgets, the site's monthly total or the spend
ledger file, so the deploy's own spend cap still holds. Dry run by default.

  set -a; . ./.env.deploy; set +a
  .venv/bin/python scripts/demo_reset.py            # count only
  .venv/bin/python scripts/demo_reset.py --apply    # delete
"""

from __future__ import annotations

import argparse
import os
import sys

import redis

PATTERNS = ("perch:rl:*", "perch:q:gs:*", "perch:q:ga:*", "perch:q:gglobal:*",
            "perch:inflight:gs:*", "perch:inflight:ga:*", "perch:inflight:gglobal:*")


def keys_to_clear(r: redis.Redis) -> dict[str, list[bytes]]:
    return {p: list(r.scan_iter(match=p, count=1000)) for p in PATTERNS}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="delete the keys (default: count only)")
    a = ap.parse_args()
    url = os.environ.get("PERCH_REDIS_URL")
    if not url:
        sys.exit("PERCH_REDIS_URL is not set (source the deploy's env file first)")
    r = redis.Redis.from_url(url)
    found = keys_to_clear(r)
    for p, ks in found.items():
        print(f"{p:28} {len(ks)}")
    if a.apply:
        n = sum(r.delete(*ks) for ks in found.values() if ks)
        print(f"deleted {n} keys")
    else:
        print("dry run: nothing deleted (add --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

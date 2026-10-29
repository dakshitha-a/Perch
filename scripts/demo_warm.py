"""`make demo-warm`: build today's briefs for the demo researchers through the running app,
with the request the web app sends, so a visitor's brief for them is reused at once.
A systemd user timer (perch-demo-warm.timer) runs it every morning; briefs reuse
finished ones for 24 hours (PERCH_BRIEF_REUSE_HOURS)."""

from __future__ import annotations

import sys
import time

import httpx

APP = "http://127.0.0.1:8090"
# The three demo briefs' researchers (OpenAlex ids), as in bench/single_card.py.
DEMO = ["A5034175589", "A5026494099", "A5057472361"]


def main() -> int:
    ok = True
    with httpx.Client(base_url=APP, timeout=30) as c:
        for aid in DEMO:  # one at a time: the app runs briefs one after another anyway
            t = time.monotonic()
            r = c.post("/briefs", json={"author_id": aid, "explain": True})
            r.raise_for_status()
            bid = r.json()["id"]
            while (b := c.get(f"/briefs/{bid}").json()["brief"])["status"] in ("queued",
                                                                                "running"):
                time.sleep(3)
            ok &= b["status"] == "done"
            print(f"{aid}: {b['status']}, {'reused' if r.json().get('reused') else 'built'} "
                  f"in {time.monotonic() - t:.0f} s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

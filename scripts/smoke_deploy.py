"""Smoke test of a running `perch serve` deploy through its URL, as a guest (S49).

Checks the health, the browse lists with the S49 sort and open-only parameters, and builds
one guest student brief and one guest researcher brief end to end, polling each to its
end. It prints one line per step with timings and counts; never model text. Exit code 0
when every step passes. A researcher brief spends on the deploy's own model budget (about
$0.10), so `--no-researcher` skips it.

  uv run --no-project --with httpx python scripts/smoke_deploy.py --base https://host:8443 \
      --author A5063022331
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

FAILED: list[str] = []


def step(name: str, ok: bool, note: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {note}")
    if not ok:
        FAILED.append(name)


def guest(c: httpx.Client, side: str) -> dict:
    r = c.post("/auth/guest", json={"audience": side})
    step(f"guest session ({side})", r.status_code in (200, 201), f"http {r.status_code}")
    return r.json() if r.status_code in (200, 201) else {}


def build(c: httpx.Client, csrf: str, body: dict, label: str, limit_s: int = 240) -> dict:
    t0 = time.monotonic()
    r = c.post("/briefs", json=body, headers={"X-CSRF-Token": csrf})
    step(f"{label}: submitted", r.status_code == 202, f"http {r.status_code}")
    if r.status_code != 202:
        return {}
    bid = r.json().get("brief_id") or r.json().get("id")
    out: dict = {}
    while time.monotonic() - t0 < limit_s:
        g = c.get(f"/briefs/{bid}")
        if g.status_code == 200:
            out = g.json()
            if (out.get("brief") or {}).get("status") in ("done", "failed", "error"):
                break
        time.sleep(2)
    leads = out.get("leads") or []
    st = (out.get("brief") or {}).get("status")
    step(f"{label}: finished", st == "done",
         f"status {st}, {len(leads)} leads, {time.monotonic() - t0:.1f} s")
    ids_as_titles = [x for x in leads if (x.get("title") or "") == (x.get("record_id") or "-")]
    step(f"{label}: no record id shown as a title", not ids_as_titles, f"{len(ids_as_titles)}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--author", default="A5063022331", help="a public OpenAlex author id")
    ap.add_argument("--no-researcher", action="store_true")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    with httpx.Client(base_url=base, timeout=30, follow_redirects=False,
                      headers={"Origin": base}) as c:
        h = c.get("/health", params={"ready": "true"})
        step("health ready", h.status_code == 200 and h.json().get("ready") is True, h.text[:120])
        for path, params in (("/awards", {}), ("/awards", {"sort": "closing", "open_only": "true"}),
                             ("/opportunities", {"sort": "amount"}),
                             ("/opportunities", {"sort": "closing", "open_only": "true"})):
            r = c.get(path, params={**params, "limit": 20})
            js = r.json() if r.status_code == 200 else {}
            items = [x for g in js.get("groups") or [] for x in g.get("items") or []]
            name = lambda x: (x.get("title") or x.get("name") or "").strip()  # noqa: E731
            titled = all(name(x) and name(x) != x.get("id") for x in items)
            step(f"GET {path} {params or ''}".strip(),
                 r.status_code == 200 and len(items) > 0 and titled,
                 f"http {r.status_code}, {len(items)} items, sort {js.get('sort')}")
        bad = c.get("/awards", params={"sort": "nonsense"})
        step("bad sort refused", bad.status_code == 422, f"http {bad.status_code}")
        s = guest(c, "student")
        if s.get("csrf"):
            build(c, s["csrf"], {"audience": "student"}, "guest student brief")
        if not a.no_researcher:
            c.cookies.clear()
            g = guest(c, "researcher")
            if g.get("csrf"):
                b = build(c, g["csrf"], {"author_id": a.author}, "guest researcher brief")
                groups = {x.get("group") for x in b.get("leads") or []}
                step("researcher brief: groups", True, f"{sorted(map(str, groups))}")
    print(f"\n{len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())

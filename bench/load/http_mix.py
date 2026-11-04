"""S47 task 4: HTTP load with the plan's path mix against the v1 app on 127.0.0.1:8195.

Pinned tool: asyncio + httpx 0.28.1 (the version in uv.lock). Start the app first
(bench/load/serve_v1.py prepare / web / worker), then:

    PERCH_LIMIT_LOCK=/run/user/1002/perch-load-gen.lock PERCH_LIMIT_CORES=8 \
      scripts/run_limited.sh uv run python bench/load/http_mix.py --users 1000 --duration 300

Mix of N simulated users (each its own address in X-Forwarded-For, the proxy trusted):
  every user      browses: /awards, /opportunities, /filters, /samples, think time 3 to 10 s
  50% of N        signed in (SYNTHETIC accounts): also account pages every 15 to 30 s
                  (/auth/session, /me/briefs, /usage, /me/docs) and Scout buttons every 20 s
  20% of N        build one brief at a random time in the window, a quarter each:
                  signed-in researcher, signed-in student, guest researcher, guest student.
                  After the POST they poll /briefs/{id} every 2 s until the end of the window.
Brief jobs go to the Postgres queue; queue depth is sampled every 5 s. The run does not wait
for the queue to drain; briefs finished inside the window are counted.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import statistics as st
import sys
import time
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8195"
DIR = Path(os.environ.get("PERCH_LOAD_DIR", "/tmp")) / "perch-s47-http"
SUPER_DB = "postgresql://postgres:perchtest@127.0.0.1:55432/perch_walk"
COOKIE = "perch_sid"
BROWSE = [
    ("browse_awards", "/awards?limit=50"),
    ("browse_awards", "/awards?temple_only=true&limit=50"),
    ("browse_awards", "/awards?q=nursing&limit=50"),
    ("browse_awards", "/awards?temple_only=true&level=undergraduate&limit=50"),
    ("browse_opps", "/opportunities?limit=50"),
    ("browse_opps", "/opportunities?q=cancer&limit=50"),
    ("browse_filters", "/filters?audience=student"),
    ("browse_filters", "/filters?audience=researcher"),
    ("browse_samples", "/samples?audience=student"),
]
ACCOUNT = [("account_session", "/auth/session"), ("account_briefs", "/me/briefs"),
           ("account_usage", "/usage"), ("account_docs", "/me/docs")]

samples: dict = {}
rows: list[tuple[float, str, int, float]] = []  # t, path, status, ms
stop = asyncio.Event()
POLL_S = 1.5  # web/app.js POLL_MS
USE_ETAG = True  # the page sends If-None-Match (web/api.js)
t0 = 0.0


def xff(i: int) -> str:
    return f"10.{(i >> 16) & 255}.{(i >> 8) & 255}.{i & 255}"


def v_kind(v) -> str:
    return f"vu{v.i} sid={'yes' if v.sid else 'no'}"


class VU:
    def __init__(self, i: int, c: httpx.AsyncClient, rng: random.Random) -> None:
        self.i, self.c, self.rng = i, c, rng
        self.sid = ""
        self.csrf = ""
        self.brief = ""

    def hdr(self, write: bool = False) -> dict:
        h = {"X-Forwarded-For": xff(self.i), "Origin": BASE}
        if self.sid:
            h["Cookie"] = f"{COOKIE}={self.sid}"
        if self.csrf:  # the web page sends it on every call
            h["X-CSRF-Token"] = self.csrf
        return h

    async def req(self, name: str, method: str, url: str, **kw) -> httpx.Response | None:
        t = time.perf_counter()
        status = 0
        r = None
        try:
            h = self.hdr(method != "GET")
            h.update(kw.pop("headers_extra", {}))
            r = await self.c.request(method, url, headers=h, **kw)
            status = r.status_code
            if status >= 400 and (name, status) not in samples:
                samples[(name, status)] = f"{v_kind(self)} {r.text[:120]}"
        except Exception:  # noqa: BLE001 - recorded as status 0
            status = 0
        rows.append((time.time() - t0, name, status, (time.perf_counter() - t) * 1000))
        return r

    async def sleep(self, a: float, b: float) -> None:
        try:
            await asyncio.wait_for(stop.wait(), self.rng.uniform(a, b))
        except TimeoutError:
            pass


async def browse(v: VU) -> None:
    while not stop.is_set():
        name, url = v.rng.choice(BROWSE)
        await v.req(name, "GET", url)
        await v.sleep(3, 10)


async def account(v: VU) -> None:
    while not stop.is_set():
        await v.sleep(15, 30)
        if stop.is_set():
            return
        name, url = v.rng.choice(ACCOUNT)
        await v.req(name, "GET", url)


async def scout(v: VU) -> None:
    while not stop.is_set():
        await v.sleep(15, 25)
        if not stop.is_set():
            await v.req("scout_buttons", "GET", "/scout/buttons")


async def build(v: VU, kind: str, authors: list[str], when: float, dur: float, done: dict) -> None:
    await v.sleep(when, when)
    if stop.is_set():
        return
    if kind.startswith("guest"):
        aud = "student" if kind.endswith("student") else "researcher"
        r = await v.req("guest_session", "POST", "/auth/guest", json={"audience": aud})
        if r is None or r.status_code != 200:
            return
        v.csrf = r.json().get("csrf", "")
        v.sid = r.cookies.get(COOKIE, "") or ""
        if not v.sid:
            for h in r.headers.get_list("set-cookie"):
                if h.startswith(COOKIE + "="):
                    v.sid = h.split("=", 1)[1].split(";", 1)[0]
    body = {"explain": True}
    if kind.endswith("researcher"):
        body["author_id"] = v.rng.choice(authors)
    name = {"guest_researcher": "brief_post_guest", "guest_student": "brief_post_guest",
            "user_researcher": "brief_post_user", "user_student": "brief_post_user"}[kind]
    r = await v.req(name, "POST", "/briefs", json=body)
    if r is None or r.status_code != 202:
        done["post_fail"] += 1
        return
    done["posted"] += 1
    bid = r.json()["id"]
    tp = time.time()
    etag = ""
    while not stop.is_set():
        await v.sleep(POLL_S, POLL_S)
        r = await v.req("brief_poll", "GET", f"/briefs/{bid}",
                        **({"headers_extra": {"If-None-Match": etag}} if etag else {}))
        if r is not None and r.status_code in (200, 304):
            etag = r.headers.get("etag", etag) if USE_ETAG else ""
        if r is not None and r.status_code == 200:
            try:
                s = (r.json().get("brief") or {}).get("status")
            except ValueError:
                s = None
            if s in ("done", "failed"):
                done["finished" if s == "done" else "failed"] += 1
                done["secs"].append(time.time() - tp)
                return


async def sampler(out: list, load: list, dsn: str) -> None:
    conn = await asyncio.to_thread(psycopg.connect, dsn, autocommit=True)
    while not stop.is_set():
        def q():
            return dict(conn.execute("SELECT state, count(*) FROM jobs GROUP BY state").fetchall())
        d = await asyncio.to_thread(q)
        la = float(open("/proc/loadavg").read().split()[0])
        out.append((round(time.time() - t0, 1), d.get("queued", 0), d.get("running", 0),
                    d.get("succeeded", 0), d.get("failed", 0) + d.get("dead", 0), la))
        if la > 96:
            print(f"load average {la} passed 96; stopping", flush=True)
            load.append(la)
            stop.set()
        try:
            await asyncio.wait_for(stop.wait(), 5)
        except TimeoutError:
            pass


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


async def run(a: argparse.Namespace) -> int:
    global t0
    users = json.loads((DIR / "users.json").read_text("utf-8"))
    res = [u for u in users if u["audience"] == "researcher"]
    stu = [u for u in users if u["audience"] == "student"]
    n = a.users
    n_acc = (n // 4) * 2
    n_each = n // 20  # 5% of N per brief kind: 4 kinds make 20%
    need_r = need_s = n_acc // 2
    if len(res) < need_r or len(stu) < need_s:
        sys.exit(f"prepare more accounts: need {need_r} researchers and {need_s} students")
    with psycopg.connect(SUPER_DB) as c:
        authors = [r[0].rsplit("/", 1)[-1] for r in c.execute(
            "SELECT r.id FROM records r WHERE r.kind = 'researcher' AND NOT r.sample AND EXISTS "
            "(SELECT 1 FROM records w WHERE w.kind = 'work' AND w.data->'author_ids' @> "
            "to_jsonb(r.id))").fetchall()]
        c.execute("DELETE FROM jobs")  # the queue starts empty (scratch database)
    cv = (ROOT / "data/synthetic/persona-1/cv.md").read_text("utf-8")
    limits = httpx.Limits(max_connections=400, max_keepalive_connections=400)
    async with httpx.AsyncClient(base_url=BASE, timeout=30, limits=limits) as c:
        # A shared client must not keep cookies: a stored guest cookie would be sent with the next
        # guest's sign-in, which ends the first guest's session. Each VU sends its own.
        c.cookies.extract_cookies = lambda response: None  # type: ignore[method-assign]
        # Seed the signed-in students' SYNTHETIC CV (not measured).
        seeded = 0
        for u in stu[:n_acc // 2]:
            r = await c.post("/me/docs", json={"kind": "cv", "text": cv, "label": "persona"},
                             headers={"Cookie": f"{COOKIE}={u['sid']}", "X-CSRF-Token": u["csrf"],
                                      "Origin": BASE, "X-Forwarded-For": "10.250.0.1"})
            r2 = await c.post("/me/docs", json={
                "kind": "interests", "text": "SYNTHETIC persona: interested in biology research, "
                "public health, community nursing and first-generation student support."},
                headers={"Cookie": f"{COOKIE}={u['sid']}", "X-CSRF-Token": u["csrf"],
                         "Origin": BASE, "X-Forwarded-For": "10.250.0.1"})
            seeded += r.status_code == 200 and r2.status_code == 200
        print(f"seeded {seeded} student CVs", flush=True)
        rng = random.Random(47)
        _vus, tasks = [], []
        done = {"posted": 0, "post_fail": 0, "finished": 0, "failed": 0, "secs": []}
        acc_r, acc_s = res[:n_acc // 2], stu[:n_acc // 2]
        signed = acc_r + acc_s
        half = n_acc // 2
        t0 = time.time()
        qs: list = []
        loadhit: list = []
        tasks.append(asyncio.create_task(sampler(qs, loadhit, SUPER_DB)))
        bi = 0
        for i in range(n):
            v = VU(i, c, random.Random(i))
            kind = None
            if i < n_acc:
                u = signed[i]
                v.sid, v.csrf = u["sid"], u["csrf"]
                tasks += [asyncio.create_task(account(v)), asyncio.create_task(scout(v))]
                if i < n_each:
                    kind = "user_researcher"
                elif half <= i < half + n_each:
                    kind = "user_student"
            elif i < n_acc + n_each:
                kind = "guest_researcher"
            elif i < n_acc + 2 * n_each:
                kind = "guest_student"
            if kind:
                bi += 1
                when = a.duration * rng.uniform(0.1, 0.7)
                tasks.append(asyncio.create_task(build(v, kind, authors, when, a.duration, done)))
            # ramp: users start spread over the ramp period
            delay = a.ramp * i / n
            tasks.append(asyncio.create_task(_delayed(browse(v), delay)))
        print(f"{n} users started; {bi} builders assigned", flush=True)
        await asyncio.sleep(a.duration)
        stop.set()
        await asyncio.wait(tasks, timeout=30)
        for t in tasks:
            t.cancel()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"u{n}{a.tag}"
    with open(out / f"http_requests_{tag}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "path", "status", "ms"])
        w.writerows((round(t, 2), p, s, round(m, 1)) for t, p, s, m in rows)
    with open(out / f"http_queue_{tag}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "queued", "running", "succeeded", "failed_or_dead", "load1"])
        w.writerows(qs)
    summ = {}
    paths = sorted({r[1] for r in rows})
    with open(out / f"http_paths_{tag}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "requests", "ok_2xx_3xx", "rate_limited_429", "errors", "p50_ms",
                    "p95_ms", "p99_ms", "max_ms", "statuses"])
        for p in paths + ["ALL"]:
            xs = [r for r in rows if p == "ALL" or r[1] == p]
            ms = [r[3] for r in xs]
            ok = sum(1 <= r[2] // 100 <= 3 for r in xs if r[2])
            lim = sum(r[2] == 429 for r in xs)
            err = len(xs) - ok - lim
            w.writerow([p, len(xs), ok, lim, err, round(pct(ms, .5), 1), round(pct(ms, .95), 1),
                        round(pct(ms, .99), 1), round(max(ms), 1),
                        json.dumps({str(k): sum(r[2] == k for r in xs)
                                    for k in sorted({r[2] for r in xs})})])
            summ[p] = dict(n=len(xs), ok=ok, limited=lim, errors=err, p50=round(pct(ms, .5), 1),
                           p95=round(pct(ms, .95), 1))
    dur = rows[-1][0] if rows else 0
    meta = dict(users=n, duration_s=a.duration, ramp_s=a.ramp, requests=len(rows),
                rps=round(len(rows) / max(dur, 1), 1), briefs=done["posted"],
                post_fail=done["post_fail"], finished_in_window=done["finished"],
                failed_in_window=done["failed"],
                brief_secs_p50=round(st.median(done["secs"]), 1) if done["secs"] else None,
                brief_secs_p95=round(pct(done["secs"], .95), 1) if done["secs"] else None,
                max_queued=max((q[1] for q in qs), default=0),
                max_running=max((q[2] for q in qs), default=0),
                max_load1=max((q[5] for q in qs), default=0), load_stop=bool(loadhit))
    (out / f"http_meta_{tag}.json").write_text(json.dumps(
        {"meta": meta, "paths": summ, "error_samples": {f"{k[0]} {k[1]}": v
                                                         for k, v in samples.items()}}, indent=1))
    print(json.dumps(meta), flush=True)
    return 0


async def _delayed(coro, delay: float) -> None:
    await asyncio.sleep(delay)
    await coro


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=1000)
    ap.add_argument("--duration", type=float, default=300)
    ap.add_argument("--poll-s", type=float, default=1.5)
    ap.add_argument("--no-etag", action="store_true")
    ap.add_argument("--tag", default="")
    ap.add_argument("--ramp", type=float, default=30)
    ap.add_argument("--out", default=str(ROOT / "bench/results/s47_load"))
    a = ap.parse_args()
    global POLL_S, USE_ETAG
    POLL_S, USE_ETAG = a.poll_s, not a.no_etag
    return asyncio.run(run(a))


if __name__ == "__main__":
    raise SystemExit(main())

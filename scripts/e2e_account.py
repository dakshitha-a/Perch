"""S41 acceptance: one account's whole life against a running app.

Signs in, uploads the SYNTHETIC persona CV, builds a brief (run the app with the fake model),
signs out, signs in again, lists and reads the brief, posts /me/delete, and then checks the
database: no user_data rows for that user, the user's key tombstoned in perch_keys, the session
destroyed. Everything uploaded is SYNTHETIC (data/synthetic/persona-1). Exit code 0 on success.

    uv run python scripts/e2e_account.py http://127.0.0.1:8090 \\
        --db-dsn postgresql://postgres:...@127.0.0.1:5432/perch \\
        --keys-dsn postgresql://postgres:...@127.0.0.1:5432/perch_keys \\
        --redis-url redis://127.0.0.1:6379/0

Sign-in: if scripts/e2e_oidc_login.py exists it is imported and its `login(base_url)` is called
(it may return a cookie string "name=value", a dict of cookies, or an httpx.Client). Otherwise
pass `--cookie name=value` for the first sign-in and `--cookie2 name=value` for the second (a
cookie from a second login of the same account). With only `--cookie` the sign-out and sign-in
steps are skipped and the script says so.

The database checks are optional and configurable: --db-dsn (the `perch` database, a role that
can read user_data and users), --keys-dsn (the `perch_keys` database), --redis-url. A check whose
DSN is not given is reported as SKIPPED, never as passed.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parent.parent
PERSONA_CV = ROOT / "data/synthetic/persona-1/cv.md"
RESULTS: list[tuple[str, str]] = []


def step(name: str, ok: bool | None, note: str = "") -> None:
    state = "SKIPPED" if ok is None else "PASS" if ok else "FAIL"
    RESULTS.append((state, name))
    print(f"{state:8} {name}" + (f"  ({note})" if note else ""), flush=True)


def need(ok: bool, name: str, note: str = "") -> None:
    step(name, ok, note)
    if not ok:
        finish()


def finish() -> None:
    bad = [n for s, n in RESULTS if s == "FAIL"]
    print(f"\n{len(RESULTS) - len(bad)} of {len(RESULTS)} steps ok"
          + (f"; failed: {', '.join(bad)}" if bad else ""))
    sys.exit(1 if bad else 0)


def parse_cookie(raw: str) -> dict[str, str]:
    name, _, value = raw.partition("=")
    return {name.strip(): value.strip()}


def helper_login(base: str) -> httpx.Client | None:
    path = ROOT / "scripts/e2e_oidc_login.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("e2e_oidc_login", path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    got = mod.login(base)
    if isinstance(got, httpx.Client):
        return got
    c = httpx.Client(base_url=base, follow_redirects=False, timeout=60)
    c.cookies.update(parse_cookie(got) if isinstance(got, str) else got)
    return c


def client_from_cookie(base: str, raw: str) -> httpx.Client:
    c = httpx.Client(base_url=base, follow_redirects=False, timeout=60)
    c.cookies.update(parse_cookie(raw))
    return c


def csrf_headers(c: httpx.Client, base: str, header: str) -> dict[str, str]:
    r = c.get("/auth/session")
    token = r.json().get("csrf", "") if r.status_code == 200 else ""
    return {header: token, "Origin": base}


def build_brief(c: httpx.Client, h: dict[str, str], author: str, timeout: float) -> str:
    r = c.post("/briefs", headers=h, json={"author_id": author, "audience": "researcher",
                                           "as_of": "2026-10-28"})
    need(r.status_code in (200, 202), "POST /briefs accepted", f"HTTP {r.status_code}")
    body = r.json()
    brief_id = str(body.get("brief_id") or body.get("id") or "")
    need(bool(brief_id), "the response names the brief")
    end = time.monotonic() + timeout
    status = ""
    while time.monotonic() < end:
        g = c.get(f"/me/briefs/{brief_id}")
        if g.status_code == 200:
            status = g.json()["brief"]["status"]
            if status in ("done", "failed"):
                break
        time.sleep(1)
    need(status == "done", "the brief finishes", f"status {status or 'none'}")
    return brief_id


def count(dsn: str, sql: str, *args: object) -> int:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(sql, args).fetchone()[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("base_url")
    ap.add_argument("--cookie", help="session cookie for the first sign-in, name=value")
    ap.add_argument("--cookie2", help="session cookie for the second sign-in, name=value")
    ap.add_argument("--cv", default=str(PERSONA_CV), help="a SYNTHETIC CV file")
    ap.add_argument("--author", default="A5026494099", help="a public OpenAlex author id")
    ap.add_argument("--csrf-header", default="X-CSRF-Token")
    ap.add_argument("--db-dsn", help="DSN of the perch database (reads user_data, users)")
    ap.add_argument("--keys-dsn", help="DSN of the perch_keys database")
    ap.add_argument("--redis-url", help="Redis URL, to check the session key is gone")
    ap.add_argument("--timeout", type=float, default=300.0, help="seconds to wait for each wait")
    a = ap.parse_args()
    base = a.base_url.rstrip("/")

    c = helper_login(base) if not a.cookie else client_from_cookie(base, a.cookie)
    if c is None:
        sys.exit("no sign-in: pass --cookie name=value or add scripts/e2e_oidc_login.py")
    sess = c.get("/auth/session")
    need(sess.status_code == 200 and sess.json().get("signed_in") is True, "signed in",
         f"HTTP {sess.status_code}")
    h = csrf_headers(c, base, a.csrf_header)

    text = Path(a.cv).read_text()
    r = c.post("/me/docs", headers=h, json={"kind": "cv", "text": text, "filename": "cv.md"})
    need(r.status_code == 200, "CV uploaded", f"HTTP {r.status_code}")
    doc_id = r.json()["id"]
    user_id: UUID | None = None
    if a.db_dsn:
        import psycopg

        with psycopg.connect(a.db_dsn, autocommit=True) as conn:
            row = conn.execute("SELECT user_id FROM user_data WHERE id = %s", (doc_id,)).fetchone()
        need(row is not None, "the CV is a user_data row")
        user_id = row[0]
        blob = count(a.db_dsn, "SELECT count(*) FROM user_data WHERE user_id = %s "
                     "AND position(%s::bytea in blob) > 0", user_id, b"PERCH-CANARY-CV")
        need(blob == 0, "the CV text is not readable in the stored blob")

    brief_id = build_brief(c, h, a.author, a.timeout)

    two = a.cookie2 or ("helper" if not a.cookie else None)
    if two is None:
        step("sign out and sign in again", None, "pass --cookie2 for a second login")
        c2, h2 = c, h
    else:
        lo = c.post("/auth/logout", headers=h)
        step("signed out", lo.status_code in (200, 204, 302), f"HTTP {lo.status_code}")
        gone = c.get("/me/briefs")
        need(gone.status_code == 401, "the old session no longer works", f"HTTP {gone.status_code}")
        c2 = helper_login(base) if two == "helper" else client_from_cookie(base, two)
        need(c2 is not None, "signed in again")
        h2 = csrf_headers(c2, base, a.csrf_header)

    lst = c2.get("/me/briefs")
    need(lst.status_code == 200 and brief_id in [b["id"] for b in lst.json()],
         "the brief is listed after signing in again")
    got = c2.get(f"/me/briefs/{brief_id}")
    need(got.status_code == 200 and got.json()["brief"]["status"] == "done" and got.json()["leads"],
         "the brief reads back with leads")

    d = c2.post("/me/delete", headers=h2, json={"confirm": "delete"})
    need(d.status_code == 202, "POST /me/delete returns 202", f"HTTP {d.status_code}")
    after = c2.get("/auth/session")
    step("the session is destroyed", after.status_code in (401, 403)
         or after.json().get("signed_in") is False, f"HTTP {after.status_code}")
    again = c2.get("/me/briefs")
    step("the old cookie reads nothing", again.status_code == 401, f"HTTP {again.status_code}")

    if a.redis_url and user_id:
        import redis

        r_ = redis.Redis.from_url(a.redis_url, decode_responses=True)
        key = [k for k in r_.scan_iter("perch:sess:*") if r_.hget(k, "uid") == str(user_id)]
        step("no Redis session key remains for the user", not key)
    else:
        step("no Redis session key remains for the user", None, "needs --redis-url and --db-dsn")

    if a.db_dsn and user_id:
        end = time.monotonic() + a.timeout  # the purge job runs on a worker
        rows = users = -1
        while time.monotonic() < end:
            rows = count(a.db_dsn, "SELECT count(*) FROM user_data WHERE user_id = %s", user_id)
            users = count(a.db_dsn, "SELECT count(*) FROM users WHERE id = %s", user_id)
            if rows == 0 and users == 0:
                break
            time.sleep(1)
        step("zero user_data rows for the user", rows == 0, f"{rows} left")
        step("the users row is gone", users == 0, f"{users} left")
        step("shred_log holds the user", count(
            a.db_dsn, "SELECT count(*) FROM shred_log WHERE user_id = %s", user_id) == 1)
    else:
        step("zero user_data rows for the user", None, "no --db-dsn")
    if a.keys_dsn and user_id:
        step("no key rows remain", count(
            a.keys_dsn, "SELECT count(*) FROM user_keys WHERE user_id = %s", user_id) == 0)
        step("the user's key is tombstoned in perch_keys", count(
            a.keys_dsn, "SELECT count(*) FROM key_tombstones WHERE user_id = %s", user_id) == 1)
    else:
        step("the user's key is tombstoned in perch_keys", None, "no --keys-dsn or --db-dsn")
    finish()


if __name__ == "__main__":
    main()

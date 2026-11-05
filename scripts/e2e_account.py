"""S41 acceptance: one account's whole life against the full app, with no model spend.

Run from the main checkout, with the dev stack (Postgres, Redis, Keycloak) up and the e2e
databases migrated, including a perch_keys database. The script loads `.env` and `.env.e2e`:

  1. starts the full app (perch.api.create_app with account services) on 127.0.0.1:8190, which
     the Keycloak dev realm allows as a redirect URI, with PERCH_LLM_DEFAULT=fake:fake-1;
  2. starts `perch worker` (kinds brief and purge) as a subprocess on the perch_worker role,
     also on the fake provider;
  3. signs in through Keycloak (scripts/e2e_oidc_login.py `login`), accepts the consent, sets
     the student role, uploads the SYNTHETIC persona-1 CV, builds a brief that reads it, signs
     out, signs in again, lists and reads the brief;
  4. posts /me/delete and checks: zero user_data rows for the user, no key rows and exactly one
     tombstone in perch_keys, and the session gone from the app and from Redis.

    scripts/run_limited.sh uv run python scripts/e2e_account.py

Needed in the environment (from `.env` and `.env.e2e`): PERCH_OIDC_CLIENT_SECRET,
PERCH_DATABASE_URL (role perch_web, database perch_e2e), PERCH_REDIS_URL, PERCH_PEPPER,
PERCH_PEPPER_GUEST, PERCH_KEYS_DATABASE_URL (role perch_keys), PERCH_MASTER_KEY (base64 of 32
bytes) with PERCH_MASTER_KEY_ID, PERCH_PUBLIC_URL=http://127.0.0.1:8190, PERCH_COOKIE_INSECURE=1.
The worker needs the perch_worker role: set PERCH_E2E_WORKER_DATABASE_URL, or PERCH_WORKER_PASSWORD
(the script then rewrites PERCH_DATABASE_URL to that role). The brief needs the public corpus
in the e2e database; an empty corpus gives a brief with no leads, which the script reports.

Everything uploaded is SYNTHETIC (data/synthetic/persona-1). Exit code 0 when every step passes.
The stored rows are read through the perch_web role under the user's own row-level security
(`user_tx`), never as an administrator, so "zero rows" means zero rows the user could see.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parent.parent
PERSONA_CV = ROOT / "data/synthetic/persona-1/cv.md"
PORT = 8190
BASE = f"http://127.0.0.1:{PORT}"
RESULTS: list[tuple[str, str]] = []
CHILDREN: list[subprocess.Popen] = []
SERVER: list[object] = []



def _kc_issuer() -> str:
    """The dev Keycloak's advertised issuer (the public URL when KC_HOSTNAME is set)."""
    import httpx
    try:
        return httpx.get("http://127.0.0.1:8180/realms/perch/.well-known/openid-configuration",
                         timeout=5).json()["issuer"]
    except (httpx.HTTPError, ValueError, KeyError):
        return "http://127.0.0.1:8180/realms/perch"

def step(name: str, ok: bool | None, note: str = "") -> None:
    state = "SKIPPED" if ok is None else "PASS" if ok else "FAIL"
    RESULTS.append((state, name))
    print(f"{state:8} {name}" + (f"  ({note})" if note else ""), flush=True)


def finish() -> None:
    for p in CHILDREN:
        p.terminate()
    for p in CHILDREN:
        try:
            p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
    for s in SERVER:
        s.should_exit = True  # type: ignore[attr-defined]
    bad = [n for s, n in RESULTS if s == "FAIL"]
    print(f"\n{len(RESULTS) - len(bad)} of {len(RESULTS)} steps ok"
          + (f"; failed: {', '.join(bad)}" if bad else ""), flush=True)
    sys.stdout.flush()
    os._exit(1 if bad else 0)  # the app thread and the worker are not waited for


def need(ok: bool, name: str, note: str = "") -> None:
    step(name, ok, note)
    if not ok:
        finish()


# --- environment, app and worker ---

def load_env() -> None:
    from perch.config import load_dotenv

    for f in (".env", ".env.e2e"):
        load_dotenv(ROOT / f)
    os.environ["PERCH_PUBLIC_URL"] = BASE
    os.environ["PERCH_COOKIE_INSECURE"] = "1"
    # web and worker refuse to start without a shred ledger (S48 M3); a scratch one here
    os.environ.setdefault("PERCH_SHRED_LEDGER_URI", tempfile.mkdtemp(prefix="perch-e2e-ledger-"))
    os.environ["PERCH_LLM_DEFAULT"] = "fake:fake-1"  # no spend, whatever .env says
    os.environ["PERCH_STORED_BRIEFS"] = "1"
    os.environ.pop("PERCH_ENV", None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.setdefault("PERCH_OIDC_ISSUER", _kc_issuer())
    os.environ.setdefault("PERCH_OIDC_CLIENT_ID", "perch-web")
    os.environ.setdefault("PERCH_CONSENT_PROVIDER_NAME", "SYNTHETIC Provider")
    os.environ.setdefault("PERCH_CONSENT_VERSION", "1")
    os.environ.setdefault("PERCH_MASTER_KEY_ID", "m1")
    os.environ.setdefault("PERCH_PROFILE", "cloud-cpu")


def missing_env() -> list[str]:
    want = ["PERCH_OIDC_CLIENT_SECRET", "PERCH_DATABASE_URL", "PERCH_REDIS_URL", "PERCH_PEPPER",
            "PERCH_PEPPER_GUEST", "PERCH_KEYS_DATABASE_URL", "PERCH_MASTER_KEY"]
    return [k for k in want if not os.environ.get(k)]


def worker_url() -> str | None:
    if os.environ.get("PERCH_E2E_WORKER_DATABASE_URL"):
        return os.environ["PERCH_E2E_WORKER_DATABASE_URL"]
    pw = os.environ.get("PERCH_WORKER_PASSWORD")
    if not pw:
        return None
    u = urlsplit(os.environ["PERCH_DATABASE_URL"])
    host = u.hostname or "127.0.0.1"
    port = f":{u.port}" if u.port else ""
    return urlunsplit((u.scheme, f"perch_worker:{pw}@{host}{port}", u.path, "", ""))


def start_app(scratch: Path) -> None:
    import uvicorn

    from perch import awards as aw
    from perch.api import create_app
    from perch.cli import default_client
    from perch.jobs import InProcessRunner
    from perch.service import BriefService, Clients, default_models

    service = BriefService(str(scratch / "perch.db"), default_models(True, scratch, None),
                           Clients(openalex=default_client), Path(aw.OVERRIDES))
    app = create_app(service, InProcessRunner(), stored_briefs=True)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    SERVER.append(server)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(300):
        if server.started:
            return
        time.sleep(0.1)
    raise SystemExit(f"the app did not start on 127.0.0.1:{PORT}")


def start_worker(scratch: Path, url: str) -> None:
    env = {**os.environ, "PERCH_DATABASE_URL": url, "PERCH_DATABASE_DIRECT_URL": url,
           "PERCH_LLM_DEFAULT": "fake:fake-1"}
    log = open(scratch / "worker.log", "w")  # noqa: SIM115 - lives as long as the worker
    CHILDREN.append(subprocess.Popen(
        [sys.executable, "-m", "perch.cli", "--db", str(scratch / "perch.db"), "worker",
         "--concurrency", "2", "--kinds", "brief,purge"], env=env, cwd=ROOT,
        stdout=log, stderr=subprocess.STDOUT))


# --- helpers ---

def helper_login(base: str) -> httpx.Client:
    path = ROOT / "scripts/e2e_oidc_login.py"
    spec = importlib.util.spec_from_file_location("e2e_oidc_login", path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.login(base)


def headers(c: httpx.Client, base: str) -> dict[str, str]:
    r = c.get("/auth/session")
    return {"X-CSRF-Token": r.json().get("csrf", "") if r.status_code == 200 else "",
            "Origin": base}


def session_id(c: httpx.Client) -> str:
    from perch.auth import settings

    return c.cookies.get(settings.session_cookie_name()) or ""


def sign_in(base: str, label: str) -> tuple[httpx.Client, dict[str, str]]:
    try:
        c = helper_login(base)
    except Exception as e:  # noqa: BLE001
        need(False, label, f"{type(e).__name__}: {e}")
    s = c.get("/auth/session")
    need(s.status_code == 200 and s.json().get("signed_in") is True, label)
    return c, headers(c, base)


def user_count(pool: object, uid: UUID, sql: str) -> int:
    from perch.store import pg

    with pg.user_tx(pool, uid) as conn:  # type: ignore[arg-type]
        return conn.execute(sql, (uid,)).fetchone()[0]


def keys_count(dsn: str, sql: str, uid: UUID) -> int:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(sql, (uid,)).fetchone()[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--cv", default=str(PERSONA_CV), help="a SYNTHETIC CV file")
    ap.add_argument("--author", default="A5026494099", help="a public OpenAlex author id")
    ap.add_argument("--timeout", type=float, default=600.0, help="seconds to wait for a job")
    a = ap.parse_args()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    load_env()
    if gone := missing_env():
        sys.exit("missing in .env or .env.e2e: " + ", ".join(gone))
    wurl = worker_url()
    if wurl is None:
        sys.exit("set PERCH_E2E_WORKER_DATABASE_URL (role perch_worker) or PERCH_WORKER_PASSWORD")

    import redis

    from perch.store import pg

    scratch = Path(tempfile.mkdtemp(prefix="perch-e2e-account-"))
    start_app(scratch)
    start_worker(scratch, wurl)
    base = BASE
    pool = pg.make_pool(os.environ["PERCH_DATABASE_URL"], 2)
    rds = redis.Redis.from_url(os.environ["PERCH_REDIS_URL"], decode_responses=True)
    keys_dsn = os.environ["PERCH_KEYS_DATABASE_URL"]

    h = httpx.get(base + "/health", params={"ready": "true"}, timeout=30)
    need(h.status_code == 200 and h.json().get("keys") == "ok" and h.json().get("ready") is True,
         "health ready, including the keys database", str(h.json()))

    c, hd = sign_in(base, "signed in")
    sid = session_id(c)
    uid_raw = rds.hget(f"perch:sess:{sid}", "uid")
    need(bool(uid_raw), "the session names a user")
    uid = UUID(uid_raw)

    r = c.post("/me/roles", headers=hd, json={"roles": ["student"]})
    need(r.status_code == 200 and r.json()["roles"] == ["student"], "role set to student",
         f"HTTP {r.status_code}")
    # A returning test user may hold consent from an earlier run; withdraw it so the check
    # below always starts from a user without consent.
    c.post("/me/consent/withdraw", headers=hd)
    r = c.post("/me/docs", headers=hd, json={"kind": "cv", "text": "x"})
    need(r.status_code == 403 and r.json().get("detail") == "consent_required",
         "uploading before consent is refused", f"HTTP {r.status_code}")
    r = c.post("/me/consent", headers=hd, json={})
    need(r.status_code == 200, "consent accepted", f"HTTP {r.status_code}")

    r = c.post("/me/docs", headers=hd, json={"kind": "cv", "text": Path(a.cv).read_text(),
                                             "filename": "cv.md"})
    need(r.status_code == 200, "SYNTHETIC CV uploaded", f"HTTP {r.status_code}")
    cv_id = r.json()["id"]
    n = user_count(pool, uid, "SELECT count(*) FROM user_data WHERE user_id = %s")
    need(n == 1, "one user_data row for the CV", f"{n}")


    with pg.user_tx(pool, uid) as conn:
        hits = conn.execute("SELECT count(*) FROM user_data WHERE user_id = %s "
                            "AND position(%s::bytea in blob) > 0",
                            (uid, b"PERCH-CANARY-CV")).fetchone()[0]
    need(hits == 0, "the CV text is not readable in the stored blob")
    need(keys_count(keys_dsn, "SELECT count(*) FROM user_keys WHERE user_id = %s", uid) >= 1,
         "the user has a wrapped key in perch_keys")

    r = c.post("/briefs", headers=hd, json={"author_id": a.author, "as_of": "2026-10-28",
                                            "doc_ids": [cv_id]})
    need(r.status_code == 202, "POST /briefs accepted", f"HTTP {r.status_code} {r.text[:120]}")
    brief_id = r.json()["id"]
    again = c.post("/briefs", headers=hd, json={"author_id": a.author, "as_of": "2026-10-28",
                                                "doc_ids": [cv_id]})
    need(again.status_code == 202 and again.json()["id"] == brief_id,
         "the same request again returns the same brief")
    status, end = "", time.monotonic() + a.timeout
    while time.monotonic() < end:
        g = c.get(f"/me/briefs/{brief_id}")
        if g.status_code == 200:
            status = g.json()["brief"]["status"]
            if status in ("done", "failed"):
                break
        time.sleep(1)
    need(status == "done", "the brief finishes on the worker", f"status {status or 'none'}")
    leads = len(c.get(f"/me/briefs/{brief_id}").json()["leads"])
    step("the brief has leads", leads > 0 or None, f"{leads} leads" if leads else
         "no leads: the e2e database holds no public corpus")

    lo = c.post("/auth/logout", headers=hd)
    step("signed out", lo.status_code == 200, f"HTTP {lo.status_code}")
    need(c.get("/me/briefs").status_code == 401, "the old session no longer works")
    need(rds.exists(f"perch:sess:{sid}") == 0, "the session key is gone from Redis after logout")

    c2, h2 = sign_in(base, "signed in again")
    need(session_id(c2) != sid, "a new session id was issued")
    lst = c2.get("/me/briefs")
    need(lst.status_code == 200 and brief_id in [b["id"] for b in lst.json()],
         "the brief is listed after signing in again")
    got = c2.get(f"/me/briefs/{brief_id}")
    need(got.status_code == 200 and got.json()["brief"]["status"] == "done",
         "the brief reads back")
    sid2 = session_id(c2)

    d = c2.post("/me/delete", headers=h2, json={"confirm": "delete"})
    need(d.status_code == 202, "POST /me/delete returns 202", f"HTTP {d.status_code}")
    after = c2.get("/auth/session")
    step("the session is gone", after.json().get("signed_in") is False)
    step("the old cookie reads nothing", c2.get("/me/briefs").status_code == 401)
    step("no session key remains in Redis", rds.exists(f"perch:sess:{sid2}") == 0
         and rds.exists(f"perch:usess:{uid}") == 0)

    rows = users = -1
    end = time.monotonic() + a.timeout  # the purge job runs on the worker
    while time.monotonic() < end:
        rows = user_count(pool, uid, "SELECT count(*) FROM user_data WHERE user_id = %s")
        users = user_count(pool, uid, "SELECT count(*) FROM users WHERE id = %s")
        if rows == 0 and users == 0:
            break
        time.sleep(1)
    step("zero user_data rows for the user", rows == 0, f"{rows} left")
    step("the users row is gone", users == 0, f"{users} left")
    step("no key rows remain in perch_keys", keys_count(
        keys_dsn, "SELECT count(*) FROM user_keys WHERE user_id = %s", uid) == 0)
    step("exactly one tombstone in perch_keys", keys_count(
        keys_dsn, "SELECT count(*) FROM key_tombstones WHERE user_id = %s", uid) == 1)
    finish()


if __name__ == "__main__":
    main()

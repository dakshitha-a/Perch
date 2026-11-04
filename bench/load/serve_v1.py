"""S47 task 4 helper: the v1 app (accounts, Redis, Postgres) for the HTTP load test, on
127.0.0.1:8195, split in three modes so each can run under scripts/run_limited.sh:

  prepare N_RESEARCHER N_STUDENT   write the env file and create SYNTHETIC accounts + sessions
  web [--procs K]                  uvicorn with K processes (default 1)
  worker [--concurrency N]         `perch worker` (bench/load/worker_main.py: fake provider with
                                   measured latencies), meant for PERCH_LIMIT_GPU=3

Databases are the walk scratch copies of the e2e container (perch_walk, perch_walk_keys; made by
`scripts/walk_server.py --setup`), Redis database 13. State lives in $PERCH_LOAD_DIR.
Everything is SYNTHETIC. The secrets are random per prepare and never leave the scratch dir.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PORT = 8195
DIR = Path(os.environ.get("PERCH_LOAD_DIR", tempfile.gettempdir())) / "perch-s47-http"
SUPER = "postgresql://postgres:perchtest@127.0.0.1:55432/postgres"
REDIS = "redis://127.0.0.1:56379/13"
ROLE_PW = "walk-throwaway-pw"


def dsn(db: str, user: str) -> str:
    return f"postgresql://{user}:{ROLE_PW}@127.0.0.1:55432/{db}"


def load_env(extra: dict | None = None) -> None:
    cfg = json.loads((DIR / "env.json").read_text("utf-8"))
    os.environ.update(cfg)
    os.environ.update(extra or {})
    if os.environ.get("PERCH_LOAD_POOL"):  # connections per web process (the file says 20)
        os.environ["PERCH_DB_POOL_MAX"] = os.environ["PERCH_LOAD_POOL"]
    for k in ("PERCH_ENV", "ANTHROPIC_API_KEY", "PERCH_MODEL_SERVER"):
        os.environ.pop(k, None)


def prepare(n_res: int, n_stu: int) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    cfg = dict(
        PERCH_PUBLIC_URL=f"http://127.0.0.1:{PORT}", PERCH_COOKIE_INSECURE="1",
        PERCH_LLM_DEFAULT="fake:fake-1", PERCH_STORED_BRIEFS="1",
        PERCH_DATABASE_URL=dsn("perch_walk", "perch_web"),
        PERCH_DATABASE_DIRECT_URL=dsn("perch_walk", "perch_web"),
        PERCH_KEYS_DATABASE_URL=dsn("perch_walk_keys", "perch_keys"), PERCH_REDIS_URL=REDIS,
        PERCH_PEPPER=secrets.token_hex(32), PERCH_PEPPER_GUEST=secrets.token_hex(32),
        PERCH_AUDIT_KEY=secrets.token_hex(32),
        PERCH_MASTER_KEY=base64.b64encode(secrets.token_bytes(32)).decode(),
        PERCH_MASTER_KEY_ID="load", PERCH_CONSENT_PROVIDER_NAME="SYNTHETIC Provider",
        PERCH_CONSENT_VERSION="1", PERCH_PROFILE="cloud-gpu", PERCH_DB_POOL_MAX="20",
        PERCH_TRUSTED_PROXIES="127.0.0.0/8")
    (DIR / "env.json").write_text(json.dumps(cfg), "utf-8")
    os.environ.update(cfg)
    import redis

    from perch import redisx
    from perch.auth import accounts
    from perch.store import pg

    r = redis.Redis.from_url(REDIS, decode_responses=True)
    r.flushdb()  # database 13 is the load test's own
    pool = pg.make_pool(cfg["PERCH_DATABASE_URL"], 4)
    users = []
    for i in range(n_res + n_stu):
        side = "researcher" if i < n_res else "student"
        uid = accounts.login_user(pool, "synthetic-load", f"load-user-{i}")
        accounts.set_roles(pool, uid, [side])
        accounts.set_last_audience(pool, uid, side)
        accounts.add_consent(pool, uid, 1, "SYNTHETIC Provider")
        sid, csrf = redisx.create_session(r, uid=uid, roles=[side], audience=side,
                                          name=f"load{i}", idle_s=7200, abs_s=28800)
        r.hset(f"{redisx.PREFIX}:sess:{sid}", "consent", "1")  # the session holds the version
        users.append({"uid": str(uid), "audience": side, "sid": sid, "csrf": csrf})
    (DIR / "users.json").write_text(json.dumps(users), "utf-8")
    print(f"prepared {len(users)} accounts in {DIR}")


def make_app():  # noqa: ANN201 - uvicorn factory: one app per process
    load_env()
    scratch = Path(tempfile.mkdtemp(prefix="perch-s47-web-"))
    from perch import awards as aw
    from perch.api import create_app
    from perch.cli import default_client
    from perch.jobs import InProcessRunner
    from perch.service import BriefService, Clients, default_models
    from perch.store import pg
    from perch.store.hybrid import HybridRepository

    pool = pg.make_pool(os.environ["PERCH_DATABASE_URL"])
    service = BriefService(str(scratch / "perch.db"), default_models(True, scratch, None),
                           Clients(openalex=default_client), Path(aw.OVERRIDES),
                           repo_factory=lambda: HybridRepository(pool, scratch / "briefs.db"))
    return create_app(service, InProcessRunner(), stored_briefs=True)


def web(procs: int) -> None:
    import uvicorn

    os.chdir(ROOT)
    load_env()
    uvicorn.run("bench.load.serve_v1:make_app", factory=True, host="127.0.0.1", port=PORT,
                workers=procs, log_level="warning", app_dir=str(ROOT))


def worker(conc: int) -> None:
    import subprocess

    load_env({"PERCH_DATABASE_URL": dsn("perch_walk", "perch_worker"),
              "PERCH_DATABASE_DIRECT_URL": dsn("perch_walk", "perch_worker")})
    scratch = Path(tempfile.mkdtemp(prefix="perch-s47-worker-"))
    env = {**os.environ, "PERCH_LOAD_LATENCIES": str(DIR / "latencies.json"),
           "PERCH_LOAD_STATS": str(DIR / "worker_stats.jsonl"),
           "PERCH_LOAD_CACHE_SERVICE": "1"}
    os.chdir(ROOT)
    sys.exit(subprocess.call(
        [sys.executable, str(ROOT / "bench/load/worker_main.py"), "--db",
         str(scratch / "perch.db"), "worker", "--concurrency", str(conc), "--kinds",
         "brief,scout_turn,purge"], env=env))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["prepare", "web", "worker"])
    ap.add_argument("a", nargs="*", type=int)
    ap.add_argument("--procs", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=16)
    a = ap.parse_args()
    if a.mode == "prepare":
        prepare(a.a[0], a.a[1])
    elif a.mode == "web":
        web(a.procs)
    else:
        worker(a.concurrency)

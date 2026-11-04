"""A dev server for the UX walk (S43): the full v1 app on 127.0.0.1:8191 with the fake model.

  scripts/walk_server.py --setup     # create the scratch databases (needs the superuser DSN)
  PERCH_LIMIT_GPU=3 scripts/run_limited.sh uv run python scripts/walk_server.py

Setup copies `perch_dev` to `perch_walk` and `perch_keys_e2e` to `perch_walk_keys` on the test
Postgres container, migrates both, and gives the application roles a fixed throwaway password
(the test suite does the same on this container). The superuser DSN is used for that step only.
Serving needs Redis (database 14) and starts `perch worker` for the brief jobs. Everything is
SYNTHETIC or public; the secrets below are random per run and never leave the process. No .env
file is read. There is no Keycloak here: sign-in is walked from the main checkout with
`--login-helper` (see scripts/ux_walk.py), which needs the dev Keycloak and its client secret.
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
PORT = 8191
SUPER = os.environ.get("PERCH_WALK_SUPER_DSN", "postgresql://postgres:perchtest@127.0.0.1:55432/postgres")
REDIS = "redis://127.0.0.1:56379/14"
DB, KEYS_DB = "perch_walk", "perch_walk_keys"
ROLE_PW = "walk-throwaway-pw"


def _dsn(db: str, user: str | None = None) -> str:
    p = urlsplit(SUPER)
    host = f"{p.hostname}:{p.port}"
    netloc = f"{user}:{ROLE_PW}@{host}" if user else f"{p.username}:{p.password}@{host}"
    return urlunsplit((p.scheme, netloc, f"/{db}", "", ""))


def setup() -> None:
    import psycopg

    from perch.db.keys_migrate import apply_key_migrations
    from perch.db.migrate import migrate

    with psycopg.connect(SUPER, autocommit=True) as c:
        for name, template in ((DB, "perch_dev"), (KEYS_DB, "perch_keys_e2e")):
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            c.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
    migrate(_dsn(DB))
    apply_key_migrations(_dsn(KEYS_DB))
    with psycopg.connect(_dsn(DB), autocommit=True) as c:
        for role in ("perch_owner", "perch_web", "perch_worker", "perch_keys"):
            c.execute(f"ALTER ROLE {role} PASSWORD '{ROLE_PW}'")
    print(f"scratch databases {DB} and {KEYS_DB} ready")


def environment() -> None:
    os.environ.update(
        PERCH_PUBLIC_URL=f"http://127.0.0.1:{PORT}", PERCH_COOKIE_INSECURE="1",
        PERCH_LLM_DEFAULT="fake:fake-1", PERCH_STORED_BRIEFS="1",
        PERCH_DATABASE_URL=_dsn(DB, "perch_web"), PERCH_DATABASE_DIRECT_URL=_dsn(DB, "perch_web"),
        PERCH_KEYS_DATABASE_URL=_dsn(KEYS_DB, "perch_keys"), PERCH_REDIS_URL=REDIS,
        PERCH_PEPPER=secrets.token_hex(32), PERCH_PEPPER_GUEST=secrets.token_hex(32),
        PERCH_AUDIT_KEY=secrets.token_hex(32),
        PERCH_MASTER_KEY=base64.b64encode(secrets.token_bytes(32)).decode(), PERCH_MASTER_KEY_ID="walk",
        PERCH_CONSENT_PROVIDER_NAME="SYNTHETIC Provider", PERCH_CONSENT_VERSION="1",
        PERCH_BRIEFS_PER_HOUR="1000", PERCH_PROFILE=os.environ.get("PERCH_PROFILE", "cloud-gpu"))
    for k in ("PERCH_ENV", "ANTHROPIC_API_KEY", "PERCH_MODEL_SERVER"):
        os.environ.pop(k, None)
    if os.environ.get("PERCH_OIDC_CLIENT_SECRET"):  # set by the caller for the sign-in walk only
        os.environ.setdefault("PERCH_OIDC_ISSUER", "http://127.0.0.1:8180/realms/perch")
        os.environ.setdefault("PERCH_OIDC_CLIENT_ID", "perch-web")


def serve() -> None:
    import uvicorn

    environment()
    scratch = Path(tempfile.mkdtemp(prefix="perch-walk-"))
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    from perch import awards as aw
    from perch.api import create_app
    from perch.cli import default_client
    from perch.jobs import InProcessRunner
    from perch.service import BriefService, Clients, default_models
    from perch.store import pg
    from perch.store.hybrid import HybridRepository

    pool = pg.make_pool(os.environ["PERCH_DATABASE_URL"], 4)
    service = BriefService(str(scratch / "perch.db"), default_models(True, scratch, None),
                           Clients(openalex=default_client), Path(aw.OVERRIDES),
                           repo_factory=lambda: HybridRepository(pool, scratch / "briefs.db"))
    app = create_app(service, InProcessRunner(), stored_briefs=True)
    env = {**os.environ}
    log = open(scratch / "worker.log", "w")  # noqa: SIM115 - lives as long as the worker
    worker = subprocess.Popen(
        [sys.executable, "-m", "perch.cli", "--db", str(scratch / "perch.db"), "worker",
         "--concurrency", "2", "--kinds", "brief,purge"],
        env={**env, "PERCH_DATABASE_URL": _dsn(DB, "perch_worker"),
             "PERCH_DATABASE_DIRECT_URL": _dsn(DB, "perch_worker")},
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(300):
        if server.started:
            break
        time.sleep(0.1)
    print(f"walk server on http://127.0.0.1:{PORT} (worker log {scratch / 'worker.log'})", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        worker.terminate()
        server.should_exit = True


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--setup", action="store_true", help="create the scratch databases and stop")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    setup() if a.setup else serve()

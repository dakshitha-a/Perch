"""One-shot setup for the v1 Compose stack: apply both migration sets, then set the
passwords of the database roles from the environment.

The migrations create the roles without passwords (the operator sets them, never a
migration). Passwords come from env vars so no secret sits in a file. Prints names only.
"""

from __future__ import annotations

import os
import sys

import psycopg
from psycopg import sql

from perch.db.keys_migrate import apply_key_migrations
from perch.db.migrate import migrate

ROLES = {"perch_owner": "PERCH_OWNER_PASSWORD", "perch_web": "PERCH_WEB_PASSWORD",
         "perch_worker": "PERCH_WORKER_PASSWORD", "perch_keys": "PERCH_KEYS_PASSWORD"}


def main() -> int:
    admin, keys_admin = os.environ["ADMIN_DATABASE_URL"], os.environ["ADMIN_KEYS_DATABASE_URL"]
    print("perch:", ", ".join(migrate(admin)) or "already current")
    print("perch_keys:", ", ".join(apply_key_migrations(keys_admin)) or "already current")
    with psycopg.connect(admin, autocommit=True) as conn:
        for role, var in ROLES.items():
            pw = os.environ.get(var)
            if not pw:
                print(f"{var} is not set", file=sys.stderr)
                return 1
            conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(pw)))
    print("role passwords set")
    return 0


if __name__ == "__main__":
    sys.exit(main())

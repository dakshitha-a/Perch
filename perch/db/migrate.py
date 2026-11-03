"""Ordered, idempotent SQL migrations for the `perch` database.

Files in perch/db/migrations/perch/ are applied in name order, each in its own
transaction, and recorded in schema_migrations. The first file creates the roles, so the
connecting user needs CREATEROLE (a superuser in dev and test). Every later file runs as
perch_owner: the runner issues SET ROLE, so the objects belong to perch_owner whichever
admin user ran the migration. ARCHITECTURE_V1 sections 2.1 and 2.2.

Only file names are ever printed.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations" / "perch"
OWNER = "perch_owner"
LOCK_KEY = 7_262_001  # advisory lock so two migrate runs never interleave


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def migrate(dsn: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every migration not yet recorded; return the versions applied this run."""
    applied_now: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            # Created by the connecting user; 0001 hands it to perch_owner.
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                         "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            for path in migration_files(directory):
                version = path.stem
                if version in done:
                    continue
                if not version.startswith("0001_"):
                    _become_owner(conn)
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                applied_now.append(version)
        finally:
            conn.execute("RESET ROLE")
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    return applied_now


def _become_owner(conn: psycopg.Connection) -> None:
    who = conn.execute("SELECT current_user").fetchone()[0]
    if who != OWNER:
        conn.execute(f"SET ROLE {OWNER}")

"""User-data leakage check (S42; replaces scripts/private_canary.py).

Plants a SYNTHETIC CV, interests note, entry, research direction and Scout question, each
carrying a unique canary token, through the real account path: the account routes store them
encrypted, a brief job on a worker reads them with the fake model, a brief fails on purpose
with the CV text in the exception, and a bad upload is refused. Then it scans for every token
in: captured application logs and worker output, log files under the data directories, Redis
(every key and value), every plain-text column of every table in the perch database (found by
introspecting information_schema, which covers public_cache, audit_log, jobs, job_events and
the brief rows) and the files written under the data directory. `user_data.blob` is
ciphertext: the token must not appear in it as plain bytes either.

This module holds the pieces (the canary text, the scanners and the report). The scenario
runs in tests/test_leak_check.py on the test Postgres and Redis (`make test-user`), and

    uv run python scripts/leak_check.py [--results DIR]

runs that test and writes `<DIR>/result.json`. The report names each place and whether a token
was found there: token presence only, never any text. Exit code 1 if any token is found.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_TYPES = ("text", "character varying", "character", "json", "jsonb", "name", "citext",
              "ARRAY", "USER-DEFINED")


class Canary:
    """Unique tokens for one run, one per kind of text planted."""

    KINDS = ("cv", "interests", "entry", "direction", "question", "bad_upload", "failure")

    def __init__(self) -> None:
        run = secrets.token_hex(5).upper()
        self.tokens = {k: f"PERCH-LEAK-{k.upper().replace('_', '')}-{run}" for k in self.KINDS}

    def __getitem__(self, kind: str) -> str:
        return self.tokens[kind]

    def all(self) -> list[str]:
        return list(self.tokens.values())

    def label(self, token: str) -> str:
        return next(k for k, v in self.tokens.items() if v == token)


def synthetic_cv(token: str) -> str:
    """An invented CV (SYNTHETIC, rule 12). The token sits in several lines, as a name, an
    award and a project would."""
    return (f"# CV: SYNTHETIC Student {token}\n\n## Education\n"
            "- B.S. candidate, Biology, SYNTHETIC University, expected 2027\n"
            "- GPA 3.60\n\n## Honors\n"
            f"- SYNTHETIC Dean's Scholar award {token}, 2025\n\n## Activities\n"
            f"- Led a SYNTHETIC stream survey project {token} with four students\n\n"
            "## Skills\n- Field sampling\n- Python\n")


# --- scanners: each returns {place: [token labels found]}; never any text ---

def _found(blob: bytes | str, canary: Canary) -> list[str]:
    data = blob if isinstance(blob, bytes) else blob.encode("utf-8", "ignore")
    return [canary.label(t) for t in canary.all() if t.encode() in data]


def scan_text(label: str, text: str, canary: Canary) -> dict[str, list[str]]:
    return {label: _found(text, canary)}


def scan_files(label: str, roots: Iterable[Path], canary: Canary,
               skip: Iterable[Path] = ()) -> dict[str, list[str]]:
    """Every file under `roots`, read as bytes (SQLite files and JSONL alike)."""
    hits: set[str] = set()
    n = 0
    for root in roots:
        for p in (root.rglob("*") if root.is_dir() else [root]):
            try:
                if not p.is_file() or p.is_symlink() or any(s in p.parents for s in skip):
                    continue
                n += 1
                hits.update(_found(p.read_bytes(), canary))
            except OSError:
                continue
    return {f"{label} ({n} files)": sorted(hits)}


def scan_redis(r, canary: Canary) -> dict[str, list[str]]:  # noqa: ANN001 - a redis client
    """Every key name and every value, whatever the type."""
    hits: set[str] = set()
    n = 0
    for key in r.scan_iter("*", count=500):
        n += 1
        k = key if isinstance(key, str) else key.decode("utf-8", "ignore")
        hits.update(_found(k, canary))
        t = r.type(key)
        t = t if isinstance(t, str) else t.decode()
        if t == "string":
            vals = [r.get(key)]
        elif t == "hash":
            vals = [*r.hkeys(key), *r.hvals(key)]
        elif t == "list":
            vals = r.lrange(key, 0, -1)
        elif t == "set":
            vals = list(r.smembers(key))
        elif t == "zset":
            vals = [m for m, _ in r.zrange(key, 0, -1, withscores=True)]
        elif t == "stream":
            vals = [json.dumps(e, default=str) for e in r.xrange(key)]
        else:
            vals = []
        for v in vals:
            if v is not None:
                hits.update(_found(v if isinstance(v, bytes | str) else str(v), canary))
    return {f"redis ({n} keys)": sorted(hits)}


def scan_postgres(admin_dsn: str, canary: Canary) -> dict[str, list[str]]:
    """Every column of every table in the public schema whose type can hold text, found by
    introspection, plus every bytea column (user_data.blob is ciphertext: a token in it as
    plain bytes is a leak too). Rows are matched in the database; nothing is read back."""
    import psycopg
    from psycopg import sql

    out: dict[str, list[str]] = {}
    with psycopg.connect(admin_dsn, autocommit=True) as c:
        cols = c.execute(
            "SELECT c.table_name, c.column_name, c.data_type FROM information_schema.columns c "
            "JOIN information_schema.tables t USING (table_schema, table_name) "
            "WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE' "
            "ORDER BY 1, 2").fetchall()
        for table, col, dtype in cols:
            if dtype == "bytea":
                expr = sql.SQL("position({} in {}) > 0").format(
                    sql.Placeholder(), sql.Identifier(col))
                cast = "bytea"
            elif dtype in TEXT_TYPES or dtype.startswith(("character", "text")):
                expr = sql.SQL("position({} in {}::text) > 0").format(
                    sql.Placeholder(), sql.Identifier(col))
                cast = "text"
            else:
                continue
            found = []
            for token in canary.all():
                arg = token.encode() if cast == "bytea" else token
                q = sql.SQL("SELECT 1 FROM {} WHERE ").format(sql.Identifier(table)) + expr \
                    + sql.SQL(" LIMIT 1")
                if c.execute(q, (arg,)).fetchone():
                    found.append(canary.label(token))
            out[f"postgres {table}.{col}"] = sorted(set(found))
    return out


def report(places: dict[str, list[str]], *, planted: bool, commit: str | None = None) -> dict:
    """The result: each place with the kinds of token found there (names only), and a verdict.
    Places with nothing found are listed once as a count, except the ones the plan names."""
    named = ("postgres public_cache.", "postgres audit_log.", "postgres jobs.",
             "postgres job_events.", "postgres user_data.", "redis", "logs", "output", "files")
    hits = {p: k for p, k in places.items() if k}
    clean_named = sorted(p for p, k in places.items() if not k and p.startswith(named))
    return {"planted_leak": planted, "commit": commit, "passed": not hits,
            "places_scanned": len(places), "places_with_a_token": hits,
            "named_places_clean": clean_named,
            "token_kinds_planted": list(Canary.KINDS)}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", type=Path, default=None, help="write result.json here")
    ap.add_argument("--planted", action="store_true", help="label the run as planted-leak")
    args = ap.parse_args(argv)
    env = dict(os.environ)
    env.setdefault("PERCH_TEST_DATABASE_URL",
                   "postgresql://postgres:perchtest@127.0.0.1:55432/postgres")
    env.setdefault("PERCH_TEST_KEYS_DATABASE_URL", env["PERCH_TEST_DATABASE_URL"])
    env.setdefault("PERCH_TEST_REDIS_URL", "redis://127.0.0.1:56379/15")
    out = args.results or ROOT / "build/leak_check"
    out.mkdir(parents=True, exist_ok=True)
    env["PERCH_LEAK_RESULT"] = str(out / "result.json")
    env["PERCH_LEAK_PLANTED"] = "1" if args.planted else ""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True,
                                capture_output=True, check=False).stdout.strip()
    except OSError:
        commit = ""
    env["PERCH_LEAK_COMMIT"] = commit
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/test_leak_check.py", "-q",
                        "-p", "no:cacheprovider"], cwd=ROOT, env=env, check=False)
    res = out / "result.json"
    if res.exists():
        d = json.loads(res.read_text())
        print(f"leak check: {'PASS' if d['passed'] else 'FAIL'}; places with a token: "
              f"{sorted(d['places_with_a_token']) or 'none'}")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())

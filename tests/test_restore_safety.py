"""Restore safety (S48 review M3 and S1). SYNTHETIC text only.

The shred ledger is mandatory where accounts run, and a restore marker on its volume holds the
account routes at 503 until the worker has reconciled. The database test restores both the
data and the keys database to a state from before a shred and checks that the ledger alone
brings the shred back. It needs PERCH_TEST_DATABASE_URL, PERCH_TEST_REDIS_URL and
PERCH_TEST_KEYS_DATABASE_URL.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from perch import crypto, shredhooks
from perch.crypto import KeyShredded
from perch.keystore import EnvKeyStore
from perch.user.models import EntryDoc
from tests.test_user_account import KEYS_URL, env, rds, sql  # noqa: F401 - fixtures
from tests.test_user_account import pytestmark as DB_MARKS
from tests.user_helpers import make_env

TEXT = "SYNTHETIC entry for the restore safety test"


def db(f):
    """The Postgres and Redis skips of tests/test_user_account.py, on one test only: the
    ledger tests need no database."""
    for m in DB_MARKS:
        f = m(f)
    return f


# --- the ledger is mandatory (no database needed) ---

def test_without_a_ledger_directory_shred_hooks_refuse_to_install(monkeypatch, tmp_path):
    monkeypatch.delenv("PERCH_SHRED_LEDGER_OPTIONAL", raising=False)
    monkeypatch.delenv("PERCH_SHRED_LEDGER_URI", raising=False)
    with pytest.raises(shredhooks.LedgerMissing):
        shredhooks.install(None, None)  # type: ignore[arg-type]  # refused before any use
    monkeypatch.setenv("PERCH_SHRED_LEDGER_URI", "s3://bucket/prefix")  # not written yet
    with pytest.raises(shredhooks.LedgerMissing):
        shredhooks.require_ledger()
    monkeypatch.setenv("PERCH_SHRED_LEDGER_URI", str(tmp_path / "ledger"))
    assert shredhooks.require_ledger() == tmp_path / "ledger"
    assert (tmp_path / "ledger").is_dir()


def test_the_dev_flag_allows_running_without_a_ledger(monkeypatch):
    monkeypatch.setenv("PERCH_SHRED_LEDGER_OPTIONAL", "1")
    monkeypatch.delenv("PERCH_SHRED_LEDGER_URI", raising=False)
    assert shredhooks.require_ledger() is None


def test_a_pending_restore_holds_account_routes_at_503(monkeypatch, tmp_path):
    from tests.test_api import make

    monkeypatch.setenv("PERCH_SHRED_LEDGER_URI", str(tmp_path / "ledger"))
    shredhooks.mark_restore()
    assert shredhooks.restore_pending()
    c, _ = make(tmp_path)
    for path in ("/me/briefs", "/usage", "/auth/session", "/briefs/x"):
        r = c.get(path)
        assert r.status_code == 503 and r.json()["detail"]["error"] == "restore_pending", path
        assert r.headers["retry-after"] == "60"
    assert c.get("/health").status_code == 200  # public routes still serve
    (tmp_path / "ledger" / shredhooks.RESTORE_MARKER).unlink()
    c2, _ = make(tmp_path / "again")
    assert c2.get("/briefs/x").status_code != 503
    # the marker is never read as a user id
    shredhooks.mark_restore()
    assert shredhooks.ledger_hook()  # still a valid ledger
    assert not shredhooks.restore_pending(str(tmp_path / "elsewhere"))


# --- a restore of both databases from before a shred ---

def _keys_db():
    name = f"perch_test_b_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(KEYS_URL, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    p = urlsplit(KEYS_URL)
    admin = urlunsplit((p.scheme, p.netloc, "/" + name, "", ""))
    from perch.db.keys_migrate import apply_key_migrations

    apply_key_migrations(admin)
    with psycopg.connect(KEYS_URL, autocommit=True) as c:
        c.execute("ALTER ROLE perch_keys PASSWORD 'rt'")
    rt = urlunsplit((p.scheme, f"perch_keys:rt@{p.hostname}:{p.port}", "/" + name, "", ""))
    return name, admin, rt


def _admin(url: str, query: str, *args):
    with psycopg.connect(url, autocommit=True) as c:
        cur = c.execute(query, args)
        return cur.fetchall() if cur.description else []


@pytest.mark.skipif(not KEYS_URL, reason="PERCH_TEST_KEYS_DATABASE_URL is not set")
@db
def test_restoring_both_databases_from_before_a_shred_is_undone_by_the_ledger(
        env, pg_clean, worker_pool, tmp_path):  # noqa: F811
    from perch.keystore import KeyRepository
    from perch.shredhooks import ledger_hook, shred_log_hook

    ledger = tmp_path / "ledger"
    name, admin, rt = _keys_db()
    repo = KeyRepository(rt)
    try:
        crypto.configure(repo=repo, keystore=EnvKeyStore(make_env()),
                         shred_hooks=[shred_log_hook(env.pool), ledger_hook(str(ledger))])
        rid = env.ud.put(env.uid, "entry", "student", EntryDoc(text=TEXT))
        # 1. The nightly dumps of both databases, taken before the user deletes their data.
        sql(pg_clean, "CREATE TABLE snap_users AS SELECT * FROM users WHERE id = %s", env.uid)
        sql(pg_clean, "CREATE TABLE snap_data AS SELECT * FROM user_data WHERE user_id = %s",
            env.uid)
        _admin(admin, "CREATE TABLE snap_keys AS SELECT * FROM user_keys WHERE user_id = %s",
               env.uid)
        # 2. Delete-my-data: tombstone, shred_log, ledger object; then the rows are purged.
        crypto.shred(env.uid)
        sql(pg_clean, "SELECT perch_delete_user_rows(%s)", env.uid)
        assert (ledger / str(env.uid)).is_file()
        # 3. Both databases are restored from the dumps of step 1: the tombstone, the shred_log
        #    row, the key rows, the users row and the data rows all go back together.
        _admin(admin, "DELETE FROM key_tombstones")
        _admin(admin, "INSERT INTO user_keys SELECT * FROM snap_keys")
        sql(pg_clean, "DELETE FROM shred_log")
        sql(pg_clean, "INSERT INTO users SELECT * FROM snap_users")
        sql(pg_clean, "INSERT INTO user_data SELECT * FROM snap_data")
        crypto.clear_cache()
        assert env.ud.get(env.uid, rid, EntryDoc).text == TEXT  # the user is revived
        # Without the ledger nothing remembers the shred.
        assert shredhooks.tombstone_union(rt, worker_pool, str(tmp_path / "none")) == set()
        # 4. The restore marker was written; the worker reconciles before any job runs.
        shredhooks.mark_restore(str(ledger))
        res = shredhooks.reconcile_if_restored(rt, worker_pool, str(ledger))
        assert res == {"ids": 1, "key_rows_revived": 1, "user_rows_removed": 1}
        assert not shredhooks.restore_pending(str(ledger))
        crypto.clear_cache()
        # The rows are gone, and a data row restored again later cannot be read.
        assert sql(pg_clean, "SELECT count(*) FROM user_data WHERE user_id = %s",
                   env.uid) == [(0,)]
        sql(pg_clean, "INSERT INTO users SELECT * FROM snap_users")
        sql(pg_clean, "INSERT INTO user_data SELECT * FROM snap_data")
        with pytest.raises(KeyShredded):
            env.ud.get(env.uid, rid, EntryDoc)
        sql(pg_clean, "SELECT perch_delete_user_rows(%s)", env.uid)
        assert _admin(admin, "SELECT count(*) FROM user_keys WHERE user_id = %s",
                      env.uid) == [(0,)]
        assert _admin(admin, "SELECT count(*) FROM key_tombstones WHERE user_id = %s",
                      env.uid) == [(1,)]
        assert sql(pg_clean, "SELECT count(*) FROM users WHERE id = %s", env.uid) == [(0,)]
        assert sql(pg_clean, "SELECT count(*) FROM user_data WHERE user_id = %s",
                   env.uid) == [(0,)]
        assert shredhooks.reconcile_if_restored(rt, worker_pool, str(ledger)) is None
    finally:
        repo.close()
        crypto.configure()
        sql(pg_clean, "DROP TABLE IF EXISTS snap_users, snap_data")
        with psycopg.connect(KEYS_URL, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@db
def test_reconcile_cli_removes_a_restored_users_row(env, pg_clean, worker_pool):  # noqa: F811
    """S1: the users row of a shredded user that a restore brought back is deleted too."""
    crypto.shred(env.uid)  # in-memory keys; shred_log gets the row through the hook
    assert sql(pg_clean, "SELECT count(*) FROM users WHERE id = %s", env.uid) == [(1,)]
    ids = {r[0] for r in sql(pg_clean, "SELECT user_id FROM shred_log")}
    assert ids == {env.uid}
    from unittest import mock

    with mock.patch.object(shredhooks, "tombstone_union", return_value=ids):
        res = shredhooks.reconcile("unused", worker_pool)
    assert res["user_rows_removed"] == 1
    assert sql(pg_clean, "SELECT count(*) FROM users WHERE id = %s", env.uid) == [(0,)]
    assert sql(pg_clean, "SELECT count(*) FROM shred_log WHERE user_id = %s", env.uid) == [(1,)]

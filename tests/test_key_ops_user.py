"""Rekey, tombstone retention and restore safety against the data database (S48).

SYNTHETIC text only. Needs PERCH_TEST_DATABASE_URL and PERCH_TEST_REDIS_URL, like
test_user_account.py, whose fixtures and helpers it reuses.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from perch import crypto, keyops
from perch.crypto import KeyShredded
from perch.jobs import PostgresRunner
from perch.user.models import EntryDoc
from tests.test_user_account import (  # noqa: F401  fixtures and helpers
    FAST,
    env,
    job_state,
    pytestmark,
    rds,
    run_worker,
    sql,
)
from tests.user_helpers import new_user

TEXT = "SYNTHETIC entry text for the key operations tests"


def _versions(pg, uid):
    return sorted(r[0] for r in sql(pg, "SELECT key_version FROM user_data WHERE user_id = %s",
                                    uid))


def _seed(env_, n=3):
    ids = [env_.ud.put(env_.uid, "entry", "student", EntryDoc(text=f"{TEXT} {i}"))
           for i in range(n)]
    env_.ud.link_openalex(env_.uid, "A0000000001")
    return ids


def test_rekey_moves_every_blob_to_the_newest_version(env, pg_clean, worker_pool):
    ids = _seed(env)
    stamps = {r[0]: r[1] for r in sql(pg_clean, "SELECT id, updated_at FROM user_data")}
    assert crypto.rotate_data_key(env.uid) == 2
    assert _versions(pg_clean, env.uid) == [1, 1, 1]
    assert keyops.rekey_user(worker_pool, env.uid, dry_run=True) == {
        "stale": 4, "done": 0, "failed": 0}  # three rows and the OpenAlex link
    assert _versions(pg_clean, env.uid) == [1, 1, 1]
    assert keyops.rekey_user(worker_pool, env.uid, batch=2) == {
        "stale": 4, "done": 4, "failed": 0}
    assert _versions(pg_clean, env.uid) == [2, 2, 2]
    assert {r[0]: r[1] for r in sql(pg_clean, "SELECT id, updated_at FROM user_data")} == stamps
    for i, rid in enumerate(ids):
        assert env.ud.get(env.uid, rid, EntryDoc).text == f"{TEXT} {i}"
    assert env.ud.linked_openalex(env.uid) == "A0000000001"
    # idempotent, and the old key version is still stored and readable
    assert keyops.rekey_user(worker_pool, env.uid) == {"stale": 0, "done": 0, "failed": 0}
    assert env.keys.get(env.uid, 1) is not None


def test_rekey_all_lists_only_rotated_users(env, pg_clean, worker_pool):
    _seed(env)
    other = new_user(pg_clean)
    env.ud.put(other, "entry", "student", EntryDoc(text=TEXT))
    crypto.rotate_data_key(env.uid)
    assert keyops.rekey_all(worker_pool, dry_run=True) == {
        "users": 1, "stale": 4, "done": 0, "failed": 0}
    assert keyops.rekey_all(worker_pool) == {"users": 1, "stale": 4, "done": 4, "failed": 0}
    assert keyops.rekey_all(worker_pool) == {"users": 1, "stale": 0, "done": 0, "failed": 0}
    assert _versions(pg_clean, other) == [1]


def test_rekey_leaves_an_undecryptable_row_and_reports_it(env, pg_clean, worker_pool):
    ids = _seed(env, 2)
    crypto.rotate_data_key(env.uid)
    sql(pg_clean, "UPDATE user_data SET blob = set_byte(blob, 30, 255 - get_byte(blob, 30)) "
        "WHERE id = %s", ids[0])  # a damaged blob
    res = keyops.rekey_user(worker_pool, env.uid)
    assert res["failed"] == 1 and res["done"] == 2  # the other row and the link moved
    assert env.ud.get(env.uid, ids[1], EntryDoc).text == f"{TEXT} 1"


def test_rekey_purge_job_audits_counts_only(env, pg_clean):
    _seed(env)
    crypto.rotate_data_key(env.uid)
    runner = PostgresRunner(pg_clean.worker, timing=FAST, pool_size=4)
    try:
        jid = runner.submit("purge", {"action": "rekey", "user_id": str(env.uid)}, None, "rk-1")
        run_worker(pg_clean, ["purge"], lambda: job_state(pg_clean, jid) == "succeeded")
        assert job_state(pg_clean, jid) == "succeeded"
    finally:
        runner.close()
    assert _versions(pg_clean, env.uid) == [2, 2, 2]
    detail = sql(pg_clean, "SELECT detail FROM audit_log WHERE event = 'key_rotate_data'")[0][0]
    assert detail == {"user_id": str(env.uid), "stale": 4, "done": 4, "failed": 0}
    assert TEXT not in json.dumps(detail)


def test_rekey_does_nothing_for_a_shredded_user(env, pg_clean, worker_pool):
    _seed(env)
    crypto.rotate_data_key(env.uid)
    crypto.shred(env.uid)
    assert keyops.rekey_user(worker_pool, env.uid) == {"stale": 0, "done": 0, "failed": 0}


def _shred_aged(env_, pg, uid, days):
    crypto.shred(uid)
    sql(pg, "UPDATE shred_log SET shredded_at = now() - %s * interval '1 day' "
        "WHERE user_id = %s", days, uid)
    env_.keys.tombstone_at[uid] = datetime.now(UTC) - timedelta(days=days)


def test_tombstone_purge_removes_all_three_copies_past_retention(env, pg_clean, worker_pool,
                                                                 tmp_path):
    old, recent = new_user(pg_clean), new_user(pg_clean)
    for u in (old, recent):
        env.ud.put(u, "entry", "student", EntryDoc(text=TEXT))
    _shred_aged(env, pg_clean, old, 401)
    _shred_aged(env, pg_clean, recent, 36)  # inside any backup window
    (tmp_path / str(old)).write_text((datetime.now(UTC) - timedelta(days=401)).date().isoformat()
                                     + "\n")
    (tmp_path / str(recent)).write_text(datetime.now(UTC).date().isoformat() + "\n")
    (tmp_path / "notes.txt").write_text("not a ledger object")
    dry = keyops.purge_old_tombstones(worker_pool, dry_run=True, ledger=str(tmp_path))
    assert dry == {"retention_days": 400, "ledger": 1, "shred_log": 1, "key_tombstones": 1}
    assert env.keys.tombstones == {old, recent}
    assert len(list(tmp_path.iterdir())) == 3
    done = keyops.purge_old_tombstones(worker_pool, dry_run=False, ledger=str(tmp_path))
    assert done == dry
    assert env.keys.tombstones == {recent}
    assert [r[0] for r in sql(pg_clean, "SELECT user_id FROM shred_log")] == [recent]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([str(recent), "notes.txt"])
    again = keyops.purge_old_tombstones(worker_pool, dry_run=False, ledger=str(tmp_path))
    assert again["key_tombstones"] == again["shred_log"] == again["ledger"] == 0
    with pytest.raises(crypto.CryptoError):  # under the floor
        keyops.purge_old_tombstones(worker_pool, dry_run=False, days=399)


def test_worker_role_cannot_delete_a_recent_shred_log_row(env, pg_clean, worker_pool):
    recent = new_user(pg_clean)
    _shred_aged(env, pg_clean, recent, 36)
    with worker_pool.connection() as c:
        n = c.execute("DELETE FROM shred_log").rowcount  # the policy hides rows under 400 days
    assert n == 0
    assert sql(pg_clean, "SELECT count(*) FROM shred_log") == [(1,)]


def test_tombstones_purge_job_audits_counts(env, pg_clean):
    old = new_user(pg_clean)
    _shred_aged(env, pg_clean, old, 401)
    runner = PostgresRunner(pg_clean.worker, timing=FAST, pool_size=4)
    try:
        jid = runner.submit("purge", {"action": "tombstones"}, None, "tb-1")
        run_worker(pg_clean, ["purge"], lambda: job_state(pg_clean, jid) == "succeeded")
        assert job_state(pg_clean, jid) == "succeeded"
    finally:
        runner.close()
    assert old not in env.keys.tombstones
    detail = sql(pg_clean, "SELECT detail FROM audit_log WHERE event = 'tombstones_purge'")[0][0]
    assert detail["key_tombstones"] == 1 and detail["shred_log"] == 1
    assert set(detail) == {"retention_days", "ledger", "shred_log", "key_tombstones"}


def test_restored_row_of_a_tombstoned_user_cannot_be_decrypted(env, pg_clean):
    """Restore safety: a backup brings back the user's rows and key rows; the tombstone, kept
    for longer than any backup, keeps them unreadable, and when the whole keys database is
    restored and loses it, the other copies re-assert it."""
    rid = env.ud.put(env.uid, "entry", "student", EntryDoc(text=TEXT))
    row = sql(pg_clean, "SELECT id, user_id, kind, audience, key_version, blob FROM user_data "
              "WHERE id = %s", rid)[0]
    keys_snapshot = dict(env.keys.keys)
    crypto.shred(env.uid)
    sql(pg_clean, "DELETE FROM user_data WHERE id = %s", rid)  # the live rows were purged
    # 1. The old rows and old key rows come back from backups.
    sql(pg_clean, "INSERT INTO user_data (id, user_id, kind, audience, key_version, blob) "
        "VALUES (%s, %s, %s, %s, %s, %s)", *row)
    with pytest.raises(KeyShredded):
        env.keys.put(next(iter(keys_snapshot.values())))  # the trigger rule: refused
    with pytest.raises(KeyShredded):
        env.ud.get(env.uid, rid, EntryDoc)
    # 2. The keys database is restored whole and loses the tombstone: the data is revived.
    env.keys.keys.update(keys_snapshot)
    env.keys.tombstones.clear()
    crypto.clear_cache()
    assert env.ud.get(env.uid, rid, EntryDoc).text == TEXT  # the risk being guarded
    # 3. Reconcile from the shred_log copy, as the restore runbook requires.
    ids = {r[0] for r in sql(pg_clean, "SELECT user_id FROM shred_log")}
    assert ids == {env.uid}
    assert crypto.reconcile_shreds(ids) == 1
    with pytest.raises(KeyShredded):
        env.ud.get(env.uid, rid, EntryDoc)
    assert env.keys.latest(env.uid) is None
    assert UUID(str(env.uid)) in env.keys.tombstones

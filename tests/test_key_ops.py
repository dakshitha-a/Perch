"""Master-key dry run, tombstone retention and the rotated-user listing (S48).
In-memory tests always run; the Postgres ones need PERCH_TEST_KEYS_DATABASE_URL.
SYNTHETIC text only."""

from __future__ import annotations

import base64
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from perch import crypto
from perch.crypto import Aad, CryptoError
from perch.keystore import EnvKeyStore, InMemoryKeyRepository
from tests.test_keystore import (  # noqa: F401  fixtures
    keys_db,
    needs_db,
    repo,
    runtime_url,
)

CANARY = b"SYNTHETIC-canary-keyops-2c8e"


def aad_for(uid, row="r1"):
    return Aad(uid, "user_data", "blob", row, "cv:researcher")


def make_env(mid, prev=None, key=None):
    env = {"PERCH_MASTER_KEY": base64.b64encode(key or os.urandom(32)).decode(),
           "PERCH_MASTER_KEY_ID": mid}
    if prev:
        env["PERCH_MASTER_KEY_PREV_ID"] = prev[0]
        env["PERCH_MASTER_KEY_PREV"] = base64.b64encode(prev[1]).decode()
    return env


@pytest.fixture
def mem():
    r = InMemoryKeyRepository()
    crypto.configure(repo=r, keystore=EnvKeyStore(make_env("m1")))
    yield r
    crypto.configure()


def enc(u, plain=CANARY, row="r1"):
    return crypto.encrypt_field(u, plain, aad_for(u, row), create=True)


def test_rotate_master_dry_run_counts_and_changes_nothing():
    old_key = os.urandom(32)
    r = InMemoryKeyRepository()
    crypto.configure(repo=r, keystore=EnvKeyStore(make_env("m1", key=old_key)))
    users = [uuid4() for _ in range(4)]
    blobs = {u: enc(u) for u in users}
    crypto.configure(repo=r, keystore=EnvKeyStore(make_env("m2", prev=("m1", old_key))))
    before = dict(r.keys)
    assert crypto.rotate_master("m1", "m2", dry_run=True) == 4
    assert r.keys == before
    assert crypto.rotate_master("m1", "m2") == 4
    assert crypto.rotate_master("m1", "m2", dry_run=True) == 0  # idempotent: nothing left
    assert crypto.rotate_master("m1", "m2") == 0
    for u in users:  # the old id stayed readable throughout, and the new one reads everything
        assert crypto.decrypt_field(u, blobs[u], aad_for(u)) == CANARY
    crypto.configure()


def test_tombstone_retention_floor():
    assert crypto.tombstone_retention_days(35) == 400
    assert crypto.tombstone_retention_days(35, 500) == 500
    with pytest.raises(CryptoError):
        crypto.tombstone_retention_days(35, 399)
    with pytest.raises(CryptoError):  # a backup kept longer than 400 days lifts the floor
        crypto.tombstone_retention_days(500, 450)


def test_purge_tombstones_keeps_recent_ones_and_dry_run_deletes_nothing(mem):
    old, recent = uuid4(), uuid4()
    for u in (old, recent):
        enc(u)
        crypto.shred(u)
    mem.tombstone_at[old] = datetime.now(UTC) - timedelta(days=401)
    with pytest.raises(CryptoError):
        crypto.purge_tombstones(399, dry_run=False)
    assert crypto.purge_tombstones(400, dry_run=True) == 1
    assert mem.tombstones == {old, recent}
    assert crypto.purge_tombstones(400, dry_run=False) == 1
    assert mem.tombstones == {recent}
    assert crypto.purge_tombstones(400, dry_run=False) == 0  # idempotent


def test_purged_tombstone_is_older_than_any_backup_that_could_hold_the_key(mem):
    """A tombstone younger than the longest backup (35 days by default) is never purged."""
    u = uuid4()
    enc(u)
    crypto.shred(u)
    mem.tombstone_at[u] = datetime.now(UTC) - timedelta(days=36)
    assert crypto.purge_tombstones(crypto.tombstone_retention_days(35), dry_run=False) == 0
    assert u in mem.tombstones


def test_rotated_user_listing(mem):
    a, b = uuid4(), uuid4()
    enc(a)
    enc(b)
    crypto.new_data_key(a)
    assert crypto.users_with_rotated_keys(None, 10) == [(a, 2)]
    assert crypto.users_with_rotated_keys(a, 10) == []
    assert crypto.newest_version(a) == 2 and crypto.newest_version(uuid4()) is None


@needs_db
def test_purge_tombstones_function_in_postgres(repo, keys_db):
    old, recent = uuid4(), uuid4()
    for u in (old, recent):
        enc(u)
        crypto.shred(u)
    with psycopg.connect(keys_db, autocommit=True) as c:  # owner side: backdate one
        c.execute("UPDATE key_tombstones SET shredded_at = now() - interval '401 days' "
                  "WHERE user_id = %s", (old,))
    with pytest.raises(CryptoError):
        crypto.purge_tombstones(399, dry_run=False)
    with pytest.raises(psycopg.errors.Error):  # the database refuses a short age itself
        repo.purge_tombstones(30, dry_run=False)
    assert crypto.purge_tombstones(400, dry_run=True) == 1
    assert repo.is_tombstoned(old) and repo.is_tombstoned(recent)
    assert crypto.purge_tombstones(400, dry_run=False) == 1
    assert not repo.is_tombstoned(old) and repo.is_tombstoned(recent)
    assert crypto.purge_tombstones(400, dry_run=False) == 0


@needs_db
def test_rotated_listing_and_master_count_in_postgres(repo):
    a, b = uuid4(), uuid4()
    enc(a)
    enc(b)
    crypto.new_data_key(a)
    assert crypto.users_with_rotated_keys(None, 10) == [(a, 2)]
    assert crypto.users_with_rotated_keys(a, 10) == []
    assert repo.count_for_master("m1") == 3

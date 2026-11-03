"""perch.keystore: key stores always; the Postgres repository when PERCH_TEST_KEYS_DATABASE_URL
is set (a superuser URL; the tests create and drop databases named perch_test_b_*).
SYNTHETIC text only."""

from __future__ import annotations

import base64
import os
import threading
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest

from perch import crypto
from perch.crypto import Aad, CryptoError, DecryptError, KeyMissing, KeyShredded
from perch.db.keys_migrate import apply_key_migrations, pending_files
from perch.keystore import (
    EnvKeyStore,
    KeyRepository,
    KmsKeyStore,
    WrappedKey,
    key_store,
)

CANARY = b"SYNTHETIC-canary-entry-text-91bd"


def enc(user_id, plaintext, aad):
    """First-write encrypt: the caller says it may create version 1."""
    return crypto.encrypt_field(user_id, plaintext, aad, create=True)


ADMIN_URL = os.environ.get("PERCH_TEST_KEYS_DATABASE_URL", "")


def b64(n: int = 32) -> str:
    return base64.b64encode(os.urandom(n)).decode()


# ---- key stores, no database ----


def test_env_store_wrap_unwrap():
    ks = EnvKeyStore({"PERCH_MASTER_KEY": b64(), "PERCH_MASTER_KEY_ID": "m1"})
    uid = uuid4()
    key = os.urandom(32)
    wrapped, mid = ks.wrap(key, user_id=uid, key_version=1)
    assert mid == ks.current_master_id == "m1"
    assert key not in wrapped
    assert ks.unwrap(WrappedKey(uid, 1, wrapped, mid)) == key
    with pytest.raises(DecryptError):  # AAD binds user and version
        ks.unwrap(WrappedKey(uuid4(), 1, wrapped, mid))
    with pytest.raises(DecryptError):
        ks.unwrap(WrappedKey(uid, 2, wrapped, mid))


def test_env_store_rejects_bad_keys_without_echoing():
    secret = base64.b64encode(b"short").decode()
    with pytest.raises(CryptoError) as e:
        EnvKeyStore({"PERCH_MASTER_KEY": secret})
    assert secret not in str(e.value)
    with pytest.raises(CryptoError):
        EnvKeyStore({})
    with pytest.raises(CryptoError):
        EnvKeyStore({"PERCH_MASTER_KEY": "not base64!!"})


def test_env_store_refused_in_prod():
    with pytest.raises(CryptoError):
        EnvKeyStore({"PERCH_MASTER_KEY": b64(), "PERCH_ENV": "prod"})
    with pytest.raises(CryptoError):
        key_store({"PERCH_MASTER_KEY": b64(), "PERCH_ENV": "prod", "PERCH_KEYSTORE": "env"})


def test_kms_stub_names_missing_config():
    with pytest.raises(NotImplementedError, match="PERCH_KMS_KEY_URI"):
        KmsKeyStore({})
    with pytest.raises(NotImplementedError, match="UNVERIFIED"):
        key_store({"PERCH_KEYSTORE": "kms", "PERCH_KMS_KEY_URI": "kms://example"})
    with pytest.raises(NotImplementedError):  # prod default is kms
        key_store({"PERCH_ENV": "prod"})


def test_key_store_default_is_env_in_dev():
    assert isinstance(
        key_store({"PERCH_MASTER_KEY": b64(), "PERCH_MASTER_KEY_ID": "m1"}), EnvKeyStore
    )
    with pytest.raises(CryptoError):
        key_store({"PERCH_MASTER_KEY": b64(), "PERCH_KEYSTORE": "bogus"})


def test_prev_key_reads_old_wrapping():
    old = os.urandom(32)
    ks_old = EnvKeyStore(
        {"PERCH_MASTER_KEY": base64.b64encode(old).decode(), "PERCH_MASTER_KEY_ID": "m1"}
    )
    uid = uuid4()
    key = os.urandom(32)
    wrapped, mid = ks_old.wrap(key, user_id=uid, key_version=1)
    ks_new = EnvKeyStore(
        {
            "PERCH_MASTER_KEY": b64(),
            "PERCH_MASTER_KEY_ID": "m2",
            "PERCH_MASTER_KEY_PREV": base64.b64encode(old).decode(),
            "PERCH_MASTER_KEY_PREV_ID": "m1",
        }
    )
    assert ks_new.unwrap(WrappedKey(uid, 1, wrapped, mid)) == key
    with pytest.raises(CryptoError):
        EnvKeyStore({"PERCH_MASTER_KEY": b64(), "PERCH_MASTER_KEY_PREV": b64()})


# ---- Postgres key repository ----

needs_db = pytest.mark.skipif(not ADMIN_URL, reason="PERCH_TEST_KEYS_DATABASE_URL not set")


def _with_db(url: str, name: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, "/" + name, p.query, p.fragment))


@pytest.fixture
def keys_db():
    name = f"perch_test_b_{uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    url = _with_db(ADMIN_URL, name)
    try:
        yield url
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _as_runtime(url: str) -> str:
    """The same database, logged in as the runtime role perch_keys (grants are exercised)."""
    p = urlsplit(url)
    return urlunsplit((p.scheme, f"perch_keys:rt@{p.hostname}:{p.port}", p.path, "", ""))


@pytest.fixture
def runtime_url(keys_db):
    apply_key_migrations(keys_db)
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute("ALTER ROLE perch_keys PASSWORD 'rt'")
    return _as_runtime(keys_db)


@pytest.fixture
def repo(keys_db, runtime_url):
    r = KeyRepository(runtime_url)
    crypto.configure(
        repo=r, keystore=EnvKeyStore({"PERCH_MASTER_KEY": b64(), "PERCH_MASTER_KEY_ID": "m1"})
    )
    yield r
    crypto.configure()
    r.close()


def aad_for(uid, row="row-1"):
    return Aad(uid, "user_data", "blob", row, "cv:researcher")


@needs_db
def test_migrations_apply_once_and_in_order(keys_db):
    names = [p.stem for p in pending_files()]
    assert names == sorted(names) and names
    assert apply_key_migrations(keys_db) == names
    assert apply_key_migrations(keys_db) == []
    with psycopg.connect(keys_db) as c:
        tables = {
            r[0]
            for r in c.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
        owners = {
            r[0]
            for r in c.execute(
                "SELECT tableowner FROM pg_tables WHERE tablename IN ('user_keys','key_tombstones')"
            )
        }
    assert {"user_keys", "key_tombstones", "schema_migrations"} <= tables
    assert owners == {"perch_keys_owner"}


@needs_db
def test_only_perch_keys_can_read_user_keys(keys_db):
    apply_key_migrations(keys_db)
    other = f"perch_test_b_role_{uuid4().hex[:8]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f"CREATE ROLE \"{other}\" LOGIN PASSWORD 'x'")
    try:
        p = urlsplit(keys_db)
        url = urlunsplit((p.scheme, f"{other}:x@{p.hostname}:{p.port}", p.path, "", ""))
        with pytest.raises(psycopg.Error):
            with psycopg.connect(url) as c:
                c.execute("SELECT * FROM user_keys")
        with psycopg.connect(ADMIN_URL, autocommit=True) as c:
            c.execute(f'GRANT CONNECT ON DATABASE "{p.path[1:]}" TO "{other}"')
        with psycopg.connect(keys_db, autocommit=True) as c:  # schema usage, so tables are seen
            c.execute(f'GRANT USAGE ON SCHEMA public TO "{other}"')
        with psycopg.connect(url) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT * FROM user_keys")
            c.rollback()
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT * FROM key_tombstones")
    finally:
        with psycopg.connect(keys_db, autocommit=True) as c:
            c.execute(f'DROP OWNED BY "{other}"')
        with psycopg.connect(ADMIN_URL, autocommit=True) as c:
            c.execute(f'DROP ROLE "{other}"')


@needs_db
def test_repository_basics(repo):
    uid = uuid4()
    assert repo.latest(uid) is None and repo.get(uid, 1) is None
    wk1 = WrappedKey(uid, 1, b"\x01" + b"w" * 40, "m1")
    assert repo.put(wk1) is True
    assert repo.put(wk1) is False  # ON CONFLICT DO NOTHING
    repo.put(WrappedKey(uid, 2, b"\x01" + b"v" * 40, "m1"))
    assert repo.get(uid, 1) == wk1
    assert repo.latest(uid).key_version == 2
    assert len(repo.all_for_master("m1", 10)) == 2
    assert len(repo.all_for_master("m1", 1)) == 1
    assert repo.all_for_master("nope", 10) == []
    assert repo.delete_all(uid) == 2


@needs_db
def test_trigger_refuses_key_for_tombstoned_user(repo):
    uid = uuid4()
    repo.tombstone(uid)
    repo.tombstone(uid)  # idempotent
    assert repo.is_tombstoned(uid)
    with pytest.raises(KeyShredded):
        repo.put(WrappedKey(uid, 1, b"\x01" + b"w" * 40, "m1"))
    assert repo.latest(uid) is None


@needs_db
def test_round_trip_and_aad_through_postgres(repo):
    uid = uuid4()
    aad = aad_for(uid)
    blob = enc(uid, CANARY, aad)
    crypto.clear_cache()  # force an unwrap from the database
    assert crypto.decrypt_field(uid, blob, aad) == CANARY
    with pytest.raises(DecryptError):
        crypto.decrypt_field(uid, blob, aad_for(uid, "row-2"))


@needs_db
def test_racing_first_writes_agree_on_one_key(repo):
    uid = uuid4()
    aad = aad_for(uid)
    blobs: list[bytes] = []
    barrier = threading.Barrier(6)

    def work():
        barrier.wait()
        blobs.append(enc(uid, CANARY, aad))

    threads = [threading.Thread(target=work) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(blobs) == 6
    assert len(repo.all_for_master("m1", 100)) == 1
    crypto.clear_cache()
    assert all(crypto.decrypt_field(uid, b, aad) == CANARY for b in blobs)


@needs_db
def test_rotate_master_in_postgres(repo, keys_db):
    old = os.urandom(32)
    crypto.configure(
        repo=repo,
        keystore=EnvKeyStore(
            {"PERCH_MASTER_KEY": base64.b64encode(old).decode(), "PERCH_MASTER_KEY_ID": "m1"}
        ),
    )
    users = [uuid4() for _ in range(5)]
    blobs = {u: enc(u, CANARY, aad_for(u)) for u in users}
    ks = EnvKeyStore(
        {
            "PERCH_MASTER_KEY": b64(),
            "PERCH_MASTER_KEY_ID": "m2",
            "PERCH_MASTER_KEY_PREV": base64.b64encode(old).decode(),
            "PERCH_MASTER_KEY_PREV_ID": "m1",
        }
    )
    crypto.configure(repo=repo, keystore=ks)
    assert crypto.rotate_master("m1", "m2", batch=2) == 5
    assert repo.all_for_master("m1", 10) == []
    for u in users:
        assert crypto.decrypt_field(u, blobs[u], aad_for(u)) == CANARY


@needs_db
def test_shred_in_postgres_and_restore_does_not_revive(repo, keys_db):
    uid, other = uuid4(), uuid4()
    aad, aad_o = aad_for(uid), aad_for(other)
    blob = enc(uid, CANARY, aad)
    keep = enc(other, b"keep", aad_o)
    # Snapshot of the keys database before the shred (a backup).
    with psycopg.connect(keys_db) as c:
        snap = c.execute(
            "SELECT user_id, key_version, wrapped_key, master_key_id FROM user_keys"
        ).fetchall()
    crypto.shred(uid)
    crypto.clear_cache()
    with pytest.raises(KeyShredded):
        crypto.decrypt_field(uid, blob, aad)
    with pytest.raises(KeyShredded):
        enc(uid, b"x", aad)
    assert crypto.decrypt_field(other, keep, aad_o) == b"keep"
    assert repo.is_tombstoned(uid) and repo.latest(uid) is None

    # 1. Restoring only the key rows is refused by the trigger.
    with pytest.raises(KeyShredded):
        for uid_, ver, wrapped, mid in snap:
            if uid_ == uid:
                repo.put(WrappedKey(uid_, ver, bytes(wrapped), mid))

    # 2. Restoring the whole keys database to the old snapshot loses the tombstone.
    with psycopg.connect(keys_db, autocommit=True) as c:
        c.execute("TRUNCATE key_tombstones, user_keys")
        for uid_, ver, wrapped, mid in snap:
            c.execute(
                "INSERT INTO user_keys (user_id, key_version, wrapped_key, master_key_id) "
                "VALUES (%s, %s, %s, %s)",
                (uid_, ver, wrapped, mid),
            )
    crypto.clear_cache()
    assert crypto.decrypt_field(uid, blob, aad) == CANARY  # revived: the risk being guarded
    # 3. Reconcile with the other tombstone copies (shred_log, ledger) closes it.
    assert crypto.reconcile_shreds({uid}) == 1
    crypto.clear_cache()
    with pytest.raises(KeyShredded):
        crypto.decrypt_field(uid, blob, aad)
    assert crypto.decrypt_field(other, keep, aad_o) == b"keep"


@needs_db
def test_postgres_errors_do_not_leak_secrets(repo, caplog):
    uid = uuid4()
    aad = aad_for(uid)
    blob = enc(uid, CANARY, aad)
    wrapped = repo.latest(uid).wrapped
    crypto.shred(uid)
    with pytest.raises(KeyShredded) as ei:
        enc(uid, CANARY, aad)
    text = caplog.text + str(ei.value) + repr(ei.value)
    for s in (CANARY, wrapped, blob):
        assert s.hex() not in text
        assert s.decode("latin-1") not in text


# ---- review findings (docs/v1/CRYPTO_REVIEW.md) ----


@needs_db
def test_runtime_role_cannot_erase_tombstones_or_disable_trigger(repo, runtime_url):
    """Finding 3."""
    uid = uuid4()
    repo.shred(uid)
    forbidden = [
        "DELETE FROM key_tombstones",
        "TRUNCATE key_tombstones",
        "TRUNCATE user_keys",
        "UPDATE key_tombstones SET shredded_at = now()",
        "UPDATE user_keys SET user_id = gen_random_uuid()",
        "ALTER TABLE user_keys DISABLE TRIGGER user_keys_no_revive",
        "DROP TRIGGER user_keys_no_revive ON user_keys",
        "ALTER TABLE user_keys DISABLE TRIGGER ALL",
        "DROP TABLE key_tombstones",
        "UPDATE key_masters SET kcv = '\\x00'",
        "DELETE FROM key_masters",
    ]
    for sql in forbidden:
        with psycopg.connect(runtime_url, autocommit=True) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql)
    assert repo.is_tombstoned(uid)


@needs_db
def test_shred_waits_for_an_in_flight_key_insert_and_removes_it(repo, runtime_url):
    """Finding 2: an insert that passed the trigger but has not committed is still deleted."""
    uid = uuid4()
    wk = WrappedKey(uid, 1, b"\x01" + b"w" * 40, "m1")
    writer = psycopg.connect(runtime_url)  # open transaction: holds the per-user lock
    try:
        writer.execute(
            "INSERT INTO user_keys (user_id, key_version, wrapped_key, master_key_id) "
            "VALUES (%s, %s, %s, %s)",
            (wk.user_id, wk.key_version, wk.wrapped, wk.master_key_id),
        )
        done = threading.Event()
        t = threading.Thread(target=lambda: (repo.shred(uid), done.set()))
        t.start()
        assert not done.wait(0.5)  # blocked behind the writer
        writer.commit()
        t.join(5)
        assert done.is_set()
    finally:
        writer.close()
    assert repo.latest(uid) is None and repo.is_tombstoned(uid)


@needs_db
def test_key_insert_waits_for_an_in_flight_shred_and_is_refused(repo, runtime_url):
    """Finding 2, the other order."""
    uid = uuid4()
    wk = WrappedKey(uid, 1, b"\x01" + b"w" * 40, "m1")
    shredder = psycopg.connect(runtime_url)
    try:
        shredder.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s::text, 0))", (uid,))
        shredder.execute("INSERT INTO key_tombstones (user_id) VALUES (%s)", (uid,))
        outcome: list[object] = []

        def insert():
            try:
                outcome.append(repo.put(wk))
            except KeyShredded as e:
                outcome.append(e)

        t = threading.Thread(target=insert)
        t.start()
        t.join(0.5)
        assert t.is_alive()  # waiting on the lock, not yet refused or inserted
        shredder.commit()
        t.join(5)
    finally:
        shredder.close()
    assert len(outcome) == 1 and isinstance(outcome[0], KeyShredded)
    assert repo.latest(uid) is None


@needs_db
def test_reconcile_tombstones_before_deleting(repo):
    uid = uuid4()
    repo.put(WrappedKey(uid, 1, b"\x01" + b"w" * 40, "m1"))
    assert crypto.reconcile_shreds({uid}) == 1
    assert repo.is_tombstoned(uid) and repo.latest(uid) is None


@needs_db
def test_only_the_tombstone_error_means_shredded(repo):
    """Finding 10: a CHECK violation is not 'shredded', and its message holds no row data."""
    uid = uuid4()
    secret = b"\x01" + b"SYNTHETIC-wrapped-secret" * 2
    with pytest.raises(CryptoError) as e:
        repo.put(WrappedKey(uid, 0, secret, "m1"))  # key_version >= 1 is a CHECK
    assert not isinstance(e.value, KeyShredded)
    assert secret.hex() not in str(e.value) and "SYNTHETIC" not in str(e.value)


@needs_db
def test_missing_key_row_is_not_shredded_in_postgres(repo, keys_db):
    uid = uuid4()
    aad = aad_for(uid)
    blob = enc(uid, CANARY, aad)
    with psycopg.connect(keys_db, autocommit=True) as c:  # a wrong or stale keys database
        c.execute("DELETE FROM user_keys")
    crypto.clear_cache()
    with pytest.raises(KeyMissing):
        crypto.decrypt_field(uid, blob, aad)
    with pytest.raises(KeyMissing):
        crypto.encrypt_field(uid, CANARY, aad)
    assert repo.latest(uid) is None  # nothing minted


@needs_db
def test_master_id_reuse_with_other_key_fails_in_postgres(repo):
    u = uuid4()
    enc(u, CANARY, aad_for(u))  # registers m1 with the fixture's key
    crypto.configure(
        repo=repo, keystore=EnvKeyStore({"PERCH_MASTER_KEY": b64(), "PERCH_MASTER_KEY_ID": "m1"})
    )
    with pytest.raises(CryptoError, match="different key material"):
        crypto.verify_masters()


@needs_db
def test_swapped_wrapped_keys_do_not_unwrap(repo):
    u1, u2 = uuid4(), uuid4()
    enc(u1, CANARY, aad_for(u1))
    enc(u2, CANARY, aad_for(u2))
    w2 = repo.latest(u2)
    ks = EnvKeyStore({"PERCH_MASTER_KEY": b64(), "PERCH_MASTER_KEY_ID": "m1"})
    with pytest.raises(DecryptError):  # u2's wrapped key presented as u1's
        ks.unwrap(WrappedKey(u1, 1, w2.wrapped, w2.master_key_id))


@needs_db
def test_pooled_repository_reuses_connections(keys_db, runtime_url):
    r = KeyRepository(runtime_url, max_size=2)
    try:
        pids = set()
        for _ in range(30):
            with r._conn() as c:
                pids.add(c.info.backend_pid)
        assert len(pids) <= 2  # 30 calls, at most max_size connections ever opened
    finally:
        r.close()

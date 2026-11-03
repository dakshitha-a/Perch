"""perch.crypto with an in-memory key repository. SYNTHETIC text only. No database needed."""

from __future__ import annotations

import base64
import logging
import os
from uuid import uuid4

import pytest

from perch import crypto
from perch.crypto import Aad, CryptoError, DecryptError, KeyShredded
from perch.keystore import EnvKeyStore, InMemoryKeyRepository

CANARY = b"SYNTHETIC-canary-cv-text-7f3a"


def enc(user_id, plaintext, aad):
    """First-write encrypt: the caller says it may create version 1."""
    return crypto.encrypt_field(user_id, plaintext, aad, create=True)


def make_env(mid: str = "m1", prev: tuple[str, bytes] | None = None, key: bytes | None = None):
    env = {
        "PERCH_MASTER_KEY": base64.b64encode(key or os.urandom(32)).decode(),
        "PERCH_MASTER_KEY_ID": mid,
    }
    if prev:
        env["PERCH_MASTER_KEY_PREV_ID"] = prev[0]
        env["PERCH_MASTER_KEY_PREV"] = base64.b64encode(prev[1]).decode()
    return env


@pytest.fixture
def repo():
    r = InMemoryKeyRepository()
    crypto.configure(repo=r, keystore=EnvKeyStore(make_env()))
    yield r
    crypto.configure()


def aad_for(uid, row=None, extra="cv:researcher"):
    return Aad(uid, "user_data", "blob", row or str(uuid4()), extra)


def test_round_trip(repo):
    uid = uuid4()
    aad = aad_for(uid)
    blob = enc(uid, CANARY, aad)
    assert CANARY not in blob
    assert blob[0] == 1
    assert crypto.key_version_of(blob) == 1
    assert crypto.decrypt_field(uid, blob, aad) == CANARY


@pytest.mark.parametrize(
    "change",
    [
        {"row_id": "other-row"},
        {"table": "users"},
        {"column": "other"},
        {"extra": "cv:student"},
        {"user_id": uuid4()},
    ],
)
def test_wrong_aad_fails(repo, change):
    uid = uuid4()
    aad = aad_for(uid)
    blob = enc(uid, CANARY, aad)
    bad = Aad(**{**aad.__dict__, **change})
    with pytest.raises(DecryptError):
        crypto.decrypt_field(uid, blob, bad)


def test_aad_user_must_match_caller(repo):
    uid = uuid4()
    with pytest.raises(CryptoError):
        enc(uid, b"x", aad_for(uuid4()))


def test_aad_rejects_nul():
    with pytest.raises(ValueError):
        Aad(uuid4(), "a\x00b", "c", "r")


def test_repr_has_ids_only():
    a = Aad(uuid4(), "user_data", "blob", "row-1", "cv:researcher")
    assert "cv:researcher" not in repr(a)
    assert "row-1" in repr(a)


def test_tampered_blob_fails(repo):
    uid = uuid4()
    aad = aad_for(uid)
    blob = bytearray(enc(uid, CANARY, aad))
    for i in (6, 20, len(blob) - 1):  # nonce, ciphertext, tag
        bad = bytearray(blob)
        bad[i] ^= 0x01
        with pytest.raises(DecryptError):
            crypto.decrypt_field(uid, bytes(bad), aad)
    with pytest.raises(DecryptError):
        crypto.decrypt_field(uid, bytes(blob[:-1]), aad)
    with pytest.raises(DecryptError):
        crypto.decrypt_field(uid, bytes(blob[:10]), aad)
    wrong_format = bytes([2]) + bytes(blob[1:])
    with pytest.raises(DecryptError):
        crypto.decrypt_field(uid, wrong_format, aad)


def test_key_version_is_bound(repo):
    """Rewriting the header's version to an older one fails, not downgrades."""
    uid = uuid4()
    aad = aad_for(uid)
    enc(uid, b"x", aad)
    assert crypto.new_data_key(uid) == 2
    blob = enc(uid, CANARY, aad)
    assert crypto.key_version_of(blob) == 2
    downgraded = blob[:1] + (1).to_bytes(4, "big") + blob[5:]
    with pytest.raises(DecryptError):
        crypto.decrypt_field(uid, downgraded, aad)


def test_nonces_unique(repo):
    uid = uuid4()
    aad = aad_for(uid)
    nonces = {enc(uid, b"x", aad)[5:17] for _ in range(5000)}
    assert len(nonces) == 5000


def test_nonce_guard(repo, monkeypatch):
    uid = uuid4()
    aad = aad_for(uid)
    monkeypatch.setattr(crypto, "NONCE_GUARD_LIMIT", 3)
    for _ in range(3):
        enc(uid, b"x", aad)
    with pytest.raises(CryptoError):
        enc(uid, b"x", aad)
    crypto.new_data_key(uid)  # a new version has a fresh count
    enc(uid, b"x", aad)


def test_users_have_distinct_keys(repo):
    a, b = uuid4(), uuid4()
    aad_a = aad_for(a)
    blob = enc(a, CANARY, aad_a)
    enc(b, b"y", aad_for(b))
    with pytest.raises(DecryptError):
        crypto.decrypt_field(b, blob, Aad(b, "user_data", "blob", aad_a.row_id, aad_a.extra))


def test_rotate_data_key_old_and_new_coexist(repo):
    uid = uuid4()
    aad = aad_for(uid)
    old = enc(uid, b"old text", aad)
    queued = []
    crypto.configure(repo=repo, keystore=crypto._ks(), rekey_hook=queued.append)
    assert crypto.rotate_data_key(uid) == 2
    assert queued == [uid]
    new = enc(uid, b"new text", aad)
    assert crypto.key_version_of(old) == 1
    assert crypto.key_version_of(new) == 2
    assert crypto.decrypt_field(uid, old, aad) == b"old text"
    assert crypto.decrypt_field(uid, new, aad) == b"new text"


def test_rotate_master_rewraps_without_changing_plaintext():
    old_key = os.urandom(32)
    r = InMemoryKeyRepository()
    crypto.configure(repo=r, keystore=EnvKeyStore(make_env("m1", key=old_key)))
    users = [uuid4() for _ in range(7)]
    aads = {u: aad_for(u) for u in users}
    blobs = {u: enc(u, CANARY + u.bytes, aads[u]) for u in users}
    before = {k: w.wrapped for k, w in r.keys.items()}
    new_ks = EnvKeyStore(make_env("m2", prev=("m1", old_key)))
    crypto.configure(repo=r, keystore=new_ks)  # also clears the key cache
    assert crypto.rotate_master("m1", "m2", batch=3) == 7
    assert crypto.rotate_master("m1", "m2") == 0
    assert all(w.master_key_id == "m2" for w in r.keys.values())
    assert all(r.keys[k].wrapped != before[k] for k in before)
    for u in users:
        assert crypto.decrypt_field(u, blobs[u], aads[u]) == CANARY + u.bytes
    # After the old key is removed, m2 alone still reads everything.
    only_new = EnvKeyStore({**make_env("m2", key=base64.b64decode(new_ks_key(new_ks)))})
    crypto.configure(repo=r, keystore=only_new)
    for u in users:
        assert crypto.decrypt_field(u, blobs[u], aads[u]) == CANARY + u.bytes
    crypto.configure()


def new_ks_key(ks: EnvKeyStore) -> str:
    return base64.b64encode(ks._keys[ks.current_master_id]).decode()


def test_rotate_master_checks_ids(repo):
    with pytest.raises(CryptoError):
        crypto.rotate_master("m1", "m1")
    with pytest.raises(CryptoError):
        crypto.rotate_master("m1", "zzz")


def test_shred_makes_blobs_unreadable_and_blocks_new_keys(repo):
    uid, other = uuid4(), uuid4()
    aad, aad_o = aad_for(uid), aad_for(other)
    blobs = [enc(uid, CANARY, aad) for _ in range(3)]
    keep = enc(other, b"keep", aad_o)
    called = []
    crypto.configure(repo=repo, keystore=crypto._ks(), shred_hooks=[called.append])
    crypto.shred(uid)
    crypto.shred(uid)  # idempotent
    assert called == [uid, uid]
    for b in blobs:
        with pytest.raises(KeyShredded):
            crypto.decrypt_field(uid, b, aad)
    with pytest.raises(KeyShredded):
        enc(uid, b"x", aad)
    with pytest.raises(KeyShredded):
        crypto.new_data_key(uid)
    assert repo.delete_all(uid) == 0
    assert crypto.decrypt_field(other, keep, aad_o) == b"keep"


def test_shred_defeats_cached_key(repo):
    uid = uuid4()
    aad = aad_for(uid)
    blob = enc(uid, CANARY, aad)
    assert crypto.decrypt_field(uid, blob, aad) == CANARY  # key is now cached
    repo.tombstone(uid)  # another process shredded; this one still caches the key
    with pytest.raises(KeyShredded):
        crypto.decrypt_field(uid, blob, aad)


def test_restored_key_row_does_not_revive(repo):
    uid = uuid4()
    aad = aad_for(uid)
    blob = enc(uid, CANARY, aad)
    snapshot = dict(repo.keys)
    crypto.shred(uid)
    repo.keys.update(snapshot)  # an old key snapshot comes back
    with pytest.raises(KeyShredded):
        crypto.decrypt_field(uid, blob, aad)
    # The tombstone is lost too (whole keys database restored); the other copies reconcile it.
    repo.tombstones.clear()
    assert crypto.decrypt_field(uid, blob, aad) == CANARY  # this is the revival risk
    assert crypto.reconcile_shreds({uid}) == 1
    with pytest.raises(KeyShredded):
        crypto.decrypt_field(uid, blob, aad)


def test_cache_expiry_and_eviction(repo, monkeypatch):
    uid = uuid4()
    aad = aad_for(uid)
    blob = enc(uid, CANARY, aad)
    assert (uid, 1) in crypto._S.cache
    crypto.evict_user(uid)
    assert (uid, 1) not in crypto._S.cache
    assert crypto.decrypt_field(uid, blob, aad) == CANARY
    t = [0.0]
    monkeypatch.setattr(crypto.time, "monotonic", lambda: t[0])
    crypto.clear_cache()
    crypto.decrypt_field(uid, blob, aad)
    t[0] = crypto.CACHE_TTL_S + 1
    assert crypto._cache_get(uid, 1) is None


def test_cache_bounded(repo, monkeypatch):
    monkeypatch.setattr(crypto, "CACHE_SIZE", 4)
    for _ in range(10):
        u = uuid4()
        enc(u, b"x", aad_for(u))
    assert len(crypto._S.cache) <= 4


def test_no_secrets_in_logs_or_errors(repo, caplog):
    caplog.set_level(logging.DEBUG)
    uid = uuid4()
    aad = aad_for(uid)
    blob = enc(uid, CANARY, aad)
    data_key = bytes(crypto._data_key(uid, 1))
    wrapped = repo.keys[(uid, 1)].wrapped
    errors: list[str] = []
    for fn in (
        lambda: crypto.decrypt_field(uid, blob[:-1] + b"\x00", aad),
        lambda: crypto.decrypt_field(uid, blob, aad_for(uid)),
        lambda: crypto.decrypt_field(uid, blob[:5], aad),
    ):
        with pytest.raises(DecryptError) as ei:
            fn()
        errors.append(str(ei.value) + repr(ei.value))
    crypto.shred(uid)
    with pytest.raises(KeyShredded) as ei:
        crypto.decrypt_field(uid, blob, aad)
    errors.append(str(ei.value) + repr(ei.value))
    text = caplog.text + "".join(errors)
    secrets = [CANARY, data_key, wrapped, blob]
    for s in secrets:
        assert s.decode("latin-1") not in text
        assert s.hex() not in text
        assert base64.b64encode(s).decode() not in text


# ---- review findings (docs/v1/CRYPTO_REVIEW.md) ----


def test_eviction_between_key_fetch_and_use_never_seals_under_zero_key(repo, monkeypatch):
    """Finding 1: a cache clear after the key is fetched must not zero the caller's key."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    uid = uuid4()
    aad = aad_for(uid)
    real_count = crypto._count

    def count_then_evict(u, v):
        real_count(u, v)
        crypto.clear_cache()  # eviction lands after the key was handed out

    monkeypatch.setattr(crypto, "_count", count_then_evict)
    blob = enc(uid, CANARY, aad)
    monkeypatch.setattr(crypto, "_count", real_count)
    with pytest.raises(InvalidTag):
        AESGCM(bytes(32)).decrypt(blob[5:17], blob[17:], aad.to_bytes(1))
    assert crypto.decrypt_field(uid, blob, aad) == CANARY


def test_concurrent_eviction_stress(repo):
    import threading

    uid = uuid4()
    aad = aad_for(uid)
    enc(uid, b"warm", aad)
    stop = threading.Event()
    errors: list[BaseException] = []

    def evictor():
        while not stop.is_set():
            crypto.clear_cache()
            crypto.evict_user(uid)

    def worker():
        try:
            for _ in range(300):
                blob = enc(uid, CANARY, aad)
                assert crypto.decrypt_field(uid, blob, aad) == CANARY
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    ev = threading.Thread(target=evictor)
    ws = [threading.Thread(target=worker) for _ in range(4)]
    ev.start()
    [t.start() for t in ws]
    [t.join() for t in ws]
    stop.set()
    ev.join()
    assert not errors


def test_wrapped_key_repr_has_ids_only(repo):
    uid = uuid4()
    enc(uid, CANARY, aad_for(uid))
    wk = repo.latest(uid)
    text = repr(wk) + str(wk) + f"{wk!r}"
    assert wk.wrapped.hex() not in text and wk.wrapped.decode("latin-1") not in text
    assert str(uid) in text and "m1" in text


def test_missing_key_row_is_not_shredded(repo):
    """Finding 5: an empty keys repository with an existing blob is not a shred, and a write
    does not mint a replacement key."""
    uid = uuid4()
    aad = aad_for(uid)
    blob = enc(uid, CANARY, aad)
    fresh = InMemoryKeyRepository()
    crypto.configure(repo=fresh, keystore=EnvKeyStore(make_env()))
    with pytest.raises(crypto.KeyMissing) as e:
        crypto.decrypt_field(uid, blob, aad)
    assert not isinstance(e.value, KeyShredded)
    with pytest.raises(crypto.KeyMissing):
        crypto.encrypt_field(uid, CANARY, aad)  # create not asked for
    assert fresh.keys == {}
    assert crypto.encrypt_field(uid, CANARY, aad, create=True)  # a declared first write works


def test_shredded_user_is_still_keyshredded(repo):
    uid = uuid4()
    aad = aad_for(uid)
    blob = enc(uid, CANARY, aad)
    crypto.shred(uid)
    with pytest.raises(KeyShredded):
        crypto.decrypt_field(uid, blob, aad)


def test_master_key_needs_an_explicit_id():
    env = make_env()
    del env["PERCH_MASTER_KEY_ID"]
    with pytest.raises(CryptoError, match="MASTER_KEY_ID"):
        EnvKeyStore(env)


def test_same_master_id_with_different_key_is_refused(repo):
    uid = uuid4()
    enc(uid, CANARY, aad_for(uid))
    # An operator sets a new key but forgets the new id.
    crypto.configure(repo=repo, keystore=EnvKeyStore(make_env("m1")))
    with pytest.raises(CryptoError, match="different key material"):
        crypto.encrypt_field(uid, CANARY, aad_for(uid), create=True)
    with pytest.raises(CryptoError, match="different key material"):
        crypto.verify_masters()


def test_same_master_id_same_key_is_accepted(repo):
    key = os.urandom(32)
    crypto.configure(repo=repo, keystore=EnvKeyStore(make_env("m1", key=key)))
    crypto.verify_masters()
    crypto.configure(repo=repo, keystore=EnvKeyStore(make_env("m1", key=key)))
    crypto.verify_masters()


def test_unwrap_rejects_a_short_data_key():
    from perch.keystore import WrappedKey

    key = os.urandom(32)
    ks = EnvKeyStore(make_env(key=key))
    uid = uuid4()
    wrapped, mid = ks.wrap(os.urandom(16), user_id=uid, key_version=1)  # a 128-bit "data key"
    with pytest.raises(DecryptError, match="malformed"):
        ks.unwrap(WrappedKey(uid, 1, wrapped, mid))


def test_aad_user_id_bytes_are_bound(repo):
    """The user id inside the AAD, isolated: same key, same row, different user in the AAD."""
    uid, other = uuid4(), uuid4()
    aad = aad_for(uid, row="r1")
    blob = enc(uid, CANARY, aad)
    key = crypto._data_key(uid, 1)
    # Make `other` share uid's key so only the AAD differs.
    repo.keys[(other, 1)] = repo.keys[(uid, 1)]
    crypto._cache_put(other, 1, key)
    with pytest.raises(DecryptError):
        crypto.decrypt_field(other, blob, aad_for(other, row="r1"))


def test_wrapped_key_moved_between_users_fails(repo):
    from perch.keystore import WrappedKey

    u1, u2 = uuid4(), uuid4()
    blob1 = enc(u1, CANARY, aad_for(u1))
    enc(u2, CANARY, aad_for(u2))
    w2 = repo.latest(u2)
    repo.keys[(u1, 1)] = WrappedKey(u1, 1, w2.wrapped, w2.master_key_id)
    crypto.clear_cache()
    with pytest.raises(DecryptError):
        crypto.decrypt_field(u1, blob1, aad_for(u1))


def test_every_shred_hook_runs_even_when_one_fails(repo):
    uid = uuid4()
    ran: list[str] = []

    def bad(u):
        ran.append("bad")
        raise RuntimeError("SYNTHETIC hook failure with secret " + CANARY.decode())

    def good(u):
        ran.append("good")

    crypto.configure(repo=repo, keystore=EnvKeyStore(make_env()), shred_hooks=[bad, good])
    enc(uid, CANARY, aad_for(uid))
    with pytest.raises(CryptoError) as e:
        crypto.shred(uid)
    assert ran == ["bad", "good"]
    assert CANARY.decode() not in str(e.value) and e.value.__cause__ is None
    assert repo.is_tombstoned(uid) and repo.latest(uid) is None


def test_decrypt_many_checks_the_tombstone_once(repo):
    uid = uuid4()
    aads = [aad_for(uid, row=f"r{i}") for i in range(5)]
    blobs = [enc(uid, f"SYNTHETIC-{i}".encode(), a) for i, a in enumerate(aads)]
    calls = 0
    real = repo.is_tombstoned

    def counting(u):
        nonlocal calls
        calls += 1
        return real(u)

    repo.is_tombstoned = counting
    out = crypto.decrypt_many(uid, list(zip(blobs, aads, strict=True)))
    assert out == [f"SYNTHETIC-{i}".encode() for i in range(5)] and calls == 1
    calls = 0
    for b, a in zip(blobs, aads, strict=True):
        crypto.decrypt_field(uid, b, a)
    assert calls == 5
    crypto.shred(uid)
    with pytest.raises(KeyShredded):
        crypto.decrypt_many(uid, list(zip(blobs, aads, strict=True)))
    assert crypto.decrypt_many(uid, []) == []

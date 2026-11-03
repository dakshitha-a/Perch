"""Field encryption with per-user data keys (docs/ARCHITECTURE_V1.md section 6).

Envelope: a random 256-bit data key per user and version encrypts each field with AES-256-GCM.
The data key is stored only wrapped by the master key (perch/keystore.py).

Never logged, never in an exception message: plaintext, keys, wrapped keys, blobs.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from perch.keystore import (
    CryptoError,
    DecryptError,
    KeyMissing,
    KeyRepository,
    KeyShredded,
    KeyStore,
    WrappedKey,
    key_store,
)

__all__ = [
    "Aad",
    "CryptoError",
    "DecryptError",
    "KeyMissing",
    "KeyShredded",
    "configure",
    "decrypt_many",
    "decrypt_field",
    "encrypt_field",
    "evict_user",
    "clear_cache",
    "key_version_of",
    "new_data_key",
    "reconcile_shreds",
    "rotate_data_key",
    "rotate_master",
    "shred",
    "verify_masters",
]

log = logging.getLogger("perch.crypto")

BLOB_VERSION = 0x01
_HEADER = 1 + 4 + 12
_TAG = 16
NONCE_GUARD_LIMIT = 2**30  # process-local encryptions per (user, key version)
CACHE_SIZE = 1024
CACHE_TTL_S = 300.0
_AAD_PREFIX = b"perch/v1\x00"


@dataclass(frozen=True)
class Aad:
    user_id: UUID
    table: str  # "user_data", "users"
    column: str  # "blob", "openalex_id_enc"
    row_id: str  # uuid text of the row
    extra: str = ""  # "<kind>:<audience>" for user_data

    def __post_init__(self) -> None:
        for part in (self.table, self.column, self.row_id, self.extra):
            if "\x00" in part:
                raise ValueError("AAD parts must not contain NUL")

    def to_bytes(self, key_version: int) -> bytes:
        return (
            _AAD_PREFIX
            + self.user_id.bytes
            + b"\x00"
            + self.table.encode()
            + b"\x00"
            + self.column.encode()
            + b"\x00"
            + self.row_id.encode()
            + b"\x00"
            + self.extra.encode()
            + b"\x00"
            + key_version.to_bytes(4, "big")
        )

    def __repr__(self) -> str:
        return (
            f"Aad(user_id={self.user_id}, table={self.table}, "
            f"column={self.column}, row_id={self.row_id})"
        )


class _State:
    def __init__(self) -> None:
        self.repo: KeyRepository | None = None
        self.ks: KeyStore | None = None
        self.lock = threading.Lock()
        # (user, version) -> (key, expires_at), most recently used last
        self.cache: OrderedDict[tuple[UUID, int], tuple[bytes, float]] = OrderedDict()
        self.counts: dict[tuple[UUID, int], int] = {}
        self.shred_hooks: list[Callable[[UUID], None]] = []
        self.rekey_hook: Callable[[UUID], None] | None = None
        self.verified = False


_S = _State()


def configure(
    *,
    repo: KeyRepository | None = None,
    keystore: KeyStore | None = None,
    shred_hooks: list[Callable[[UUID], None]] | None = None,
    rekey_hook: Callable[[UUID], None] | None = None,
) -> None:
    """Inject collaborators (tests, app start). Unset ones are built lazily from the environment.

    shred_hooks run inside shred() after the tombstone and key deletion: the caller registers
    the shred_log insert, the ledger object and the perch:shred publish there. rekey_hook is
    called by rotate_data_key to enqueue purge(action='rekey').
    """
    _S.repo = repo
    _S.ks = keystore
    _S.shred_hooks = list(shred_hooks or [])
    _S.rekey_hook = rekey_hook
    clear_cache()
    _S.counts.clear()
    _S.verified = False


def _repo() -> KeyRepository:
    if _S.repo is None:
        _S.repo = KeyRepository()
    return _S.repo


def _ks() -> KeyStore:
    if _S.ks is None:
        _S.ks = key_store()
    return _S.ks


def verify_masters() -> None:
    """Check every master key id this process holds against the key check values stored in the
    keys database (registering new ids). Raises CryptoError on a mismatch. Call at start; the
    crypto functions also call it once before their first key operation."""
    _repo().verify_masters(_ks().check_values())
    _S.verified = True


def _ensure_verified() -> None:
    if not _S.verified:
        verify_masters()


def evict_user(user_id: UUID) -> None:
    """Drop a user's cached keys in this process (called on a perch:shred message).

    Cached keys are immutable bytes handed out by value, so a caller that already holds one
    keeps a valid key; eviction only removes the cache entry.
    """
    with _S.lock:
        for k in [k for k in _S.cache if k[0] == user_id]:
            del _S.cache[k]


def clear_cache() -> None:
    """Drop every cached key (called on every pub/sub reconnect)."""
    with _S.lock:
        _S.cache.clear()


def _cache_get(user_id: UUID, version: int) -> bytes | None:
    with _S.lock:
        hit = _S.cache.get((user_id, version))
        if hit is None:
            return None
        if hit[1] <= time.monotonic():
            del _S.cache[(user_id, version)]
            return None
        _S.cache.move_to_end((user_id, version))
        return hit[0]


def _cache_put(user_id: UUID, version: int, key: bytes) -> bytes:
    key = bytes(key)
    with _S.lock:
        _S.cache.pop((user_id, version), None)
        _S.cache[(user_id, version)] = (key, time.monotonic() + CACHE_TTL_S)
        while len(_S.cache) > CACHE_SIZE:
            _S.cache.popitem(last=False)
    return key


def _data_key(user_id: UUID, version: int, *, checked: bool = False) -> bytes:
    """The unwrapped data key, as immutable bytes. Raises KeyShredded when the user is
    tombstoned and KeyMissing when there is neither a tombstone nor a key row.

    checked=True means the caller already ran the tombstone check for this operation
    (decrypt_many does it once for a batch).
    """
    repo = _repo()
    # Tombstone first, every time: a restored key row must not decrypt anything.
    if not checked and repo.is_tombstoned(user_id):
        evict_user(user_id)
        raise KeyShredded("the user's key has been shredded")
    cached = _cache_get(user_id, version)
    if cached is not None:
        return cached
    wk = repo.get(user_id, version)
    if wk is None:
        raise KeyMissing("no key row for this user and version, and no tombstone")
    _ensure_verified()
    return _cache_put(user_id, version, _ks().unwrap(wk))


def new_data_key(user_id: UUID) -> int:
    """Create version N+1: 32 random bytes, wrap, store. Returns the new key_version.

    Refuses if the user has a tombstone; a trigger on user_keys also refuses the insert.
    """
    repo = _repo()
    if repo.is_tombstoned(user_id):
        raise KeyShredded("the user's key has been shredded")
    ks = _ks()
    _ensure_verified()
    for _ in range(5):
        latest = repo.latest(user_id)
        version = (latest.key_version if latest else 0) + 1
        data_key = os.urandom(32)
        wrapped, master_id = ks.wrap(data_key, user_id=user_id, key_version=version)
        if repo.put(WrappedKey(user_id, version, wrapped, master_id)):
            _cache_put(user_id, version, data_key)
            return version
    raise CryptoError("could not create a key version after repeated conflicts")


def _newest(user_id: UUID, create: bool = False) -> tuple[int, bytes]:
    repo = _repo()
    if repo.is_tombstoned(user_id):
        raise KeyShredded("the user's key has been shredded")
    latest = repo.latest(user_id)
    if latest is None:
        if not create:
            # An empty keys database must not silently mint version 1 for a user whose
            # blobs already exist; only a caller that knows this is a first write says so.
            raise KeyMissing("no key for this user; pass create=True on a first write")
        # First use: insert version 1 with ON CONFLICT DO NOTHING, then re-read, so two
        # racing first writes agree on one key.
        _ensure_verified()
        data_key = os.urandom(32)
        wrapped, master_id = _ks().wrap(data_key, user_id=user_id, key_version=1)
        repo.put(WrappedKey(user_id, 1, wrapped, master_id))
        latest = repo.latest(user_id)
        if latest is None:
            raise CryptoError("could not create the first key")
    return latest.key_version, _data_key(user_id, latest.key_version, checked=True)


def _count(user_id: UUID, version: int) -> None:
    k = (user_id, version)
    with _S.lock:
        n = _S.counts.get(k, 0) + 1
        _S.counts[k] = n
    if n > NONCE_GUARD_LIMIT:
        raise CryptoError("nonce guard tripped: rotate this user's data key")


def encrypt_field(user_id: UUID, plaintext: bytes, aad: Aad, *, create: bool = False) -> bytes:
    """Encrypt under the user's newest key version.

    Version 1 is created only when create=True (the caller has checked that the user has no
    stored blobs yet); otherwise a user with no key row raises KeyMissing.
    """
    if aad.user_id != user_id:
        raise CryptoError("aad.user_id must equal user_id")
    version, key = _newest(user_id, create)
    _count(user_id, version)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, aad.to_bytes(version))
    return bytes([BLOB_VERSION]) + version.to_bytes(4, "big") + nonce + ct


def key_version_of(blob: bytes) -> int:
    if len(blob) < _HEADER + _TAG or blob[0] != BLOB_VERSION:
        raise DecryptError("blob is malformed")
    return int.from_bytes(blob[1:5], "big")


def _open(user_id: UUID, blob: bytes, aad: Aad, *, checked: bool) -> bytes:
    if aad.user_id != user_id:
        raise DecryptError("aad.user_id must equal user_id")
    version = key_version_of(blob)
    key = _data_key(user_id, version, checked=checked)
    try:
        return AESGCM(key).decrypt(blob[5:17], blob[17:], aad.to_bytes(version))
    except InvalidTag:
        raise DecryptError("blob failed authentication") from None


def decrypt_field(user_id: UUID, blob: bytes, aad: Aad) -> bytes:
    """Raises KeyShredded, KeyMissing, DecryptError. Uses the version in the blob header."""
    return _open(user_id, blob, aad, checked=False)


def decrypt_many(user_id: UUID, items: list[tuple[bytes, Aad]]) -> list[bytes]:
    """Decrypt a batch for one user with a single tombstone check (one list page, not 50
    key-database round trips). Raises on the first failure, like decrypt_field."""
    if not items:
        return []
    repo = _repo()
    if repo.is_tombstoned(user_id):
        evict_user(user_id)
        raise KeyShredded("the user's key has been shredded")
    return [_open(user_id, blob, aad, checked=True) for blob, aad in items]


def shred(user_id: UUID) -> None:
    """Tombstone and delete every key row in one locked transaction, evict caches, then run the
    registered hooks. Idempotent.

    Every hook runs even if an earlier one fails; failures are counted and raised together at
    the end as one CryptoError with fixed text, after the keys are already gone. Register the
    ledger object (the copy outside both databases) before the shred_log insert.
    """
    repo = _repo()
    repo.shred(user_id)
    evict_user(user_id)
    with _S.lock:
        for k in [k for k in _S.counts if k[0] == user_id]:
            del _S.counts[k]
    failed = 0
    for hook in list(_S.shred_hooks):
        try:
            hook(user_id)
        except Exception:  # noqa: BLE001 - messages may hold data; count only
            failed += 1
    log.info("shredded user=%s hook_failures=%d", user_id, failed)
    if failed:
        raise CryptoError("the user's keys are shredded but a shred hook failed; retry shred")


def reconcile_shreds(user_ids: set[UUID]) -> int:
    """After a restore: for every id in the union of the three tombstone sources, tombstone
    first, then delete any key rows. Returns ids that still had key rows."""
    repo = _repo()
    revived = 0
    for uid in sorted(user_ids, key=str):
        if repo.shred(uid):
            revived += 1
        evict_user(uid)
    return revived


def rotate_master(old_id: str, new_id: str, *, batch: int = 500) -> int:
    """Re-wrap every user_keys row whose master_key_id == old_id under new_id.

    Resumable and safe while serving; data blobs are untouched. The key store must hold both
    keys, and new_id must be its current master id. Returns rows rewrapped.
    """
    repo, ks = _repo(), _ks()
    if old_id == new_id:
        raise CryptoError("old and new master ids must differ")
    if ks.current_master_id != new_id:
        raise CryptoError("new_id must be the key store's current master id")
    total = 0
    while True:
        rows = repo.all_for_master(old_id, batch)
        if not rows:
            return total
        done = 0
        for wk in rows:
            data_key = ks.unwrap(wk)
            wrapped, mid = ks.wrap(data_key, user_id=wk.user_id, key_version=wk.key_version)
            if repo.rewrap(wk, wrapped, mid):
                done += 1
        total += done
        if done == 0:  # every row raced away; avoid spinning
            return total


def rotate_data_key(user_id: UUID) -> int:
    """new_data_key, then enqueue purge(action='rekey') through the registered rekey_hook."""
    version = new_data_key(user_id)
    if _S.rekey_hook is not None:
        _S.rekey_hook(user_id)
    return version

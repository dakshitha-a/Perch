"""Key stores and the key repository (docs/ARCHITECTURE_V1.md section 6.4).

A KeyStore wraps and unwraps per-user data keys under a master key. KeyRepository is the only
code that opens PERCH_KEYS_DATABASE_URL. Keys, wrapped keys and plaintext are never logged and
never put in exception messages.
"""

from __future__ import annotations

import base64
import binascii
import os
import threading
from abc import ABC, abstractmethod
from typing import NamedTuple
from uuid import UUID

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

WRAP_VERSION = 0x01


class CryptoError(Exception):
    """Base class for crypto failures. Messages are fixed text, never data."""


class KeyShredded(CryptoError):
    """Tombstone present or no key rows: the data is gone for good."""


class DecryptError(CryptoError):
    """Tag mismatch, wrong AAD, or a truncated blob."""


class WrappedKey(NamedTuple):
    user_id: UUID
    key_version: int
    wrapped: bytes
    master_key_id: str


def wrap_aad(user_id: UUID, key_version: int, master_key_id: str) -> bytes:
    return (
        b"perch/v1/wrap\x00"
        + user_id.bytes
        + key_version.to_bytes(4, "big")
        + master_key_id.encode("utf-8")
    )


class KeyStore(ABC):
    """Wraps and unwraps data keys. Holds no per-user state."""

    @property
    @abstractmethod
    def current_master_id(self) -> str: ...

    @abstractmethod
    def wrap(self, data_key: bytes, *, user_id: UUID, key_version: int) -> tuple[bytes, str]:
        """Returns (wrapped_bytes, master_key_id)."""

    @abstractmethod
    def unwrap(self, wk: WrappedKey) -> bytes: ...


def _decode_master(raw: str) -> bytes:
    try:
        key = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise CryptoError("master key is not valid base64") from None
    if len(key) != 32:
        raise CryptoError("master key must be 32 bytes")
    return key


class EnvKeyStore(KeyStore):
    """Dev key store. PERCH_MASTER_KEY, PERCH_MASTER_KEY_ID and the optional _PREV pair.

    Refused when PERCH_ENV=prod.
    """

    def __init__(self, env: dict[str, str] | None = None) -> None:
        e = os.environ if env is None else env
        if e.get("PERCH_ENV", "dev") == "prod":
            raise CryptoError("the env key store is refused when PERCH_ENV=prod")
        raw = e.get("PERCH_MASTER_KEY", "")
        if not raw:
            raise CryptoError("PERCH_MASTER_KEY is not set")
        self._keys: dict[str, bytes] = {}
        self._current = e.get("PERCH_MASTER_KEY_ID") or "m1"
        self._keys[self._current] = _decode_master(raw)
        prev = e.get("PERCH_MASTER_KEY_PREV", "")
        if prev:
            prev_id = e.get("PERCH_MASTER_KEY_PREV_ID", "")
            if not prev_id or prev_id == self._current:
                raise CryptoError("PERCH_MASTER_KEY_PREV_ID must be set and differ from the id")
            self._keys[prev_id] = _decode_master(prev)

    @property
    def current_master_id(self) -> str:
        return self._current

    def wrap(self, data_key: bytes, *, user_id: UUID, key_version: int) -> tuple[bytes, str]:
        nonce = os.urandom(12)
        ct = AESGCM(self._keys[self._current]).encrypt(
            nonce, data_key, wrap_aad(user_id, key_version, self._current)
        )
        return bytes([WRAP_VERSION]) + nonce + ct, self._current

    def unwrap(self, wk: WrappedKey) -> bytes:
        key = self._keys.get(wk.master_key_id)
        if key is None:
            raise CryptoError("no master key for the wrapped key's master id")
        w = wk.wrapped
        if len(w) < 1 + 12 + 16 or w[0] != WRAP_VERSION:
            raise DecryptError("wrapped key is malformed")
        try:
            return AESGCM(key).decrypt(
                w[1:13], w[13:], wrap_aad(wk.user_id, wk.key_version, wk.master_key_id)
            )
        except InvalidTag:
            raise DecryptError("wrapped key failed authentication") from None


class KmsKeyStore(KeyStore):
    """Production key store. The vendor client will live inside this class.

    UNVERIFIED until a host is chosen. Construction fails with a clear message.
    """

    def __init__(self, env: dict[str, str] | None = None) -> None:
        e = os.environ if env is None else env
        uri = e.get("PERCH_KMS_KEY_URI", "")
        if not uri:
            raise NotImplementedError(
                "KmsKeyStore needs PERCH_KMS_KEY_URI and a KMS client for the chosen host; "
                "neither exists yet (UNVERIFIED until a host is chosen)"
            )
        raise NotImplementedError(
            "KmsKeyStore has no KMS client yet: the call format is UNVERIFIED "
            "until a host is chosen"
        )

    @property
    def current_master_id(self) -> str:  # pragma: no cover
        raise NotImplementedError

    def wrap(self, data_key: bytes, *, user_id: UUID, key_version: int) -> tuple[bytes, str]:
        raise NotImplementedError("KmsKeyStore is not implemented")  # pragma: no cover

    def unwrap(self, wk: WrappedKey) -> bytes:
        raise NotImplementedError("KmsKeyStore is not implemented")  # pragma: no cover


def key_store(env: dict[str, str] | None = None) -> KeyStore:
    """Chosen by PERCH_KEYSTORE. Default env in dev, kms in prod."""
    e = os.environ if env is None else env
    prod = e.get("PERCH_ENV", "dev") == "prod"
    kind = e.get("PERCH_KEYSTORE") or ("kms" if prod else "env")
    if prod and kind == "env":
        raise CryptoError("PERCH_ENV=prod requires PERCH_KEYSTORE=kms")
    if kind == "env":
        return EnvKeyStore(e)
    if kind == "kms":
        return KmsKeyStore(e)
    raise CryptoError("PERCH_KEYSTORE must be env or kms")


class KeyRepository:
    """The only code that opens PERCH_KEYS_DATABASE_URL."""

    def __init__(self, url: str | None = None) -> None:
        self._url = url

    def _connect(self) -> psycopg.Connection:
        url = self._url or os.environ.get("PERCH_KEYS_DATABASE_URL", "")
        if not url:
            raise CryptoError("PERCH_KEYS_DATABASE_URL is not set")
        return psycopg.connect(url, autocommit=True)

    @staticmethod
    def _wk(row: tuple) -> WrappedKey:
        return WrappedKey(row[0], row[1], bytes(row[2]), row[3])

    def get(self, user_id: UUID, key_version: int) -> WrappedKey | None:
        with self._connect() as c:
            row = c.execute(
                "SELECT user_id, key_version, wrapped_key, master_key_id FROM user_keys "
                "WHERE user_id = %s AND key_version = %s",
                (user_id, key_version),
            ).fetchone()
        return self._wk(row) if row else None

    def latest(self, user_id: UUID) -> WrappedKey | None:
        with self._connect() as c:
            row = c.execute(
                "SELECT user_id, key_version, wrapped_key, master_key_id FROM user_keys "
                "WHERE user_id = %s ORDER BY key_version DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return self._wk(row) if row else None

    def put(self, wk: WrappedKey) -> bool:
        """Insert with ON CONFLICT DO NOTHING. True when this call inserted the row.

        Raises KeyShredded when the database trigger refuses a tombstoned user.
        """
        try:
            with self._connect() as c:
                cur = c.execute(
                    "INSERT INTO user_keys (user_id, key_version, wrapped_key, master_key_id) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (wk.user_id, wk.key_version, wk.wrapped, wk.master_key_id),
                )
                return cur.rowcount == 1
        except psycopg.errors.IntegrityConstraintViolation:
            raise KeyShredded("user key is tombstoned") from None

    def rewrap(self, old: WrappedKey, wrapped: bytes, master_key_id: str) -> bool:
        """Replace the wrapping of one row if it still has the old master id."""
        with self._connect() as c:
            cur = c.execute(
                "UPDATE user_keys SET wrapped_key = %s, master_key_id = %s "
                "WHERE user_id = %s AND key_version = %s AND master_key_id = %s",
                (wrapped, master_key_id, old.user_id, old.key_version, old.master_key_id),
            )
            return cur.rowcount == 1

    def delete_all(self, user_id: UUID) -> int:
        with self._connect() as c:
            return c.execute("DELETE FROM user_keys WHERE user_id = %s", (user_id,)).rowcount

    def tombstone(self, user_id: UUID) -> None:
        with self._connect() as c:
            c.execute(
                "INSERT INTO key_tombstones (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (user_id,),
            )

    def is_tombstoned(self, user_id: UUID) -> bool:
        with self._connect() as c:
            return (
                c.execute("SELECT 1 FROM key_tombstones WHERE user_id = %s", (user_id,)).fetchone()
                is not None
            )

    def all_for_master(self, master_key_id: str, limit: int) -> list[WrappedKey]:
        with self._connect() as c:
            rows = c.execute(
                "SELECT user_id, key_version, wrapped_key, master_key_id FROM user_keys "
                "WHERE master_key_id = %s ORDER BY user_id, key_version LIMIT %s",
                (master_key_id, limit),
            ).fetchall()
        return [self._wk(r) for r in rows]


class InMemoryKeyRepository(KeyRepository):
    """Same interface, no database. For unit tests that need no Postgres."""

    def __init__(self) -> None:
        super().__init__(None)
        self._lock = threading.Lock()
        self.keys: dict[tuple[UUID, int], WrappedKey] = {}
        self.tombstones: set[UUID] = set()

    def get(self, user_id: UUID, key_version: int) -> WrappedKey | None:
        return self.keys.get((user_id, key_version))

    def latest(self, user_id: UUID) -> WrappedKey | None:
        vs = [v for (u, v) in self.keys if u == user_id]
        return self.keys[(user_id, max(vs))] if vs else None

    def put(self, wk: WrappedKey) -> bool:
        with self._lock:
            if wk.user_id in self.tombstones:
                raise KeyShredded("user key is tombstoned")
            if (wk.user_id, wk.key_version) in self.keys:
                return False
            self.keys[(wk.user_id, wk.key_version)] = wk
            return True

    def rewrap(self, old: WrappedKey, wrapped: bytes, master_key_id: str) -> bool:
        with self._lock:
            cur = self.keys.get((old.user_id, old.key_version))
            if cur is None or cur.master_key_id != old.master_key_id:
                return False
            self.keys[(old.user_id, old.key_version)] = WrappedKey(
                old.user_id, old.key_version, wrapped, master_key_id
            )
            return True

    def delete_all(self, user_id: UUID) -> int:
        with self._lock:
            gone = [k for k in self.keys if k[0] == user_id]
            for k in gone:
                del self.keys[k]
            return len(gone)

    def tombstone(self, user_id: UUID) -> None:
        self.tombstones.add(user_id)

    def is_tombstoned(self, user_id: UUID) -> bool:
        return user_id in self.tombstones

    def all_for_master(self, master_key_id: str, limit: int) -> list[WrappedKey]:
        rows = sorted(
            (w for w in self.keys.values() if w.master_key_id == master_key_id),
            key=lambda w: (str(w.user_id), w.key_version),
        )
        return rows[:limit]

"""Key stores and the key repository (docs/ARCHITECTURE_V1.md section 6.4).

A KeyStore wraps and unwraps per-user data keys under a master key. KeyRepository is the only
code that opens PERCH_KEYS_DATABASE_URL. Keys, wrapped keys and plaintext are never logged and
never put in exception messages.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import threading
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import NamedTuple
from uuid import UUID

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg_pool import ConnectionPool

WRAP_VERSION = 0x01
TOMBSTONED_SQLSTATE = "P0K01"  # raised by the user_keys trigger (keys migration 0002)
_KCV_LABEL = b"perch/v1/kcv"


class CryptoError(Exception):
    """Base class for crypto failures. Messages are fixed text, never data."""


class KeyShredded(CryptoError):
    """Tombstone present or no key rows: the data is gone for good."""


class DecryptError(CryptoError):
    """Tag mismatch, wrong AAD, or a truncated blob."""


class KeyMissing(CryptoError):
    """No key row and no tombstone: the keys database is wrong or stale, not a shred."""


class WrappedKey(NamedTuple):
    user_id: UUID
    key_version: int
    wrapped: bytes
    master_key_id: str

    def __repr__(self) -> str:  # never print the wrapped key
        return (
            f"WrappedKey(user_id={self.user_id}, key_version={self.key_version}, "
            f"master_key_id={self.master_key_id!r})"
        )


def check_value(master: bytes) -> bytes:
    """Key check value: proves a master id still names the same key material."""
    return hmac.new(master, _KCV_LABEL, hashlib.sha256).digest()


def _checked_data_key(key: bytes) -> bytes:
    if len(key) != 32:
        raise DecryptError("wrapped key is malformed")
    return key


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

    def check_values(self) -> dict[str, bytes]:
        """Master id -> key check value for every master key this store holds."""
        return {}


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
        self._current = e.get("PERCH_MASTER_KEY_ID", "")
        if not self._current:
            raise CryptoError("PERCH_MASTER_KEY_ID must be set with PERCH_MASTER_KEY")
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

    def check_values(self) -> dict[str, bytes]:
        return {mid: check_value(k) for mid, k in self._keys.items()}

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
            plain = AESGCM(key).decrypt(
                w[1:13], w[13:], wrap_aad(wk.user_id, wk.key_version, wk.master_key_id)
            )
        except InvalidTag:
            raise DecryptError("wrapped key failed authentication") from None
        return _checked_data_key(plain)


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
    """The only code that opens PERCH_KEYS_DATABASE_URL. One small connection pool."""

    def __init__(self, url: str | None = None, *, max_size: int = 8) -> None:
        self._url = url
        self._max = max_size
        self._pool: ConnectionPool | None = None
        self._pool_lock = threading.Lock()

    def _conn(self) -> AbstractContextManager[psycopg.Connection]:
        """A pooled autocommit connection (a context manager that returns it to the pool)."""
        if self._pool is None:
            with self._pool_lock:
                if self._pool is None:
                    url = self._url or os.environ.get("PERCH_KEYS_DATABASE_URL", "")
                    if not url:
                        raise CryptoError("PERCH_KEYS_DATABASE_URL is not set")
                    pool = ConnectionPool(
                        url,
                        min_size=1,
                        max_size=self._max,
                        kwargs={"autocommit": True},
                        check=ConnectionPool.check_connection,
                        open=False,
                    )
                    pool.open(wait=False)
                    self._pool = pool
        return self._pool.connection()

    def close(self) -> None:
        with self._pool_lock:
            if self._pool is not None:
                self._pool.close()
                self._pool = None

    @staticmethod
    def _wk(row: tuple) -> WrappedKey:
        return WrappedKey(row[0], row[1], bytes(row[2]), row[3])

    def get(self, user_id: UUID, key_version: int) -> WrappedKey | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT user_id, key_version, wrapped_key, master_key_id FROM user_keys "
                "WHERE user_id = %s AND key_version = %s",
                (user_id, key_version),
            ).fetchone()
        return self._wk(row) if row else None

    def latest(self, user_id: UUID) -> WrappedKey | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT user_id, key_version, wrapped_key, master_key_id FROM user_keys "
                "WHERE user_id = %s ORDER BY key_version DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return self._wk(row) if row else None

    def put(self, wk: WrappedKey) -> bool:
        """Insert with ON CONFLICT DO NOTHING. True when this call inserted the row.

        Raises KeyShredded when the database trigger refuses a tombstoned user. Any other
        integrity error becomes a CryptoError with fixed text (the driver message can quote
        the failing row).
        """
        try:
            with self._conn() as c:
                cur = c.execute(
                    "INSERT INTO user_keys (user_id, key_version, wrapped_key, master_key_id) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (wk.user_id, wk.key_version, wk.wrapped, wk.master_key_id),
                )
                return cur.rowcount == 1
        except psycopg.errors.Error as e:
            if e.sqlstate == TOMBSTONED_SQLSTATE:
                raise KeyShredded("user key is tombstoned") from None
            if isinstance(e, psycopg.errors.IntegrityError | psycopg.errors.DataError):
                raise CryptoError("key row was refused by the keys database") from None
            raise

    def rewrap(self, old: WrappedKey, wrapped: bytes, master_key_id: str) -> bool:
        """Replace the wrapping of one row if it still has the old master id."""
        with self._conn() as c:
            cur = c.execute(
                "UPDATE user_keys SET wrapped_key = %s, master_key_id = %s "
                "WHERE user_id = %s AND key_version = %s AND master_key_id = %s",
                (wrapped, master_key_id, old.user_id, old.key_version, old.master_key_id),
            )
            return cur.rowcount == 1

    def delete_all(self, user_id: UUID) -> int:
        with self._conn() as c:
            return c.execute("DELETE FROM user_keys WHERE user_id = %s", (user_id,)).rowcount

    def tombstone(self, user_id: UUID) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO key_tombstones (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (user_id,),
            )

    def shred(self, user_id: UUID) -> int:
        """Tombstone, then delete every key row, in one transaction under the per-user
        advisory lock that the user_keys trigger also takes. Returns key rows deleted."""
        with self._conn() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s::text, 0))", (user_id,))
            c.execute(
                "INSERT INTO key_tombstones (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (user_id,),
            )
            return c.execute("DELETE FROM user_keys WHERE user_id = %s", (user_id,)).rowcount

    def is_tombstoned(self, user_id: UUID) -> bool:
        with self._conn() as c:
            return (
                c.execute("SELECT 1 FROM key_tombstones WHERE user_id = %s", (user_id,)).fetchone()
                is not None
            )

    def all_for_master(self, master_key_id: str, limit: int) -> list[WrappedKey]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT user_id, key_version, wrapped_key, master_key_id FROM user_keys "
                "WHERE master_key_id = %s ORDER BY user_id, key_version LIMIT %s",
                (master_key_id, limit),
            ).fetchall()
        return [self._wk(r) for r in rows]

    def users_with_rotated_keys(self, after: UUID | None, limit: int) -> list[tuple[UUID, int]]:
        """(user_id, newest version) for users with more than one key version, by user id."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT user_id, max(key_version) FROM user_keys "
                "WHERE (%s::uuid IS NULL OR user_id > %s::uuid) "
                "GROUP BY user_id HAVING max(key_version) > 1 ORDER BY user_id LIMIT %s",
                (after, after, limit)).fetchall()
        return [(r[0], r[1]) for r in rows]

    def count_for_master(self, master_key_id: str) -> int:
        with self._conn() as c:
            return c.execute("SELECT count(*) FROM user_keys WHERE master_key_id = %s",
                             (master_key_id,)).fetchone()[0]

    def purge_tombstones(self, older_than_days: int, dry_run: bool = True) -> int:
        """Delete (or with dry_run only count) tombstones older than the age, through the
        definer function, which refuses an age under 400 days."""
        with self._conn() as c:
            return c.execute("SELECT perch_keys_purge_tombstones(make_interval(days => %s), %s)",
                             (older_than_days, dry_run)).fetchone()[0]

    def verify_masters(self, values: dict[str, bytes]) -> None:
        """Register each master id's key check value on first sight; refuse a different key
        under an id that is already registered."""
        for mid, kcv in values.items():
            with self._conn() as c:
                c.execute(
                    "INSERT INTO key_masters (master_key_id, kcv) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (mid, kcv),
                )
                row = c.execute(
                    "SELECT kcv FROM key_masters WHERE master_key_id = %s", (mid,)
                ).fetchone()
            if row is None or not hmac.compare_digest(bytes(row[0]), kcv):
                raise CryptoError("a master key id is registered with different key material")


class InMemoryKeyRepository(KeyRepository):
    """Same interface, no database. For unit tests that need no Postgres."""

    def __init__(self) -> None:
        super().__init__(None)
        self._lock = threading.Lock()
        self.keys: dict[tuple[UUID, int], WrappedKey] = {}
        self.tombstones: set[UUID] = set()
        self.tombstone_at: dict[UUID, datetime] = {}  # tests backdate this
        self.masters: dict[str, bytes] = {}

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
        with self._lock:
            self.tombstones.add(user_id)
            self.tombstone_at.setdefault(user_id, datetime.now(UTC))

    def shred(self, user_id: UUID) -> int:
        with self._lock:
            self.tombstones.add(user_id)
            self.tombstone_at.setdefault(user_id, datetime.now(UTC))
            gone = [k for k in self.keys if k[0] == user_id]
            for k in gone:
                del self.keys[k]
            return len(gone)

    def close(self) -> None:
        return None

    def verify_masters(self, values: dict[str, bytes]) -> None:
        with self._lock:
            for mid, kcv in values.items():
                if not hmac.compare_digest(self.masters.setdefault(mid, kcv), kcv):
                    raise CryptoError("a master key id is registered with different key material")

    def is_tombstoned(self, user_id: UUID) -> bool:
        return user_id in self.tombstones

    def users_with_rotated_keys(self, after: UUID | None, limit: int) -> list[tuple[UUID, int]]:
        newest: dict[UUID, int] = {}
        for u, v in self.keys:
            newest[u] = max(newest.get(u, 0), v)
        rows = [(u, v) for u, v in newest.items()
                if v > 1 and (after is None or str(u) > str(after))]
        return sorted(rows, key=lambda r: str(r[0]))[:limit]

    def count_for_master(self, master_key_id: str) -> int:
        return sum(1 for w in self.keys.values() if w.master_key_id == master_key_id)

    def purge_tombstones(self, older_than_days: int, dry_run: bool = True) -> int:
        old = [u for u, at in self.tombstone_at.items()
               if u in self.tombstones and at < datetime.now(UTC) - timedelta(days=older_than_days)]
        if not dry_run:
            self.tombstones.difference_update(old)
        return len(old)

    def all_for_master(self, master_key_id: str, limit: int) -> list[WrappedKey]:
        rows = sorted(
            (w for w in self.keys.values() if w.master_key_id == master_key_id),
            key=lambda w: (str(w.user_id), w.key_version),
        )
        return rows[:limit]

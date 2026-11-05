"""Typed, encrypted access to `user_data` (ARCHITECTURE_V1 sections 2.2 and 6.4).

This is the only module that reads or writes `user_data.blob` or `users.openalex_id_enc`.
Each call opens `user_tx(user_id)` (or runs inside a connection the caller passes, which a job
handler takes from `ctx.user_tx()` so the write is lease-fenced), builds the AAD, encrypts or
decrypts, and validates against the pydantic model for the kind.

Never logged: plaintext, blobs, keys. Errors carry fixed messages only (section 3.7).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import TypeVar
from uuid import UUID, uuid4

import psycopg
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ValidationError

from perch import crypto
from perch.crypto import Aad, CryptoError, KeyMissing
from perch.store import pg
from perch.user.models import MODEL_FOR_KIND, Audience, UserKind

M = TypeVar("M", bound=BaseModel)


class UserDataError(Exception):
    """A user-data failure with a fixed message."""


class NotFound(UserDataError):
    pass


class Conflict(UserDataError):
    """A stale write: the row changed since `expect_updated_at`."""


class BadBlob(UserDataError):
    """A decrypted blob that does not match its model. The value is never echoed."""


def aad_for(user_id: UUID, row_id: UUID | str, kind: str, audience: str) -> Aad:
    return Aad(user_id, "user_data", "blob", str(row_id), f"{kind}:{audience}")


def _load(model_cls: type[M], plain: bytes) -> M:  # noqa: UP047
    try:
        return model_cls.model_validate_json(plain)
    except ValidationError:
        raise BadBlob("stored data does not match its model") from None


def _dump(model: BaseModel) -> bytes:
    return json.dumps(json.loads(model.model_dump_json()), separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


class UserData:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    @contextmanager
    def _tx(self, user_id: UUID, conn: psycopg.Connection | None) -> Iterator[psycopg.Connection]:
        if conn is not None:
            yield conn
        else:
            with pg.user_tx(self.pool, user_id) as c:
                yield c

    # -- encryption with the first-write rule --

    def _encrypt(self, c: psycopg.Connection, user_id: UUID, plain: bytes, aad: Aad) -> bytes:
        """Encrypt under the user's key. A key is minted (create=True) only when the user has
        no user_data rows at all: rows without a key mean the key is gone, and a new key would
        silently hide that (S37 review)."""
        try:
            return crypto.encrypt_field(user_id, plain, aad)
        except KeyMissing:
            if c.execute("SELECT 1 FROM user_data WHERE user_id = %s LIMIT 1",
                         (user_id,)).fetchone() is not None:
                raise
            return crypto.encrypt_field(user_id, plain, aad, create=True)

    # -- typed access --

    def put(self, user_id: UUID, kind: UserKind, audience: Audience, model: BaseModel, *,
            row_id: UUID | None = None, conn: psycopg.Connection | None = None) -> UUID:
        """Insert one row; return its id. A new CV replaces the old one for that audience."""
        expected = MODEL_FOR_KIND.get(kind)
        if expected is None or not isinstance(model, expected):
            raise UserDataError("model does not match the kind")
        rid = row_id or uuid4()
        plain = _dump(model)
        with self._tx(user_id, conn) as c:
            blob = self._encrypt(c, user_id, plain, aad_for(user_id, rid, kind, audience))
            if kind == "cv":
                c.execute("DELETE FROM user_data WHERE user_id = %s AND audience = %s "
                          "AND kind = 'cv'", (user_id, audience))
            c.execute("INSERT INTO user_data (id, user_id, kind, audience, key_version, blob) "
                      "VALUES (%s, %s, %s, %s, %s, %s)",
                      (rid, user_id, kind, audience, crypto.key_version_of(blob), blob))
        return rid

    def get(self, user_id: UUID, row_id: UUID, model_cls: type[M], *,
            conn: psycopg.Connection | None = None) -> M | None:
        got = self.get_row(user_id, row_id, model_cls, conn=conn)
        return got[0] if got else None

    def get_row(self, user_id: UUID, row_id: UUID, model_cls: type[M], *,
                conn: psycopg.Connection | None = None, kind: str | None = None
                ) -> tuple[M, datetime, str, str] | None:
        """(model, updated_at, kind, audience), or None for a missing or foreign id, or for a
        row of another kind than `kind` when one is given (checked before any decryption)."""
        with self._tx(user_id, conn) as c:
            row = c.execute("SELECT kind, audience, blob, updated_at FROM user_data "
                            "WHERE id = %s AND user_id = %s", (row_id, user_id)).fetchone()
        if row is None or (kind is not None and row[0] != kind):
            return None
        kind, audience, blob, updated = row
        plain = crypto.decrypt_field(user_id, bytes(blob), aad_for(user_id, row_id, kind, audience))
        return _load(model_cls, plain), updated, kind, audience

    def list(self, user_id: UUID, kind: UserKind, audience: Audience, model_cls: type[M], *,
             limit: int = 50, conn: psycopg.Connection | None = None) -> list[tuple[UUID, M]]:
        with self._tx(user_id, conn) as c:
            rows = c.execute(
                "SELECT id, blob FROM user_data WHERE user_id = %s AND kind = %s "
                "AND audience = %s ORDER BY updated_at DESC, id LIMIT %s",
                (user_id, kind, audience, limit)).fetchall()
        plains = crypto.decrypt_many(
            user_id, [(bytes(b), aad_for(user_id, i, kind, audience)) for i, b in rows])
        return [(i, _load(model_cls, p)) for (i, _), p in zip(rows, plains, strict=True)]

    def update(self, user_id: UUID, row_id: UUID, model: BaseModel, *,
               expect_updated_at: datetime, conn: psycopg.Connection | None = None) -> datetime:
        """Replace a row's content. Raises Conflict on a stale write and NotFound for a missing
        id. Returns the new `updated_at`, which the next update expects."""
        plain = _dump(model)
        with self._tx(user_id, conn) as c:
            row = c.execute("SELECT kind, audience FROM user_data WHERE id = %s AND user_id = %s",
                            (row_id, user_id)).fetchone()
            if row is None:
                raise NotFound("no such row")
            expected = MODEL_FOR_KIND[row[0]]
            if not isinstance(model, expected):
                raise UserDataError("model does not match the kind")
            blob = self._encrypt(c, user_id, plain, aad_for(user_id, row_id, row[0], row[1]))
            got = c.execute(
                "UPDATE user_data SET blob = %s, key_version = %s, updated_at = clock_timestamp() "
                "WHERE id = %s AND user_id = %s AND updated_at = %s RETURNING updated_at",
                (blob, crypto.key_version_of(blob), row_id, user_id,
                 expect_updated_at)).fetchone()
            if got is None:
                raise Conflict("the row changed")
        return got[0]

    def delete(self, user_id: UUID, row_id: UUID, *, kinds: tuple[str, ...] | None = None,
               conn: psycopg.Connection | None = None) -> bool:
        with self._tx(user_id, conn) as c:
            return c.execute(
                "DELETE FROM user_data WHERE id = %s AND user_id = %s "
                "AND (%s::text[] IS NULL OR kind = ANY(%s))",
                (row_id, user_id, list(kinds) if kinds else None,
                 list(kinds) if kinds else None)).rowcount > 0

    def count(self, user_id: UUID, *, conn: psycopg.Connection | None = None) -> int:
        with self._tx(user_id, conn) as c:
            return c.execute("SELECT count(*) FROM user_data WHERE user_id = %s",
                             (user_id,)).fetchone()[0]

    # -- the OpenAlex link: users.openalex_id_enc --

    def link_openalex(self, user_id: UUID, author_id: str | None, *,
                      conn: psycopg.Connection | None = None) -> None:
        with self._tx(user_id, conn) as c:
            if author_id is None:
                blob = None
            else:
                blob = self._encrypt_link(c, user_id, author_id)
            c.execute("UPDATE users SET openalex_id_enc = %s, openalex_linked_at = now() "
                      "WHERE id = %s", (blob, user_id))

    def _encrypt_link(self, c: psycopg.Connection, user_id: UUID, author_id: str) -> bytes:
        aad = Aad(user_id, "users", "openalex_id_enc", str(user_id))
        return self._encrypt(c, user_id, author_id.encode(), aad)

    def linked_openalex(self, user_id: UUID, *, conn: psycopg.Connection | None = None
                        ) -> str | None:
        with self._tx(user_id, conn) as c:
            row = c.execute("SELECT openalex_id_enc FROM users WHERE id = %s",
                            (user_id,)).fetchone()
        if row is None or row[0] is None:
            return None
        aad = Aad(user_id, "users", "openalex_id_enc", str(user_id))
        return crypto.decrypt_field(user_id, bytes(row[0]), aad).decode()


__all__ = ["BadBlob", "Conflict", "CryptoError", "NotFound", "UserData",
                      "UserDataError", "aad_for"]

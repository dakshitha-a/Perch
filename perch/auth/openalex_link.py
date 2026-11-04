"""The self-asserted OpenAlex link (section 7.5, D-4), stored encrypted in
users.openalex_id_enc.

STUB BEHIND AN INTERFACE. Section 6 names perch/user/data.py as the only code that touches this
column, but that module belongs to the user-data work. `OpenAlexLinkStore` is the seam: this
default implements it directly with perch.crypto, using the AAD the contract gives
(table users, column openalex_id_enc, row id the user id, no extra). When perch/user/data.py has
an equivalent, point app.state.openalex_links at it and delete the default below.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from psycopg_pool import ConnectionPool

from perch import crypto
from perch.crypto import Aad
from perch.store.pg import user_tx


class OpenAlexLinkStore(Protocol):
    def put(self, user_id: UUID, author_id: str) -> None: ...
    def get(self, user_id: UUID) -> str | None: ...


def _aad(user_id: UUID) -> Aad:
    return Aad(user_id, "users", "openalex_id_enc", str(user_id))


class CryptoLinkStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def put(self, user_id: UUID, author_id: str) -> None:
        blob = crypto.encrypt_field(user_id, author_id.encode(), _aad(user_id), create=True)
        with user_tx(self.pool, user_id) as c:
            c.execute("UPDATE users SET openalex_id_enc = %s, openalex_linked_at = now() "
                      "WHERE id = %s", (blob, user_id))

    def get(self, user_id: UUID) -> str | None:
        with user_tx(self.pool, user_id) as c:
            row = c.execute("SELECT openalex_id_enc FROM users WHERE id = %s",
                            (user_id,)).fetchone()
        if not row or row[0] is None:
            return None
        return crypto.decrypt_field(user_id, bytes(row[0]), _aad(user_id)).decode()

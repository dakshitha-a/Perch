"""The self-asserted OpenAlex link (section 7.5, D-4), stored encrypted in
users.openalex_id_enc.

`OpenAlexLinkStore` is the seam the auth routes use. The only implementation is
`UserDataLinkStore`, which goes through perch/user/data.py, the one module that touches the
column (section 2.2). Encryption, the AAD and the key-minting rule live there.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from perch.user.data import UserData


class OpenAlexLinkStore(Protocol):
    def put(self, user_id: UUID, author_id: str) -> None: ...
    def get(self, user_id: UUID) -> str | None: ...


class UserDataLinkStore:
    def __init__(self, ud: UserData) -> None:
        self.ud = ud

    def put(self, user_id: UUID, author_id: str) -> None:
        self.ud.link_openalex(user_id, author_id)

    def get(self, user_id: UUID) -> str | None:
        return self.ud.linked_openalex(user_id)

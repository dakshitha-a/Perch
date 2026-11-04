"""Sessions in Redis (ARCHITECTURE_V1 sections 7.1 and 7.3). S41 seam: the dataclass is fixed;
SessionStore is implemented by the auth work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

Audience = Literal["researcher", "student"]


@dataclass
class Session:
    sid: str
    user_id: UUID | None  # None for a guest
    guest: bool
    roles: frozenset[str]  # any of "student", "researcher", "staff"; empty for a guest
    audience: Audience
    csrf: str
    display_name: str | None
    created: float
    abs_exp: float

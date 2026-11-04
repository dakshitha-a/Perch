"""The AuthProvider interface (ARCHITECTURE_V1 section 7.1). OidcProvider lives in oidc.py."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class AuthError(Exception):
    """A sign-in failure with a fixed code, such as "state_unknown" or "bad_token"."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str  # the IdP's stable id for the user
    display_name: str | None  # session only, never stored in Postgres
    claims: Mapping[str, Any]  # raw claims, read by role mapping, never stored


@dataclass(frozen=True)
class AuthRedirect:
    url: str
    state: str
    binder: str  # random value set as the __Host-perch_oidc cookie


class AuthProvider(ABC):
    name: str

    @abstractmethod
    async def begin(self, return_to: str) -> AuthRedirect: ...

    @abstractmethod
    async def complete(self, params: Mapping[str, str],
                       binder: str | None) -> tuple[Identity, str]: ...

    @abstractmethod
    async def end_session_url(self, post_logout_redirect: str) -> str | None: ...


def safe_return_to(v: str | None) -> str:
    if v and v.startswith("/") and not v.startswith("//") and "\\" not in v and "\n" not in v:
        return v
    return "/"

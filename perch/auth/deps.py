"""FastAPI dependencies (ARCHITECTURE_V1 section 7.1). S41 seam: these signatures are fixed.
Code that needs the signed-in user depends on them; tests replace them with
`app.dependency_overrides`. The auth work implements the bodies."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request

from perch.auth.session import Session


async def session_optional(request: Request) -> Session | None:
    raise NotImplementedError


async def require_session(request: Request) -> Session:  # 401 when none
    raise NotImplementedError


async def require_user(request: Request) -> Session:  # 401 for none, 403 for a guest
    raise NotImplementedError


def require_role(*roles: str) -> Callable[..., Session]:  # 403 when not held
    raise NotImplementedError


async def require_csrf(request: Request) -> None:  # on every non-GET
    raise NotImplementedError


def require_consent(session: Session) -> None:  # 403 consent_required
    raise NotImplementedError

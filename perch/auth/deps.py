"""FastAPI dependencies (ARCHITECTURE_V1 section 7.1). S41 seam: these signatures are fixed.
Code that needs the signed-in user depends on them; tests replace them with
`app.dependency_overrides`.

The session store is read from `request.app.state.sessions` (a SessionStore, or None when the
app runs without Redis, in which case nobody is signed in).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

from perch.auth import audit, settings
from perch.auth.session import Session
from perch.config import env

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def session_optional(request: Request) -> Session | None:
    cached = getattr(request.state, "perch_session", False)
    if cached is not False:
        return cached
    store = getattr(request.app.state, "sessions", None)
    sid = request.cookies.get(settings.session_cookie_name())
    s = await store.get(sid) if store is not None and sid else None
    request.state.perch_session = s
    return s


async def require_session(request: Request) -> Session:  # 401 when none
    s = await session_optional(request)
    if s is None:
        raise HTTPException(401, "not_signed_in")
    return s


async def require_user(request: Request) -> Session:  # 401 for none, 403 for a guest
    s = await require_session(request)
    if s.guest or s.user_id is None:
        raise HTTPException(403, "account_required")
    return s


USER = Depends(require_user)


def require_role(*roles: str) -> Callable[..., Session]:  # 403 when not held
    wanted = frozenset(roles)

    async def dep(session: Session = USER) -> Session:
        if not (session.roles & wanted):
            raise HTTPException(403, "role_required")
        return session

    return dep


def origin_ok(request: Request) -> bool:
    """The Origin header must equal PERCH_PUBLIC_URL's origin. Absent or different: refused."""
    want = settings.public_origin()
    got = request.headers.get("origin")
    return bool(want and got and got == want)


def reject_csrf(request: Request, why: str, session: Session | None = None) -> HTTPException:
    audit.record(request, "csrf_reject", actor=session.user_id if session else None, why=why)
    return HTTPException(403, "csrf_rejected")


async def require_csrf(request: Request) -> None:  # on every non-GET
    if request.method in SAFE_METHODS:
        return
    s = await require_session(request)
    if not origin_ok(request):
        raise reject_csrf(request, "origin", s)
    store = request.app.state.sessions
    if not store.csrf_ok(s, request.headers.get("x-csrf-token")):
        raise reject_csrf(request, "token", s)


def require_consent(session: Session) -> None:  # 403 consent_required
    """Accepted and not withdrawn at the current PERCH_CONSENT_VERSION. A version bump makes
    every older acceptance stale. A guest never has consent."""
    need = int(env("PERCH_CONSENT_VERSION", "1") or 1)
    if session.guest or session.consent_version < need:
        raise HTTPException(403, "consent_required")

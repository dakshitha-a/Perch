"""Auth, guest and account routes (ARCHITECTURE_V1 section 7). Included in the app by
perch.auth.wiring.install_auth.

State read from `request.app.state`:
  sessions        SessionStore (Redis)
  pool            psycopg ConnectionPool for perch_web
  auth_provider   an AuthProvider (OidcProvider in production)
  author_lookup   callable(author_id) -> None, raises LookupError when OpenAlex has no such id
  openalex_links  an OpenAlexLinkStore

Nothing here logs a cookie, a token, a code, an address or the OpenAlex id.
"""

from __future__ import annotations

import hashlib
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from perch import redisx as rx
from perch.auth import accounts, audit, settings
from perch.auth.base import AuthError, AuthProvider, safe_return_to
from perch.auth.consent import consent_text
from perch.auth.deps import (
    origin_ok,
    reject_csrf,
    require_csrf,
    require_user,
    session_optional,
)
from perch.auth.session import Audience, Session, SessionStore
from perch.config import env
from perch.sources import openalex as oa

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}
USER = Depends(require_user)


# --- helpers ---

def _store(request: Request) -> SessionStore:
    s = getattr(request.app.state, "sessions", None)
    if s is None:
        raise HTTPException(503, "auth_unavailable")
    return s


def _pool(request: Request):  # noqa: ANN202
    p = getattr(request.app.state, "pool", None)
    if p is None:
        raise HTTPException(503, "db_unavailable")
    return p


def _json(data: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers=NO_STORE)


def _limit(request: Request, scope: str, subject: str) -> None:
    ok, retry = rx.rate_limit(_store(request).r, scope, subject)
    if not ok:
        # One audit row per subject, scope and window, so a flood of 429s cannot flood the table.
        _, window = rx.rate_table()[scope]
        first = _store(request).r.set(f"{rx.PREFIX}:rl_audit:{scope}:{subject}", 1, nx=True,
                                      ex=window)
        if first:
            audit.record(request, "rate_limited", scope=scope)
        raise HTTPException(429, "rate_limited", headers={"Retry-After": str(retry)})


def _addr_subject(request: Request) -> str:
    return rx.hash_subject(rx.client_addr(request))


def _set_session_cookie(resp: Response, sid: str) -> None:
    # Session cookie: no Max-Age, no Domain, Path=/ (section 7.3).
    resp.set_cookie(settings.session_cookie_name(), sid, httponly=True,
                    secure=not settings.cookie_insecure(), samesite="lax", path="/")


def _clear_session_cookie(resp: Response) -> None:
    resp.delete_cookie(settings.session_cookie_name(), path="/", httponly=True,
                       secure=not settings.cookie_insecure(), samesite="lax")


def _set_oidc_cookie(resp: Response, binder: str) -> None:
    resp.set_cookie(settings.oidc_cookie_name(), binder, max_age=settings.OIDC_COOKIE_MAX_AGE,
                    httponly=True, secure=not settings.cookie_insecure(), samesite="lax",
                    path="/")


def _clear_oidc_cookie(resp: Response) -> None:
    resp.delete_cookie(settings.oidc_cookie_name(), path="/", httponly=True,
                       secure=not settings.cookie_insecure(), samesite="lax")


def _provider(request: Request) -> AuthProvider:
    p = getattr(request.app.state, "auth_provider", None)
    if p is None:
        raise HTTPException(503, "auth_unavailable")
    return p


def _needs_welcome(roles: frozenset[str] | set[str], consent_version: int) -> bool:
    return not (roles & {"student", "researcher"}) or consent_version < settings.consent_version()


# --- sign-in ---

@router.get("/auth/login")
async def login(request: Request, return_to: str | None = None) -> Response:
    _limit(request, "login_global", "site")
    _limit(request, "login_start", _addr_subject(request))
    if getattr(request.app.state, "auth_provider", None) is None:
        # A browser navigation: land on the app with a code, never on a JSON page (S43 M1).
        return RedirectResponse("/#/?signin=unavailable", status_code=302, headers=NO_STORE)
    red = await _provider(request).begin(safe_return_to(return_to))
    resp = RedirectResponse(red.url, status_code=302, headers=NO_STORE)
    _set_oidc_cookie(resp, red.binder)
    return resp


@router.get("/auth/callback")
async def callback(request: Request) -> Response:
    if getattr(request.app.state, "auth_provider", None) is None:
        return RedirectResponse("/#/?signin=unavailable", status_code=302, headers=NO_STORE)
    binder = request.cookies.get(settings.oidc_cookie_name())
    _limit(request, "login_callback", hashlib.sha256((binder or "none").encode()).hexdigest())
    store, pool = _store(request), _pool(request)
    try:
        identity, return_to = await _provider(request).complete(dict(request.query_params), binder)
    except AuthError:
        # The code is not shown; the app says "Sign-in did not finish" (S43 M1).
        resp = RedirectResponse("/#/?signin=failed", status_code=302, headers=NO_STORE)
        _clear_oidc_cookie(resp)
        return resp
    uid = await run_in_threadpool(accounts.login_user, pool, identity.issuer, identity.subject)
    acct = await run_in_threadpool(accounts.load_account, pool, uid)
    roles = set(acct.roles)
    group = env("PERCH_STAFF_GROUP")
    groups = identity.claims.get("groups")
    if group and isinstance(groups, list) and group in groups:
        roles.add("staff")  # session only; UNVERIFIED for Temple until the claim is confirmed
    audience: Audience | None = acct.last_audience if acct.last_audience in roles else None  # type: ignore[assignment]
    # A new sid is always issued; any sid the browser sent is deleted (fixation).
    old = request.cookies.get(settings.session_cookie_name())
    if old:
        await store.destroy(old)
    s = await store.create_user(uid, roles, identity, audience=audience,
                                consent_version=acct.consent_version)
    target = return_to
    if _needs_welcome(acct.roles, acct.consent_version):
        target = "/welcome?return_to=" + quote(return_to, safe="/")
    resp = RedirectResponse(target, status_code=302, headers=NO_STORE)
    _set_session_cookie(resp, s.sid)
    _clear_oidc_cookie(resp)
    return resp


@router.post("/auth/logout")
async def logout(request: Request) -> Response:
    s = await session_optional(request)
    end_url: str | None = None
    if s is not None:
        await require_csrf(request)
        await _store(request).destroy(s.sid)
        if not s.guest and getattr(request.app.state, "auth_provider", None) is not None:
            end_url = await request.app.state.auth_provider.end_session_url(
                settings.public_url() + "/")
    resp = _json({"end_session_url": end_url})
    _clear_session_cookie(resp)
    return resp


@router.get("/auth/session")
async def session_info(request: Request) -> Response:
    s = await session_optional(request)
    if s is None:
        return _json({"signed_in": False, "accounts_open": settings.accounts_open()})
    out: dict = {"signed_in": not s.guest, "guest": s.guest, "roles": sorted(s.roles),
                 "audience": s.audience, "csrf": s.csrf, "display_name": s.display_name,
                 "expires_at": s.abs_exp, "accounts_open": settings.accounts_open()}
    if s.guest:
        out["notice"] = "Nothing is saved in a guest session. It ends in an hour."
    else:
        need = settings.consent_version()
        out["consent"] = {"required": s.consent_version < need, "current_version": need,
                          "accepted_version": s.consent_version,
                          "provider_name": settings.consent_provider_name(),
                          "text": consent_text()}  # the welcome screen shows it as built
        out["needs_welcome"] = _needs_welcome(s.roles, s.consent_version)
        pool = getattr(request.app.state, "pool", None)
        if pool is not None and s.user_id is not None:
            acct = await run_in_threadpool(accounts.load_account, pool, s.user_id)
            out["openalex_linked"] = acct.openalex_linked
    return _json(out)


# --- guest ---

class GuestIn(BaseModel):
    audience: Literal["researcher", "student"] = "researcher"


@router.post("/auth/guest")
async def guest(request: Request, body: GuestIn | None = None) -> Response:
    # CSRF-exempt (no session yet), but same-origin.
    if not origin_ok(request):
        raise reject_csrf(request, "origin")
    _limit(request, "guest_new_global", "site")
    _limit(request, "guest_new", _addr_subject(request))
    store = _store(request)
    old = request.cookies.get(settings.session_cookie_name())
    if old:
        await store.destroy(old)
    s = await store.create_guest((body or GuestIn()).audience)
    resp = _json({"guest": True, "audience": s.audience, "csrf": s.csrf, "expires_at": s.abs_exp,
                  "notice": "Nothing is saved in a guest session. It ends in an hour."})
    _set_session_cookie(resp, s.sid)
    return resp


# --- account ---

class ConsentIn(BaseModel):
    version: int | None = None


class RolesIn(BaseModel):
    roles: list[Literal["student", "researcher"]] = Field(min_length=1)  # never "staff"


class AudienceIn(BaseModel):
    audience: Literal["researcher", "student"]


class OpenAlexIn(BaseModel):
    author_id: str = Field(max_length=64)


@router.post("/me/consent", dependencies=[Depends(require_csrf)])
async def consent(request: Request, body: ConsentIn | None = None,
                  s: Session = USER) -> Response:
    need = settings.consent_version()
    if body is not None and body.version is not None and body.version != need:
        raise HTTPException(409, "consent_version_changed")
    assert s.user_id is not None
    _limit(request, "api_write", str(s.user_id))
    await run_in_threadpool(accounts.add_consent, _pool(request), s.user_id, need,
                            settings.consent_provider_name())
    await _store(request).set_consent(s.sid, need)
    await _store(request).set_consent_all(s.user_id, need)
    return _json({"consent_version": need})


@router.post("/me/consent/withdraw", dependencies=[Depends(require_csrf)])
async def consent_withdraw(request: Request, s: Session = USER) -> Response:
    assert s.user_id is not None
    _limit(request, "api_write", str(s.user_id))
    await run_in_threadpool(accounts.withdraw_consent, _pool(request), s.user_id)
    await _store(request).set_consent(s.sid, 0)
    await _store(request).set_consent_all(s.user_id, 0)
    return _json({"consent_version": 0})


@router.post("/me/roles", dependencies=[Depends(require_csrf)])
async def set_roles(request: Request, body: RolesIn, s: Session = USER
                    ) -> Response:
    assert s.user_id is not None
    _limit(request, "api_write", str(s.user_id))
    roles = await run_in_threadpool(accounts.set_roles, _pool(request), s.user_id,
                                    sorted(set(body.roles)))
    store = _store(request)
    await store.set_roles(s.sid, roles | (s.roles & {"staff"}))
    audience = s.audience
    if audience not in roles:  # the current screen side is no longer held
        audience = "student" if "student" in roles else "researcher"
        await store.set_audience(s.sid, audience)
        await run_in_threadpool(accounts.set_last_audience, _pool(request), s.user_id, audience)
    return _json({"roles": sorted(roles), "audience": audience})


@router.post("/me/audience", dependencies=[Depends(require_csrf)])
async def set_audience(request: Request, body: AudienceIn,
                       s: Session = USER) -> Response:
    if body.audience not in s.roles:
        raise HTTPException(403, "audience_not_held")
    assert s.user_id is not None
    _limit(request, "api_write", str(s.user_id))
    await _store(request).set_audience(s.sid, body.audience)
    await run_in_threadpool(accounts.set_last_audience, _pool(request), s.user_id, body.audience)
    return _json({"audience": body.audience})


@router.put("/me/openalex", dependencies=[Depends(require_csrf)])
async def put_openalex(request: Request, body: OpenAlexIn,
                       s: Session = USER) -> Response:
    assert s.user_id is not None
    _limit(request, "api_write", str(s.user_id))
    raw = body.author_id.strip()
    author_id = oa.parse_author_id(raw)
    if not author_id or not oa.author_id_ok(author_id):
        raise HTTPException(422, "invalid_author_id")
    lookup = getattr(request.app.state, "author_lookup", None)
    if lookup is None:
        raise HTTPException(503, "openalex_unavailable")
    try:
        await run_in_threadpool(lookup, author_id)
    except LookupError as e:
        raise HTTPException(404, "author_not_found") from e
    links = getattr(request.app.state, "openalex_links", None)
    if links is None:
        raise HTTPException(503, "db_unavailable")
    await run_in_threadpool(links.put, UUID(str(s.user_id)), author_id)
    return _json({"linked": True, "author_id": author_id})


# --- welcome: the screen is the app's, at #/welcome (S43) ---

@router.get("/welcome")
async def welcome(return_to: str | None = None) -> Response:
    """The sign-in callback sends a new account here. The app owns the screen, so this only
    redirects to it and carries a safe return_to along in the hash."""
    target = safe_return_to(return_to)
    dest = "/#/welcome" + (f"?return_to={quote(target, safe='/')}" if target != "/" else "")
    return RedirectResponse(dest, status_code=302, headers=NO_STORE)

"""Web startup wiring for auth (section 7) and the health readiness check.

`install_auth(app, service)` is the one call from perch/api.py. It includes the router, and at
startup builds the Redis client, the SessionStore, the Postgres pool, the OIDC provider, the
OpenAlex link store, and registers the shred hooks (perch/shredhooks.py). Each part is built
only when its setting is present, so an app without PERCH_REDIS_URL or PERCH_DATABASE_URL
(the unit tests, the fallback demo) starts as before with nobody signed in.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI

from perch import shredhooks
from perch.auth.openalex_link import CryptoLinkStore
from perch.auth.routes import router
from perch.auth.session import SessionStore
from perch.config import env
from perch.redisx import get_client
from perch.store.pg import make_pool

log = logging.getLogger("perch.auth")


def _author_lookup(service: Any) -> Callable[[str], None] | None:  # noqa: ANN401
    if service is None:
        return None

    def lookup(author_id: str) -> None:
        try:
            with service.clients.openalex() as c:
                c.get_author(author_id)
        except httpx.HTTPStatusError as e:
            if 400 <= e.response.status_code < 500:
                raise LookupError(author_id) from e
            raise

    return lookup


def build_state(app: FastAPI, service: Any = None) -> None:  # noqa: ANN401
    """Build what the environment asks for. A part already set on app.state (tests inject
    them) is left alone, and a part with no setting stays as it is."""
    state = app.state
    if state.sessions is None and env("PERCH_REDIS_URL"):
        state.redis = get_client()
        state.sessions = SessionStore(state.redis)
    r = state.sessions.r if state.sessions is not None else None
    if state.pool is None and env("PERCH_DATABASE_URL"):
        state.pool = make_pool()
    if state.pool is not None and getattr(state, "openalex_links", None) is None:
        state.openalex_links = CryptoLinkStore(state.pool)
    if getattr(state, "author_lookup", None) is None:
        state.author_lookup = _author_lookup(service)
    if (getattr(state, "auth_provider", None) is None and r is not None
            and env("PERCH_OIDC_ISSUER") and env("PERCH_OIDC_CLIENT_ID")):
        from perch.auth.oidc import OidcProvider

        state.auth_provider = OidcProvider.from_env(r)
    state.stop_shred_listener = (shredhooks.install(state.pool, r)
                                 if state.pool is not None else (lambda: None))
    log.info("auth wired: redis=%s postgres=%s oidc=%s", r is not None,
             state.pool is not None, getattr(state, "auth_provider", None) is not None)


def close_state(app: FastAPI) -> None:
    stop = getattr(app.state, "stop_shred_listener", None)
    if stop:
        stop()
    pool = getattr(app.state, "pool", None)
    if pool is not None:
        pool.close()


def install_auth(app: FastAPI, service: Any = None) -> None:  # noqa: ANN401
    app.state.sessions = None
    app.state.pool = None
    app.include_router(router)
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a: FastAPI) -> AsyncIterator[Any]:
        build_state(app, service)
        try:
            async with inner(a) as state:
                yield state
        finally:
            close_state(app)

    app.router.lifespan_context = lifespan


def readiness(app: FastAPI) -> dict[str, Any]:
    """Postgres and Redis reachable. A part that is not configured is reported as such and does
    not make the process unready."""
    out: dict[str, Any] = {}
    pool = getattr(app.state, "pool", None)
    if pool is None:
        out["postgres"] = "not_configured"
    else:
        try:
            with pool.connection() as c:
                c.execute("SELECT 1")
            out["postgres"] = "ok"
        except Exception:  # noqa: BLE001
            out["postgres"] = "down"
    store = getattr(app.state, "sessions", None)
    if store is None:
        out["redis"] = "not_configured"
    else:
        try:
            out["redis"] = "ok" if store.r.ping() else "down"
        except Exception:  # noqa: BLE001
            out["redis"] = "down"
    out["ready"] = "down" not in out.values()
    return out

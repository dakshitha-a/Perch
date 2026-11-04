"""HTTP API (SPEC section 6). Run with `perch serve`.

  GET  /health[?deep=true]                     liveness; deep: each model service up or down
  GET  /authors/resolve?q=<name|orcid|id>      candidates for the Find screen

One set of brief routes serves both sides and both kinds of visitor. With account services
(perch/auth, perch/user) a brief belongs to a signed-in user, stored encrypted, or to a guest,
held in Redis for an hour; the session cookie says which. Without them (unit tests, the bench,
replays) the routes work on the service's own store when `stored_briefs=True`, and answer 404
otherwise.

  POST /briefs                                  {"author_id"?, "as_of"?, "top"?, "explain"?, ...}
                                                a job (202). A student's brief needs no author id:
                                                it reads the CV and entries (a guest gets the
                                                SYNTHETIC sample persona)
  GET  /briefs/{id}                             status, stages, profile, leads with records
  POST /briefs/{id}/leads/{lead_id}/keep        and /dismiss, /restore
  GET  /briefs/{id}/export.json[?status=kept]   brief, leads and every record they cite
  GET  /briefs/{id}/export.md, /export.html    the brief as Markdown, or a page to print or save
                                                as PDF; ?status=kept for the kept leads only
  GET  /briefs/{id}/compare[?status=kept|all]   kept leads side by side, each cell with its record
  POST /briefs/{id}/handoff                     {"office", "lead_ids"?}: a hand-off draft to one
                                                Temple office about the kept leads (skill 3);
                                                returned, never stored or sent
  GET  /briefs/{id}/student/note?route=F|S      a student's note to the office for one route
  GET  /records/{id}                            a stored public record, with provenance
  POST /briefs/{id}/scout                       {"question"}: a Scout session about the
                                                brief (S10); each step runs at once (S28)
  GET  /scout/{session}                         its questions, tool cards and answers
  POST /scout/{session}/{action}                ask {"question"}: a follow-up, or stop:
                                                end the current question between steps

  GET  /                                       the web app (web/), when present

Briefs run as background jobs; poll GET /briefs/{id}. Nothing is sent anywhere.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from perch import awards as aw
from perch import compare as cmp
from perch import export as ex
from perch.auth.wiring import install_auth, readiness
from perch.config import env
from perch.jobs import ClosureRunner
from perch.request_models import BriefOptions, HandoffRequest, ScoutRequest
from perch.schemas import (
    USER_KINDS,
    Award,
    Brief,
    Lead,
    Opportunity,
    Organisation,
    Record,
    Researcher,
    Scholarship,
    Work,
)
from perch.scout.hub import Busy, ScoutHub
from perch.scout.hub import view as scout_view
from perch.scout.log import ScoutLog
from perch.service import BriefService
from perch.skills.handoff import Draft
from perch.sources import grants_gov
from perch.sources import openalex as oa
from perch.store.base import Repository

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
KEY_PAPERS = 5  # per thread, most recent-weighted first (thread order from perch.profile)


EMPTY_FIND = "Type a name, ORCID iD or OpenAlex ID."


def draft_json(d: Draft) -> dict:
    return {"office": {"key": d.office.key, "name": d.office.name, "url": d.office.url},
            "to": "", "subject": d.subject, "body": d.body, "lead_ids": d.lead_ids,
            "cited_ids": d.cited_ids, "flagged": d.flagged, "model": d.model,
            "opening_by": d.opening_by}


class BriefRequest(BriefOptions):
    author_id: str | None = Field(None, description="OpenAlex author id, e.g. A5023080104; "
                                  "a student brief has none")
    agencies: list[str] = Field(default_factory=list)
    audience: Literal["researcher", "student"] | None = None  # v1: the session's side decides
    doc_ids: list[UUID] = Field(default_factory=list, max_length=20)  # signed in: user_data rows


async def account_session(request: Request) -> object | None:
    """The v1 session when the app has account services (app.state.user_services), else None,
    so the fallback path is unchanged (S41 part B)."""
    if getattr(request.app.state, "user_services", None) is None:
        return None
    import inspect

    from perch.auth import deps

    # Called by hand, not as a sub-dependency, so the fallback app never touches sessions;
    # an `app.dependency_overrides` entry (tests) is still honoured.
    fn = request.app.dependency_overrides.get(deps.session_optional, deps.session_optional)
    sess = fn(request)
    if inspect.isawaitable(sess):
        sess = await sess
    if sess is None:
        raise HTTPException(401, {"error": "auth_required"})
    return sess


async def optional_session(request: Request) -> object | None:
    """The v1 session when there is one, else None: for routes that serve public records to
    anyone and the user's own documents to their owner."""
    if getattr(request.app.state, "user_services", None) is None:
        return None
    import inspect

    from perch.auth import deps

    fn = request.app.dependency_overrides.get(deps.session_optional, deps.session_optional)
    sess = fn(request)
    return await sess if inspect.isawaitable(sess) else sess


def user_record(request: Request, sess: object | None, record_id: str) -> dict | None:
    """One of the signed-in user's own documents, by the id an explanation cites it by:
    `user:proposal`, `user:interests`, `user:achievement-a` (entries, oldest first). The CV is
    not served; its parse is on the brief. Only the owner's rows are read."""
    from perch.student import achievement_docs
    from perch.user.models import EntryDoc, UserDoc

    if sess is None or getattr(sess, "user_id", None) is None:
        return None
    sv = request.app.state.user_services
    kind = record_id.split(":", 1)[1]
    doc: UserDoc | None = None
    if kind.startswith("achievement-"):
        entries = [e.text for _, e in reversed(sv.ud.list(sess.user_id, "entry", sess.audience,
                                                          EntryDoc, limit=50))]
        doc = next((d for d in achievement_docs(entries) if d.id == record_id), None)
    else:
        doc = next((d for _, d in sv.ud.list(sess.user_id, "doc", sess.audience, UserDoc,
                                             limit=50) if d.id == record_id), None)
    if doc is None:
        return None
    return {"kind": "user", "id": doc.id, "title": doc.title, "text": doc.abstract,
            "source": "user", "source_url": None, "fetched_at": doc.fetched_at.isoformat()}


def user_records(b: Brief) -> dict[str, dict]:
    """The user's own documents the brief cites (a proposal, the interests note, each
    achievement), as the evidence panel opens them. Read through the brief's store, so a
    guest's SYNTHETIC persona and a signed-in user's rows both work; none without a store."""
    from perch.student import achievement_docs
    from perch.user.briefs import current_store

    store = current_store.get()
    if store is None:
        return {}
    docs = list(store.user_docs())
    if b.options.get("student"):
        try:
            inp = store.student_inputs()
        except (LookupError, ValueError):
            return {}
        docs = ([inp.interests] if inp.interests else []) + achievement_docs(inp.entries)
    return {d.id: {"kind": "user", "id": d.id, "title": d.title, "text": d.abstract,
                   "source": "user", "source_url": None,
                   "fetched_at": d.fetched_at.isoformat()} for d in docs}


class WebFiles(StaticFiles):
    """The web app's files, revalidated on every load (S27). Without a Cache-Control
    header, browsers kept old scripts after a release, so visitors saw the previous app."""

    async def get_response(self, path: str, scope: dict) -> Response:
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def record_json(r: Record) -> dict:
    return {"kind": r.kind, **r.model_dump(mode="json")}


def lead_json(lead: Lead, r: Repository) -> dict:
    """A lead with its record, by the lead's route: A a grant, B a company with its signals,
    F and S a student's fellowship or scholarship. Every value is copied from the record."""
    if lead.route == "B":
        return _route_b(lead, r)
    if lead.route in ("F", "S"):
        return _student(lead, r)
    opp = r.get(Opportunity, lead.record_id)
    return {**lead.model_dump(mode="json"),
            "opportunity": opp.model_dump(mode="json", exclude={"description"}) if opp else None}


def _student(lead: Lead, r: Repository) -> dict:
    """A student lead (route F or S) with its record: a Scholarship, or the NIH Opportunity
    behind a fellowship."""
    rec = r.get(Scholarship, lead.record_id) or r.get(Opportunity, lead.record_id)
    out = {**lead.model_dump(mode="json"), "record": None}
    if isinstance(rec, Scholarship):
        out["record"] = {"kind": "scholarship", **rec.model_dump(mode="json")}
        if rec.application_requirements:
            out["record"]["requirements"] = rec.application_requirements.items()
    elif rec is not None:
        out["record"] = {"kind": "opportunity",
                         **rec.model_dump(mode="json", exclude={"description"})}
    return out


SIGNAL_RECORDS = 25  # records sent per Route B signal, newest first; any beyond are counted (U38)


def _route_b(lead: Lead, r: Repository) -> dict:
    """A Route B lead with its organisation and, per signal, the code-written sentence and
    the newest few evidence records (title and date copied from each record)."""
    from perch.route_b import sentence

    org = r.get(Organisation, lead.record_id)
    name = org.name if org else lead.record_id
    items = []
    for s in lead.signals:
        recs = []
        for i in s.record_ids[:SIGNAL_RECORDS]:
            x = r.get_any(i)
            if isinstance(x, Work):
                recs.append({"id": x.id, "kind": "work", "title": x.title,
                             "date": x.publication_date, "venue": x.venue})
            elif isinstance(x, Award):
                recs.append({"id": x.id, "kind": "award", "title": x.title,
                             "date": x.start_date, "venue": x.award_number})
        items.append({"kind": s.kind, "text": sentence(s, name, len(lead.cited_ids)),
                      "records": recs, "more": max(s.count - len(recs), 0)})
    return {**lead.model_dump(mode="json"), "opportunity": None,
            "organisation": org.model_dump(mode="json") if org else None,
            "signal_items": items}


def paper_json(w: Work) -> dict:
    return w.model_dump(mode="json", include={"id", "title", "publication_year", "venue", "doi",
                                              "type", "cited_by_count", "source", "source_url",
                                              "fetched_at"})


class RateLimiter:
    """New briefs per client in a sliding hour. In memory: a restart clears it."""

    def __init__(self, per_hour: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_hour, self.clock = per_hour, clock
        self.seen: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def take(self, key: str) -> int:
        """0 and the request is counted, or the seconds until one is allowed."""
        with self.lock:
            t, q = self.clock(), self.seen[key]
            while q and q[0] <= t - 3600:
                q.popleft()
            if len(q) >= self.per_hour:
                return int(q[0] + 3600 - t) + 1
            q.append(t)
            return 0


MAX_BODY = 8_000_000  # bytes; the largest request is a 5 MB file as base64 (about 6.7 MB)


class BodyLimit:
    """Pure ASGI middleware: a request body over MAX_BODY answers 413 before the app reads
    it (review S10). A declared Content-Length is checked at once; a chunked body is read
    here up to the limit and then handed on."""

    def __init__(self, app: Callable, limit: int = MAX_BODY) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        too_big = JSONResponse({"detail": "The request is too large."}, status_code=413)
        if (n := headers.get(b"content-length")) is not None:
            if not n.isdigit() or int(n) > self.limit:
                await too_big(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return
        if b"chunked" not in headers.get(b"transfer-encoding", b""):
            await self.app(scope, receive, send)
            return
        body, more = bytearray(), True
        while more:
            m = await receive()
            if m["type"] != "http.request":
                return
            body += m.get("body", b"")
            more = m.get("more_body", False)
            if len(body) > self.limit:
                await too_big(scope, receive, send)
                return
        sent = False

        async def replay() -> dict:
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)


def security_headers() -> dict[bytes, bytes]:
    """Headers on every response (review S11). Scripts, styles, fonts and requests come from
    this server only; the HTML export's inline style and print script by their hashes."""
    csp = ("default-src 'self'; "
           f"script-src 'self' {ex.csp_hash(ex.PRINT_JS)}; "
           f"style-src 'self' {ex.csp_hash(ex.CSS)}; "
           "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
           "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
    return {b"content-security-policy": csp.encode(), b"x-frame-options": b"DENY",
            b"x-content-type-options": b"nosniff", b"referrer-policy": b"no-referrer"}


class SecurityHeaders:
    """Pure ASGI middleware that adds security_headers() to every HTTP response. FastAPI's
    own /docs page loads its scripts from a CDN, so it gets no CSP."""

    def __init__(self, app: Callable) -> None:
        self.app, self.headers = app, security_headers()

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        docs = scope.get("path", "") in ("/docs", "/redoc", "/docs/oauth2-redirect")
        # A user's answers are never kept by the browser's HTTP cache (review P3).
        private = scope.get("path", "").startswith(("/briefs", "/scout", "/me"))

        async def add(message: dict) -> None:
            if message["type"] == "http.response.start":
                have = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in self.headers.items() if k not in have
                         and not (docs and k == b"content-security-policy")]
                if private and b"cache-control" not in have:
                    extra.append((b"cache-control", b"no-store"))
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, add)


class Crashed:
    """Pure ASGI middleware: an unhandled exception becomes a 500 naming its type only,
    and is not raised further, so no server log holds its message or traceback."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def watch(message: dict) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, watch)
        except Exception as exc:  # noqa: BLE001 - every error ends here, by type only
            # The type alone reaches the server log: never the message or a traceback.
            logging.getLogger("perch").error("internal error (%s)", type(exc).__name__)
            if not started:
                await JSONResponse({"detail": f"internal error ({type(exc).__name__})"},
                                   status_code=500)(scope, receive, send)


# How `perch serve` runs uvicorn. The tunnel connects from loopback and sets
# X-Forwarded-For to the visitor's address; uvicorn trusts loopback only, so it puts that
# address in request.client before the app sees the request (review W16).
SERVE_OPTIONS = {"proxy_headers": True, "forwarded_allow_ips": "127.0.0.1,::1"}


def client_key(request: Request) -> str:
    """The visitor's address, as uvicorn's proxy-header handling leaves it. A forwarded
    header from any other address is ignored, so it cannot reset a visitor's limits.
    An IPv6 address is keyed by its /64, the block one subscriber usually holds; an
    IPv4-mapped one by its IPv4 address (review S6)."""
    host = request.client.host if request.client else "unknown"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return host


def dependencies() -> dict[str, str]:
    """Health URLs of the model services the current setup calls."""
    from perch.llm.systemone import server_url
    from perch.profiles import current

    p, out = current(), {}
    specs = [p.chat, *p.roles.values()]
    if any(x.startswith("ollama:") for x in specs):  # cloud-cpu has no local model server
        out["ollama"] = (env("OLLAMA_BASE_URL") or "http://127.0.0.1:11434") + "/api/tags"
    for key in (p.grounder, p.reranker):
        if key.startswith("systemone:"):
            name = key.split(":", 1)[1]
            out[name] = server_url(name) + "/health"
    if server := env("PERCH_MODEL_SERVER"):
        out["model_server"] = server + "/health"
    return out


def up(url: str) -> bool:
    try:
        return httpx.get(url, timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


def create_app(service: BriefService, runner: ClosureRunner,
               resolver: type[oa.OpenAlexClient] | None = None,
               web_dir: Path | None = WEB_DIR, scout_runner: ClosureRunner | None = None,
               scout_log: ScoutLog | None = None, stored_briefs: bool | None = None) -> FastAPI:
    stored_briefs = bool(stored_briefs)

    def stored_only(request: Request) -> None:
        if not stored_briefs and getattr(request.app.state, "user_services", None) is None:
            raise HTTPException(404, "Briefs are not available on this server.")

    STORED = [Depends(stored_only)]
    app = FastAPI(title="Perch API", description="See every route to fund your work. "
                  + grants_gov.ATTRIBUTION, version="0.1.0")
    @app.exception_handler(RequestValidationError)
    def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default answer echoes the submitted input; this one names fields only,
        # so no request body ever comes back in a response or a proxy log.
        errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "invalid")}
                  for e in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    # Exception type only: messages can quote request text. A middleware, not an exception
    # handler: Starlette re-raises after its handler runs, and uvicorn then logs the
    # traceback with its message (review S5).
    # Responses over 1 KB are gzipped when the browser asks (review P3): polls and the
    # app's scripts shrink several times over.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(BodyLimit, limit=MAX_BODY)  # inside Crashed: its 413 stays a 413
    app.add_middleware(Crashed)
    app.add_middleware(SecurityHeaders)  # outermost, so a 500 or 413 carries them too

    origins = [o.strip() for o in (env("PERCH_CORS_ORIGINS") or "").split(",") if o.strip()]
    if origins:  # the web app is same-origin; other origins only when listed
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["*"])

    install_auth(app, service)  # S41: router, Redis and session store, shred hooks

    @app.get("/health")
    def health(deep: bool = False, ready: bool = False):  # noqa: ANN202
        """Liveness (process up). ?ready=true adds Postgres and Redis; ?deep=true, each model
        service the profile uses as up or down."""
        if ready:
            r = readiness(app)
            return JSONResponse({"status": "ok" if r["ready"] else "degraded", **r},
                                status_code=200 if r["ready"] else 503)
        if not deep:
            return {"status": "ok"}
        checks = {name: up(url) for name, url in dependencies().items()}
        return {"status": "ok" if all(checks.values()) else "degraded", "services": checks}

    ID_HINT = ("An OpenAlex author ID is an A followed by at least eight digits. Check it, or "
               "search by name or ORCID iD.")

    @app.get("/authors/resolve")
    def resolve(q: str) -> dict:
        if not q.strip():  # F25: an empty search found three real authors
            raise HTTPException(422, EMPTY_FIND)
        if (oid := oa.parse_orcid(q)) and not oa.orcid_ok(oid):  # Q18
            raise HTTPException(422, "That is not a valid ORCID iD: its last character does "
                                "not match the rest. Check it on orcid.org.")
        if oa.looks_like_author_id(q) and not oa.author_id_ok(q):  # R5: before any lookup
            raise HTTPException(422, ID_HINT)
        try:
            with service.clients.openalex() as c:
                if oa.parse_orcid(q):
                    found = [c.resolve_by_orcid(q)]
                elif oa.parse_author_id(q) and " " not in q.strip():
                    found = [c.get_author(q)]
                else:
                    found = c.resolve_by_name(q)
        except httpx.HTTPStatusError as e:  # an id OpenAlex does not know (R5)
            if 400 <= e.response.status_code < 500:
                raise HTTPException(404, "No OpenAlex author has that ID. Check it, or search "
                                    "by name or ORCID iD.") from e
            raise
        # Not cached: a search is not a brief, and the pick screen needs only this answer.
        # The brief's researcher stage fetches the one person picked (review S13).
        return {"candidates": [record_json(x) for x in found]}

    limiter = RateLimiter(int(env("PERCH_BRIEFS_PER_HOUR") or 10))

    @app.post("/briefs", status_code=202, dependencies=STORED)
    def create_brief(req: BriefRequest, request: Request,
                     sess: object | None = Depends(account_session)) -> dict:
        student = sess is not None and sess.audience == "student"
        if not student and not oa.parse_author_id(req.author_id or ""):
            raise HTTPException(422, f"not an OpenAlex author id: {req.author_id!r}")
        if sess is not None:  # v1: the brief lives in user_data (or Redis for a guest)
            from perch.redisx import QuotaExceeded
            from perch.user.briefs import submit_brief
            from perch.user.quota import RateLimited

            sv = request.app.state.user_services
            if req.doc_ids:
                if sess.user_id is None:
                    raise HTTPException(403, {"error": "account_required"})
                from perch.auth.deps import require_consent
                from perch.user.docs import owns_all

                require_consent(sess)  # before any row is looked at
                if not owns_all(sv.ud, sess.user_id, req.doc_ids):
                    raise HTTPException(422, "Some documents are not yours or no longer exist.")
            try:
                bid, job = submit_brief(service, sv.runner, sv.ud, sv.redis, sess, req.author_id,
                                        doc_ids=req.doc_ids,
                                        as_of=req.as_of, top=req.top, explain=req.explain,
                                        min_amount=req.min_amount, agencies=req.agencies,
                                        context=req.context())
            except RateLimited as e:
                raise HTTPException(429, {"error": "rate_limited"},
                                    headers={"Retry-After": str(e.retry_after)}) from None
            except QuotaExceeded:
                raise HTTPException(429, {"error": "quota_exceeded"}) from None
            return {"id": bid, "job_id": str(job), "status": "queued", "poll": f"/briefs/{bid}"}
        wait = limiter.take(client_key(request))
        if wait:
            raise HTTPException(429, f"Limit of {limiter.per_hour} new briefs an hour reached. "
                                f"Try again in {wait // 60 + 1} minutes.",
                                headers={"Retry-After": str(wait)})
        b = service.create(req.author_id, as_of=req.as_of, top=req.top, explain=req.explain,
                           min_amount=req.min_amount, agencies=req.agencies,
                           context=req.context())
        runner.submit(b.id, lambda: service.run(b.id))
        return {"id": b.id, "status": b.status, "poll": f"/briefs/{b.id}"}

    def load(brief_id: str, svc: BriefService = service) -> tuple[Brief, list[Lead]]:
        got = svc.get(brief_id)
        if not got:
            raise HTTPException(404, f"no brief {brief_id!r}")
        return got

    @contextmanager
    def scope(request: Request, sess: object | None, brief_id: str) -> Iterator[None]:
        """With accounts, the brief lives in its owner's store (encrypted rows, or Redis for a
        guest): set it for the call, so every service call reads and writes that brief.
        Another user's brief is a 404. Without accounts nothing changes."""
        if sess is None:
            yield
            return
        from perch.user.briefs import open_store, using_store

        sv = request.app.state.user_services
        store = open_store(sv.ud, sv.redis, sess, brief_id)
        if store is None:
            raise HTTPException(404, {"error": "not_found"})
        with using_store(store):
            yield

    def signed_in(sess: object | None) -> None:
        """Hand-offs and Scout need an account (guests store nothing; ARCHITECTURE_V1 7.4)."""
        if sess is not None and sess.user_id is None:
            raise HTTPException(403, {"error": "account_required"})
        if sess is not None:
            from perch.auth.deps import require_consent

            require_consent(sess)

    @app.get("/briefs/{brief_id}", dependencies=STORED)
    def get_brief(brief_id: str, request: Request,
                  sess: object | None = Depends(account_session)) -> Response:
        """The brief, with an ETag: a poll that sends the last ETag gets 304 and no body
        while nothing changed (review P3)."""
        with scope(request, sess, brief_id):
            out = brief_view(brief_id)
        body = json.dumps(jsonable_encoder(out), separators=(",", ":")).encode()
        tag = '"' + hashlib.sha256(body).hexdigest()[:20] + '"'
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers={"ETag": tag})
        return Response(body, media_type="application/json", headers={"ETag": tag})

    def brief_view(brief_id: str, svc: BriefService = service) -> dict:
        b, leads = load(brief_id, svc)
        with svc.repo() as r:
            res = r.get(Researcher, b.researcher_id)
            out = [lead_json(x, r) for x in leads]
            ov = aw.load_overrides(res.id, svc.overrides) if res else None
            linked = aw.link_stored(res, r.list(Award), ov) if res and ov else []
            pids = {i for t in b.threads for i in t.get("work_ids", [])[:KEY_PAPERS]}
            pids |= {f"https://openalex.org/{c}" for x in leads for c in x.cited_ids
                     if c.startswith("W")}
            # T28: every paper the summary cites, as the export names them, so the Profile
            # shows the same citations
            pids |= {f"https://openalex.org/{c}" for c in re.findall(r"\bW\d{5,}\b",
                                                                      b.summary or "")}
            papers = {w.id: paper_json(w) for w in (r.get(Work, i) for i in sorted(pids)) if w}
        awards = [{"key": s.key, "award_number": s.award_number, "agency": s.agency,
                   "title": s.title, "start_date": s.start_date, "end_date": s.end_date,
                   "source_url": s.end_record.source_url if s.end_record else None,
                   "record_id": (s.end_record or s.records[0]).id,
                   "matched_by_initial": s.matched_by_initial}
                  for s in aw.summarise(linked, res, ov) if s.key in set(b.award_ids)]
        view = {"brief": b.model_dump(mode="json"),
                "researcher": record_json(res) if res else None, "awards": awards,
                "papers": papers,
                "leads": out, "notice": grants_gov.ATTRIBUTION}
        view["papers"].update(user_records(b))
        if b.options.get("student"):  # what the CV parse read, for the Profile screen
            from perch.student import parse_student_cv
            from perch.user.briefs import current_store

            store = current_store.get()
            if store is not None:
                try:
                    view["student"] = parse_student_cv(store.student_inputs().cv).summary()
                except (LookupError, ValueError):
                    pass
        return view

    def set_status(brief_id: str, lead_id: str, status: str) -> dict:
        lead = service.set_lead_status(brief_id, lead_id, status)
        if not lead:
            raise HTTPException(404, f"no lead {lead_id!r} in brief {brief_id!r}")
        return lead.model_dump(mode="json")

    @app.post("/briefs/{brief_id}/leads/{lead_id}/{action}", dependencies=STORED)
    def lead_action(brief_id: str, lead_id: str, action: Literal["keep", "dismiss", "restore"],
                    request: Request, sess: object | None = Depends(account_session)) -> dict:
        status = {"keep": "kept", "dismiss": "dismissed", "restore": "new"}[action]
        with scope(request, sess, brief_id):
            return set_status(brief_id, lead_id, status)

    @app.get("/briefs/{brief_id}/export.json", dependencies=STORED)
    def export(brief_id: str, request: Request, status: str | None = None,
               sess: object | None = Depends(account_session)) -> dict:
        with scope(request, sess, brief_id):
            return export_json(brief_id, status)

    def export_json(brief_id: str, status: str | None = None, svc: BriefService = service
                    ) -> dict:
        """The whole brief: the user's own, so nothing is withheld. A sample persona's
        records stay in a list of their own (rule 11)."""
        b, leads = load(brief_id, svc)
        if status:  # e.g. ?status=kept: the Keep bar's download
            leads = [x for x in leads if x.status == status]
        ids = {b.researcher_id, *(x.record_id for x in leads)}
        ids |= {f"https://openalex.org/{c}" for x in leads for c in x.cited_ids
                if c.startswith("W")}
        ids |= {f"grants_gov:{c}" for x in leads if x.route == "A" for c in x.cited_ids
                if not c.startswith("W")}
        ids |= {i for x in leads for sig in x.signals for i in sig.record_ids}
        with svc.repo() as r:
            records = [record_json(y) for y in (r.get_any(i) for i in sorted(ids)) if y]
        out_leads = [x.model_dump(mode="json") for x in leads]
        out = {"brief": b.model_dump(mode="json"), "leads": out_leads, "records": records,
               "notice": grants_gov.ATTRIBUTION}
        if any(x.sample for x in leads):
            out["sample_notice"] = ex.SAMPLE_BANNER
            # G23, rule 11: SYNTHETIC samples never share a list with public records
            out["samples"] = {
                "leads": [y for x, y in zip(leads, out_leads, strict=True) if x.sample],
                "records": [r for r in records if r.get("source") == "synthetic"]}
            out["leads"] = [y for x, y in zip(leads, out_leads, strict=True) if not x.sample]
            out["records"] = [r for r in records if r.get("source") != "synthetic"]
        return out

    def export_blocks(brief_id: str, status: str | None, svc: BriefService = service
                      ) -> tuple[list, str]:
        b, leads = load(brief_id, svc)
        if status:
            leads = [x for x in leads if x.status == status]
        if b.options.get("student"):
            with svc.repo() as r:
                recs = {x.record_id: r.get(Scholarship, x.record_id)
                        or r.get(Opportunity, x.record_id) for x in leads}
            return ex.brief_blocks(b, leads, records=recs), "Perch student brief"
        with svc.repo() as r:
            res = r.get(Researcher, b.researcher_id)
            opps = {x.record_id: o for x in leads if x.route == "A"
                    and (o := r.get(Opportunity, x.record_id))}
            orgs = {x.record_id: o for x in leads if x.route == "B"
                    and (o := r.get(Organisation, x.record_id))}
            wids = {f"https://openalex.org/{c}" for x in leads for c in x.cited_ids
                    if c.startswith("W")}
            # the summary cites papers too, named by title in the export (R9)
            wids |= {f"https://openalex.org/{c}" for c in re.findall(r"\bW\d{5,}\b",
                                                                      b.summary or "")}
            works = {w.id: w for w in (r.get(Work, i) for i in sorted(wids)) if w}
            rows = cmp.compare(b, leads, r, "kept")
        docs = bool(b.options.get("user_data"))  # the brief read the user's own documents
        name = res.display_name if res else b.researcher_id
        return (ex.brief_blocks(b, leads, researcher=res, opps=opps, orgs=orgs, works=works,
                                compare_rows=rows, documents=docs),
                f"Perch brief: {name}")

    @app.get("/briefs/{brief_id}/export.md", dependencies=STORED)
    def export_md(brief_id: str, request: Request, status: Literal["kept"] | None = None,
                  sess: object | None = Depends(account_session)) -> Response:
        with scope(request, sess, brief_id):
            bs, _ = export_blocks(brief_id, status)
        return Response(ex.to_markdown(bs), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="perch-brief-{brief_id}.md"'})

    @app.get("/briefs/{brief_id}/export.html", dependencies=STORED)
    def export_html(brief_id: str, request: Request, status: Literal["kept"] | None = None,
                    sess: object | None = Depends(account_session)) -> Response:
        with scope(request, sess, brief_id):
            bs, title = export_blocks(brief_id, status)
        return Response(ex.to_html(bs, title), media_type="text/html; charset=utf-8")

    @app.get("/briefs/{brief_id}/compare", dependencies=STORED)
    def compare_view(brief_id: str, request: Request,
                     status: Literal["kept", "all"] = "kept",
                     sess: object | None = Depends(account_session)) -> dict:
        with scope(request, sess, brief_id):
            b, leads = load(brief_id)
            with service.repo() as r:
                rows = cmp.compare(b, leads, r, None if status == "all" else status)
        return cmp.rows_json(rows)

    handoff_limiter = RateLimiter(int(env("PERCH_HANDOFF_PER_HOUR") or 30))

    @app.post("/briefs/{brief_id}/handoff", dependencies=STORED)
    def handoff(brief_id: str, req: HandoffRequest, request: Request,
                sess: object | None = Depends(account_session)) -> dict:
        signed_in(sess)
        with scope(request, sess, brief_id):
            b, _ = load(brief_id)
            if b.options.get("student"):  # student notes come from /student/note
                raise HTTPException(422, "A student brief drafts its note to the office from "
                                    "the Compare tab.")
            wait = handoff_limiter.take(client_key(request))
            if wait:
                raise HTTPException(429, f"Too many drafts this hour. Try again in "
                                    f"{wait // 60 + 1} minutes.",
                                    headers={"Retry-After": str(wait)})
            try:
                d = service.handoff(brief_id, req.office, req.lead_ids or None)
            except LookupError as e:  # F26: nothing kept for that office
                raise HTTPException(422, str(e)) from e
        if d is None:
            raise HTTPException(404, f"no brief {brief_id!r}")
        return draft_json(d)

    @app.get("/briefs/{brief_id}/student/note", dependencies=STORED)
    def student_note(brief_id: str, route: Literal["F", "S"], request: Request,
                     sess: object | None = Depends(account_session)) -> dict:
        """The Compare tab's note for one route, written by code (review W9): the same
        function as Scout's draft_note, so there is one source."""
        from perch.scout.student_tools import facts_of, record_of, write_note

        with scope(request, sess, brief_id):
            b, leads = load(brief_id)
            if not b.options.get("student"):
                raise HTTPException(422, "Only a student brief has a note.")
            kept = [x for x in leads if x.status == "kept" and x.route == route]
            if not kept:
                raise HTTPException(404, "Nothing kept for that office.")
            return write_note(route, [(x, facts_of(record_of(service, x))) for x in kept])

    @app.get("/records/{record_id:path}")
    def get_record(record_id: str, request: Request,
                   sess: object | None = Depends(optional_session)) -> dict:
        if record_id.startswith("user:"):  # the signed-in user's own document or entry
            doc = user_record(request, sess, record_id)
            if doc is None:
                raise HTTPException(404, f"no record {record_id!r}")
            return doc
        with service.repo() as r:
            x = r.get_any(record_id)
            if x is None and re.fullmatch(r"[AWI]\d+", record_id):  # short OpenAlex id
                x = r.get_any(f"https://openalex.org/{record_id}")
            if x is None:  # an opportunity number, as cited in explanations
                x = r.get_any(f"grants_gov:{record_id}")
        if x is None or (not stored_briefs and x.kind in USER_KINDS):
            raise HTTPException(404, f"no record {record_id!r}")
        return record_json(x)

    # --- Scout (S10) ---
    hub = ScoutHub(service, scout_runner or runner, scout_log)
    scout_limiter = RateLimiter(int(env("PERCH_SCOUT_PER_HOUR") or 30))

    def ask_allowed(request: Request) -> None:
        wait = scout_limiter.take(client_key(request))
        if wait:
            raise HTTPException(429, f"Limit of {scout_limiter.per_hour} Scout questions an "
                                f"hour reached. Try again in {wait // 60 + 1} minutes.",
                                headers={"Retry-After": str(wait)})

    def owner_of(sess: object | None) -> str | None:
        return None if sess is None else str(sess.user_id)

    @app.post("/briefs/{brief_id}/scout", status_code=202, dependencies=STORED)
    def scout_start(brief_id: str, req: ScoutRequest, request: Request,
                    sess: object | None = Depends(account_session)) -> dict:
        signed_in(sess)
        with scope(request, sess, brief_id):
            b, _ = load(brief_id)
            if b.status != "done":
                raise HTTPException(409, "Scout can start once the brief has finished.")
            if not req.question.strip():
                raise HTTPException(422, "Ask Scout a question.")
            ask_allowed(request)
            return scout_view(hub.start(brief_id, b.researcher_id, req.question.strip(),
                                        owner=owner_of(sess)))

    def entry(sid: str, sess: object | None):  # noqa: ANN202 - an Entry
        e = hub.get(sid)
        if e is None or e.owner != owner_of(sess):  # another user's session is a 404
            raise HTTPException(404, "No such Scout session. Sessions end when the server "
                                "restarts.")
        return e

    @app.get("/scout/{sid}", dependencies=STORED)
    def scout_get(sid: str, sess: object | None = Depends(account_session)) -> dict:
        return scout_view(entry(sid, sess))

    @app.post("/scout/{sid}/{action}", status_code=202, dependencies=STORED)
    def scout_act(sid: str, action: Literal["ask", "stop"],
                  req: ScoutRequest, request: Request,
                  sess: object | None = Depends(account_session)) -> dict:
        e = entry(sid, sess)
        if action == "ask":
            if not req.question.strip():
                raise HTTPException(422, "Ask Scout a question.")
            ask_allowed(request)
        try:
            with scope(request, sess, e.brief_id):
                hub.act(e, action, req.question.strip())
        except Busy as err:
            raise HTTPException(409, str(err)) from err
        return scout_view(e)

    from perch.scholarships import ensure_samples

    try:  # the SYNTHETIC sample store a student brief reads (rule 11)
        ensure_samples()
    except OSError:
        logging.getLogger("perch").warning("the sample store could not be prepared")

    from perch.user.routes import router as user_router

    app.include_router(user_router)  # /me/docs, /me/delete, /me/briefs, /usage (S41 part B)

    if web_dir and (web_dir / "index.html").is_file():  # after every API route
        app.mount("/", WebFiles(directory=web_dir, html=True), name="web")
    return app

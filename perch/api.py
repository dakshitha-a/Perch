"""HTTP API (SPEC section 6). Run with `perch serve`.

  GET  /health[?deep=true]                     liveness; deep: each model service up or down
  GET  /authors/resolve?q=<name|orcid|id>      candidates for the Find screen
Since S23 the web app runs every brief in a session (/private/*, perch/private/routes.py),
and nothing about a visitor is stored. The stored-brief routes below exist only when
PERCH_STORED_BRIEFS=1 (development, the bench, replays); otherwise they answer 404.

  POST /briefs                                  {"author_id", "as_of"?, "top"?, "explain"?, ...}
                                                a job (202), limited to 10 new briefs an hour
                                                per visitor
  GET  /briefs/{id}                             status, stages, profile, leads with records
  POST /briefs/{id}/leads/{lead_id}/keep        and /dismiss, /restore
  GET  /briefs/{id}/export.json[?status=kept]   brief, leads and every record they cite
  GET  /briefs/{id}/export.md, /export.html    the brief as Markdown, or a page to print or save
                                                as PDF; ?status=kept for the kept leads only
  GET  /briefs/{id}/compare[?status=kept|all]   kept leads side by side, each cell with its record
  POST /briefs/{id}/handoff                     {"office", "lead_ids"?}: a hand-off draft to one
                                                Temple office about the kept leads (skill 3);
                                                returned, never stored or sent
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

import ipaddress
import logging
import re
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from perch import awards as aw
from perch import compare as cmp
from perch import egress
from perch import export as ex
from perch.config import env
from perch.jobs import JobRunner
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


def draft_json(d: Draft) -> dict:
    return {"office": {"key": d.office.key, "name": d.office.name, "url": d.office.url},
            "to": "", "subject": d.subject, "body": d.body, "lead_ids": d.lead_ids,
            "cited_ids": d.cited_ids, "flagged": d.flagged, "model": d.model,
            "withheld": d.withheld}


class BriefRequest(BriefOptions):
    author_id: str = Field(description="OpenAlex author id, e.g. A5023080104")
    agencies: list[str] = Field(default_factory=list)


class WebFiles(StaticFiles):
    """The web app's files, revalidated on every load (S27). Without a Cache-Control
    header, browsers kept old scripts after a release, so visitors saw the previous app."""

    async def get_response(self, path: str, scope: dict) -> Response:
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def record_json(r: Record) -> dict:
    return {"kind": r.kind, **r.model_dump(mode="json")}


def lead_json(lead: Lead, opp: Opportunity | None) -> dict:
    return {**lead.model_dump(mode="json"),
            "opportunity": opp.model_dump(mode="json", exclude={"description"}) if opp else None}


def student_json(lead: Lead, r: Repository) -> dict:
    """A student-mode lead (route F or S) with its record: a Scholarship, or the NIH
    Opportunity behind a fellowship. Every value is copied from the record."""
    from perch.schemas import Scholarship

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


def route_b_json(lead: Lead, r: Repository) -> dict:
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
        # A session's answers are never kept by the browser's HTTP cache (review P3).
        private = scope.get("path", "").startswith("/private")

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


def create_app(service: BriefService, runner: JobRunner,
               resolver: type[oa.OpenAlexClient] | None = None,
               web_dir: Path | None = WEB_DIR, scout_runner: JobRunner | None = None,
               scout_log: ScoutLog | None = None, stored_briefs: bool | None = None) -> FastAPI:
    if stored_briefs is None:
        stored_briefs = env("PERCH_STORED_BRIEFS") == "1"

    def stored_only() -> None:
        if not stored_briefs:
            raise HTTPException(404, "Briefs are not stored on this server; use a session.")

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

    @app.get("/health")
    def health(deep: bool = False) -> dict:
        """Liveness; with ?deep=true, each model service the profile uses as up or down."""
        if not deep:
            return {"status": "ok"}
        checks = {name: up(url) for name, url in dependencies().items()}
        return {"status": "ok" if all(checks.values()) else "degraded", "services": checks}

    ID_HINT = ("An OpenAlex author ID is an A followed by at least eight digits. Check it, or "
               "search by name or ORCID iD.")

    @app.get("/authors/resolve")
    def resolve(q: str) -> dict:
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
    def create_brief(req: BriefRequest, request: Request) -> dict:
        if not oa.parse_author_id(req.author_id):
            raise HTTPException(422, f"not an OpenAlex author id: {req.author_id!r}")
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

    @app.get("/briefs/{brief_id}", dependencies=STORED)
    def get_brief(brief_id: str) -> dict:
        return brief_view(brief_id)

    def brief_view(brief_id: str, svc: BriefService = service) -> dict:
        b, leads = load(brief_id, svc)
        with svc.repo() as r:
            res = r.get(Researcher, b.researcher_id)
            opps = {x.record_id: r.get(Opportunity, x.record_id) for x in leads
                    if x.route == "A"}
            out = [lead_json(x, opps.get(x.record_id)) if x.route == "A"
                   else route_b_json(x, r) if x.route == "B" else student_json(x, r)
                   for x in leads]
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
        return {"brief": b.model_dump(mode="json"),
                "researcher": record_json(res) if res else None, "awards": awards,
                "papers": papers,
                "leads": out, "notice": grants_gov.ATTRIBUTION}

    def set_status(brief_id: str, lead_id: str, status: str) -> dict:
        lead = service.set_lead_status(brief_id, lead_id, status)
        if not lead:
            raise HTTPException(404, f"no lead {lead_id!r} in brief {brief_id!r}")
        return lead.model_dump(mode="json")

    @app.post("/briefs/{brief_id}/leads/{lead_id}/keep", dependencies=STORED)
    def keep(brief_id: str, lead_id: str) -> dict:
        return set_status(brief_id, lead_id, "kept")

    @app.post("/briefs/{brief_id}/leads/{lead_id}/dismiss", dependencies=STORED)
    def dismiss(brief_id: str, lead_id: str) -> dict:
        return set_status(brief_id, lead_id, "dismissed")

    @app.post("/briefs/{brief_id}/leads/{lead_id}/restore", dependencies=STORED)
    def restore(brief_id: str, lead_id: str) -> dict:
        return set_status(brief_id, lead_id, "new")

    @app.get("/briefs/{brief_id}/export.json", dependencies=STORED)
    def export(brief_id: str, status: str | None = None) -> dict:
        return export_json(brief_id, status)

    def export_json(brief_id: str, status: str | None = None, svc: BriefService = service,
                    masker: egress.Masker | None = None, documents: bool = False) -> dict:
        """`documents`: a session holding documents; every model text counts as private."""
        b, leads = load(brief_id, svc)
        documents = documents or bool(b.options.get("documents"))
        if status:  # e.g. ?status=kept: the Keep bar's download
            leads = [x for x in leads if x.status == status]
        ids = {b.researcher_id, *(x.record_id for x in leads)}
        ids |= {f"https://openalex.org/{c}" for x in leads for c in x.cited_ids
                if c.startswith("W")}
        ids |= {f"grants_gov:{c}" for x in leads if x.route == "A" for c in x.cited_ids
                if not c.startswith("W")}
        ids |= {i for x in leads for sig in x.signals for i in sig.record_ids}
        with svc.repo() as r:
            records = [record_json(x) for x in
                       egress.public_only(y for y in (r.get_any(i) for i in sorted(ids)) if y)]
        out_leads = [{**x.model_dump(mode="json"),
                      "explanation": egress.release_model(x.explanation, x.cited_ids, masker,
                                                          documents),
                      "inference": egress.release_model(x.inference, x.cited_ids, masker,
                                                        documents),
                      # Layer 2 flags quote the model's own sentences, so they leave alike.
                      "unsupported": [egress.release_model(u, x.cited_ids, masker, documents)
                                      for u in x.unsupported],
                      "notes": [egress.release(n, ["private:cv"], masker) if "(private)" in n
                                else n for n in x.notes],
                      # Student mode: the rule lines and gaps are written by code, so they
                      # stay; only model text is withheld (Q12). A CV value in a line is
                      # dropped, or masked on opt-in (Q42).
                      "verdict_lines": [egress.release_cv_line(v, masker)
                                        for v in x.verdict_lines],
                      "gaps": [egress.release_cv_line(g, masker) for g in x.gaps],
                      } for x in leads]
        brief = b.model_dump(mode="json")
        brief.update(summary=egress.release_model(b.summary, [], masker, documents),
                     topics=[t for t in (egress.release_model(x, [], masker, documents)
                                         for x in b.topics) if t != egress.WITHHELD],
                     threads=[egress.release_thread(t, masker) for t in b.threads])
        out = {"brief": brief, "leads": out_leads, "records": records,
               "notice": grants_gov.ATTRIBUTION}
        if documents and masker is None and (n := ex._withheld(b, leads)):
            out["withheld"] = {"texts": n, "note": egress.withheld_note(n)}
        if any(x.sample for x in leads):
            out["sample_notice"] = ex.SAMPLE_BANNER
        return out

    def export_blocks(brief_id: str, status: str | None, svc: BriefService = service,
                      masker: egress.Masker | None = None,
                      documents: bool = False) -> tuple[list, str]:
        b, leads = load(brief_id, svc)
        documents = documents or bool(b.options.get("documents"))
        if status:
            leads = [x for x in leads if x.status == status]
        if b.options.get("student"):
            from perch.schemas import Scholarship

            with svc.repo() as r:
                recs = {x.record_id: r.get(Scholarship, x.record_id)
                        or r.get(Opportunity, x.record_id) for x in leads}
            return (ex.student_blocks(b, leads, recs, masker=masker, documents=documents),
                    "Perch student brief (private)")
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
        name = res.display_name if res else b.researcher_id
        return (ex.blocks(b, res, leads, opps, orgs, works, rows, masker=masker,
                          documents=documents),
                f"Perch brief: {name}")

    @app.get("/briefs/{brief_id}/export.md", dependencies=STORED)
    def export_md(brief_id: str, status: Literal["kept"] | None = None) -> Response:
        bs, _ = export_blocks(brief_id, status)
        return Response(ex.to_markdown(bs), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="perch-brief-{brief_id}.md"'})

    @app.get("/briefs/{brief_id}/export.html", dependencies=STORED)
    def export_html(brief_id: str, status: Literal["kept"] | None = None) -> Response:
        bs, title = export_blocks(brief_id, status)
        return Response(ex.to_html(bs, title), media_type="text/html; charset=utf-8")

    @app.get("/briefs/{brief_id}/compare", dependencies=STORED)
    def compare_view(brief_id: str, status: Literal["kept", "all"] = "kept") -> dict:
        b, leads = load(brief_id)
        with service.repo() as r:
            rows = cmp.compare(b, leads, r, None if status == "all" else status)
        return cmp.rows_json(rows)

    handoff_limiter = RateLimiter(int(env("PERCH_HANDOFF_PER_HOUR") or 30))

    @app.post("/briefs/{brief_id}/handoff", dependencies=STORED)
    def handoff(brief_id: str, req: HandoffRequest, request: Request) -> dict:
        load(brief_id)
        wait = handoff_limiter.take(client_key(request))
        if wait:
            raise HTTPException(429, f"Too many drafts this hour. Try again in {wait // 60 + 1} "
                                "minutes.", headers={"Retry-After": str(wait)})
        d = service.handoff(brief_id, req.office, req.lead_ids or None)
        if d is None:
            raise HTTPException(404, f"no brief {brief_id!r}")
        return draft_json(d)

    @app.get("/records/{record_id:path}")
    def get_record(record_id: str) -> dict:
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

    @app.post("/briefs/{brief_id}/scout", status_code=202, dependencies=STORED)
    def scout_start(brief_id: str, req: ScoutRequest, request: Request) -> dict:
        b, _ = load(brief_id)
        if b.status != "done":
            raise HTTPException(409, "Scout can start once the brief has finished.")
        if not req.question.strip():
            raise HTTPException(422, "Ask Scout a question.")
        ask_allowed(request)
        return scout_view(hub.start(brief_id, b.researcher_id, req.question.strip()))

    def entry(sid: str):  # noqa: ANN202 - an Entry
        e = hub.get(sid)
        if e is None:
            raise HTTPException(404, "No such Scout session. Sessions end when the server "
                                "restarts.")
        return e

    @app.get("/scout/{sid}", dependencies=STORED)
    def scout_get(sid: str) -> dict:
        return scout_view(entry(sid))

    @app.post("/scout/{sid}/{action}", status_code=202, dependencies=STORED)
    def scout_act(sid: str, action: Literal["ask", "stop"],
                  req: ScoutRequest, request: Request) -> dict:
        e = entry(sid)
        if action == "ask":
            if not req.question.strip():
                raise HTTPException(422, "Ask Scout a question.")
            ask_allowed(request)
        try:
            hub.act(e, action, req.question.strip())
        except Busy as err:
            raise HTTPException(409, str(err)) from err
        return scout_view(e)

    from perch.private.routes import add_private_routes

    add_private_routes(app, service, runner, scout_runner or runner, brief_view=brief_view,
                       export_json=export_json, export_blocks=export_blocks, load=load,
                       limiter=RateLimiter, client_key=client_key)

    if web_dir and (web_dir / "index.html").is_file():  # after every API route
        app.mount("/", WebFiles(directory=web_dir, html=True), name="web")
    return app

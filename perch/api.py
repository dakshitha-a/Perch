"""HTTP API (SPEC section 6). Run with `perch serve`.

  GET  /health[?deep=true]                     liveness; deep: each model service up or down
  GET  /authors/resolve?q=<name|orcid|id>      candidates for the Find screen
  POST /briefs                                  {"author_id", "as_of"?, "top"?, "explain"?, ...}
                                                a finished brief with the same options from the
                                                last 24 h is reused (200); else a job (202),
                                                limited to 10 new briefs an hour per visitor
  GET  /briefs/{id}                             status, stages, profile, leads with records
  POST /briefs/{id}/leads/{lead_id}/keep        and /dismiss, /restore
  GET  /briefs/{id}/export.json[?status=kept]   brief, leads and every record they cite
  GET  /records/{id}                            any stored record, with provenance
  POST /briefs/{id}/scout                       {"question", "mode": "ask"|"run"}: a Scout
                                                session about the brief (S10)
  GET  /scout/{session}                         its questions, tool cards and answers
  POST /scout/{session}/{action}                approve or skip {"card_id"?}, ask
                                                {"question"}, or mode (toggle)

  GET  /                                       the web app (web/), when present

Briefs run as background jobs; poll GET /briefs/{id}. Nothing is sent anywhere.
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from perch import awards as aw
from perch.config import env
from perch.jobs import JobRunner
from perch.schemas import Award, Brief, Lead, Opportunity, Record, Researcher, Work
from perch.scout.hub import Busy, ScoutHub
from perch.scout.hub import view as scout_view
from perch.scout.log import ScoutLog
from perch.service import BriefService, brief_options
from perch.sources import grants_gov
from perch.sources import openalex as oa

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
KEY_PAPERS = 5  # per thread, most recent-weighted first (thread order from perch.profile)


class ScoutRequest(BaseModel):
    question: str = Field("", max_length=1000)
    mode: Literal["ask", "run"] = "ask"
    card_id: str | None = None


class BriefRequest(BaseModel):
    author_id: str = Field(description="OpenAlex author id, e.g. A5023080104")
    as_of: date | None = None
    top: int = Field(10, ge=1, le=25)
    explain: bool = True
    min_amount: float | None = None
    agencies: list[str] = Field(default_factory=list)


def record_json(r: Record) -> dict:
    return {"kind": r.kind, **r.model_dump(mode="json")}


def lead_json(lead: Lead, opp: Opportunity | None) -> dict:
    return {**lead.model_dump(mode="json"),
            "opportunity": opp.model_dump(mode="json", exclude={"description"}) if opp else None}


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


def client_key(request: Request) -> str:
    """The visitor's address. Behind the tunnel every request comes from 127.0.0.1, so a
    local request is keyed on the first X-Forwarded-For address the proxy adds."""
    host = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for", "")
    if host in ("127.0.0.1", "::1") and fwd:
        return fwd.split(",")[0].strip()
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
               scout_log: ScoutLog | None = None) -> FastAPI:
    app = FastAPI(title="Perch API", description="See every route to fund your work. "
                  + grants_gov.ATTRIBUTION, version="0.1.0")
    @app.exception_handler(RequestValidationError)
    def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default answer echoes the submitted input; this one names fields only,
        # so no request body ever comes back in a response or a proxy log.
        errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "invalid")}
                  for e in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(Exception)
    def crashed(request: Request, exc: Exception) -> JSONResponse:
        # Exception type only: messages can quote request text.
        return JSONResponse({"detail": f"internal error ({type(exc).__name__})"},
                            status_code=500)

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

    @app.get("/authors/resolve")
    def resolve(q: str) -> dict:
        with service.clients.openalex() as c:
            if oa.parse_orcid(q):
                found = [c.resolve_by_orcid(q)]
            elif oa.parse_author_id(q) and " " not in q.strip():
                found = [c.get_author(q)]
            else:
                found = c.resolve_by_name(q)
        with service.repo() as r:
            r.upsert(found)
        return {"candidates": [record_json(x) for x in found]}

    limiter = RateLimiter(int(env("PERCH_BRIEFS_PER_HOUR") or 10))
    reuse_hours = float(env("PERCH_BRIEF_REUSE_HOURS") or 24)

    @app.post("/briefs", status_code=202)
    def create_brief(req: BriefRequest, request: Request, response: Response) -> dict:
        if not oa.parse_author_id(req.author_id):
            raise HTTPException(422, f"not an OpenAlex author id: {req.author_id!r}")
        options = brief_options(req.as_of, req.top, req.explain, req.min_amount, req.agencies)
        if reuse_hours > 0 and (b := service.reuse(req.author_id, options, reuse_hours)):
            response.status_code = 200  # a finished brief: no job, not counted in the limit
            return {"id": b.id, "status": b.status, "poll": f"/briefs/{b.id}", "reused": True}
        wait = limiter.take(client_key(request))
        if wait:
            raise HTTPException(429, f"Limit of {limiter.per_hour} new briefs an hour reached. "
                                f"Try again in {wait // 60 + 1} minutes.",
                                headers={"Retry-After": str(wait)})
        b = service.create(req.author_id, as_of=req.as_of, top=req.top, explain=req.explain,
                           min_amount=req.min_amount, agencies=req.agencies)
        runner.submit(b.id, lambda: service.run(b.id))
        return {"id": b.id, "status": b.status, "poll": f"/briefs/{b.id}"}

    def load(brief_id: str) -> tuple[Brief, list[Lead]]:
        got = service.get(brief_id)
        if not got:
            raise HTTPException(404, f"no brief {brief_id!r}")
        return got

    @app.get("/briefs/{brief_id}")
    def get_brief(brief_id: str) -> dict:
        b, leads = load(brief_id)
        with service.repo() as r:
            res = r.get(Researcher, b.researcher_id)
            opps = {x.record_id: r.get(Opportunity, x.record_id) for x in leads}
            ov = aw.load_overrides(res.id, service.overrides) if res else None
            linked = aw.link_awards(res, r.list(Award), ov) if res and ov else []
            pids = {i for t in b.threads for i in t.get("work_ids", [])[:KEY_PAPERS]}
            pids |= {f"https://openalex.org/{c}" for x in leads for c in x.cited_ids
                     if c.startswith("W")}
            papers = {w.id: paper_json(w) for w in (r.get(Work, i) for i in sorted(pids)) if w}
        awards = [{"key": s.key, "award_number": s.award_number, "agency": s.agency,
                   "title": s.title, "start_date": s.start_date, "end_date": s.end_date,
                   "source_url": s.end_record.source_url if s.end_record else None,
                   "record_id": (s.end_record or s.records[0]).id}
                  for s in aw.summarise(linked) if s.key in set(b.award_ids)]
        return {"brief": b.model_dump(mode="json"),
                "researcher": record_json(res) if res else None, "awards": awards,
                "papers": papers,
                "leads": [lead_json(x, opps.get(x.record_id)) for x in leads],
                "notice": grants_gov.ATTRIBUTION}

    def set_status(brief_id: str, lead_id: str, status: str) -> dict:
        lead = service.set_lead_status(brief_id, lead_id, status)
        if not lead:
            raise HTTPException(404, f"no lead {lead_id!r} in brief {brief_id!r}")
        return lead.model_dump(mode="json")

    @app.post("/briefs/{brief_id}/leads/{lead_id}/keep")
    def keep(brief_id: str, lead_id: str) -> dict:
        return set_status(brief_id, lead_id, "kept")

    @app.post("/briefs/{brief_id}/leads/{lead_id}/dismiss")
    def dismiss(brief_id: str, lead_id: str) -> dict:
        return set_status(brief_id, lead_id, "dismissed")

    @app.post("/briefs/{brief_id}/leads/{lead_id}/restore")
    def restore(brief_id: str, lead_id: str) -> dict:
        return set_status(brief_id, lead_id, "new")

    @app.get("/briefs/{brief_id}/export.json")
    def export(brief_id: str, status: str | None = None) -> dict:
        b, leads = load(brief_id)
        if status:  # e.g. ?status=kept: the Keep bar's download
            leads = [x for x in leads if x.status == status]
        ids = {b.researcher_id, *(x.record_id for x in leads)}
        ids |= {f"https://openalex.org/{c}" for x in leads for c in x.cited_ids
                if c.startswith("W")}
        ids |= {f"grants_gov:{c}" for x in leads for c in x.cited_ids if not c.startswith("W")}
        with service.repo() as r:
            records = [record_json(x) for x in (r.get_any(i) for i in sorted(ids)) if x]
        return {"brief": b.model_dump(mode="json"),
                "leads": [x.model_dump(mode="json") for x in leads], "records": records,
                "notice": grants_gov.ATTRIBUTION}

    @app.get("/records/{record_id:path}")
    def get_record(record_id: str) -> dict:
        with service.repo() as r:
            x = r.get_any(record_id)
            if x is None and re.fullmatch(r"[AW]\d+", record_id):  # short OpenAlex id
                x = r.get_any(f"https://openalex.org/{record_id}")
            if x is None:  # an opportunity number, as cited in explanations
                x = r.get_any(f"grants_gov:{record_id}")
        if x is None:
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

    @app.post("/briefs/{brief_id}/scout", status_code=202)
    def scout_start(brief_id: str, req: ScoutRequest, request: Request) -> dict:
        b, _ = load(brief_id)
        if b.status != "done":
            raise HTTPException(409, "Scout can start once the brief has finished.")
        if not req.question.strip():
            raise HTTPException(422, "Ask Scout a question.")
        ask_allowed(request)
        return scout_view(hub.start(brief_id, b.researcher_id, req.question.strip(), req.mode))

    def entry(sid: str):  # noqa: ANN202 - an Entry
        e = hub.get(sid)
        if e is None:
            raise HTTPException(404, "No such Scout session. Sessions end when the server "
                                "restarts.")
        return e

    @app.get("/scout/{sid}")
    def scout_get(sid: str) -> dict:
        return scout_view(entry(sid))

    @app.post("/scout/{sid}/{action}", status_code=202)
    def scout_act(sid: str, action: Literal["approve", "skip", "ask", "mode"],
                  req: ScoutRequest, request: Request) -> dict:
        e = entry(sid)
        if action == "ask":
            if not req.question.strip():
                raise HTTPException(422, "Ask Scout a question.")
            ask_allowed(request)
        try:
            hub.act(e, action, req.card_id, req.question.strip())
        except Busy as err:
            raise HTTPException(409, str(err)) from err
        return scout_view(e)

    if web_dir and (web_dir / "index.html").is_file():  # after every API route
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app

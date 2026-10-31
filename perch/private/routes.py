"""Session HTTP routes (S13; every brief since S23). On unless PERCH_PRIVATE_MODE=0.

The session token travels in the X-Perch-Private header only, never in a path or a
query string, so no access or proxy log can hold it. Private input travels in POST
bodies; files come as base64 in JSON (Starlette spools large multipart uploads to
disk, which private mode must not do).

  GET  /private                         enabled, the privacy statement, kinds and caps
  POST /private/session                 open a session; returns its token
  GET  /private/session                 the session's documents (kind, characters)
  POST /private/end                     drop everything in the session
  POST /private/documents               {"kind", "text"} or {"kind", "filename", "data"}
  POST /private/documents/{kind}/remove
  POST /private/cloud                   {"on", "confirm"?}: Cloud on or off for this session;
                                        on needs "confirm" equal to the provider's name
  POST /private/brief                   {"author_id"?, "top"?, "explain"?, "direction"?, ...}:
                                        a brief; needs an author id or a document
  GET  /private/brief                   the brief, as GET /briefs/{id} with private records
  POST /private/leads/{lead_id}/{keep|dismiss|restore}
  GET  /private/records/{id}            a record, public or private
  GET  /private/compare
  POST /private/handoff                 {"office", "lead_ids"?, "mask"?}
  GET  /private/export.json|.md|.html   ?mask=true for masked private text
  POST /private/unmask                  {"text"}: placeholders back to the originals
  POST /private/scout, GET /private/scout/{sid}, POST /private/scout/{sid}/{action}
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from perch import compare as cmp
from perch import export as ex
from perch.config import env
from perch.jobs import JobRunner
from perch.privacy import PrivateSettings
from perch.private.inputs import FORMATS, KINDS, MAX_BYTES, MAX_CHARS, InputError, Upload
from perch.private.session import (
    BRIEFS_PER_SESSION,
    IDLE_SECONDS,
    MAX_TOTAL_CHARS,
    SESSIONS_PER_ADDRESS,
    PrivateSession,
    PrivateSessions,
    TooManyFromAddress,
    add_document,
)
from perch.schemas import Opportunity, Record, Work, belongs_to
from perch.sources import openalex as oa

STUDENT_KINDS = ("interests", "achievements")
SESSION_HEADER = "X-Perch-Private"  # the header that carries the session id


class DocumentRequest(BaseModel):
    kind: Literal["cv", "proposal", "direction", "manuscript", "interests", "achievements"]
    text: str | None = Field(None, max_length=MAX_CHARS * 2)
    filename: str | None = Field(None, max_length=200)
    data: str | None = Field(None, max_length=MAX_BYTES * 4 // 3 + 8)  # base64


class PrivateBriefRequest(BaseModel):
    author_id: str | None = Field(None, max_length=100)
    as_of: date | None = None
    top: int = Field(10, ge=1, le=25)
    explain: bool = True
    min_amount: float | None = Field(None, ge=0)
    # The optional context fields (Q16): used as a query only, held with the brief.
    direction: str | None = Field(None, max_length=1000)
    include_keywords: list[str] = Field(default_factory=list, max_length=20)
    exclude_keywords: list[str] = Field(default_factory=list, max_length=20)
    career_stage: Literal["early_stage", "established"] | None = None

    def context(self) -> dict:
        clean = lambda xs: [x.strip()[:60] for x in xs if x.strip()]  # noqa: E731
        return {"direction": (self.direction or "").strip(),
                "include_keywords": clean(self.include_keywords),
                "exclude_keywords": clean(self.exclude_keywords),
                "career_stage": self.career_stage}


class CloudRequest(BaseModel):
    on: bool
    # The second confirm (S24, Q30): "send my documents to <provider>", typed or sent as-is.
    documents_confirm: str | None = Field(None, max_length=100)
    confirm: str | None = Field(None, max_length=40)


class PrivateHandoffRequest(BaseModel):
    office: Literal["research_development", "technology_commercialization"]
    lead_ids: list[str] = Field(default_factory=list, max_length=25)
    mask: bool = False


class ScoutReq(BaseModel):
    question: str = Field("", max_length=1000)


class TextRequest(BaseModel):
    text: str = Field(max_length=200_000)


def doc_json(kind: str, d: Work) -> dict:
    return {"kind": kind, "label": KINDS[kind], "id": d.id, "chars": len(d.abstract or "")}


def private_record_json(d: Work) -> dict:
    return {"kind": "private", "id": d.id, "title": d.title, "text": d.abstract,
            "source": "private", "source_url": None, "fetched_at": d.fetched_at.isoformat(),
            "private": True}


def session_records(s: PrivateSession) -> dict[str, Work]:
    """The session's documents and, in student mode, one record per achievement."""
    from perch.private.student import achievement_docs

    out: dict[str, Work] = {d.id: d for d in s.docs.values()}
    if ach := s.docs.get("achievements"):
        # stamped with the upload time, so the answer, and its ETag, stay the same (P3)
        out.update({d.id: d for d in achievement_docs(ach.abstract or "", ach.fetched_at)})
    return out


SYNTHETIC_DIR = Path(__file__).resolve().parents[2] / "data/synthetic"


def docs_phrase(provider: str | None) -> str:
    return f"send my documents to {(provider or '').lower()}"


def _read(rel: str) -> str:
    return (SYNTHETIC_DIR / rel).read_text(encoding="utf-8")


def _researcher_sample() -> dict:
    # persona-1's README forbids attaching its CV to a real researcher's profile, so the
    # researcher sample steers the search (direction, keywords, draft aims) and leaves the
    # CV empty (S24 decision).
    ctx = json.loads(_read("persona-1/context.json"))
    return {"label": "SYNTHETIC persona-1", "direction": ctx["direction"],
            "include_keywords": ctx["include_keywords"],
            "exclude_keywords": ctx["exclude_keywords"],
            "proposal": _read("persona-1/specific_aims_draft.md"), "cv": ""}


def _student_sample() -> dict:
    return {"label": "SYNTHETIC persona-ug", "cv": _read("persona-ug/cv.md"),
            "interests": _read("persona-ug/interests.md"),
            "achievements": _read("persona-ug/achievements.md")}


SAMPLES: dict[str, Callable[[], dict]] = {"researcher": _researcher_sample,
                                          "student": _student_sample}


def student_offices() -> dict:
    from perch.scout.student_tools import OFFICES

    return {r: {"name": n, "url": u} for r, (n, u) in OFFICES.items()}


def per_hour(name: str, default: int) -> int:
    """An hourly cap from the environment, or its default when unset or empty."""
    return int(env(name) or default)


def add_private_routes(app: FastAPI, service: object, runner: JobRunner,
                       scout_runner: JobRunner, *, brief_view: Callable, export_json: Callable,
                       export_blocks: Callable, load: Callable, limiter: type,
                       client_key: Callable[[Request], str],
                       settings: PrivateSettings | None = None) -> PrivateSessions:
    settings = settings or PrivateSettings.from_env()
    problems = settings.problems()
    on = settings.enabled and not problems
    sessions = PrivateSessions(service, settings, per_address=per_hour(
        "PERCH_SESSIONS_PER_ADDRESS", SESSIONS_PER_ADDRESS))
    # A session's queued brief job is dropped when the session ends or expires, or when
    # a newer brief replaces it; a running one stops before its next stage (review S7).
    sessions.on_end = lambda s: s.brief_id and runner.cancel(f"private-{s.brief_id}")

    def submit(s: PrivateSession, old: str | None, bid: str) -> None:
        if old and old != bid:
            runner.cancel(f"private-{old}")
        runner.submit(f"private-{bid}", lambda: s.service.run(bid))
    if on:  # student mode reads the sample store; load it now, outside any session
        from perch.scholarships import ensure_samples

        ensure_samples()
    # Hourly caps per visitor, each read from the environment (.env.example lists them).
    open_limit = limiter(per_hour("PERCH_SESSIONS_PER_HOUR", 20))  # new sessions
    brief_limit = limiter(per_hour("PERCH_BRIEFS_PER_HOUR", 10))
    handoff_limit = limiter(per_hour("PERCH_HANDOFF_PER_HOUR", 30))
    docs_limit = limiter(per_hour("PERCH_DOCUMENTS_PER_HOUR", 60))  # uploads and pastes
    # Scout questions, per visitor and per session: each runs up to 8 model turns.
    scout_limit = limiter(per_hour("PERCH_SCOUT_PER_HOUR", 30))
    scout_session_limit = limiter(per_hour("PERCH_SCOUT_PER_HOUR", 30))
    cloud_day = {"day": "", "n": 0}  # cloud briefs today, whole server, in memory only
    cloud_lock = threading.Lock()
    app.state.private_sessions = sessions
    from perch.private.warm import WarmBriefs, is_default, warm_authors

    warm = WarmBriefs(sessions, settings, warm_authors() if on else [],
                      submit=runner.submit)
    app.state.warm_briefs = warm
    warm.start()  # a job on the brief runner; the server answers while it builds
    warm.schedule()

    def cloud_info() -> dict:
        p = settings.cloud_provider
        return {"available": bool(p) and on, "provider": p,
                "model": settings.cloud_spec.partition(":")[2] if p else None,
                "warning": (f"Cloud sends what you type (the researcher you look up and any "
                            f"direction or keywords) and the text of the public papers and "
                            f"listings in your brief to {p}, through its API, to write the "
                            f"summary, the fit explanations and hand-off openings. "
                            + (f"Documents you add go to {p} only after a second warning. "
                               if settings.cloud_documents else
                               f"Documents you add never go to {p}: Cloud stays off while a "
                               f"session holds documents. ")
                            + "Search, ranking and Scout stay on local models.")
                if p else None,
                # Documents on Cloud after a second warning (S24, Q30), off by default.
                "documents": bool(p) and on and settings.cloud_documents,
                "documents_phrase": docs_phrase(p) if p else None,
                "documents_warning": (f"This also sends the documents you add (your CV, "
                                      f"draft proposal or unpublished work) to {p}. They "
                                      f"may hold names, contact details and unpublished "
                                      f"ideas. Perch cannot take them back once sent.")
                if p and settings.cloud_documents else None}

    def take_cloud(what: str = "briefs") -> None:
        """One of today's cloud uses, whole server: a brief or a hand-off draft (S17)."""
        with cloud_lock:
            today = date.today().isoformat()
            if cloud_day["day"] != today:
                cloud_day.update(day=today, n=0)
            if cloud_day["n"] >= settings.cloud_per_day:
                raise HTTPException(429, f"Cloud {what} for today are used up. Turn Cloud "
                                    "off to use local models.")
            cloud_day["n"] += 1

    @app.get("/private")
    def private_info() -> dict:
        return {"enabled": on, "statement": settings.statement() if on else None,
                "kinds": {k: v for k, v in KINDS.items() if k not in STUDENT_KINDS},
                # A student may have a résumé rather than a CV (S22, audit S2).
                "student_kinds": {**{k: KINDS[k] for k in ("cv", *STUDENT_KINDS)},
                                  "cv": "Your CV or résumé"},
                "formats": list(FORMATS), "max_bytes": MAX_BYTES,
                "max_chars": MAX_CHARS, "max_total_chars": MAX_TOTAL_CHARS,
                "idle_minutes": IDLE_SECONDS // 60, "cloud": cloud_info(),
                # The Temple office for each student route; its note comes from
                # /private/student/note (review W9).
                "student_offices": student_offices()}

    @app.get("/private/samples/{name}")
    def sample(name: Literal["researcher", "student"]) -> dict:
        """SYNTHETIC text for "Fill with a sample" (S24). Read from data/synthetic, so the
        canary files stay the one source; nothing here is about a real person."""
        if not on:
            raise HTTPException(404, "Private mode is not available on this server.")
        return SAMPLES[name]()

    def session(token: str | None) -> PrivateSession:
        if not on:
            raise HTTPException(404, "Private mode is not available on this server.")
        s = sessions.get(token)
        if s is None:
            raise HTTPException(401, "No private session. It may have ended or timed out.")
        return s

    @app.post("/private/session", status_code=201)
    def open_session(request: Request) -> dict:
        if not on:
            raise HTTPException(404, "Private mode is not available on this server.")
        if wait := open_limit.take(client_key(request)):
            raise HTTPException(429, "Too many private sessions this hour.",
                                headers={"Retry-After": str(wait)})
        try:
            s = sessions.open(client_key(request))
        except OverflowError as e:
            raise HTTPException(503, str(e)) from e
        except TooManyFromAddress as e:
            raise HTTPException(429, f"Too many open sessions: {e}.",
                                headers={"Retry-After": "600"}) from e
        except PermissionError as e:
            raise HTTPException(403, f"Private mode refused: {e}") from e
        return {"token": s.token, "idle_minutes": IDLE_SECONDS // 60,
                "statement": settings.statement(), "cloud": False}

    @app.get("/private/session")
    def get_session(x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        cv = s.cv
        return {"documents": [doc_json(k, d) for k, d in s.docs.items()],
                "brief_id": s.brief_id, "chars": s.chars(), "cloud": s.cloud,
                "cv": {"degree_year": cv.degree_year, "rank": cv.rank,
                       "sponsors": cv.sponsors, "nih_awards": cv.nih_substantial} if cv else None}

    @app.post("/private/end")
    def end(x_perch_private: str | None = Header(None)) -> dict:
        return {"ended": sessions.end(x_perch_private)}

    @app.post("/private/cloud")
    def set_cloud(req: CloudRequest, x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        if req.on:
            p = settings.cloud_provider
            if not (p and on):
                raise HTTPException(404, "Cloud is not offered on this server.")
            if (req.confirm or "").strip().lower() != p.lower():
                raise HTTPException(422, f"Confirm by sending the provider's name, {p}.")
            docs_ok = (req.documents_confirm or "").strip().lower() == docs_phrase(p)
            if s.docs and not (settings.cloud_documents and docs_ok):
                raise HTTPException(409, "Remove your documents first: they stay on local "
                                    "models." if not settings.cloud_documents else
                                    f"Confirm the second warning: {docs_phrase(p)}.")
            s.cloud_docs = settings.cloud_documents and docs_ok
        s.cloud = req.on
        if not req.on:
            s.cloud_docs = False
        return {"cloud": s.cloud, "documents": s.cloud_docs}

    @app.post("/private/documents", status_code=201)
    def add_doc(req: DocumentRequest, request: Request,
                x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        if wait := docs_limit.take(client_key(request)):
            raise HTTPException(429, "Too many documents added this hour.",
                                headers={"Retry-After": str(wait)})
        if s.cloud and not s.cloud_docs:
            raise HTTPException(409, "Turn Cloud off first: documents stay on local models.")
        try:
            data = (base64.b64decode(req.data, validate=True) if req.data is not None
                    else None)
            doc = Upload(req.kind, req.text, req.filename, data).doc()
            with s.lock:
                add_document(s, doc)
        except binascii.Error as e:
            raise HTTPException(422, "the file data is not base64") from e
        except InputError as e:
            raise HTTPException(422, str(e)) from e
        return doc_json(req.kind, doc)

    @app.post("/private/documents/{kind}/remove")
    def remove_doc(kind: str, x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        with s.lock:
            return {"removed": s.docs.pop(kind, None) is not None}

    @app.post("/private/brief", status_code=202)
    def start_brief(req: PrivateBriefRequest, request: Request,
                    x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        if not s.docs and not req.author_id:
            raise HTTPException(422, "Choose a researcher or add a document first.")
        if s.briefs_run >= BRIEFS_PER_SESSION:
            raise HTTPException(429, f"A session runs at most {BRIEFS_PER_SESSION} briefs.")
        if req.author_id and not oa.parse_author_id(req.author_id):  # before the hourly cap
            raise HTTPException(422, "not an OpenAlex author id")
        # A warm copy costs no model time, so it does not count against the hourly cap.
        if is_default(req, s) and (w := warm.take(s, req.author_id)) is not None:
            s.briefs_run += 1  # a copy of a warm demo brief, held in this session only
            return {"id": w.id, "status": w.status, "warm": True}
        throttle(request)
        if s.cloud and (not s.docs or s.cloud_docs) and req.explain:
            take_cloud()
        old = s.brief_id
        try:
            b = s.service.create_private(req.author_id, as_of=req.as_of, top=req.top,
                                         explain=req.explain, min_amount=req.min_amount,
                                         context=req.context())
        except ValueError as e:
            raise HTTPException(422, "not an OpenAlex author id") from e
        s.briefs_run += 1
        submit(s, old, b.id)
        return {"id": b.id, "status": b.status}

    @app.post("/private/student/brief", status_code=202)
    def start_student(req: PrivateBriefRequest, request: Request,
                      x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        if "cv" not in s.docs:
            raise HTTPException(422, "Add your CV first.")
        if "interests" not in s.docs and "achievements" not in s.docs:
            raise HTTPException(422, "Add your interests or achievements too.")
        if s.briefs_run >= BRIEFS_PER_SESSION:
            raise HTTPException(429, f"A session runs at most {BRIEFS_PER_SESSION} briefs.")
        throttle(request)
        s.cloud = s.cloud_docs = False  # a student's CV stays on local models
        old = s.brief_id
        b = s.service.create_student(as_of=req.as_of, top=req.top, explain=req.explain)
        s.briefs_run += 1
        submit(s, old, b.id)
        return {"id": b.id, "status": b.status}

    def throttle(request: Request) -> None:
        if wait := brief_limit.take(client_key(request)):
            raise HTTPException(429, f"Limit of {brief_limit.per_hour} new briefs an hour "
                                f"reached. Try again in {wait // 60 + 1} minutes.",
                                headers={"Retry-After": str(wait)})

    def brief_id(s: PrivateSession) -> str:
        if not s.brief_id:
            raise HTTPException(404, "No private brief yet.")
        return s.brief_id

    @app.get("/private/brief")
    def get_brief(request: Request, x_perch_private: str | None = Header(None)) -> Response:
        """The brief, with an ETag: a poll that sends the last ETag gets 304 and no body
        while nothing changed (review P3)."""
        out = brief_json(session(x_perch_private))
        body = json.dumps(jsonable_encoder(out), separators=(",", ":")).encode()
        tag = '"' + hashlib.sha256(body).hexdigest()[:20] + '"'
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers={"ETag": tag})
        return Response(body, media_type="application/json", headers={"ETag": tag})

    def brief_json(s: PrivateSession) -> dict:
        out = brief_view(brief_id(s), s.service)
        out["papers"].update({i: private_record_json(d) for i, d in session_records(s).items()})
        out["private"] = True
        if out["brief"]["options"].get("student") and "cv" in s.docs:
            from perch.student import parse_student_cv

            out["student"] = parse_student_cv(s.docs["cv"].abstract or "").summary()
        return out

    @app.post("/private/leads/{lead_id}/{action}")
    def set_status(lead_id: str, action: Literal["keep", "dismiss", "restore"],
                   x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        status = {"keep": "kept", "dismiss": "dismissed", "restore": "new"}[action]
        lead = s.service.set_lead_status(brief_id(s), lead_id, status)
        if not lead:
            raise HTTPException(404, "no such lead")
        return lead.model_dump(mode="json")

    @app.get("/private/records/{record_id:path}")
    def get_record(record_id: str, x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        d = session_records(s).get(record_id)
        if d:
            return private_record_json(d)
        with s.service.repo() as r:
            x: Record | None = (r.get_any(record_id) or r.get_any(f"grants_gov:{record_id}")
                                or r.get_any(f"https://openalex.org/{record_id}"))
        if x is None or not belongs_to(x, s.brief_id):  # another visitor's (review S9)
            raise HTTPException(404, "no such record")
        return {"kind": x.kind, **x.model_dump(mode="json")}

    @app.get("/private/student/note")
    def student_note(route: Literal["F", "S"],
                     x_perch_private: str | None = Header(None)) -> dict:
        """The Compare tab's note for one route, written by code (review W9): the same
        function as Scout's draft_note, so there is one source."""
        from perch.scout.student_tools import facts_of, record_of, write_note

        s = session(x_perch_private)
        b, leads = load(brief_id(s), s.service)
        if not b.options.get("student"):
            raise HTTPException(422, "Only a student brief has a note.")
        kept = [x for x in leads if x.status == "kept" and x.route == route]
        if not kept:
            raise HTTPException(404, "Nothing kept for that office.")
        return write_note(route, [(x, facts_of(record_of(s.service, x))) for x in kept])

    @app.get("/private/compare")
    def compare(status: Literal["kept", "all"] = "kept",
                x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        b, leads = load(brief_id(s), s.service)
        with s.service.repo() as r:
            rows = cmp.compare(b, leads, r, None if status == "all" else status)
        return cmp.rows_json(rows)

    def masker_for(s: PrivateSession, mask: bool):  # noqa: ANN202 - Masker or None
        if not mask:
            return None
        b, leads = load(brief_id(s), s.service)
        with s.service.repo() as r:
            public = [o.description or o.title for x in leads
                      if (o := r.get(Opportunity, x.record_id))]
        return s.make_masker(public)

    @app.post("/private/handoff")
    def handoff(req: PrivateHandoffRequest, request: Request,
                x_perch_private: str | None = Header(None)) -> dict:
        from perch.api import draft_json

        s = session(x_perch_private)
        b, _ = load(brief_id(s), s.service)
        if b.options.get("student"):  # student drafts are written on the Compare tab
            raise HTTPException(422, "A student brief drafts its hand-offs on the Compare tab.")
        if wait := handoff_limit.take(client_key(request)):
            raise HTTPException(429, "Too many drafts this hour.",
                                headers={"Retry-After": str(wait)})
        if s.service.models.cloud():  # the opening paragraph goes to the cloud model
            take_cloud("hand-off drafts")
        d = s.service.handoff(brief_id(s), req.office, req.lead_ids or None,
                              masker=masker_for(s, req.mask))
        if d is None:
            raise HTTPException(404, "No private brief yet.")
        return {**draft_json(d), "masked": req.mask}

    @app.get("/private/export.json")
    def export_j(mask: bool = False, status: Literal["kept"] | None = None,
                 x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        return {**export_json(brief_id(s), status, s.service, masker_for(s, mask),
                              bool(s.docs)), "masked": mask}

    @app.get("/private/export.md")
    def export_md(mask: bool = False, status: Literal["kept"] | None = None,
                  x_perch_private: str | None = Header(None)) -> Response:
        s = session(x_perch_private)
        bs, _ = export_blocks(brief_id(s), status, s.service, masker_for(s, mask),
                              bool(s.docs))
        return Response(ex.to_markdown(bs), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition":
                                 'attachment; filename="perch-private-brief.md"'})

    @app.get("/private/export.html")
    def export_html(mask: bool = False, status: Literal["kept"] | None = None,
                    x_perch_private: str | None = Header(None)) -> Response:
        s = session(x_perch_private)
        bs, title = export_blocks(brief_id(s), status, s.service, masker_for(s, mask),
                                  bool(s.docs))
        return Response(ex.to_html(bs, title), media_type="text/html; charset=utf-8")

    @app.post("/private/unmask")
    def unmask(req: TextRequest, x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        if s.masker is None:
            raise HTTPException(409, "Nothing has been masked in this session.")
        return {"text": s.masker.unmask(req.text)}

    # --- private Scout: a hub per session, no log, local models only ---

    def hub(s: PrivateSession):  # noqa: ANN202 - a ScoutHub
        from perch.scout.hub import ScoutHub

        if s.scout is None:
            s.scout = ScoutHub(s.service, scout_runner, None, private=settings)
        return s.scout

    def ask_allowed(s: PrivateSession, request: Request) -> None:
        wait = (scout_session_limit.take(f"session:{s.token}")
                or scout_limit.take(client_key(request)))
        if wait:
            raise HTTPException(429, f"Limit of {scout_limit.per_hour} Scout questions an "
                                f"hour reached. Try again in {wait // 60 + 1} minutes.",
                                headers={"Retry-After": str(wait)})

    @app.post("/private/scout", status_code=202)
    def scout_start(req: ScoutReq, request: Request,
                    x_perch_private: str | None = Header(None)) -> dict:
        from perch.scout.hub import view

        s = session(x_perch_private)
        b, _ = load(brief_id(s), s.service)
        if b.status != "done":
            raise HTTPException(409, "Scout can start once the brief has finished.")
        if not req.question.strip():
            raise HTTPException(422, "Ask Scout a question.")
        ask_allowed(s, request)
        try:
            e = hub(s).start(b.id, b.researcher_id, req.question.strip())
        except PermissionError as err:
            raise HTTPException(403, str(err)) from err
        return view(e)

    @app.get("/private/scout/{sid}")
    def scout_get(sid: str, x_perch_private: str | None = Header(None)) -> dict:
        from perch.scout.hub import view

        e = hub(session(x_perch_private)).get(sid)
        if e is None:
            raise HTTPException(404, "No such Scout session.")
        return view(e)

    @app.post("/private/scout/{sid}/{action}", status_code=202)
    def scout_act(sid: str, action: Literal["ask", "stop"], req: ScoutReq, request: Request,
                  x_perch_private: str | None = Header(None)) -> dict:
        from perch.scout.hub import Busy, view

        s = session(x_perch_private)
        e = hub(s).get(sid)
        if e is None:
            raise HTTPException(404, "No such Scout session.")
        if action == "ask":
            if not req.question.strip():
                raise HTTPException(422, "Ask Scout a question.")
            ask_allowed(s, request)
        try:
            hub(s).act(e, action, req.question.strip())
        except Busy as err:
            raise HTTPException(409, str(err)) from err
        return view(e)

    return sessions

"""Private-mode HTTP routes (S13). Off unless PERCH_PRIVATE_MODE=1 with no problems.

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
  POST /private/brief                   {"author_id"?, "top"?, "explain"?}: a private brief
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
from collections.abc import Callable
from datetime import date
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from perch import compare as cmp
from perch import export as ex
from perch.jobs import JobRunner
from perch.privacy import PrivateSettings
from perch.private.inputs import FORMATS, KINDS, MAX_BYTES, MAX_CHARS, InputError, Upload
from perch.private.session import (
    BRIEFS_PER_SESSION,
    IDLE_SECONDS,
    MAX_TOTAL_CHARS,
    PrivateSession,
    PrivateSessions,
    add_document,
)
from perch.schemas import Opportunity, Record, Work

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


class PrivateHandoffRequest(BaseModel):
    office: Literal["research_development", "technology_commercialization"]
    lead_ids: list[str] = Field(default_factory=list, max_length=25)
    mask: bool = False


class ScoutReq(BaseModel):
    question: str = Field("", max_length=1000)
    mode: Literal["ask", "run"] = "ask"
    card_id: str | None = None


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
        out.update({d.id: d for d in achievement_docs(ach.abstract or "")})
    return out


def add_private_routes(app: FastAPI, service: object, runner: JobRunner,
                       scout_runner: JobRunner, *, brief_view: Callable, export_json: Callable,
                       export_blocks: Callable, load: Callable, limiter: type,
                       client_key: Callable[[Request], str],
                       settings: PrivateSettings | None = None) -> PrivateSessions:
    settings = settings or PrivateSettings.from_env()
    problems = settings.problems()
    on = settings.enabled and not problems
    sessions = PrivateSessions(service, settings)
    if on:  # student mode reads the sample store; load it now, outside any session
        from perch.scholarships import ensure_samples

        ensure_samples()
    open_limit = limiter(20)  # new sessions an hour per visitor
    app.state.private_sessions = sessions

    @app.get("/private")
    def private_info() -> dict:
        return {"enabled": on, "statement": settings.statement() if on else None,
                "kinds": {k: v for k, v in KINDS.items() if k not in STUDENT_KINDS},
                # A student may have a résumé rather than a CV (S22, audit S2).
                "student_kinds": {**{k: KINDS[k] for k in ("cv", *STUDENT_KINDS)},
                                  "cv": "Your CV or résumé"},
                "formats": list(FORMATS), "max_bytes": MAX_BYTES,
                "max_chars": MAX_CHARS, "max_total_chars": MAX_TOTAL_CHARS,
                "idle_minutes": IDLE_SECONDS // 60}

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
            s = sessions.open()
        except OverflowError as e:
            raise HTTPException(503, str(e)) from e
        except PermissionError as e:
            raise HTTPException(403, f"Private mode refused: {e}") from e
        return {"token": s.token, "idle_minutes": IDLE_SECONDS // 60,
                "statement": settings.statement()}

    @app.get("/private/session")
    def get_session(x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        cv = s.cv
        return {"documents": [doc_json(k, d) for k, d in s.docs.items()],
                "brief_id": s.brief_id, "chars": s.chars(),
                "cv": {"degree_year": cv.degree_year, "rank": cv.rank,
                       "sponsors": cv.sponsors, "nih_awards": cv.nih_substantial} if cv else None}

    @app.post("/private/end")
    def end(x_perch_private: str | None = Header(None)) -> dict:
        return {"ended": sessions.end(x_perch_private)}

    @app.post("/private/documents", status_code=201)
    def add_doc(req: DocumentRequest, x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
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
    def start_brief(req: PrivateBriefRequest, x_perch_private: str | None = Header(None)
                    ) -> dict:
        s = session(x_perch_private)
        if not s.docs:
            raise HTTPException(422, "Add at least one document first.")
        if s.briefs_run >= BRIEFS_PER_SESSION:
            raise HTTPException(429, f"A session runs at most {BRIEFS_PER_SESSION} briefs.")
        try:
            b = s.service.create_private(req.author_id, as_of=req.as_of, top=req.top,
                                         explain=req.explain)
        except ValueError as e:
            raise HTTPException(422, "not an OpenAlex author id") from e
        s.briefs_run += 1
        runner.submit(f"private-{b.id}", lambda: s.service.run(b.id))
        return {"id": b.id, "status": b.status}

    @app.post("/private/student/brief", status_code=202)
    def start_student(req: PrivateBriefRequest, x_perch_private: str | None = Header(None)
                      ) -> dict:
        s = session(x_perch_private)
        if "cv" not in s.docs:
            raise HTTPException(422, "Add your CV first.")
        if "interests" not in s.docs and "achievements" not in s.docs:
            raise HTTPException(422, "Add your interests or achievements too.")
        if s.briefs_run >= BRIEFS_PER_SESSION:
            raise HTTPException(429, f"A session runs at most {BRIEFS_PER_SESSION} briefs.")
        b = s.service.create_student(as_of=req.as_of, top=req.top, explain=req.explain)
        s.briefs_run += 1
        runner.submit(f"private-{b.id}", lambda: s.service.run(b.id))
        return {"id": b.id, "status": b.status}

    def brief_id(s: PrivateSession) -> str:
        if not s.brief_id:
            raise HTTPException(404, "No private brief yet.")
        return s.brief_id

    @app.get("/private/brief")
    def get_brief(x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
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
        if x is None:
            raise HTTPException(404, "no such record")
        return {"kind": x.kind, **x.model_dump(mode="json")}

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

    handoff_limit = limiter(30)

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
        d = s.service.handoff(brief_id(s), req.office, req.lead_ids or None,
                              masker=masker_for(s, req.mask))
        if d is None:
            raise HTTPException(404, "No private brief yet.")
        return {**draft_json(d), "masked": req.mask}

    @app.get("/private/export.json")
    def export_j(mask: bool = False, status: Literal["kept"] | None = None,
                 x_perch_private: str | None = Header(None)) -> dict:
        s = session(x_perch_private)
        return {**export_json(brief_id(s), status, s.service, masker_for(s, mask)),
                "masked": mask}

    @app.get("/private/export.md")
    def export_md(mask: bool = False, status: Literal["kept"] | None = None,
                  x_perch_private: str | None = Header(None)) -> Response:
        s = session(x_perch_private)
        bs, _ = export_blocks(brief_id(s), status, s.service, masker_for(s, mask))
        return Response(ex.to_markdown(bs), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition":
                                 'attachment; filename="perch-private-brief.md"'})

    @app.get("/private/export.html")
    def export_html(mask: bool = False, status: Literal["kept"] | None = None,
                    x_perch_private: str | None = Header(None)) -> Response:
        s = session(x_perch_private)
        bs, title = export_blocks(brief_id(s), status, s.service, masker_for(s, mask))
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

    @app.post("/private/scout", status_code=202)
    def scout_start(req: ScoutReq, x_perch_private: str | None = Header(None)) -> dict:
        from perch.scout.hub import view

        s = session(x_perch_private)
        b, _ = load(brief_id(s), s.service)
        if b.status != "done":
            raise HTTPException(409, "Scout can start once the brief has finished.")
        if not req.question.strip():
            raise HTTPException(422, "Ask Scout a question.")
        try:
            e = hub(s).start(b.id, b.researcher_id, req.question.strip(), req.mode)
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
    def scout_act(sid: str, action: Literal["approve", "skip", "ask", "mode"], req: ScoutReq,
                  x_perch_private: str | None = Header(None)) -> dict:
        from perch.scout.hub import Busy, view

        e = hub(session(x_perch_private)).get(sid)
        if e is None:
            raise HTTPException(404, "No such Scout session.")
        try:
            hub(session(x_perch_private)).act(e, action, req.card_id, req.question.strip())
        except Busy as err:
            raise HTTPException(409, str(err)) from err
        return view(e)

    return sessions

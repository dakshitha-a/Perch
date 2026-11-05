"""Account routes for the signed-in user (ARCHITECTURE_V1 sections 7.5 and 9.2): documents and
entries, delete-my-data, briefs, usage.

Auth comes from perch/auth/deps.py (`require_user`, `require_csrf`). Services come from
`request.app.state.user_services`, set when the app is built; nothing here reads a user's text
into a log or a response other than the owner's own rows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import redis
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from perch import redisx
from perch.auth import deps
from perch.auth.session import Session
from perch.citizenship import CITIZENSHIP_VALUES, STATE_CODES
from perch.jobs import JobRunner
from perch.user import docs, quota, saved
from perch.user import profile as profile_store
from perch.user.data import BadBlob, UserData
from perch.user.delete import delete_account
from perch.user.inputs import MAX_BYTES, MAX_CHARS, InputError
from perch.user.models import ProfileDoc, StoredBrief

log = logging.getLogger("perch.user.routes")
router = APIRouter()


@dataclass
class UserServices:
    pool: ConnectionPool
    ud: UserData
    runner: JobRunner
    redis: redis.Redis


def services(request: Request) -> UserServices:
    s = getattr(request.app.state, "user_services", None)
    if s is None:
        raise HTTPException(503, "The account service is not configured.")
    return s


class DocAdd(BaseModel):
    kind: Literal["cv", "proposal", "direction", "manuscript", "interests", "entry"]
    label: str | None = Field(None, max_length=120)
    text: str | None = Field(None, max_length=MAX_CHARS * 2)
    filename: str | None = Field(None, max_length=200)
    data: str | None = Field(None, max_length=MAX_BYTES * 4 // 3 + 8)  # base64 of a file


class SavedAdd(BaseModel):
    record_id: str = Field(min_length=1, max_length=200)


class ProfilePut(BaseModel):
    """The optional picks (S53). Anything outside the closed lists is a 422."""

    citizenship: Literal[CITIZENSHIP_VALUES] | None = None  # type: ignore[valid-type]
    residency_state: Literal[STATE_CODES] | None = None  # type: ignore[valid-type]


class DeleteConfirm(BaseModel):
    confirm: Literal["delete"]


def _uid(s: Session) -> UUID:
    if s.user_id is None:
        raise HTTPException(401, {"error": "auth_required"})
    return s.user_id


def _side(s: Session, audience: str | None) -> Literal["researcher", "student"]:
    a = audience or s.audience
    if a not in ("researcher", "student"):
        raise HTTPException(422, "audience must be researcher or student")
    return a  # type: ignore[return-value]


def _consented(s: Session) -> None:
    """Writing the CV, entries or documents, or building from them, needs the current consent
    (7.5). Listing and deleting do not: a user who withdrew can still see and remove what is
    stored."""
    deps.require_consent(s)


def _limit(sv: UserServices, uid: UUID, scope: str) -> None:
    ok, retry = redisx.rate_limit(sv.redis, scope, f"u:{uid}")
    if not ok:
        raise HTTPException(429, {"error": "rate_limited"}, headers={"Retry-After": str(retry)})


# --- documents, CV and entries ---

@router.get("/me/docs")
def list_docs(audience: str | None = None, s: Session = Depends(deps.require_user),
              sv: UserServices = Depends(services)) -> list[dict]:
    # Listing what is stored (names and kinds, never text) needs no consent, so a user who
    # withdrew can still see what Perch holds before deleting it (S43 M6).
    return docs.listing(sv.ud, _uid(s), _side(s, audience))


@router.post("/me/docs", dependencies=[Depends(deps.require_csrf)])
def add_doc(req: DocAdd, audience: str | None = None, s: Session = Depends(deps.require_user),
            sv: UserServices = Depends(services)) -> dict:
    _consented(s)
    uid, side = _uid(s), _side(s, audience)
    _limit(sv, uid, "upload")
    try:
        rid = docs.add(sv.ud, uid, side, req.kind, text=req.text, filename=req.filename,
                       data_b64=req.data, label=req.label)
    except InputError as e:  # a plain sentence that never quotes the input
        raise HTTPException(422, str(e)) from e
    return next(d for d in docs.listing(sv.ud, uid, side) if d["id"] == str(rid))


@router.delete("/me/docs/{doc_id}", dependencies=[Depends(deps.require_csrf)])
def remove_doc(doc_id: UUID, s: Session = Depends(deps.require_user),
               sv: UserServices = Depends(services)) -> dict:
    if not docs.remove(sv.ud, _uid(s), doc_id):
        raise HTTPException(404, {"error": "not_found"})  # also for another user's id
    return {"ok": True}


# --- optional citizenship and state of residence (S53) ---

@router.get("/me/profile")
def get_profile(audience: str | None = None, s: Session = Depends(deps.require_user),
                sv: UserServices = Depends(services)) -> dict:
    # Like the document listing, reading what is stored needs no consent.
    p = profile_store.read(sv.ud, _uid(s), _side(s, audience))
    return {"citizenship": p.citizenship, "residency_state": p.residency_state}


@router.put("/me/profile", dependencies=[Depends(deps.require_csrf)])
def put_profile(req: ProfilePut, audience: str | None = None,
                s: Session = Depends(deps.require_user),
                sv: UserServices = Depends(services)) -> dict:
    _consented(s)
    uid = _uid(s)
    _limit(sv, uid, "api_write")
    p = profile_store.save(sv.ud, uid, _side(s, audience),
                           ProfileDoc(citizenship=req.citizenship,
                                      residency_state=req.residency_state))
    return {"citizenship": p.citizenship, "residency_state": p.residency_state}


# --- saved awards and funding calls (S49 V2) ---

def _public_repo(request: Request):  # noqa: ANN202
    f = getattr(request.app.state, "public_repo", None)
    if f is None:
        raise HTTPException(503, "The account service is not configured.")
    return f


@router.get("/me/saved")
def list_saved(request: Request, audience: str | None = None,
               s: Session = Depends(deps.require_user),
               sv: UserServices = Depends(services)) -> dict:
    return saved.listing(sv.ud, _public_repo(request), _uid(s), _side(s, audience))


@router.post("/me/saved", dependencies=[Depends(deps.require_csrf)])
def add_saved(req: SavedAdd, request: Request, audience: str | None = None,
              s: Session = Depends(deps.require_user),
              sv: UserServices = Depends(services)) -> JSONResponse:
    _consented(s)
    uid, side = _uid(s), _side(s, audience)
    _limit(sv, uid, "api_write")
    try:
        sid, row, created = saved.save(sv.ud, _public_repo(request), uid, side, req.record_id)
    except saved.SampleRefused:
        raise HTTPException(422, {"error": "sample_not_saved"}) from None
    except saved.NotFound:
        raise HTTPException(404, {"error": "not_found"}) from None
    except saved.Full:
        raise HTTPException(409, {"error": "saved_full"}) from None
    return JSONResponse({"saved_id": str(sid), "record_id": row.record_id,
                         "saved_at": row.saved_at.isoformat()}, status_code=201 if created else 200)


@router.delete("/me/saved/{saved_id}", dependencies=[Depends(deps.require_csrf)])
def remove_saved(saved_id: UUID, s: Session = Depends(deps.require_user),
                 sv: UserServices = Depends(services)) -> dict:
    if not saved.remove(sv.ud, _uid(s), saved_id):
        raise HTTPException(404, {"error": "not_found"})
    return {"ok": True}


# --- delete-my-data ---

@router.post("/me/delete", status_code=202, dependencies=[Depends(deps.require_csrf)])
def delete_me(req: DeleteConfirm, s: Session = Depends(deps.require_user),
              sv: UserServices = Depends(services)) -> dict:
    """Section 6.6 order. The keys are shredded first; the rest of the order follows, and the
    session ends. Returns 202: the row clearing is a queued purge job."""
    try:
        delete_account(_uid(s), pool=sv.pool, runner=sv.runner, r=sv.redis)
    except Exception as e:  # noqa: BLE001 - the keys may already be gone; never echo a message
        log.error("delete failed err=%s", type(e).__name__)
        raise HTTPException(500, {"error": "delete_incomplete"}) from None
    return {"ok": True}


# --- briefs ---

def _summary(rid: UUID, sb: StoredBrief) -> dict:
    b = sb.brief
    return {"id": str(rid), "status": b.status, "researcher_id": b.researcher_id,
            "created_at": b.created_at.isoformat(),
            # Public and SYNTHETIC sample leads are counted apart (standing rule 11).
            "leads": sum(not x.sample for x in sb.leads),
            "sample_leads": sum(bool(x.sample) for x in sb.leads),
            # Kept leads, public and sample apart, for My Perch (S49 V3).
            "kept": sum(x.status == "kept" and not x.sample for x in sb.leads),
            "sample_kept": sum(x.status == "kept" and bool(x.sample) for x in sb.leads),
            "topics": b.topics[:5],
            # S50 QA: a stored failed brief says why on My Perch, as the brief page does
            **({"error": b.error} if b.status == "failed" and b.error else {})}


@router.get("/me/briefs")
def list_briefs(audience: str | None = None, s: Session = Depends(deps.require_user),
                sv: UserServices = Depends(services)) -> list[dict]:
    from perch.user.briefs import overlay_summaries

    out = [_summary(i, sb) for i, sb in sv.ud.list(_uid(s), "brief", _side(s, audience),
                                                   StoredBrief)]
    overlay_summaries(sv.ud, _uid(s), out)  # S50 C3: an ended job shows as failed here too
    return out


@router.get("/me/briefs/{brief_id}")
def get_brief(brief_id: UUID, s: Session = Depends(deps.require_user),
              sv: UserServices = Depends(services)) -> dict:
    try:
        sb = sv.ud.get(_uid(s), brief_id, StoredBrief)
    except BadBlob:  # a row of another kind under this id
        sb = None
    if sb is None:
        raise HTTPException(404, {"error": "not_found"})
    return {"id": str(brief_id), "brief": sb.brief.model_dump(mode="json"),
            "leads": [x.model_dump(mode="json") for x in sb.leads]}


# --- usage ---

@router.get("/usage")
def get_usage(s: Session = Depends(deps.require_user),
              sv: UserServices = Depends(services)) -> dict:
    u = quota.usage(sv.redis, sv.pool, _uid(s))
    return {"spent_usd": u.spent_usd, "limit_usd": u.limit_usd,
            "resets_at": u.resets_at.isoformat()}

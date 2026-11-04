"""The web side of Scout (Phase 8): what the Scout routes in perch/api.py do.

Buttons are answered here, in the web process, by code: no model, no gate, no queue hop. A
question is stored as a message in the user's encrypted `scout_session` row and a `scout_turn`
job is submitted with the row's id and the message's id (ids only, ARCHITECTURE_V1 3.5); the
worker answers it. Both paths append to the same row, and `view` is the one JSON shape the
frontend reads.

Guests have no Scout: the caller checks the session is a user's before anything here runs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import HTTPException

from perch.jobs import TERMINAL, JobState
from perch.llm import Provider, spec_for_role
from perch.redisx import QuotaExceeded
from perch.scout import buttons as btn
from perch.scout import session, texts
from perch.scout.job import account_data
from perch.scout.read_tools import ScoutData
from perch.scout.turn import Meter, TurnDeps, message, run_turn, user_message
from perch.user import quota
from perch.user.data import NotFound
from perch.user.models import ScoutSessionDoc

if TYPE_CHECKING:
    from perch.schemas import Brief
    from perch.service import BriefService
    from perch.user.routes import UserServices

LIVE = {"queued", "running"}
STALE_S = 120  # a question with no job, or whose job is unknown, stops counting as busy after this


def usage_view(sv: UserServices, uid: UUID) -> dict[str, Any]:
    """The account's day, copied from the counter: what the frontend renders as a meter."""
    u = quota.usage(sv.redis, sv.pool, uid)
    return {"used_usd": u.spent_usd, "limit_usd": u.limit_usd, "spent_usd": u.spent_usd,
            "remaining_usd": max(0.0, round(u.limit_usd - u.spent_usd, 6)),
            "resets_at": u.resets_at.isoformat()}


def _job_state(sv: UserServices, uid: UUID, mid: dict[str, Any] | None) -> str | None:
    if not mid or not mid.get("job_id"):
        return None
    st = sv.runner.status(UUID(mid["job_id"]), uid)
    return st.state.value if st else None


def _age_s(m: dict[str, Any]) -> float:
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(m["at"])).total_seconds()
    except (KeyError, ValueError):
        return float("inf")


def is_busy(sv: UserServices, uid: UUID, pend: dict[str, Any] | None) -> bool:
    """Scout is busy while the last question's job is queued or running. A question that has
    no job yet is busy only for a short time (the job is submitted a moment later); after
    STALE_S with no job, or with a job the queue no longer knows, it is not busy, so the
    session cannot be stuck."""
    if pend is None:
        return False
    state = _job_state(sv, uid, pend)
    if state in LIVE:
        return True
    return state is None and _age_s(pend) < STALE_S


def view(sv: UserServices, uid: UUID, sid: UUID, doc: ScoutSessionDoc,
         audience: str) -> dict[str, Any]:
    """The session as JSON. `exchanges` keeps the shape the old Scout view had, so the existing
    screen still reads it; `messages` and the new keys carry the grounded answers."""
    ex = session.exchanges(doc)
    pend = session.pending(doc)
    state = _job_state(sv, uid, pend)
    busy = is_busy(sv, uid, pend)
    error = None
    if pend is not None and not busy:
        stopped = state == JobState.CANCELLED.value
        error = None if stopped else "Scout stopped before it could answer. Ask again."
        for x in ex:
            if x["id"] == pend["id"]:
                x |= {"status": "stopped" if stopped else "failed", "by_user": stopped,
                      "errors": [error] if error else []}
    return {
        "id": str(sid), "brief_id": doc.brief_id, "audience": audience,
        "status": "running" if busy else ("failed" if error else "done"),
        "busy": busy, "error": error, "model": spec_for_role("scout"), "policy": "cloud",
        "tokens": 0, "usd": 0.0, "exchanges": ex, "messages": doc.messages,
        "buttons": btn.buttons(audience), "usage": usage_view(sv, uid),
        "scope": texts.SCOPE, "examples": list(texts.EXAMPLES),
    }


def normalise_note(d: dict[str, Any], record_ids: list[str]) -> dict[str, Any]:
    return {"office": {"name": d["office"], "url": d.get("office_page")}, "to": d.get("to", ""),
            "subject": d["subject"], "body": d["body"], "record_ids": record_ids,
            "sample": d.get("sample", False)}


def handoff_for(service: BriefService, brief_id: str, data: ScoutData
                ) -> Callable[[], dict[str, Any] | None]:
    """The code-written hand-off for the kept leads, as a callable the intent runs. The caller
    runs it with the brief's store set (the `scope` context in perch/api.py)."""
    def draft() -> dict[str, Any] | None:
        got = data.brief()
        if got is None:
            return None
        _, leads = got
        kept = [x for x in leads if x.status == "kept"]
        if data.audience == "student":
            from perch.scout.student_tools import facts_of, record_of, write_note

            for route in ("F", "S"):
                rows = [x for x in kept if x.route == route]
                if rows:
                    pairs = [(x, facts_of(record_of(service, x))) for x in rows]
                    return normalise_note(write_note(route, pairs), [x.record_id for x in rows])
            return None
        for office, route in (("research_development", "A"),
                              ("technology_commercialization", "B")):
            if any(x.route == route for x in kept):
                d = service.handoff(brief_id, office, use_model=False)
                if d is None:
                    return None
                ids = [x.record_id for x in kept if x.route == route]
                return {"office": {"key": d.office.key, "name": d.office.name,
                                   "url": d.office.url}, "to": "", "subject": d.subject,
                        "body": d.body, "record_ids": ids, "sample": False}
        return None

    return draft


def _no_model(role: str) -> Provider:
    raise RuntimeError(f"a button never calls a model ({role})")


def audience_of(brief: Brief) -> str:
    return "student" if brief.options.get("student") else "researcher"


def start_session(sv: UserServices, uid: UUID, audience: str, brief_id: str | None) -> UUID:
    return session.create(sv.ud, uid, audience, brief_id)  # type: ignore[arg-type]


def ask(sv: UserServices, service: BriefService, uid: UUID, sid: UUID, *,
        question: str | None = None,
        intent: str | None = None) -> None:
    """Add one user message to the session and answer it (a button, here) or queue it."""
    got = session.load(sv.ud, uid, sid)
    if got is None:
        raise HTTPException(404, {"error": "not_found"})
    doc, _, audience = got
    pend = session.pending(doc)
    if is_busy(sv, uid, pend):
        raise HTTPException(409, "Scout is still working on the last question.")
    if intent:
        if intent not in btn.INTENTS:
            raise HTTPException(422, "Unknown button.")
        data = account_data(sv.ud, uid, audience, service, doc.brief_id)
        draft = handoff_for(service, doc.brief_id, data) if doc.brief_id else None
        deps = TurnDeps(data=data, provider_for=_no_model, meter=Meter(), handoff=draft)
        um = user_message(intent=intent)
        reply = run_turn(deps, doc.messages, intent=intent)
        reply["reply_to"] = um["id"]
        session.append(sv.ud, uid, sid, [um, reply])
        return
    q = (question or "").strip()
    if not q:
        raise HTTPException(422, "Ask Scout a question.")
    if texts.DISTRESS_RE.search(q):
        # Free and first: before the rate limit, the budget and any model. The reply is code-
        # written text with Temple's own services, so a user out of budget still gets it (S45 S1).
        if recent_distress(doc.messages):
            return  # the care text is already the last reply; no new rows (S45 S1)
        um = user_message(question=q)
        reply = message("assistant", "distress", texts.distress_message(audience),
                        gate="keyword", reply_to=um["id"])
        session.append(sv.ud, uid, sid, [um, reply])
        return
    from perch.user.quota import RateLimited

    try:
        quota.admit(sv.redis, sv.pool, uid, "submit_job")
    except RateLimited as e:
        raise HTTPException(429, {"error": "rate_limited"},
                            headers={"Retry-After": str(e.retry_after)}) from None
    except QuotaExceeded:
        raise HTTPException(429, {"error": "quota_exceeded", "message": texts.BUDGET,
                                  "usage": usage_view(sv, uid)}) from None
    um = user_message(question=q)
    session.append(sv.ud, uid, sid, [um])
    key = hashlib.sha256(f"scout|{uid}|{um['id']}".encode()).hexdigest()
    job = sv.runner.submit("scout_turn", {"session_id": str(sid), "message_id": um["id"]}, uid,
                           key, audience=audience)  # type: ignore[arg-type]
    session.set_job(sv.ud, uid, sid, um["id"], str(job))


DISTRESS_QUIET_SECONDS = 60


def recent_distress(messages: list[dict[str, Any]]) -> bool:
    """Was the last message a distress reply written under a minute ago? The free distress path
    skips the write then, so repeated crisis text cannot fill the session with rows."""
    if not messages or messages[-1].get("kind") != "distress":
        return False
    try:
        at = datetime.fromisoformat(str(messages[-1].get("at")))
    except ValueError:
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - at).total_seconds() < DISTRESS_QUIET_SECONDS


def stop(sv: UserServices, uid: UUID, sid: UUID) -> None:
    got = session.load(sv.ud, uid, sid)
    if got is None:
        raise HTTPException(404, {"error": "not_found"})
    pend = session.pending(got[0])
    if pend is not None and pend.get("job_id"):
        sv.runner.cancel(UUID(pend["job_id"]), uid)


def cover_submit(sv: UserServices, uid: UUID, audience: str, brief_id: str, record_id: str
                 ) -> dict[str, Any]:
    """Queue a `cover_points` job: ids only in the payload, one live job per brief and record."""
    from perch.jobs import PayloadError
    from perch.user.quota import RateLimited

    try:
        quota.admit(sv.redis, sv.pool, uid, "submit_job")
    except RateLimited as e:
        raise HTTPException(429, {"error": "rate_limited"},
                            headers={"Retry-After": str(e.retry_after)}) from None
    except QuotaExceeded:
        raise HTTPException(429, {"error": "quota_exceeded", "message": texts.BUDGET,
                                  "usage": usage_view(sv, uid)}) from None
    key = hashlib.sha256(f"cover|{uid}|{brief_id}|{record_id}".encode()).hexdigest()
    try:
        job = sv.runner.submit("cover_points", {"brief_id": brief_id, "record_id": record_id},
                               uid, key, audience=audience)  # type: ignore[arg-type]
    except PayloadError:
        raise HTTPException(422, "That record id cannot be used.") from None
    return {"job_id": str(job), "status": "queued",
            "poll": f"/briefs/{brief_id}/cover-points?record_id={record_id}&job_id={job}"}


COVER_NOTE = ("Points to put in your own words. Each pairs one thing the record asks for with "
              "one thing from your CV or entries. Check every point before you use it.")


def cover_get(sv: UserServices, uid: UUID, audience: str, brief_id: str, record_id: str,
              job_id: str | None) -> dict[str, Any]:
    """{"result": the stored set or null, "job": {"id", "state"} or null}."""
    from perch.user.models import CoverPointSet

    found = None
    for _, x in sv.ud.list(uid, "cover_points", audience, CoverPointSet, limit=100):  # type: ignore[arg-type]
        if x.brief_id == brief_id and x.record_id == record_id:
            found = x.model_dump(mode="json")
            found["note"] = COVER_NOTE
            break
    job = None
    if job_id:
        try:
            st = sv.runner.status(UUID(job_id), uid)
        except ValueError:
            st = None
        job = {"id": job_id, "state": st.state.value} if st else None
    return {"result": found, "job": job}


def sessions_for(sv: UserServices, uid: UUID, audience: str, brief_id: str) -> list[UUID]:
    rows = sv.ud.list(uid, "scout_session", audience, ScoutSessionDoc, limit=50)
    return [i for i, d in rows if d.brief_id == brief_id]


def delete(sv: UserServices, uid: UUID, sid: UUID) -> bool:
    try:
        return sv.ud.delete(uid, sid, kinds=("scout_session",))
    except NotFound:
        return False


__all__ = ["TERMINAL", "ask", "audience_of", "delete", "sessions_for", "start_session", "stop",
           "usage_view", "view"]

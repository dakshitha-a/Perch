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
from perch.scout.turn import Meter, TurnDeps, run_turn, user_message
from perch.user import quota
from perch.user.data import NotFound
from perch.user.models import ScoutSessionDoc

if TYPE_CHECKING:
    from perch.schemas import Brief
    from perch.service import BriefService
    from perch.user.routes import UserServices

LIVE = {"queued", "running"}


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


def view(sv: UserServices, uid: UUID, sid: UUID, doc: ScoutSessionDoc,
         audience: str) -> dict[str, Any]:
    """The session as JSON. `exchanges` keeps the shape the old Scout view had, so the existing
    screen still reads it; `messages` and the new keys carry the grounded answers."""
    ex = session.exchanges(doc)
    pend = session.pending(doc)
    state = _job_state(sv, uid, pend)
    busy = pend is not None and (state is None or state in LIVE)
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
    if pend is not None and (_job_state(sv, uid, pend) in LIVE | {None}):
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


def stop(sv: UserServices, uid: UUID, sid: UUID) -> None:
    got = session.load(sv.ud, uid, sid)
    if got is None:
        raise HTTPException(404, {"error": "not_found"})
    pend = session.pending(got[0])
    if pend is not None and pend.get("job_id"):
        sv.runner.cancel(UUID(pend["job_id"]), uid)


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

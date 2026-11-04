"""Scout history as one encrypted `user_data` row of kind `scout_session` (Phase 8).

All reads and writes go through perch/user/data.py. The row holds the messages; nothing about a
question or an answer is kept anywhere else. A turn appends a user message, then (later) the
assistant message that answers it, linked by `reply_to`. Whether Scout is busy is derived from
the row: the last user message has no reply yet.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg

from perch.user.data import Conflict, NotFound, UserData
from perch.user.models import Audience, ScoutSessionDoc

MAX_MESSAGES = 60
RETRIES = 5


def create(ud: UserData, uid: UUID, audience: Audience, brief_id: str | None) -> UUID:
    return ud.put(uid, "scout_session", audience,
                  ScoutSessionDoc(brief_id=brief_id, audience=audience))


def load(ud: UserData, uid: UUID, sid: UUID, *, conn: psycopg.Connection | None = None
         ) -> tuple[ScoutSessionDoc, Any, str] | None:
    """(session, updated_at, audience), or None for a missing or foreign id."""
    got = ud.get_row(uid, sid, ScoutSessionDoc, conn=conn)
    if got is None or got[2] != "scout_session":
        return None
    return got[0], got[1], got[3]


def append(ud: UserData, uid: UUID, sid: UUID, new: list[dict[str, Any]], *,
           conn: psycopg.Connection | None = None) -> ScoutSessionDoc:
    """Add messages to the session, retrying when another write got there first."""
    for _ in range(RETRIES):
        got = load(ud, uid, sid, conn=conn)
        if got is None:
            raise NotFound("no such session")
        doc, ts, _ = got
        doc.messages = [*doc.messages, *new][-MAX_MESSAGES:]
        try:
            ud.update(uid, sid, doc, expect_updated_at=ts, conn=conn)
            return doc
        except Conflict:
            continue
    raise Conflict("the session kept changing")


def replied(doc: ScoutSessionDoc, message_id: str) -> bool:
    return any(m.get("reply_to") == message_id for m in doc.messages)


def pending(doc: ScoutSessionDoc) -> dict[str, Any] | None:
    """The last user message when nothing answers it yet."""
    for m in reversed(doc.messages):
        if m["role"] == "assistant" and m.get("reply_to"):
            return None
        if m["role"] == "user":
            return None if replied(doc, m["id"]) else m
    return None


def _draft_card(xid: str, d: dict[str, Any]) -> dict[str, Any]:
    """The hand-off intent's note as a card, which is how the existing screen shows a draft."""
    o = d.get("office") or {}
    return {"id": f"{xid}:draft", "tool": "draft_note", "arguments": {}, "status": "done",
            "detail": "", "records": d.get("record_ids", []), "points": None, "where": "code",
            "provider": "", "draft": {"office": o.get("name"), "office_page": o.get("url"),
                                      "subject": d["subject"], "body": d["body"]}}


def exchanges(doc: ScoutSessionDoc) -> list[dict[str, Any]]:
    """The view the web app already reads: one entry per question, with its answer."""
    out: list[dict[str, Any]] = []
    for m in doc.messages:
        if m["role"] == "user":
            out.append({"id": m["id"], "question": m["text"], "kind": m["kind"],
                        "intent": m.get("intent"), "status": "running", "answer": None,
                        "answer_by": None, "flagged": False, "errors": [], "cards": [],
                        "message": None, "job_id": m.get("job_id")})
        elif out:
            x = next((e for e in reversed(out) if e["id"] == m.get("reply_to")), out[-1])
            code = m["kind"] in ("intent", "refusal", "distress", "budget", "error")
            x |= {"status": "failed" if m["kind"] == "error" else "done",
                  "answer": m["text"], "answer_by": "code" if code else "model",
                  "flagged": bool(m.get("flagged")),
                  "errors": [m["text"]] if m["kind"] == "error" else [],
                  "cards": [{"id": f"{x['id']}:{i}", "tool": t, "arguments": {},
                             "status": "done", "detail": "", "records": [], "draft": None,
                             "points": None, "where": "code", "provider": ""}
                            for i, t in enumerate(m.get("steps") or [])]
                           + ([_draft_card(x["id"], m["draft"])] if m.get("draft") else []),
                  "message": m}
    return out


def set_job(ud: UserData, uid: UUID, sid: UUID, message_id: str, job_id: str) -> None:
    """Record which job answers a message, so the view can read the job's state."""
    for _ in range(RETRIES):
        got = load(ud, uid, sid)
        if got is None:
            raise NotFound("no such session")
        doc, ts, _aud = got
        for m in doc.messages:
            if m["id"] == message_id:
                m["job_id"] = job_id
        try:
            ud.update(uid, sid, doc, expect_updated_at=ts)
            return
        except Conflict:
            continue
    raise Conflict("the session kept changing")

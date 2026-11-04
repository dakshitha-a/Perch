"""A signed-in user's CV, entries and documents, as encrypted `user_data` rows.

Contact details are blanked at parse time, so a stored text never holds them (section 2.2) and
no model ever sees them (standing rule 5). Nothing here logs text.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
from uuid import UUID

import psycopg

from perch.llm.contacts import blank_contacts
from perch.user.cv import parse_cv
from perch.user.data import UserData
from perch.user.inputs import KINDS, MAX_CHARS, InputError, clean, make_doc, parse_bytes
from perch.user.models import Audience, CvDoc, EntryDoc, UserDoc

MAX_ENTRIES = 50
MAX_TOTAL_CHARS = 200_000  # all docs, the CV and entries of one account and side
DOC_KINDS = ("cv", "proposal", "direction", "manuscript", "interests", "entry")


class LimitError(InputError):
    """The account holds as much as it may."""


def _facts(text: str) -> dict:
    f = parse_cv(text)
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v)
            for k, v in dataclasses.asdict(f).items()}


def read_text(kind: str, text: str | None, filename: str | None, data_b64: str | None) -> str:
    """The text of a paste or an upload (base64 in JSON). Raises InputError with a plain
    sentence that never quotes the input."""
    if kind not in DOC_KINDS:
        raise InputError(f"Unknown document kind: use one of {', '.join(DOC_KINDS)}.")
    if data_b64 is not None:
        try:
            raw = base64.b64decode(data_b64, validate=True)
        except binascii.Error as e:
            raise InputError("The file could not be read: choose it again.") from e
        text = parse_bytes(filename or "", raw)
    return text or ""


def _held_chars(ud: UserData, user_id: UUID, audience: Audience,
                conn: psycopg.Connection | None) -> int:
    n = 0
    for kind, cls in (("cv", CvDoc), ("doc", UserDoc), ("entry", EntryDoc)):
        for _, m in ud.list(user_id, kind, audience, cls, limit=200, conn=conn):  # type: ignore[arg-type]
            n += len(m.text if hasattr(m, "text") else (m.abstract or ""))
    return n


def add(ud: UserData, user_id: UUID, audience: Audience, kind: str, *, text: str | None = None,
        filename: str | None = None, data_b64: str | None = None, label: str | None = None,
        conn: psycopg.Connection | None = None) -> UUID:
    """Store one CV, entry or document; return the row id. A new CV, or a document of the
    same kind, replaces the old one."""
    body = clean(read_text(kind, text, filename, data_b64))
    if not body:
        raise InputError("That text is empty: paste some text first." if not filename
                         else "That file holds no text Perch can read.")
    if len(body) > MAX_CHARS:
        raise InputError(f"That text is longer than {MAX_CHARS:,} characters: shorten it, "
                         "then add it again.")
    body = blank_contacts(body)
    if _held_chars(ud, user_id, audience, conn) + len(body) > MAX_TOTAL_CHARS:
        raise LimitError(f"An account holds at most {MAX_TOTAL_CHARS:,} characters in all: "
                         "remove a document first.")
    if kind == "cv":
        return ud.put(user_id, "cv", audience,
                      CvDoc(text=body, filename=filename, facts=_facts(body)), conn=conn)
    if kind == "entry":
        if len(ud.list(user_id, "entry", audience, EntryDoc, limit=MAX_ENTRIES + 1,
                       conn=conn)) >= MAX_ENTRIES:
            raise LimitError(f"An account holds at most {MAX_ENTRIES} entries: remove one first.")
        return ud.put(user_id, "entry", audience,
                      EntryDoc(text=body, label=(label or "")[:120] or None), conn=conn)
    doc = make_doc(kind, body, filename, keep_name=True)
    for rid, old in ud.list(user_id, "doc", audience, UserDoc, limit=200, conn=conn):
        if old.id == doc.id:  # one document per kind and side
            ud.delete(user_id, rid, conn=conn)
    return ud.put(user_id, "doc", audience, doc, conn=conn)


def listing(ud: UserData, user_id: UUID, audience: Audience) -> list[dict]:
    """Labels and sizes, never the text."""
    out: list[dict] = []
    for rid, m in ud.list(user_id, "cv", audience, CvDoc, limit=1):
        out.append({"id": str(rid), "kind": "cv", "label": KINDS["cv"], "chars": len(m.text),
                    "name": m.filename})
    for rid, d in ud.list(user_id, "doc", audience, UserDoc, limit=50):
        out.append({"id": str(rid), "kind": d.id.split(":", 1)[1], "label": KINDS.get(
            d.id.split(":", 1)[1], d.title), "chars": len(d.abstract or ""), "name": d.filename})
    for rid, e in ud.list(user_id, "entry", audience, EntryDoc, limit=MAX_ENTRIES):
        out.append({"id": str(rid), "kind": "entry", "label": e.label or "Entry",
                    "chars": len(e.text), "name": None})
    return out


def remove(ud: UserData, user_id: UUID, row_id: UUID) -> bool:
    """Delete one CV, document or entry. Another kind of row (a brief) is not removed here."""
    return ud.delete(user_id, row_id, kinds=("cv", "doc", "entry"))


def owns_all(ud: UserData, user_id: UUID, ids: list[UUID]) -> bool:
    """True when every id is a CV, document or entry row of this user (rows only, no text)."""
    if not ids:
        return True
    from perch.store import pg

    with pg.user_tx(ud.pool, user_id) as c:
        n = c.execute("SELECT count(*) FROM user_data WHERE user_id = %s AND id = ANY(%s) "
                      "AND kind IN ('cv','doc','entry')", (user_id, list(ids))).fetchone()[0]
    return n == len(set(ids))

"""A signed-in user's optional citizenship and state of residence: one encrypted `profile` row
per user and side (S53). Read by the brief job; never shown to a model, never logged.
"""

from __future__ import annotations

from uuid import UUID

import psycopg

from perch.user.data import UserData
from perch.user.models import Audience, ProfileDoc


def read(ud: UserData, user_id: UUID, audience: Audience, *,
         conn: psycopg.Connection | None = None) -> ProfileDoc:
    """The stored picks, or an empty ProfileDoc."""
    rows = ud.list(user_id, "profile", audience, ProfileDoc, limit=1, conn=conn)
    return rows[0][1] if rows else ProfileDoc()


def save(ud: UserData, user_id: UUID, audience: Audience, doc: ProfileDoc, *,
         conn: psycopg.Connection | None = None) -> ProfileDoc:
    """Replace the side's picks. Two blank picks remove the row: nothing is kept for nothing."""
    for rid, _ in ud.list(user_id, "profile", audience, ProfileDoc, limit=5, conn=conn):
        ud.delete(user_id, rid, kinds=("profile",), conn=conn)
    if doc.citizenship is not None or doc.residency_state is not None:
        ud.put(user_id, "profile", audience, doc, conn=conn)
    return doc

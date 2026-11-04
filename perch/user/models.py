"""Blob models of `user_data` (ARCHITECTURE_V1 section 2.2). One pydantic model per kind.

SYNTHETIC text only in tests. `extra="forbid"` keeps a blob from drifting. Errors on a decrypted
blob are reduced to a fixed message in perch/user/data.py, so a value is never echoed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from perch.schemas import Brief, Lead, utcnow
from perch.user.inputs import UserDoc

UserKind = Literal["cv", "entry", "doc", "brief", "saved_item", "handoff", "cover_points",
                   "scout_session"]
Audience = Literal["researcher", "student"]
USER_KINDS: tuple[str, ...] = ("cv", "entry", "doc", "brief", "saved_item", "handoff",
                               "cover_points", "scout_session")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CvDoc(_M):
    """Parsed CV facts and cleaned text. Contact details are blanked before this is built."""

    text: str
    filename: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)  # perch.user.cv.CVFacts as a dict
    created_at: datetime = Field(default_factory=utcnow)


class EntryDoc(_M):
    """One achievement or note the user typed."""

    text: str
    label: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class StoredBrief(_M):
    """The Brief and its Lead list, including lead status and explanation text."""

    brief: Brief
    leads: list[Lead] = Field(default_factory=list)


class SavedItem(_M):
    record_id: str
    note: str | None = None
    saved_at: datetime = Field(default_factory=utcnow)


class HandoffDraft(_M):
    brief_id: str
    office: str
    draft: dict[str, Any]


class CoverPointSet(_M):
    """The cover points for one record of one brief (S45), stored encrypted. `points` are
    {asks, asks_ids, you, you_ids}; every id is a record id the model was given."""

    brief_id: str
    record_id: str
    points: list[dict[str, Any]] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)  # layer 2 flags: shown flagged
    sources: dict[str, str] = Field(default_factory=dict)  # id -> title
    title: str = ""
    sample: bool = False
    status: Literal["done", "withheld"] = "done"  # withheld: failed the check twice
    created_at: datetime = Field(default_factory=utcnow)


class ScoutSessionDoc(_M):
    """One Scout conversation (Phase 8). Messages are `{id, role, kind, text, at, ...}`: a user
    message holds the question or the button intent; an assistant message holds the answer and
    its checks (perch/scout/turn.py). It is the only place the history lives, encrypted."""

    brief_id: str | None = None
    audience: Audience | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)


MODEL_FOR_KIND: dict[str, type[BaseModel]] = {
    "cv": CvDoc, "entry": EntryDoc, "doc": UserDoc, "brief": StoredBrief,
    "saved_item": SavedItem, "handoff": HandoffDraft, "cover_points": CoverPointSet,
    "scout_session": ScoutSessionDoc,
}

__all__ = ["Audience", "CoverPointSet", "CvDoc", "EntryDoc", "HandoffDraft", "MODEL_FOR_KIND",
           "SavedItem", "ScoutSessionDoc", "StoredBrief", "USER_KINDS", "UserDoc", "UserKind"]

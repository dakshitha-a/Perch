"""Blob models of `user_data` (ARCHITECTURE_V1 section 2.2). One pydantic model per kind.

SYNTHETIC text only in tests. `extra="forbid"` keeps a blob from drifting. Errors on a decrypted
blob are reduced to a fixed message in perch/user/data.py, so a value is never echoed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from perch.citizenship import CITIZENSHIP_VALUES, STATE_CODES
from perch.schemas import Brief, Lead, utcnow
from perch.user.inputs import UserDoc

UserKind = Literal["cv", "entry", "doc", "brief", "saved_item", "handoff", "cover_points",
                   "scout_session", "profile"]
Audience = Literal["researcher", "student"]
USER_KINDS: tuple[str, ...] = ("cv", "entry", "doc", "brief", "saved_item", "handoff",
                               "cover_points", "scout_session", "profile")


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
    """The newest hand-off draft for one office of one brief (S48 S3), stored encrypted: its
    opening paragraph may cite the user's own documents. Nothing is sent."""

    brief_id: str
    office: str
    draft: dict[str, Any]
    created_at: datetime = Field(default_factory=utcnow)


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


class ProfileDoc(_M):
    """The optional picks that let Perch compare a listing's own rule with the user: a
    citizenship status and a state of residence (S53). Either may be null. Stored encrypted;
    never shown to a model (standing rule 5) and never logged."""

    citizenship: Literal[CITIZENSHIP_VALUES] | None = None  # type: ignore[valid-type]
    residency_state: Literal[STATE_CODES] | None = None  # type: ignore[valid-type]


MODEL_FOR_KIND: dict[str, type[BaseModel]] = {
    "cv": CvDoc, "entry": EntryDoc, "doc": UserDoc, "brief": StoredBrief,
    "saved_item": SavedItem, "handoff": HandoffDraft, "cover_points": CoverPointSet,
    "scout_session": ScoutSessionDoc, "profile": ProfileDoc,
}

__all__ = ["Audience", "CoverPointSet", "CvDoc", "EntryDoc", "HandoffDraft", "MODEL_FOR_KIND",
           "ProfileDoc", "SavedItem", "ScoutSessionDoc", "StoredBrief", "USER_KINDS", "UserDoc",
           "UserKind"]

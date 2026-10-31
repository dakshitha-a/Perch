"""Request bodies shared by the stored-brief API (perch.api) and the session routes
(perch.private.routes). One definition each (review W15); the session routes add only
what differs."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class ScoutRequest(BaseModel):
    question: str = Field("", max_length=1000)


class HandoffRequest(BaseModel):
    office: Literal["research_development", "technology_commercialization"]
    lead_ids: list[str] = Field(default_factory=list, max_length=25)


class BriefOptions(BaseModel):
    """What a brief is asked for, apart from whose it is."""

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

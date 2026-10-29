"""Record schemas. Every record carries provenance: source, source_url, fetched_at.

Numbers and dates are typed fields copied from the source record by a fetcher
(standing rule 3). Nothing here is filled in by a model.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class Record(BaseModel):
    """Base for everything the store holds."""

    model_config = ConfigDict(extra="forbid")

    kind: ClassVar[str] = "record"

    id: str = Field(min_length=1, description="Stable id, e.g. an OpenAlex URL or award number")
    source: str = Field(min_length=1, description="Short source name, e.g. 'openalex'")
    source_url: str = Field(min_length=1, description="URL of the exact record fetched")
    fetched_at: datetime = Field(description="When the record was fetched (UTC)")

    @field_validator("fetched_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware")
        return v.astimezone(UTC)


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    score: float | None = None


class Researcher(Record):
    kind: ClassVar[str] = "researcher"

    display_name: str
    orcid: str | None = None
    institutions: list[str] = Field(default_factory=list, description="Last known institutions")
    works_count: int | None = None
    cited_by_count: int | None = None
    topics: list[Topic] = Field(default_factory=list)


class Work(Record):
    kind: ClassVar[str] = "work"

    title: str
    publication_year: int | None = None
    publication_date: date | None = None
    venue: str | None = None
    doi: str | None = None
    type: str | None = None
    abstract: str | None = None
    author_ids: list[str] = Field(default_factory=list)
    institution_ids: list[str] = Field(default_factory=list)
    topics: list[Topic] = Field(default_factory=list)
    referenced_works: list[str] = Field(default_factory=list)
    cited_by_count: int | None = None


class Award(Record):
    kind: ClassVar[str] = "award"

    agency: str
    award_number: str
    title: str
    pi_names: list[str] = Field(default_factory=list)
    institution: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    amount: float | None = Field(default=None, description="As the source states it")
    amount_basis: str | None = Field(
        default=None, description="What amount means, e.g. 'fiscal year' or 'estimated total'"
    )
    fiscal_year: int | None = None
    activity_code: str | None = None
    opportunity_number: str | None = Field(
        default=None, description="Funding opportunity the award was made under"
    )


class Opportunity(Record):
    kind: ClassVar[str] = "opportunity"

    opportunity_number: str
    title: str
    agency: str
    open_date: date | None = None
    close_date: date | None = None
    award_ceiling: float | None = None
    award_floor: float | None = None
    eligible_applicants: list[str] = Field(default_factory=list)
    eligibility_notes: str | None = None
    activity_code: str | None = None
    description: str | None = None
    status: str | None = Field(default=None, description="As listed: forecasted, posted, ...")
    archive_date: date | None = None
    assistance_listings: list[str] = Field(default_factory=list, description="CFDA / ALN")
    funding_instruments: list[str] = Field(default_factory=list)


class Organisation(Record):
    kind: ClassVar[str] = "organisation"

    name: str
    type: str | None = Field(default=None, description="Type as the source labels it")
    country: str | None = None


class Lead(Record):
    """A route to funding for one brief. Provenance is the record it points at."""

    kind: ClassVar[str] = "lead"

    brief_id: str
    route: Literal["A", "B"]
    record_id: str = Field(description="Opportunity (route A) or Organisation (route B) id")
    rank: int | None = None
    rerank_score: float | None = None
    matched_thread: int | None = None
    fit_score: float | None = None
    explanation: str | None = Field(default=None, description="Factual sentences, validated")
    inference: str | None = Field(default=None, description="Link sentence, shown as inference")
    unsupported: list[str] = Field(default_factory=list, description="Validator layer 2 flags")
    cited_ids: list[str] = Field(default_factory=list)
    status: Literal["new", "kept", "dismissed"] = "new"
    flagged: bool = Field(default=False, description="Explanation withheld after two failures")
    inferred: bool = Field(default=False, description="Route B leads are inferences, never facts")


class Stage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["pending", "running", "done", "skipped", "failed"] = "pending"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    detail: str | None = None


class Brief(Record):
    """One run of the pipeline for one researcher. source is 'perch'."""

    kind: ClassVar[str] = "brief"

    researcher_id: str
    created_at: datetime = Field(default_factory=utcnow)
    status: Literal["queued", "running", "done", "failed"] = "queued"
    stages: list[Stage] = Field(default_factory=list)
    error: str | None = None
    options: dict = Field(default_factory=dict, description="as_of, top, explain, constraints")
    work_ids: list[str] = Field(default_factory=list)
    award_ids: list[str] = Field(default_factory=list)
    lead_ids: list[str] = Field(default_factory=list)
    award_horizon: date | None = Field(default=None, description="End date of last public award")
    threads: list[dict] = Field(default_factory=list, description="index, label, weight, work_ids")
    topics: list[str] = Field(default_factory=list)
    summary: str | None = None
    timings_ms: dict[str, float] = Field(default_factory=dict)


RECORD_TYPES: tuple[type[Record], ...] = (
    Researcher, Work, Award, Opportunity, Organisation, Lead, Brief,
)

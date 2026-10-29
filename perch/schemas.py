"""Record schemas. Every record carries provenance: source, source_url, fetched_at.

Numbers and dates are typed fields copied from the source record by a fetcher
(standing rule 3). Nothing here is filled in by a model.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    aliases: list[str] = Field(
        default_factory=list,
        description="Names as each source wrote them, merged into this organisation (Route B)",
    )
    institution_ids: list[str] = Field(
        default_factory=list, description="OpenAlex institution ids merged into this one"
    )


class Signal(BaseModel):
    """One public signal behind a Route B lead. Counts and dates are computed by code
    from the records in record_ids; nothing here comes from a model."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["citing_works", "sbir_sttr", "topic_works"]
    record_ids: list[str] = Field(default_factory=list, description="Evidence records")
    count: int = 0
    latest: date | None = Field(default=None, description="Newest record date, copied")
    score: float = 0.0


class Lead(Record):
    """A route to funding for one brief. Provenance is the record it points at."""

    kind: ClassVar[str] = "lead"

    brief_id: str
    route: Literal["A", "B", "F", "S"] = Field(
        description="A grants, B industry; student mode: F fellowships, S scholarships")
    record_id: str = Field(description="Opportunity (A, F), Organisation (B) or Scholarship "
                                       "(F, S) id")
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
    signals: list[Signal] = Field(default_factory=list, description="Route B only")
    relationship: str | None = Field(default=None, description="Route B: suggested type, by rule")
    confidence: str | None = Field(default=None, description="Route B: label from signal count")
    notes: list[str] = Field(default_factory=list,
                             description="Rule notes written by code, e.g. a career-stage unlock")
    # Student mode (S18): eligibility by rule and the gap list, written by code.
    verdict: Literal["eligible", "may be eligible", "not eligible"] | None = None
    verdict_reason: str | None = None
    verdict_lines: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list, description="Requirements the CV lacks")
    gap_keys: list[str] = Field(default_factory=list)
    sample: bool = Field(default=False, description="Points at a SYNTHETIC sample record")


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


class Change(BaseModel):
    """One thing that changed since the last monitoring run. before and after are copied
    from record fields by code (an ISO date, or None); nothing here comes from a model."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["award_ending", "new_lead", "dropped_lead", "close_date", "new_industry_lead"]
    record_id: str
    title: str
    source_url: str
    before: str | None = None
    after: str | None = None
    trigger: bool = Field(default=False, description="Counts toward drafting an email")


class Digest(Record):
    """One monitoring run for one researcher (S16). source is 'perch'."""

    kind: ClassVar[str] = "digest"

    researcher_id: str
    brief_id: str
    baseline_brief_id: str | None = Field(default=None, description="The last run's brief")
    as_of: date
    changes: list[Change] = Field(default_factory=list)
    snapshot: list[dict] = Field(default_factory=list,
                                 description="Route A leads: record_id, rank, close_date")
    draft_subject: str | None = Field(default=None, description="None: nothing fired")
    draft_body: str | None = None
    refresh: dict = Field(default_factory=dict, description="Grants.gov refresh counts")


Level = Literal["high school", "associate", "bachelor's", "graduate", "professional"]
Requirement = Literal["transcript", "essay", "letters", "portfolio", "interview", "FAFSA"]


class ScholarshipEligibility(BaseModel):
    """Who may apply, as the record states it. None means the record does not say."""

    model_config = ConfigDict(extra="forbid")

    gpa_min: float | None = None
    residency_state: str | None = Field(default=None, description="Two-letter state code")
    citizenship: str | None = Field(default=None, description="As written, e.g. 'U.S. citizen'")
    class_year: list[int] = Field(default_factory=list,
                                  description="Undergraduate years 1 to 4; empty means any")
    major: list[str] = Field(default_factory=list, description="Empty means any major")
    enrolment_status: Literal["full-time", "part-time", "any"] | None = None
    graduation_by: date | None = Field(default=None,
                                       description="Must graduate on or before this date")
    graduation_after: date | None = Field(default=None,
                                          description="Must graduate on or after this date")
    targeted_criterion: str | None = Field(
        default=None, description="Free text the student judges for themselves; never asked")
    notes: str | None = Field(default=None, description="Eligibility text copied from a page")


class ScholarshipRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: bool = False
    essay: bool = False
    letters_count: int = 0
    portfolio: bool = False
    interview: bool = False
    fafsa: bool = False

    def items(self) -> list[str]:
        """Each requirement as one line, in a fixed order. Written by code."""
        out = []
        if self.transcript:
            out.append("transcript")
        if self.essay:
            out.append("essay")
        if self.letters_count:
            n = self.letters_count
            out.append(f"{n} letter{'s' if n > 1 else ''} of recommendation")
        if self.portfolio:
            out.append("portfolio")
        if self.interview:
            out.append("interview")
        if self.fafsa:
            out.append("FAFSA")
        return out


class Scholarship(Record):
    """A scholarship, fellowship, grant or prize for a student (S17).

    Two kinds live under this type and never mix in a list (standing rule 11):
    public records copied from a public page (source e.g. 'temple_sdfa'), and synthetic
    sample records (source 'synthetic', id 'sample:sch-NNNN'), kept in their own store.
    """

    kind: ClassVar[str] = "scholarship"

    name: str
    sponsor: str | None = None
    purpose: str | None = None
    level_of_study: list[Level] = Field(default_factory=list, description="Empty: not stated")
    field_of_study: list[str] = Field(default_factory=list, description="Empty: any field")
    award_type: Literal["scholarship", "fellowship", "grant", "prize"] | None = None
    amount_min: float | None = None
    amount_max: float | None = None
    deadline: date | None = None
    eligibility: ScholarshipEligibility = Field(default_factory=ScholarshipEligibility)
    application_requirements: ScholarshipRequirements | None = Field(
        default=None, description="None: the record does not list them")
    international_ok: bool | None = Field(default=None, description="None: not stated")
    canary: str | None = Field(default=None, description="Synthetic records only")

    @property
    def synthetic(self) -> bool:
        return self.source == "synthetic"

    @model_validator(mode="after")
    def _consistent(self) -> Scholarship:
        if self.source == "synthetic" and not (self.id.startswith("sample:") and self.canary):
            raise ValueError("a synthetic record needs a sample: id and a canary")
        if self.id.startswith("sample:") and self.source != "synthetic":
            raise ValueError("sample: ids are for synthetic records only")
        if (self.amount_min is not None and self.amount_max is not None
                and self.amount_min > self.amount_max):
            raise ValueError("amount_min is above amount_max")
        return self


RECORD_TYPES: tuple[type[Record], ...] = (
    Researcher, Work, Award, Opportunity, Organisation, Lead, Brief, Digest, Scholarship,
)

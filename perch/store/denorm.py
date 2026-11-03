"""Filter columns derived from a record's own fields (ARCHITECTURE_V1 section 2.2).

Code fills these, never a model. Used by both repositories so browse filters agree.
Fields that arrive in Phase 4 (scope, schools, temple_funded) are read with getattr and
default to the external values until the schemas carry them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from perch.schemas import Record

STORED_KINDS = ("researcher", "work", "award", "opportunity", "organisation", "scholarship")


@dataclass(frozen=True)
class Columns:
    scope: str = "external"
    schools: list[str] = field(default_factory=list)
    temple_funded: bool = False
    audience_level: list[str] = field(default_factory=list)
    deadline: date | None = None
    amount_max: float | None = None
    status: str | None = None


def columns(r: Record) -> Columns:
    scope = getattr(r, "scope", None) or "external"
    schools = sorted({s for s in (getattr(r, "schools", None) or []) if s})
    if scope == "school" and not schools:
        scope = "external"  # the CHECK forbids school with an empty list
    if scope != "school":
        schools = []
    kind = r.kind
    return Columns(
        scope=scope,
        schools=schools,
        temple_funded=bool(getattr(r, "temple_funded", False)),
        audience_level=(list(getattr(r, "level_of_study", []) or [])
                        if kind == "scholarship" else []),
        deadline=(getattr(r, "close_date", None) if kind == "opportunity"
                  else getattr(r, "deadline", None) if kind == "scholarship" else None),
        amount_max=(getattr(r, "award_ceiling", None) if kind == "opportunity"
                    else getattr(r, "amount_max", None) if kind == "scholarship" else None),
        status=getattr(r, "status", None) if kind == "opportunity" else None,
    )


def matches_text(r: Record, q: str) -> bool:
    """Case-insensitive substring over the record's title, name, purpose and description."""
    text = " ".join(str(v) for v in
                    (getattr(r, a, None) for a in ("title", "name", "purpose", "description"))
                    if v)
    return q.lower() in text.lower()


# The same four fields, as a SQL expression over records.data, for Postgres ILIKE.
TEXT_SQL = ("concat_ws(' ', data->>'title', data->>'name', data->>'purpose', "
            "data->>'description')")

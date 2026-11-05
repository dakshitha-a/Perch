"""Filter columns derived from a record's own fields (ARCHITECTURE_V1 section 2.2).

Code fills these, never a model. Used by both repositories so browse filters agree.
Fields that arrive in Phase 4 (scope, schools, temple_funded) are read with getattr and
default to the external values until the schemas carry them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from perch.schemas import Record

# "Temple only" means listed on a Temple page (S43 fork F1): the record's own source decides.
TEMPLE_SOURCES = ("temple_pages", "temple_sdfa")

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


# A scholarship's level_of_study in the page-level words, so one level filter finds both
# ("bachelor's" on 44 SDFA records was missed by "undergraduate", S49 S8).
LEVEL_WORDS = {"bachelor's": "undergraduate", "associate": "undergraduate",
               "graduate": "graduate", "professional": "graduate"}


def _audience(r: Record, kind: str) -> list[str]:
    """The page-level audience when Phase 4 set it, else the scholarship's levels."""
    level = getattr(r, "audience_level", None)
    if level:
        return [level]
    if kind != "scholarship":
        return []
    levels = getattr(r, "level_of_study", []) or []
    return list(dict.fromkeys(LEVEL_WORDS.get(x, x) for x in levels))


def columns(r: Record) -> Columns:
    schools = sorted({s for s in (getattr(r, "schools", None) or []) if s})
    # A Temple-page record with no stated scope stays inside Temple as "unstated" (fork F2);
    # any other record without one is external. Schools are kept whatever the scope.
    fallback = "unstated" if r.source in TEMPLE_SOURCES else "external"
    scope = getattr(r, "scope", None) or fallback
    if scope == "school" and not schools:
        scope = fallback  # a school scope with no school named is not a stated scope
    kind = r.kind
    return Columns(
        scope=scope,
        schools=schools,
        temple_funded=bool(getattr(r, "temple_funded", False)),
        audience_level=_audience(r, kind),
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

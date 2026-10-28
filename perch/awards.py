"""Link public awards to a researcher, and compute the public award horizon.

Linking is by name: same last name, and the same first name or a matching first
initial. data/overrides/award_links.csv corrects it by hand, one row per fix:

  kind            value                 effect
  query_name      First Last            name to search award sources with (repeatable)
  include_award   <source>:<number>     link this award even if the name does not match
  exclude_award   <source>:<number>     never link this award

The horizon is the latest end date across linked award records. Nothing about lab
finances is inferred from it.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from perch.schemas import Award, Researcher

OVERRIDES = Path("data/overrides/award_links.csv")
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "md", "phd"}


def name_parts(name: str) -> tuple[str, str]:
    """(first, last), lowercased, without accents, punctuation or suffixes."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    tokens = [t for t in re.split(r"[^a-z]+", text.lower()) if t and t not in SUFFIXES]
    if not tokens:
        return "", ""
    return tokens[0], tokens[-1]


def search_name(name: str) -> tuple[str, str]:
    """(First, Last) for querying award sources: accents and initials dropped, case kept."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    tokens = [t for t in re.split(r"[^A-Za-z'-]+", text) if t and t.lower() not in SUFFIXES]
    return (tokens[0], tokens[-1]) if tokens else ("", "")


def same_person(a: str, b: str) -> bool:
    fa, la = name_parts(a)
    fb, lb = name_parts(b)
    if not la or la != lb:
        return False
    if len(fa) == 1 or len(fb) == 1:
        return fa[:1] == fb[:1]
    return fa == fb


@dataclass
class Overrides:
    query_names: list[str] = field(default_factory=list)
    include: set[str] = field(default_factory=set)
    exclude: set[str] = field(default_factory=set)


def load_overrides(author_id: str, path: Path = OVERRIDES) -> Overrides:
    out = Overrides()
    if not path.is_file():
        return out
    short = author_id.rstrip("/").rsplit("/", 1)[-1]
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["author_id"].rstrip("/").rsplit("/", 1)[-1] != short:
                continue
            value = row["value"].strip()
            if row["kind"] == "query_name":
                out.query_names.append(value)
            elif row["kind"] == "include_award":
                out.include.add(value)
            elif row["kind"] == "exclude_award":
                out.exclude.add(value)
    return out


def award_key(a: Award) -> str:
    return f"{a.source}:{a.award_number}"


def query_names(r: Researcher, ov: Overrides) -> list[str]:
    return ov.query_names or [r.display_name]


def link_awards(r: Researcher, awards: Iterable[Award], ov: Overrides) -> list[Award]:
    """Award records (every fiscal year) that belong to the researcher."""
    names = [r.display_name, *ov.query_names]
    out = []
    for a in awards:
        key = award_key(a)
        if key in ov.exclude:
            continue
        if key in ov.include or any(same_person(n, pi) for n in names for pi in a.pi_names):
            out.append(a)
    return out


@dataclass
class AwardSummary:
    """One award across its fiscal-year records. Every field is copied from a record."""

    key: str
    source: str
    award_number: str
    title: str
    agency: str
    activity_code: str | None
    start_date: date | None
    end_date: date | None
    end_record: Award | None
    opportunity_numbers: list[str]
    records: list[Award]


def summarise(records: Iterable[Award]) -> list[AwardSummary]:
    groups: dict[str, list[Award]] = {}
    for a in records:
        groups.setdefault(award_key(a), []).append(a)
    out = []
    for key, recs in groups.items():
        recs.sort(key=lambda a: (a.fiscal_year or 0, a.id), reverse=True)
        latest = recs[0]
        starts = [a.start_date for a in recs if a.start_date]
        ended = [a for a in recs if a.end_date]
        end_rec = max(ended, key=lambda a: (a.end_date, a.fiscal_year or 0)) if ended else None
        out.append(AwardSummary(
            key=key, source=latest.source, award_number=latest.award_number,
            title=latest.title, agency=latest.agency, activity_code=latest.activity_code,
            start_date=min(starts) if starts else None,
            end_date=end_rec.end_date if end_rec else None, end_record=end_rec,
            opportunity_numbers=sorted({a.opportunity_number for a in recs
                                        if a.opportunity_number}),
            records=recs,
        ))
    out.sort(key=lambda s: (s.end_date or date.min, s.key), reverse=True)
    return out


def award_horizon(summaries: list[AwardSummary]) -> AwardSummary | None:
    """The award whose latest record ends last, or None if no award has an end date."""
    dated = [s for s in summaries if s.end_date]
    return max(dated, key=lambda s: (s.end_date, s.key)) if dated else None

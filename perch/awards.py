"""Link public awards to a researcher, and compute the public award horizon.

Linking is by name: same last name, and the same first name or a matching first
initial. When that links nothing, Perch searches by last name alone and links records
whose first initial matches; such awards are labelled "matched by initial" (S27, Q38).
data/overrides/award_links.csv corrects it by hand, one row per fix:

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
from typing import TYPE_CHECKING

from perch.schemas import Award, Researcher

if TYPE_CHECKING:
    from perch.sources.nih_reporter import NIHReporterClient
    from perch.sources.nsf import NSFClient

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


def same_person(a: str, b: str, by_initial: bool = False) -> bool:
    """Same last name and same first name; a one-letter first name, or `by_initial`,
    needs only the first initial to match."""
    fa, la = name_parts(a)
    fb, lb = name_parts(b)
    if not la or la != lb:
        return False
    if by_initial or len(fa) == 1 or len(fb) == 1:
        return fa[:1] == fb[:1]
    return fa == fb


def full_match(a: str, b: str) -> bool:
    fa, la = name_parts(a)
    fb, lb = name_parts(b)
    return bool(la) and la == lb and len(fa) > 1 and fa == fb


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


def link_awards(r: Researcher, awards: Iterable[Award], ov: Overrides,
                by_initial: bool = False) -> list[Award]:
    """Award records (every fiscal year) that belong to the researcher."""
    names = [r.display_name, *ov.query_names]
    out = []
    for a in awards:
        key = award_key(a)
        if key in ov.exclude:
            continue
        if key in ov.include or any(same_person(n, pi, by_initial)
                                    for n in names for pi in a.pi_names):
            out.append(a)
    return out


def by_initial_only(r: Researcher, a: Award, ov: Overrides) -> bool:
    """Linked on a first initial alone: no full first-name match and no hand override."""
    if award_key(a) in ov.include or ov.query_names:
        return False
    return not any(full_match(r.display_name, pi) for pi in a.pi_names)


def fallback_needed(linked: list[Award], ov: Overrides) -> bool:
    """Search by last name only when the full-name search linked nothing and no hand
    override names the person."""
    return not linked and not ov.query_names


def link_stored(r: Researcher, awards: list[Award], ov: Overrides) -> list[Award]:
    """Link stored records: by name, then by first initial if that finds nothing."""
    linked = link_awards(r, awards, ov)
    return link_awards(r, awards, ov, by_initial=True) if fallback_needed(linked, ov) else linked


def fetch_and_link(r: Researcher, ov: Overrides, nih: NIHReporterClient, nsf: NSFClient
                   ) -> tuple[list[Award], list[Award]]:
    """(fetched, linked) from RePORTER and NSF: full names first, then last name only."""
    fetched: list[Award] = []
    for name in query_names(r, ov):
        first, last = search_name(name)
        fetched += nih.awards_for_pi(first, last)
        fetched += nsf.awards_for_pi(f"{first} {last}")
    linked = link_awards(r, fetched, ov)
    if fallback_needed(linked, ov):
        last = search_name(r.display_name)[1]
        if last:
            fetched += nih.awards_for_pi("", last)
            fetched += nsf.awards_for_pi(last)
            linked = link_awards(r, fetched, ov, by_initial=True)
    return fetched, linked


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
    matched_by_initial: bool = False  # see by_initial_only; the Profile tab says so


def summarise(records: Iterable[Award], r: Researcher | None = None,
              ov: Overrides | None = None) -> list[AwardSummary]:
    """`r` and `ov` mark awards linked on a first initial alone."""
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
            matched_by_initial=bool(r) and all(by_initial_only(r, a, ov or Overrides())
                                               for a in recs),
        ))
    out.sort(key=lambda s: (s.end_date or date.min, s.key), reverse=True)
    return out


def award_horizon(summaries: list[AwardSummary]) -> AwardSummary | None:
    """The award whose latest record ends last, or None if no award has an end date."""
    dated = [s for s in summaries if s.end_date]
    return max(dated, key=lambda s: (s.end_date, s.key)) if dated else None

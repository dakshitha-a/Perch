"""CSV and JSON file importers: one row per award, columns mapped to record fields.

Column to field table (the column name is the field name; lists are `;`-separated in CSV
and may be real lists in JSON; an empty cell means "not stated" and is left out):

Scholarship (kind="scholarship", the default)
  required   source_url, name
  optional   id, source, fetched_at (ISO 8601 with a zone; default: the time of the read),
             sponsor, purpose, award_type (scholarship|fellowship|grant|prize),
             amount_min, amount_max (numbers), deadline (YYYY-MM-DD),
             deadline_quote, amount_quote, details_url, details_fetched_at,
             level_of_study, field_of_study (lists), international_ok (true|false)
Opportunity (kind="opportunity")
  required   source_url, title, agency
  optional   id, source, fetched_at, opportunity_number (default: the id),
             award_floor, award_ceiling, open_date, close_date, close_date_note,
             description, eligibility_notes, deadline_quote, amount_quote, details_url,
             details_fetched_at
Both kinds also take: page_owner, scope (temple_wide|school|external), schools (list),
temple_funded (true|false), audience_level (undergraduate|graduate|faculty|postdoc|mixed),
apply_url.

Rules. A row without a source_url is rejected (rule 4). A row whose id starts with "sample:"
or whose source is "synthetic" is rejected: samples are never imported (rule 11). A row that
fails the record's own validation is rejected with the reason. Columns not in the table are
ignored and listed in `ignored_columns`. `source` defaults to the importer's `source` (feed).
Nothing is computed: a value is copied from the cell.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from perch.schemas import Opportunity, Scholarship

COMMON = ("id", "source", "source_url", "fetched_at", "page_owner", "scope", "schools",
          "temple_funded", "audience_level", "apply_url", "deadline_quote", "amount_quote",
          "details_url", "details_fetched_at")
FIELDS = {
    "scholarship": COMMON + ("name", "sponsor", "purpose", "award_type", "amount_min",
                             "amount_max", "deadline", "level_of_study", "field_of_study",
                             "international_ok"),
    "opportunity": COMMON + ("title", "agency", "opportunity_number", "award_floor",
                             "award_ceiling", "open_date", "close_date", "close_date_note",
                             "description", "eligibility_notes"),
}
REQUIRED = {"scholarship": ("source_url", "name"), "opportunity": ("source_url", "title", "agency")}
LISTS = {"schools", "level_of_study", "field_of_study"}
NUMBERS = {"amount_min", "amount_max", "award_floor", "award_ceiling"}
BOOLS = {"temple_funded", "international_ok"}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def _clean(col: str, v: object) -> object:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if col in LISTS:
        return [x.strip() for x in v.split(";") if x.strip()] if isinstance(v, str) else list(v)
    if col in NUMBERS:
        return float(str(v).replace(",", "").replace("$", ""))
    if col in BOOLS:
        if isinstance(v, bool):
            return v
        t = str(v).strip().lower()
        if t in ("true", "yes", "1"):
            return True
        if t in ("false", "no", "0"):
            return False
        raise ValueError(f"{col}: not true or false")
    return v.strip() if isinstance(v, str) else v


class RowImporter:
    """Shared mapping for the CSV and JSON importers."""

    def __init__(self, path: Path | str, *, kind: str = "scholarship", source: str = "feed",
                 now: datetime | None = None) -> None:
        if kind not in FIELDS:
            raise ValueError("kind must be scholarship or opportunity")
        self.path, self.kind, self.source = Path(path), kind, source
        self.now = now or datetime.now(UTC)
        self.rejected: list[tuple[int, str]] = []
        self.ignored_columns: list[str] = []

    def rows(self) -> list[dict]:  # pragma: no cover - overridden
        raise NotImplementedError

    def read(self) -> list[Scholarship | Opportunity]:
        self.rejected, self.ignored_columns = [], []
        known, out = set(FIELDS[self.kind]), []
        ignored: set[str] = set()
        for n, raw in enumerate(self.rows(), start=1):
            ignored |= {c for c in raw if c not in known}
            try:
                out.append(self._record({c: raw[c] for c in raw if c in known}))
            except (ValueError, ValidationError) as e:
                self.rejected.append((n, str(e).splitlines()[0][:200]))
        self.ignored_columns = sorted(ignored)
        return out

    def _record(self, raw: dict) -> Scholarship | Opportunity:
        d = {c: v for c, v in ((c, _clean(c, v)) for c, v in raw.items()) if v is not None}
        for col in REQUIRED[self.kind]:
            if col not in d:
                raise ValueError(f"missing {col}" + (" (rule 4)" if col == "source_url" else ""))
        d.setdefault("source", self.source)
        if d["source"] == "synthetic" or str(d.get("id", "")).startswith("sample:"):
            raise ValueError("sample records are never imported (rule 11)")
        name = d["name"] if self.kind == "scholarship" else d["title"]
        d.setdefault("id", f"{d['source']}:{_slug(name)}-"
                     f"{hashlib.sha1((d['source_url'] + name).encode()).hexdigest()[:6]}")
        if isinstance(d.get("fetched_at"), str):
            d["fetched_at"] = datetime.fromisoformat(d["fetched_at"])
        d.setdefault("fetched_at", self.now)
        if self.kind == "scholarship":
            return Scholarship(**d)
        d.setdefault("opportunity_number", d["id"])
        return Opportunity(**d)


class CsvImporter(RowImporter):
    def rows(self) -> list[dict]:
        with self.path.open(newline="", encoding="utf-8") as fh:
            return [dict(r) for r in csv.DictReader(fh)]


class JsonImporter(RowImporter):
    """A JSON array of objects, or an object with the array under "records"."""

    def rows(self) -> list[dict]:
        data = json.loads(self.path.read_text("utf-8"))
        if isinstance(data, dict):
            data = data.get("records", [])
        if not isinstance(data, list):
            raise ValueError("expected a JSON array of objects")
        return [r for r in data if isinstance(r, dict)]

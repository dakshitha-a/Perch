"""Merge Temple award records that are the same award (REBUILD_PLAN Phase 4 task 4).

University-wide programs appear on several school pages, so the extraction holds the same
award more than once. Rules, all by code:

- Candidates share a record type and a normalised title (lower case, punctuation and a
  leading "the" removed).
- Two candidates merge only when nothing they both state conflicts: apply_url (compared
  without scheme, "www." and a trailing slash), amount (min and max), and deadline (the
  date, or the quoted text when there is no date). A field one of them lacks never blocks.
- Two awards with conflicting amounts or deadlines are never merged. The pair is logged
  (`Conflict`) and both records stay. Conflicting apply_urls also keep records apart, and are
  logged the same way.
- Clustering is greedy in a fixed order, and a record joins a cluster only when it is
  compatible with every member, so the result does not depend on chance.
- The kept record starts from the member with the most kept fields. A field it lacks is
  filled from another member, whose page is then named in `field_sources`, and
  `field_quotes` keep the sentence from the page each field came from. `seen_on` lists every
  page (url, fetched_at, owner) the award appeared on.

Scope (ARCHITECTURE_V1 D-14; the record's `Scope` value for university-wide is `temple_wide`):
an award on pages of two or more schools, or on a page owned by a university-wide office
(SDFA, Student Financial Services, OVPR, Education Abroad, Graduate School, Undergraduate
Studies, the Honors Program) is `temple_wide`. An award on one school's pages is `school`.
Anything else, for instance a degree-program page whose school is not stated, keeps scope
None rather than a guess (rule 10); the UI shows it under "All Temple".
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from perch.schemas import Opportunity, PageSighting, Scholarship
from perch.temple_extract import norm

Rec = Scholarship | Opportunity

# Inventory owners that are university-wide offices (UNVERIFIED as a list: widen it only
# from a page that says the office serves all of Temple).
UNIVERSITY_OWNERS = {
    "SDFA", "Student Financial Services", "OVPR", "Education Abroad", "Graduate School",
    "Undergraduate Studies", "Undergraduate Studies research", "Honors Program",
    "Temple Japan (via Education Abroad)",
}
# Two inventory owners that are one school.
SCHOOL_ALIASES = {"CPH (Social Work)": "CPH", "LKSOM Dept of Medicine": "LKSOM"}


def school_key(owner: str) -> str:
    return SCHOOL_ALIASES.get(owner, owner)


def norm_title(t: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", norm(t).lower().replace("&", " and "))
    t = re.sub(r"^(?:the)\s+", "", " ".join(t.split()))
    return t


def norm_url(u: str | None) -> str | None:
    if not u:
        return None
    u = re.sub(r"^https?://(?:www\.)?", "", u.strip().lower())
    return u.split("#")[0].rstrip("/")


def title_of(r: Rec) -> str:
    return r.name if isinstance(r, Scholarship) else r.title


def amount_of(r: Rec) -> tuple[float | None, float | None] | None:
    lo, hi = ((r.amount_min, r.amount_max) if isinstance(r, Scholarship)
              else (r.award_floor, r.award_ceiling))
    return None if lo is None and hi is None else (lo, hi)


def deadline_of(r: Rec) -> tuple[str, str] | None:
    """("date", iso) when the page gave a full date, else ("text", quote) or None."""
    d = r.deadline if isinstance(r, Scholarship) else r.close_date
    if d:
        return "date", d.isoformat()
    q = r.field_quotes.get("deadline_text")
    return ("text", norm(q).lower()) if q else None


def _deadlines_conflict(a: tuple[str, str] | None, b: tuple[str, str] | None) -> bool:
    """A date and a bare text never conflict: the text has no year to compare."""
    return bool(a and b and a[0] == b[0] and a[1] != b[1])


def _fields(r: Rec) -> dict[str, Any]:
    return {"apply_url": norm_url(r.apply_url), "amount": amount_of(r),
            "deadline": deadline_of(r)}


def conflicts_between(a: Rec, b: Rec) -> list[str]:
    """Names of the fields both records state with different values."""
    fa, fb = _fields(a), _fields(b)
    out = [k for k in ("apply_url", "amount") if fa[k] is not None and fb[k] is not None
           and fa[k] != fb[k]]
    if _deadlines_conflict(fa["deadline"], fb["deadline"]):
        out.append("deadline")
    return out


@dataclass
class Conflict:
    title: str
    ids: list[str]
    source_urls: list[str]
    fields: list[str]

    def as_dict(self) -> dict:
        return {"title": self.title, "ids": self.ids, "source_urls": self.source_urls,
                "fields": self.fields}


@dataclass
class DedupeReport:
    input_records: int = 0
    output_records: int = 0
    merged_groups: int = 0
    conflicts: list[Conflict] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [f"Dedupe: {self.input_records} records in, {self.output_records} out, "
                f"{self.merged_groups} merged groups, {len(self.conflicts)} conflicting pairs "
                "kept apart."]


def _richness(r: Rec) -> int:
    f = _fields(r)
    n = sum(v is not None for v in f.values())
    if isinstance(r, Scholarship):
        n += bool(r.eligibility.notes) + (r.eligibility.gpa_min is not None)
    else:
        n += bool(r.eligibility_notes)
    return n + (r.temple_funded is not None) + (r.audience_level is not None)


def _order(r: Rec) -> tuple:
    return (-_richness(r), r.source_url, r.id)


def _cluster(group: list[Rec]) -> tuple[list[list[Rec]], list[Conflict]]:
    clusters: list[list[Rec]] = []
    seen_pairs: set[tuple[str, str]] = set()
    log: list[Conflict] = []
    for r in sorted(group, key=_order):
        placed = False
        for c in clusters:
            bad = [(m, conflicts_between(m, r)) for m in c]
            if all(not f for _, f in bad):
                c.append(r)
                placed = True
                break
        if not placed:
            for c in clusters:
                for m in c:
                    f = conflicts_between(m, r)
                    key = tuple(sorted((m.id, r.id)))
                    if f and key not in seen_pairs:
                        seen_pairs.add(key)
                        ms = sorted([m, r], key=lambda x: (x.source_url, x.id))
                        log.append(Conflict(title_of(r), [x.id for x in ms],
                                            [x.source_url for x in ms], f))
            clusters.append([r])
    return clusters, log


def scope_for(owners: list[str]) -> tuple[str | None, list[str]]:
    """(scope, school keys) from the owners of every page an award appeared on."""
    schools = sorted({school_key(o) for o in owners if o and _is_school(o)})
    if len(schools) >= 2 or any(o in UNIVERSITY_OWNERS for o in owners):
        return "temple_wide", schools
    return ("school" if schools else None), schools


def _is_school(owner: str) -> bool:
    from perch.temple_extract import SCHOOL_OWNERS
    return owner in SCHOOL_OWNERS


def merge(members: list[Rec]) -> Rec:
    """One record from a cluster of compatible records (the first is the base)."""
    base = members[0].model_copy(deep=True)
    quotes = dict(base.field_quotes)
    sources: dict[str, str] = dict(base.field_sources)
    is_s = isinstance(base, Scholarship)

    # amount
    if amount_of(base) is None:
        for m in members[1:]:
            a = amount_of(m)
            if a:
                if is_s:
                    base.amount_min, base.amount_max = a
                else:
                    base.award_floor, base.award_ceiling = a
                base.amount_quote = m.amount_quote
                quotes["amount"] = m.field_quotes.get("amount", m.amount_quote or "")
                sources["amount"] = m.source_url
                break
    # deadline
    if deadline_of(base) is None:
        for m in members[1:]:
            if deadline_of(m) is not None:
                if is_s:
                    base.deadline = m.deadline
                else:
                    base.close_date = m.close_date
                    base.close_date_note = m.close_date_note
                base.deadline_quote = m.deadline_quote
                if "deadline_text" in m.field_quotes:
                    quotes["deadline_text"] = m.field_quotes["deadline_text"]
                sources["deadline"] = m.source_url
                break
    if not base.apply_url:
        for m in members[1:]:
            if m.apply_url:
                base.apply_url = m.apply_url
                quotes["apply_url"] = m.field_quotes.get("apply_url", "")
                sources["apply_url"] = m.source_url
                break
    notes = base.eligibility.notes if is_s else base.eligibility_notes
    if not notes:
        for m in members[1:]:
            mn = m.eligibility.notes if is_s else m.eligibility_notes
            if mn:
                if is_s:
                    base.eligibility.notes = mn
                    if base.eligibility.gpa_min is None:
                        base.eligibility.gpa_min = m.eligibility.gpa_min
                else:
                    base.eligibility_notes = mn
                quotes["eligibility"] = m.field_quotes.get("eligibility", "")
                sources["eligibility"] = m.source_url
                break
    if base.temple_funded is None:
        for m in members[1:]:
            if m.temple_funded:
                base.temple_funded = True
                quotes["temple_funded"] = m.field_quotes.get("temple_funded", "")
                sources["temple_funded"] = m.source_url
                break
    if base.audience_level is None:
        for m in members[1:]:
            if m.audience_level:
                base.audience_level = m.audience_level
                if "audience_level" in m.field_quotes:
                    quotes["audience_level"] = m.field_quotes["audience_level"]
                sources["audience_level"] = m.source_url
                break
    base.field_quotes = quotes
    base.field_sources = {k: v for k, v in sources.items() if v != base.source_url}
    # A deadline or amount filled from another page: details_url names that page.
    if base.field_sources.get("amount") and amount_of(members[0]) is None:
        base.details_url = base.field_sources["amount"]
    elif base.field_sources.get("deadline") and deadline_of(members[0]) is None \
            and amount_of(base) is None:
        base.details_url = base.field_sources["deadline"]
    seen: dict[str, PageSighting] = {}
    for m in members:
        for s in (m.seen_on or [PageSighting(source_url=m.source_url, fetched_at=m.fetched_at,
                                             page_owner=m.page_owner)]):
            seen.setdefault(s.source_url, s)
    base.seen_on = sorted(seen.values(), key=lambda s: s.source_url)
    owners = [s.page_owner or "" for s in base.seen_on]
    base.scope, base.schools = scope_for(owners)  # type: ignore[assignment]
    return base


def dedupe(records: list[Rec]) -> tuple[list[Rec], DedupeReport]:
    """Merged records in id order, and a report that lists every conflicting pair."""
    rep = DedupeReport(input_records=len(records))
    groups: dict[tuple[str, str], list[Rec]] = defaultdict(list)
    for r in records:
        groups[(r.kind, norm_title(title_of(r)))].append(r)
    out: list[Rec] = []
    for key in sorted(groups):
        clusters, log = _cluster(groups[key])
        rep.conflicts.extend(log)
        for c in clusters:
            if len(c) > 1:
                rep.merged_groups += 1
            out.append(merge(c))
    out.sort(key=lambda r: r.id)
    rep.output_records = len(out)
    rep.conflicts.sort(key=lambda c: (c.title, c.ids))
    return out, rep

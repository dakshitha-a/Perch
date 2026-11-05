"""Scout's read tools (Phase 8, tasks 2 and 3).

Six allowlisted tools, all read-only (standing rule 5). None writes, sends or changes a row.
They read through `ScoutData`, a bundle of read callables the caller builds: the public
repository, and for a signed-in user the brief, CV, entries and saved items. A tool that reads
the user's own text blanks contact details first (perch/llm/contacts.py), so no model sees an
email, phone number, ORCID or link from a CV.

Every tool result names the ids of what it returned, and the executor keeps those records in
`seen`. The answer's citations are checked against `seen` (perch/scout/answer.py): Scout can
cite only what it read this turn. Text a tool returns is data, never instructions.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from perch.compare import award_size
from perch.datefmt import amount_text, day, deadline
from perch.llm import Tool
from perch.llm.contacts import blank_contacts
from perch.schemas import (
    Brief,
    Lead,
    Opportunity,
    Organisation,
    Record,
    Scholarship,
    Work,
    utcnow,
)
from perch.store.base import Repository
from perch.user.cv import sections

READ_TOOLS = ("search_records", "read_record", "read_brief", "read_cv_part", "read_entries",
              "read_saved")
USER_TOOLS = ("read_cv_part", "read_entries", "read_saved")
MAX_RESULTS = 8
TEXT_CHARS = 1500
CV_PART_CHARS = 3000
ENTRY_CHARS = 600
MAX_LEADS = 12
MAX_ROWS = 10
NOT_STATED = "not stated in the record"
STOP = {"the", "and", "for", "with", "that", "this", "what", "which", "are", "any", "from",
        "about", "can", "does", "have", "how", "who", "when", "where", "find", "show", "give"}
# Kinds that are the user's own rows or Perch's own output, never read as a public record.
NOT_PUBLIC = ("brief", "lead", "digest", "researcher")


class ToolError(Exception):
    """A tool refused or failed; the message goes back to the model."""


@dataclass
class SavedRef:
    record_id: str
    note: str | None = None


def _none() -> None:
    return None


@dataclass
class ScoutData:
    """What a Scout turn may read. Every field is a read-only callable."""

    repo: Callable[[], AbstractContextManager[Repository]]
    audience: str = "researcher"
    as_of: date = field(default_factory=date.today)
    signed_in: bool = True
    brief: Callable[[], tuple[Brief, list[Lead]] | None] = _none
    cv_text: Callable[[], str | None] = _none
    entries: Callable[[], list[tuple[str | None, str]]] = list  # (label, text)
    saved: Callable[[], list[SavedRef]] = list


def user_doc(id_: str, title: str, text: str) -> Work:
    """The user's own text as a record, so the citation validator can check against it."""
    return Work(id=id_, source="user", source_url="perch://user", fetched_at=utcnow(),
                title=title, abstract=text)


def slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-") or "overview"


def deadline_words(rec: Opportunity | Scholarship, as_of: date) -> str:
    """The deadline as the record gives it. With no date, the record's or the page's own
    words, quoted (S49 M3: 43 Temple pages state a deadline with no year)."""
    if isinstance(rec, Opportunity):
        if rec.close_date:
            return deadline(rec, as_of)
        words = rec.close_date_note or rec.deadline_quote
        return f"no date; the record's words: {words}" if words else deadline(rec, as_of)
    if rec.deadline:
        return day(rec.deadline)
    return f"no date; the page's words: {rec.deadline_quote}" if rec.deadline_quote \
        else NOT_STATED


def facts(rec: Record, as_of: date) -> dict[str, Any]:
    """Title, sponsor, deadline and amount as the cards write them: copied, not computed."""
    out: dict[str, Any] = {"id": rec.id, "kind": rec.kind}
    if isinstance(rec, Opportunity):
        out |= {"title": rec.title, "sponsor": rec.agency,
                "deadline": deadline_words(rec, as_of),
                "amount": award_size(rec) or NOT_STATED}
    elif isinstance(rec, Scholarship):
        out |= {"title": rec.name, "sponsor": rec.sponsor,
                "deadline": deadline_words(rec, as_of),
                "amount": amount_text(rec) or NOT_STATED}
    elif isinstance(rec, Organisation):
        out |= {"title": rec.name, "type": rec.type}
    else:
        out["title"] = getattr(rec, "title", None) or getattr(rec, "name", None) or rec.id
    if rec.source == "synthetic":
        out["sample"] = True
        out["note"] = "SAMPLE record from a test corpus; not a real award"
    return out


def _trim(text: str | None, n: int) -> str | None:
    if not text:
        return None
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " ..."


class ReadTools:
    """One turn's tool executor. `seen` holds every record a tool returned this turn."""

    def __init__(self, data: ScoutData) -> None:
        self.data = data
        self.seen: dict[str, Record] = {}
        self.used: list[str] = []  # tool names called, in order, for the step list
        # What read_brief and read_saved returned, so the answer check can test a claim about a
        # lead's rank or kept status against it (S45 fix round 2).
        self.ranks: dict[str, int] = {}  # record id -> rank, as read
        self.kept: set[str] = set()  # leads the brief marks kept
        self.saved: set[str] = set()  # ids the user saved
        self.brief_read = False
        self.saved_read = False

    # --- definitions ---

    def definitions(self) -> list[Tool]:
        o = {"type": "object", "additionalProperties": False}
        kinds = (["scholarship", "opportunity"] if self.data.audience == "student"
                 else ["opportunity"])
        defs = [
            Tool("search_records",
                 "Search Perch's public award records by words. Returns up to 8 records with "
                 "their id, title, sponsor, deadline and amount.",
                 {**o, "properties": {"query": {"type": "string"},
                                      "kind": {"type": "string", "enum": kinds},
                                      "limit": {"type": "integer", "minimum": 1, "maximum": 8}},
                  "required": ["query"]}, strict=False),
            Tool("read_record",
                 "Read one public record in full by its id, as a search or the brief gave it.",
                 {**o, "properties": {"id": {"type": "string"}}, "required": ["id"]},
                 strict=False),
            Tool("read_brief",
                 "Read the user's current brief: its leads in order with deadline, amount and "
                 "verdict, and the gaps the rules found.", {**o, "properties": {}},
                 strict=False),
        ]
        if self.data.signed_in:
            defs += [
                Tool("read_cv_part",
                     "Read the user's own CV. Without `part` it lists the part names; with a "
                     "part name it returns that part's text.",
                     {**o, "properties": {"part": {"type": "string"}}}, strict=False),
                Tool("read_entries", "Read the achievements and notes the user typed.",
                     {**o, "properties": {}}, strict=False),
                Tool("read_saved", "Read the records the user saved, with their notes.",
                     {**o, "properties": {}}, strict=False),
            ]
        return defs

    # --- execution ---

    def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name not in READ_TOOLS:
            raise ToolError(f"no tool named {name}")
        if name in USER_TOOLS and not self.data.signed_in:
            raise ToolError("that tool needs a signed-in account")
        if not isinstance(args, dict):
            raise ToolError("arguments must be an object")
        self.used.append(name)
        keep = ("query", "kind", "limit", "id", "part")
        try:
            return getattr(self, name)(**{k: v for k, v in args.items() if k in keep})
        except TypeError as e:  # a wrong argument name or type from the model
            raise ToolError("those arguments do not fit this tool") from e

    def _see(self, rec: Record) -> Record:
        self.seen[rec.id] = rec
        return rec

    def _empty(self, id_: str, title: str, note: str) -> dict[str, Any]:
        """An empty result still has an id, so "you have nothing saved yet" can cite it."""
        self._see(user_doc(id_, title, note))
        return {"id": id_, "note": note}

    def _get(self, rid: str) -> Record | None:
        rid = rid.strip().strip("[]")
        with self.data.repo() as r:
            rec = r.get_any(rid)
            if rec is None:
                for pre in ("grants_gov:", "https://openalex.org/"):
                    rec = r.get_any(pre + rid)
                    if rec:
                        break
        if rec is None:
            from perch.user.briefs import _sample

            rec = _sample(rid)
        if rec is not None and (rec.kind in NOT_PUBLIC or rec.source == "user"):
            return None
        return rec

    def search_records(self, query: str = "", kind: str | None = None, limit: int = 5
                       ) -> dict[str, Any]:
        """Words in any order: a record that holds more of them ranks higher. An id or an
        opportunity number finds that record first."""
        q = str(query).strip()[:200]
        if not q:
            raise ToolError("query is empty")
        n = max(1, min(int(limit or 5), MAX_RESULTS))
        classes: list[type] = []
        if kind in (None, "scholarship") and self.data.audience == "student":
            classes.append(Scholarship)
        if kind in (None, "opportunity"):
            classes.append(Opportunity)
        words = [w for w in dict.fromkeys(re.findall(r"[\w'-]{3,}", q.lower()))
                 if w not in STOP][:5]
        found: dict[str, Record] = {}
        direct = self._get(q) if " " not in q else None
        if direct is not None and direct.kind in {c.kind for c in classes}:
            found[direct.id] = direct
        with self.data.repo() as r:
            for cls in classes:
                for term in [q, *words]:
                    for x in r.browse(cls, q=term, limit=25).items:
                        found.setdefault(x.id, x)

        def score(rec: Record) -> int:
            text = " ".join(str(getattr(rec, a, "") or "") for a in
                            ("title", "name", "purpose", "description", "sponsor", "agency")
                            ).lower()
            return sum(w in text for w in words)

        order = list(found.values())
        order.sort(key=lambda x: (x is not direct, -score(x)))
        rows = [facts(self._see(x), self.data.as_of) for x in order[:n]]
        return {"query": q, "count": len(rows), "records": rows}

    def read_record(self, id: str = "") -> dict[str, Any]:  # noqa: A002
        rec = self._get(str(id))
        if rec is None:
            raise ToolError(f"no public record with id {id}")
        self._see(rec)
        out = facts(rec, self.data.as_of)
        out["source_url"] = rec.source_url
        if isinstance(rec, Opportunity):
            out |= {"description": _trim(rec.description, TEXT_CHARS),
                    "eligible_applicants": rec.eligible_applicants,
                    "eligibility_notes": _trim(rec.eligibility_notes, TEXT_CHARS),
                    "details_url": rec.details_url}
        elif isinstance(rec, Scholarship):
            e = rec.eligibility
            req = rec.application_requirements
            out |= {"purpose": _trim(rec.purpose, TEXT_CHARS),
                    "level_of_study": rec.level_of_study, "field_of_study": rec.field_of_study,
                    "eligibility_notes": _trim(e.notes, TEXT_CHARS),
                    "eligibility": e.model_dump(mode="json", exclude_none=True,
                                                exclude_defaults=True),
                    "application_requirements": (
                        req.model_dump(mode="json", exclude_defaults=True) if req else None),
                    "details_url": rec.details_url}
        return out

    def read_brief(self) -> dict[str, Any]:
        got = self.data.brief()
        if got is None:
            return {"brief": None, **self._empty("user:brief", "Brief",
                                                  "The user has no finished brief yet.")}
        b, leads = got
        self.brief_read = True
        rows: list[dict[str, Any]] = []
        temple = []  # Temple internal funding: its own list, outside the ranks (S49 M9)
        for x in sorted((x for x in leads if x.status != "dismissed" and x.group
                         == "temple_internal"), key=lambda x: x.rank or 0)[:MAX_LEADS]:
            if (rec := self._get(x.record_id)) is not None:
                temple.append(facts(self._see(rec), self.data.as_of)
                              | {"kept": x.status == "kept"}
                              | ({"notes": x.notes} if x.notes else {}))
                if x.status == "kept":
                    self.kept.add(rec.id)
        for x in sorted((x for x in leads if x.status != "dismissed" and x.route != "B"
                         and x.group is None), key=lambda x: x.rank or 0)[:MAX_LEADS]:
            rec = self._get(x.record_id)
            if rec is None:
                continue
            row = facts(self._see(rec), self.data.as_of)
            row |= {"rank": x.rank, "kept": x.status == "kept"}
            if x.rank is not None:
                self.ranks[rec.id] = x.rank
            if x.status == "kept":
                self.kept.add(rec.id)
            if x.verdict:
                row["verdict"] = x.verdict
            if x.gaps:
                row["gaps"] = x.gaps[:4]
            rows.append(row)
        # SYNTHETIC samples are kept apart from public leads (standing rule 11).
        public = [r for r in rows if not r.get("sample")]
        sample = [r for r in rows if r.get("sample")]
        out: dict[str, Any] = {"leads": public,
                               "note": "Leads are in the brief's own order, the strongest first."}
        if temple:
            out["temple_internal"] = temple
            out["temple_internal_note"] = ("temple_internal lists Temple's own faculty funding, "
                                           "a separate group with no rank. Never list it with "
                                           "leads.")
        if not rows:
            out |= self._empty("user:brief", "Brief", "The user's brief has no leads.")
        if sample:
            out["sample_leads"] = sample
            out["sample_note"] = ("sample_leads are invented records for a demonstration. Never "
                                  "list or compare them together with leads, and say they are "
                                  "samples.")
        return out

    def read_cv_part(self, part: str | None = None) -> dict[str, Any]:
        text = self.data.cv_text()
        if not text:
            return {"cv": None, **self._empty("user:cv", "CV", "The user has not added a CV.")}
        secs = {slug(k): v for k, v in sections(blank_contacts(text)).items() if v}
        if not part:
            return {"parts": [{"part": k, "lines": len(v)} for k, v in secs.items()],
                    "note": "Call read_cv_part with a part name to read it."}
        key = slug(str(part).removeprefix("user:cv:"))
        if key not in secs:
            raise ToolError("no such CV part; call read_cv_part with no part to list them")
        body = _trim("\n".join(secs[key]), CV_PART_CHARS) or ""
        doc = self._see(user_doc(f"user:cv:{key}", f"CV, {key}", body))
        return {"id": doc.id, "part": key, "text": body}

    def read_entries(self) -> dict[str, Any]:
        rows = []
        for i, (label, text) in enumerate(self.data.entries()[:MAX_ROWS], 1):
            body = _trim(blank_contacts(text), ENTRY_CHARS) or ""
            label = blank_contacts(label) if label else label  # S45 S5
            doc = self._see(user_doc(f"user:entry:{i}", label or f"Entry {i}", body))
            rows.append({"id": doc.id, "label": label, "text": body})
        return {"entries": rows} if rows else {
            "entries": [], **self._empty("user:entries", "Entries", "No entries yet.")}

    def read_saved(self) -> dict[str, Any]:
        self.saved_read = True
        rows = []
        for i, s in enumerate(self.data.saved()[:MAX_ROWS], 1):
            rec = self._get(s.record_id)
            if rec:
                self.saved.add(rec.id)
            row: dict[str, Any] = (facts(self._see(rec), self.data.as_of) if rec
                                   else {"id": s.record_id, "title": None})
            if s.note:
                note = self._see(user_doc(f"user:saved:{i}", f"Note {i}",
                                          blank_contacts(s.note)))
                row |= {"note_id": note.id, "note": _trim(note.abstract, ENTRY_CHARS)}
            rows.append(row)
        return {"saved": rows} if rows else {
            "saved": [], **self._empty("user:saved", "Saved", "Nothing saved yet.")}

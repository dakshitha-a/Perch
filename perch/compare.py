"""Compare view: kept leads side by side (SPEC section 3). Deterministic, no model.

Each cell holds only what a record field says, copied, or what code computes from one
(days to the close date). A cell with nothing behind it reads "Not in the record";
it never guesses. Every cell names the record that backs it, so the web app can open
the evidence panel from any cell, and carries a sort key (None sorts last).

The plan's "effort" and "IP" have no field on any record, so the columns are named by
what they hold instead: the activity code, and the funding instrument (Route A) or the
rule-based relationship type (Route B) (docs/DECISIONS.md, S12). No likelihood column:
the back-test measures Perch's ranking, not the chance of funding.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

from perch.datefmt import day, expires_only, placeholder_close
from perch.offices import OFFICES, for_route
from perch.schemas import Brief, Lead, Opportunity, Organisation
from perch.score import match_text
from perch.store.base import Repository

NONE = "Not in the record"
COLUMNS = [
    ("money", "Money"),
    ("closes", "Closes"),
    ("code", "Activity code"),
    ("kind", "Instrument or relationship"),
    ("evidence", "Evidence"),
    ("office", "Office"),
]


@dataclass
class Cell:
    text: str
    sort: float | str | None
    record_id: str | None
    note: str | None = None  # e.g. "by rule" or "inferred", shown small


@dataclass
class Row:
    lead_id: str
    route: str
    title: str
    record_id: str
    cells: dict[str, Cell]


def lower_first(phrase: str) -> str:
    """A code-written phrase joined mid-sentence starts lower case ("proposals accepted
    anytime", "up to $250,000", "an essay"), unless it opens with an acronym (R17)."""
    if phrase[:1].isupper() and not phrase[1:2].isupper():
        return phrase[0].lower() + phrase[1:]
    return phrase


def award_size(o: Opportunity) -> str | None:
    """The award size as the card shows it (web/format.js awardSize): "$X to $Y",
    "Up to $Y" or "From $X", copied from the record's floor and ceiling; None when the
    record states neither. Compare, the exports and the hand-off all use this (Q2)."""
    lo, hi = o.award_floor, o.award_ceiling
    if hi is not None and lo:
        return f"${lo:,.0f} to ${hi:,.0f}"
    if hi is not None:
        return f"Up to ${hi:,.0f}"
    if lo:
        return f"From ${lo:,.0f}"
    return None


def money(o: Opportunity) -> Cell:
    lo, hi = o.award_floor, o.award_ceiling
    text = award_size(o)
    if text is None:
        return Cell(NONE, None, o.id)
    note = ("award floor to ceiling" if hi is not None and lo
            else "award ceiling" if hi is not None else "award floor")
    return Cell(text, hi if hi is not None else lo, o.id, note)


def closes(o: Opportunity, as_of: date) -> Cell:
    if not o.close_date:
        note = f"listed as {o.status}" if o.status else None
        return Cell(NONE, None, o.id, note)
    if placeholder_close(o, as_of):  # the card's rule: the record's words, no day count (U3)
        return Cell(o.close_date_note or "", o.close_date.isoformat(), o.id,
                    "as the record states it")
    if expires_only(o):  # F3, T17: a parent announcement's date is its expiry
        return Cell(f"Expires {day(o.close_date)}", o.close_date.isoformat(), o.id,
                    "when the announcement expires; not a deadline")
    days = (o.close_date - as_of).days
    note = (f"{days} days after the brief date" if days > 1 else
            "1 day after the brief date" if days == 1 else "on or before the brief date")
    return Cell(o.close_date.isoformat(), o.close_date.isoformat(), o.id, note)


def route_a_row(lead: Lead, o: Opportunity | None, as_of: date) -> Row:
    rid = lead.record_id
    if o is None:
        blank = Cell(NONE, None, rid)
        cells = {k: blank for k, _ in COLUMNS}
        title = rid
    else:
        papers = [c for c in lead.cited_ids if c.startswith("W")]
        state = ("explanation withheld" if lead.flagged else
                 "explanation checked" if lead.explanation else "no explanation yet")
        # The card's Match, not the rank: one number for one lead everywhere (U6).
        rank = match_text(lead.match_score) or "No Match score"
        ev = f"{rank}; cites {len(papers)} of your papers" if papers else rank
        cells = {
            "money": money(o),
            "closes": closes(o, as_of),
            "code": Cell(o.activity_code or NONE, o.activity_code, rid),
            "kind": Cell(", ".join(o.funding_instruments) or NONE,
                         ", ".join(o.funding_instruments) or None, rid, "funding instrument"),
            "evidence": Cell(ev, lead.match_score, rid, state),
        }
        title = f"{o.opportunity_number}: {o.title}"
    office = for_route("A")
    cells["office"] = Cell(office.name, office.name, None)
    return Row(lead.id, "A", title, rid, cells)


def route_b_row(lead: Lead, org: Organisation | None) -> Row:
    rid = lead.record_id
    kinds = len(lead.signals)
    blank = Cell(NONE, None, rid)
    office = for_route("B")
    cells = {
        "money": blank,
        "closes": blank,
        "code": blank,
        "kind": Cell(lead.relationship or NONE, lead.relationship, lead.id,
                     "suggested by rule"),
        "evidence": Cell(f"{kinds} kinds of public signal" if kinds != 1 else
                         "1 kind of public signal", kinds, lead.id,
                         f"{lead.confidence}; inferred, not verified" if lead.confidence
                         else "inferred, not verified"),
        "office": Cell(office.name, office.name, None),
    }
    return Row(lead.id, "B", org.name if org else rid, rid, cells)


def compare(brief: Brief, leads: list[Lead], r: Repository, status: str | None = "kept"
            ) -> list[Row]:
    """Rows for the brief's leads with that status (all leads if None), Route A first,
    each route in rank order."""
    as_of = date.fromisoformat(brief.options.get("as_of") or date.today().isoformat())
    chosen = [x for x in leads if (status is None or x.status == status)
              and x.route in ("A", "B")]  # student leads compare in the browser (S18)
    chosen.sort(key=lambda x: (x.route, x.rank or 0))
    rows = []
    for x in chosen:
        if x.route == "A":
            rows.append(route_a_row(x, r.get(Opportunity, x.record_id), as_of))
        else:
            rows.append(route_b_row(x, r.get(Organisation, x.record_id)))
    return rows


def rows_json(rows: list[Row]) -> dict:
    return {"columns": [{"key": k, "label": lbl} for k, lbl in COLUMNS],
            "rows": [asdict(x) for x in rows], "none": NONE,
            # Research briefs only: the student offices (F, S) have their own browser-side
            # drafts, and listing them here showed "no kept undefined" (S22, audit M1).
            "offices": [asdict(o) for o in OFFICES.values() if o.route in ("A", "B")]}

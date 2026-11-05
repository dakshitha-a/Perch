"""The saved list: awards and funding calls a signed-in user saved, merged with the leads they
kept in their briefs (S49 V2).

A saved item is one encrypted `saved_item` row (perch.user.models.SavedItem). The record it
points at is read from the public store at read time and is never copied into the row. Nothing
here logs a record id, a user id or a row.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from uuid import UUID

from perch.schemas import Opportunity, Record, Scholarship
from perch.store.base import Repository
from perch.user.data import UserData
from perch.user.models import Audience, SavedItem, StoredBrief

MAX_SAVED = 200
SAVEABLE = (Scholarship.kind, Opportunity.kind)
KEPT_ROUTES = ("A", "F", "S")  # grants, fellowships, scholarships; route B leads hold no date


class SampleRefused(Exception):
    """The id belongs to the SYNTHETIC corpus (standing rule 11)."""


class NotFound(Exception):
    """No public award or funding call has this id."""


class Full(Exception):
    """The side already holds MAX_SAVED saved items."""


def is_sample(record_id: str, rec: Record | None = None) -> bool:
    return record_id.startswith("sample:") or (rec is not None and rec.source == "synthetic")


def _rows(ud: UserData, uid: UUID, side: Audience) -> list[tuple[UUID, SavedItem]]:
    return ud.list(uid, "saved_item", side, SavedItem, limit=MAX_SAVED + 1)


def save(ud: UserData, repo_factory: Callable[[], Repository], uid: UUID, side: Audience,
         record_id: str) -> tuple[UUID, SavedItem, bool]:
    """Save one record; return (saved_id, row, created). Saving twice returns the first row."""
    if is_sample(record_id):
        raise SampleRefused
    with repo_factory() as repo:
        rec = repo.get_any(record_id)
    if rec is None or rec.kind not in SAVEABLE:
        raise NotFound
    if is_sample(record_id, rec):
        raise SampleRefused
    rows = _rows(ud, uid, side)
    for rid, row in rows:
        if row.record_id == record_id:
            return rid, row, False
    if len(rows) >= MAX_SAVED:
        raise Full
    item = SavedItem(record_id=record_id)
    return ud.put(uid, "saved_item", side, item), item, True


def remove(ud: UserData, uid: UUID, saved_id: UUID) -> bool:
    return ud.delete(uid, saved_id, kinds=("saved_item",))


def _order_key(entry: dict, today: date) -> tuple:
    rec = entry["record"]
    title = str((rec or {}).get("name") or (rec or {}).get("title")
                or entry["record_id"]).casefold()
    if rec is None:
        return (3, 0, title)
    d = date.fromisoformat(rec["deadline"]) if rec.get("deadline") else None
    if d is None:
        return (2, 0, title)
    if d >= today:
        return (0, d.toordinal(), title)
    return (1, -d.toordinal(), title)


def listing(ud: UserData, repo_factory: Callable[[], Repository], uid: UUID, side: Audience,
            *, today: date | None = None) -> dict:
    """Saved rows plus kept leads, one entry per record id, in the contract's order: upcoming
    dates ascending, past dates newest first, no date, no record."""
    from perch.browse.routes import item

    today = today or date.today()
    entries: dict[str, dict] = {}

    def entry(record_id: str) -> dict:
        return entries.setdefault(record_id, {"record_id": record_id, "saved_id": None,
                                              "saved_at": None, "kept_in": [], "record": None})

    for rid, row in _rows(ud, uid, side):
        e = entry(row.record_id)
        e["saved_id"], e["saved_at"] = str(rid), row.saved_at.isoformat()
    for bid, sb in ud.list(uid, "brief", side, StoredBrief, limit=50):
        for lead in sb.leads:
            if (lead.status == "kept" and not lead.sample and lead.route in KEPT_ROUTES
                    and not is_sample(lead.record_id)):
                entry(lead.record_id)["kept_in"].append(
                    {"brief_id": str(bid), "built_at": sb.brief.created_at.isoformat()})
    with repo_factory() as repo:
        for record_id, e in list(entries.items()):
            rec = repo.get_any(record_id)
            if rec is None:
                continue  # the store no longer holds it: shown with record null
            if rec.kind in SAVEABLE and not is_sample(record_id, rec):
                e["record"] = item(rec)
            else:
                del entries[record_id]  # not a public award or funding call
    items = sorted(entries.values(), key=lambda e: _order_key(e, today))
    return {"audience": side, "total": len(items), "items": items}

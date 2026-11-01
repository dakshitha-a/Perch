"""Dates as the web app shows them, for text that code writes on the server (U3, U14).

`day` matches `formatDate` in web/format.js: "29 Sep 2026". `closes` applies the lead
card's rule (web/app.js `leadCard`): NSF gives open-anytime programmes a placeholder
close date decades out, so a close date more than ten years away is shown as the
record's own deadline note, such as "Proposals accepted anytime", with no day count.
Both read record fields only; nothing here makes up a date.
"""

from __future__ import annotations

import re
from datetime import date

from perch.schemas import Opportunity

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FAR_DAYS = 3650  # the card's threshold: more than ten years out


def day(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def shown(v: str) -> str:
    """An ISO date as the cards write it ("15 Feb 2027"); any other text, such as
    "Proposals accepted anytime" or "Not in the record", as it is (Q22, R1)."""
    try:
        return day(date.fromisoformat(v))
    except (TypeError, ValueError):
        return v


# T17: NIH parent announcements take applications on NIH's standard due dates; the
# record's close date is when the announcement expires, not a deadline. A note that says
# standard dates apply is the record's own words, as "Proposals accepted anytime" is.
STANDARD_DATES = re.compile(r"\bstandard (?:due |receipt )?dates apply\b", re.I)
PARENT = re.compile(r"\(Parent\b")


def placeholder_close(o: Opportunity, as_of: date | None = None) -> bool:
    """The close date is a far-off placeholder and the record says so in words, or the
    record says standard dates apply (T17)."""
    return bool(o.close_date and o.close_date_note
                and ((o.close_date - (as_of or date.today())).days > FAR_DAYS
                     or STANDARD_DATES.search(o.close_date_note)))


def expires_only(o: Opportunity) -> bool:
    """A parent announcement whose record gives no deadline words: its close date is when
    it expires (T17)."""
    return bool(o.close_date and not o.close_date_note and PARENT.search(o.title or ""))


def no_deadline(o: Opportunity, as_of: date | None = None) -> bool:
    """No close date that is a deadline: none, a placeholder, or an expiry date."""
    return not o.close_date or placeholder_close(o, as_of) or expires_only(o)


def closes(o: Opportunity, as_of: date | None = None) -> str | None:
    """The close date as shown, or the record's deadline note, or "Expires <date>" for a
    parent announcement; None when the record has no close date."""
    if not o.close_date:
        return None
    if placeholder_close(o, as_of):
        return o.close_date_note
    return f"Expires {day(o.close_date)}" if expires_only(o) else day(o.close_date)


def deadline(o: Opportunity, as_of: date | None = None) -> str:
    """The close date as a clause with its own verb, for text read after a title (F3, F22):
    "closes 4 Feb 2027"; the record's own words, such as "Proposals accepted anytime"; or,
    for a parent announcement, "the announcement expires 7 May 2028", never a deadline."""
    if not o.close_date:
        return "close date not in the record"
    if placeholder_close(o, as_of):
        return o.close_date_note or ""
    if expires_only(o):
        return f"no deadline in the record; the announcement expires {day(o.close_date)}"
    return f"closes {day(o.close_date)}"

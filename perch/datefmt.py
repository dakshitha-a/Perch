"""Dates as the web app shows them, for text that code writes on the server (U3, U14).

`day` matches `formatDate` in web/format.js: "29 Sep 2026". `closes` applies the lead
card's rule (web/app.js `leadCard`): NSF gives open-anytime programmes a placeholder
close date decades out, so a close date more than ten years away is shown as the
record's own deadline note, such as "Proposals accepted anytime", with no day count.
Both read record fields only; nothing here makes up a date.
"""

from __future__ import annotations

from datetime import date

from perch.schemas import Opportunity

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FAR_DAYS = 3650  # the card's threshold: more than ten years out


def day(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def placeholder_close(o: Opportunity, as_of: date | None = None) -> bool:
    """The close date is a far-off placeholder and the record says so in words."""
    return bool(o.close_date and o.close_date_note
                and (o.close_date - (as_of or date.today())).days > FAR_DAYS)


def closes(o: Opportunity, as_of: date | None = None) -> str | None:
    """The close date as shown, or the record's deadline note; None when the record has
    no close date."""
    if not o.close_date:
        return None
    return o.close_date_note if placeholder_close(o, as_of) else day(o.close_date)

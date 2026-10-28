"""NSF Award Search API fetcher: Temple awards with start and expiration dates.

Verified against live responses on 2026-10-28; fixtures in tests/fixtures/nsf/,
endpoint and terms in docs/SOURCES.md. Responses include PI and program-officer
emails and phone numbers; the parser never reads them, and fixtures are saved
through redact_contacts() so they never reach the repo.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import httpx

from perch.schemas import Award

SOURCE = "nsf"
API = "https://api.nsf.gov/services/v1"
TEMPLE_AWARDEE = '"Temple University"'
PAGE = 25  # the API's maximum results per page
CONTACT_FIELDS = ("piEmail", "poEmail", "poPhone", "awardeePhone")
EMAIL_RE = re.compile(r"\s*\S+@\S+")


def _date(value: str | None) -> date | None:
    """NSF dates look like '06/30/2016'."""
    try:
        return datetime.strptime(value, "%m/%d/%Y").date() if value else None
    except ValueError:
        return None


def _amount(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def strip_email(entry: str) -> str:
    """'Jane Doe <her email>' -> 'Jane Doe'. Entries arrive as name, space, email."""
    return EMAIL_RE.sub("", entry).strip()


def redact_contacts(data: dict[str, Any]) -> dict[str, Any]:
    """Remove emails and phone numbers from an API response, for saving fixtures."""
    for a in (data.get("response") or {}).get("award") or []:
        for f in CONTACT_FIELDS:
            if f in a:
                a[f] = "[redacted]"
        for f in ("pi", "coPDPI"):
            if isinstance(a.get(f), list):
                a[f] = [strip_email(x) + " [email redacted]" for x in a[f]]
    return data


def parse_award(raw: dict[str, Any], fetched_at: datetime) -> Award:
    aid = str(raw["id"])
    lead = " ".join(x for x in (raw.get("piFirstName"), raw.get("piLastName")) if x)
    co = [strip_email(x).replace(" [email redacted]", "") for x in raw.get("coPDPI") or []]
    amount = _amount(raw.get("estimatedTotalAmt"))
    return Award(
        id=f"nsf:{aid}",
        source=SOURCE,
        source_url=f"{API}/awards/{aid}.json",
        fetched_at=fetched_at,
        agency=raw.get("agency") or "NSF",
        award_number=aid,
        title=raw.get("title") or "",
        pi_names=[n for n in [lead, *co] if n],
        institution=raw.get("awardeeName"),
        start_date=_date(raw.get("startDate")),
        end_date=_date(raw.get("expDate")),
        amount=amount,
        amount_basis="estimated total" if amount is not None else None,
        opportunity_number=None,  # the Award Search API has no solicitation field
    )


class NSFClient:
    def __init__(self, transport: httpx.BaseTransport | None = None, min_interval: float = 1.0,
                 retries: int = 3, timeout: float = 60.0) -> None:
        headers = {"User-Agent": "perch (Temple AI Build Challenge prototype)"}
        self.http = httpx.Client(base_url=API, transport=transport, timeout=timeout,
                                 headers=headers)
        self.min_interval = min_interval  # self-imposed; the API states no limit
        self.retries = retries
        self._last = 0.0

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> NSFClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = self.http.get("/awards.json", params=params)
            if (r.status_code == 429 or r.status_code >= 500) and attempt < self.retries:
                time.sleep(2 ** (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("unreachable")

    def iter_awards(self, params: dict[str, Any]) -> Iterator[Award]:
        offset = 0  # record offset, 0-based
        while True:
            data = self.get({**params, "rpp": PAGE, "offset": offset})
            now = datetime.now(UTC)
            resp = data.get("response") or {}
            awards = resp.get("award") or []
            yield from (parse_award(a, now) for a in awards)
            offset += len(awards)
            total = (resp.get("metadata") or {}).get("totalCount", 0)
            if not awards or offset >= total:
                return

    def awards_for_pi(self, name: str, awardee: str = TEMPLE_AWARDEE) -> list[Award]:
        """Awards at awardee where name is the lead PI or a co-PI, deduplicated."""
        seen: dict[str, Award] = {}
        for role in ("pdPIName", "coPDPI"):
            for a in self.iter_awards({"awardeeName": awardee, role: name}):
                seen.setdefault(a.id, a)
        return list(seen.values())

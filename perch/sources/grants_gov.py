"""Grants.gov fetcher: federal funding opportunities through the public Applicant API.

Verified against live responses on 2026-10-28; fixtures in tests/fixtures/grants_gov/,
endpoints and terms in docs/SOURCES.md. search2 and fetchOpportunity need no key.
The terms require this notice wherever the data is shown:

  "This product uses the Grants.gov API but is not endorsed or certified by the
  U.S. Department of Health and Human Services."

Records carry agency contact names, emails and phones; the parser never reads
them, and fixtures are saved through redact_contacts().
"""

from __future__ import annotations

import html
import re
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import httpx

from perch.schemas import Opportunity

SOURCE = "grants_gov"
API = "https://api.grants.gov/v1/api"
DETAIL_URL = "https://www.grants.gov/search-results-detail/{id}"
ATTRIBUTION = ("This product uses the Grants.gov API but is not endorsed or certified by the "
               "U.S. Department of Health and Human Services.")
OPEN_STATUSES = "forecasted|posted"
PAGE = 100
CONTACT_FIELDS = ("agencyContactEmail", "agencyContactPhone", "agencyContactName",
                  "agencyContactDesc", "agencyContactEmailDesc", "agencyPhone", "contactInfo")
Json = dict[str, "Json"] | list["Json"] | str | int | float | bool | None
# NIH-style activity codes in a title, e.g. "(R01 Clinical Trial Required)".
# NIH codes: letter + two digits (R01), two letters + digit (DP1, UG3), letter digit letter (U2C).
ACTIVITY_RE = re.compile(r"\((?:Parent )?([A-Z]\d{2}|[A-Z]{2}\d|[A-Z]\d[A-Z])\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _date(value: str | None) -> date | None:
    """Accepts 'Nov 17, 2026 12:00:00 AM EST' (detail) and '11/17/2026' (search)."""
    if not value:
        return None
    for fmt, text in (("%b %d, %Y", value[:12].strip().rstrip(",")), ("%m/%d/%Y", value[:10])):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    m = re.match(r"([A-Z][a-z]{2} \d{1,2}, \d{4})", value)
    return datetime.strptime(m.group(1), "%b %d, %Y").date() if m else None


def _money(value: object) -> float | None:
    """Ceilings and floors arrive as numbers, numeric strings, or 'none'."""
    try:
        v = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _text(value: str | None) -> str | None:
    if not value:
        return None
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value))).strip() or None


def hit_close_date(hit: dict[str, Any]) -> date | None:
    """A search2 hit's close date ("MM/DD/YYYY" or empty)."""
    return _date(hit.get("closeDate"))


def redact_contacts(data: Json) -> Json:
    """Replace contact fields anywhere in a response (they also appear in history),
    and any email address inside other text."""
    if isinstance(data, str):
        return EMAIL_RE.sub("[email redacted]", data)
    if isinstance(data, dict):
        for k, v in data.items():
            data[k] = "[redacted]" if k in CONTACT_FIELDS and v else redact_contacts(v)
        # Next to agencyDetails, agencyName is a contact on DoD and DOE records.
        if "agencyDetails" in data and data.get("agencyName"):
            data["agencyName"] = "[redacted]"
    elif isinstance(data, list):
        for i, v in enumerate(data):
            data[i] = redact_contacts(v)
    return data


def agency_name(detail: dict[str, Any]) -> str:
    """The agency's name from `agencyDetails`. The synopsis-level `agencyName` is not
    used: on DoD and DOE records it holds the contact person's name and role."""
    syn = detail.get("synopsis") or {}
    for d in (syn.get("agencyDetails"), detail.get("agencyDetails"),
              syn.get("topAgencyDetails"), detail.get("topAgencyDetails")):
        if isinstance(d, dict) and d.get("agencyName"):
            return str(d["agencyName"])
    return syn.get("agencyCode") or detail.get("owningAgencyCode") or ""


def parse_opportunity(detail: dict[str, Any], fetched_at: datetime,
                      status: str | None = None) -> Opportunity:
    syn = detail.get("synopsis") or {}
    title = html.unescape(detail.get("opportunityTitle") or "").replace("\xa0", " ")
    activity = ACTIVITY_RE.search(title)
    return Opportunity(
        id=f"{SOURCE}:{detail['opportunityNumber']}",
        source=SOURCE,
        source_url=DETAIL_URL.format(id=detail["id"]),
        fetched_at=fetched_at,
        opportunity_number=detail["opportunityNumber"],
        title=title,
        agency=agency_name(detail),
        open_date=_date(syn.get("postingDate")),
        close_date=_date(syn.get("responseDate")),
        archive_date=_date(syn.get("archiveDate")),
        award_ceiling=_money(syn.get("awardCeiling")),
        award_floor=_money(syn.get("awardFloor")),
        # Grants.gov returns list fields in a different order on each call; sort them so
        # a refresh reports only real changes.
        eligible_applicants=sorted({t["description"] for t in syn.get("applicantTypes") or []
                                    if t.get("description")}),
        eligibility_notes=_text(syn.get("applicantEligibilityDesc")),
        activity_code=activity.group(1) if activity else None,
        description=_text(syn.get("synopsisDesc")),
        status=status,
        assistance_listings=sorted({c["cfdaNumber"] for c in detail.get("cfdas") or []
                                    if c.get("cfdaNumber")}),
        funding_instruments=sorted({f["description"] for f in syn.get("fundingInstruments") or []
                                    if f.get("description")}),
    )


class GrantsGovClient:
    def __init__(self, transport: httpx.BaseTransport | None = None, min_interval: float = 1.0,
                 retries: int = 3, timeout: float = 60.0) -> None:
        headers = {"User-Agent": "perch (Temple AI Build Challenge prototype)"}
        self.http = httpx.Client(base_url=API, transport=transport, timeout=timeout,
                                 headers=headers)
        self.min_interval = min_interval  # self-imposed; no published limit
        self.retries = retries
        self._last = 0.0

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> GrantsGovClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = self.http.post(path, json=body)
            if (r.status_code == 429 or r.status_code >= 500) and attempt < self.retries:
                time.sleep(2 ** (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            if data.get("errorcode", 0) != 0:
                raise RuntimeError(f"Grants.gov {path}: {data.get('msg')}")
            return data
        raise RuntimeError("unreachable")

    def search(self, statuses: str = OPEN_STATUSES, agencies: str = "", keyword: str = "",
               start: int = 0, rows: int = PAGE, opp_num: str = "") -> dict[str, Any]:
        body = {"keyword": keyword, "oppStatuses": statuses, "agencies": agencies,
                "rows": rows, "startRecordNum": start}
        if opp_num:
            body["oppNum"] = opp_num
        return self.post("/search2", body)["data"]

    def iter_hits(self, statuses: str = OPEN_STATUSES, agencies: str = "", keyword: str = "",
                  limit: int | None = None) -> Iterator[dict[str, Any]]:
        start, seen = 0, 0
        while True:
            data = self.search(statuses, agencies, keyword, start)
            hits = data.get("oppHits") or []
            for h in hits:
                if limit is not None and seen >= limit:
                    return
                seen += 1
                yield h
            start += len(hits)
            if not hits or start >= data.get("hitCount", 0):
                return

    def fetch(self, opportunity_id: str | int, status: str | None = None) -> Opportunity:
        data = self.post("/fetchOpportunity", {"opportunityId": int(opportunity_id)})["data"]
        return parse_opportunity(data, datetime.now(UTC), status)

    def iter_opportunities(self, statuses: str = OPEN_STATUSES, agencies: str = "",
                           keyword: str = "", limit: int | None = None) -> Iterator[Opportunity]:
        """Search, then fetch each hit's full record (one request per opportunity)."""
        for h in self.iter_hits(statuses, agencies, keyword, limit):
            yield self.fetch(h["id"], h.get("oppStatus"))

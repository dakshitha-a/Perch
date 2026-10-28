"""NIH RePORTER v2 fetcher: Temple awards, one record per fiscal-year application.

Verified against live responses on 2026-10-28; fixture in tests/fixtures/nih_reporter/,
endpoint and terms in docs/SOURCES.md. RePORTER asks for no more than one request
per second and large jobs on weekends or overnight (9 pm to 5 am Eastern).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import httpx

from perch.schemas import Award

SOURCE = "nih_reporter"
API = "https://api.reporter.nih.gov"
# Organisation name filter; RePORTER lists Temple as "TEMPLE UNIV OF THE COMMONWEALTH".
TEMPLE_ORG = "TEMPLE UNIV"
PAGE = 500  # RePORTER's maximum page size
FIELDS = [
    "ApplId", "ProjectNum", "CoreProjectNum", "ProjectTitle", "FiscalYear", "ProjectStartDate",
    "ProjectEndDate", "AwardAmount", "OpportunityNumber", "ActivityCode", "AgencyIcAdmin",
    "PrincipalInvestigators", "Organization", "ProjectDetailUrl", "AwardNoticeDate",
]


def _date(value: str | None) -> date | None:
    """RePORTER dates look like '2023-06-05T00:00:00'."""
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _pi_name(p: dict[str, Any]) -> str:
    parts = [p.get("first_name"), p.get("middle_name"), p.get("last_name")]
    return " ".join(x.strip() for x in parts if x and x.strip())


def parse_project(raw: dict[str, Any], fetched_at: datetime) -> Award:
    appl = raw["appl_id"]
    ic = raw.get("agency_ic_admin") or {}
    return Award(
        id=f"nih:{appl}",
        source=SOURCE,
        source_url=raw.get("project_detail_url") or f"https://reporter.nih.gov/project-details/{appl}",
        fetched_at=fetched_at,
        agency="NIH" + (f" {ic['abbreviation']}" if ic.get("abbreviation") else ""),
        award_number=raw.get("core_project_num") or raw.get("project_num") or str(appl),
        title=raw.get("project_title") or "",
        pi_names=[_pi_name(p) for p in raw.get("principal_investigators") or []],
        institution=(raw.get("organization") or {}).get("org_name"),
        start_date=_date(raw.get("project_start_date")),
        end_date=_date(raw.get("project_end_date")),
        amount=raw.get("award_amount"),
        amount_basis="fiscal year" if raw.get("award_amount") is not None else None,
        fiscal_year=raw.get("fiscal_year"),
        activity_code=raw.get("activity_code"),
        opportunity_number=raw.get("opportunity_number"),
    )


class NIHReporterClient:
    """Synchronous client, spaced to at most one request per second."""

    def __init__(self, transport: httpx.BaseTransport | None = None, min_interval: float = 1.0,
                 retries: int = 3, timeout: float = 60.0) -> None:
        headers = {"User-Agent": "perch (Temple AI Build Challenge prototype)"}
        self.http = httpx.Client(base_url=API, transport=transport, timeout=timeout,
                                 headers=headers)
        self.min_interval = min_interval
        self.retries = retries
        self._last = 0.0

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> NIHReporterClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def search(self, criteria: dict[str, Any], offset: int = 0) -> dict[str, Any]:
        body = {"criteria": criteria, "include_fields": FIELDS, "offset": offset, "limit": PAGE,
                "sort_field": "fiscal_year", "sort_order": "desc"}
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = self.http.post("/v2/projects/search", json=body)
            if (r.status_code == 429 or r.status_code >= 500) and attempt < self.retries:
                time.sleep(2 ** (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("unreachable")

    def iter_projects(self, criteria: dict[str, Any]) -> Iterator[Award]:
        offset = 0
        while True:
            data = self.search(criteria, offset)
            now = datetime.now(UTC)
            results = data.get("results") or []
            yield from (parse_project(r, now) for r in results)
            offset += len(results)
            if not results or offset >= (data.get("meta") or {}).get("total", 0):
                return

    def awards_for_pi(self, first_name: str, last_name: str,
                      org: str = TEMPLE_ORG) -> list[Award]:
        """Every fiscal-year record at org listing this person among its PIs."""
        criteria = {"org_names": [org],
                    "pi_names": [{"first_name": first_name, "last_name": last_name}]}
        return list(self.iter_projects(criteria))

    def awards_for_org(self, fiscal_years: list[int], org: str = TEMPLE_ORG) -> list[Award]:
        return list(self.iter_projects({"org_names": [org], "fiscal_years": fiscal_years}))

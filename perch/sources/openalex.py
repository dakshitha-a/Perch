"""OpenAlex fetcher: resolve a researcher and pull their works.

Verified against live responses on 2026-10-28; fixtures in tests/fixtures/openalex/,
endpoints, costs and terms in docs/SOURCES.md. Without an API key, requests share
a small daily budget per IP; set OPENALEX_API_KEY in .env for a personal budget.
The key is sent as a Bearer header so it never appears in URLs or logs.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import httpx

from perch.schemas import Researcher, Topic, Work

SOURCE = "openalex"
API = "https://api.openalex.org"
# Temple University's OpenAlex institution id, read from /institutions on 2026-10-28.
TEMPLE_INSTITUTION_ID = "https://openalex.org/I84392919"
MAX_CANDIDATES = 3

ORCID_RE = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$")
AUTHOR_RE = re.compile(r"(A\d+)$")


def short_id(openalex_id: str) -> str:
    """'https://openalex.org/A123' -> 'A123'."""
    return openalex_id.rstrip("/").rsplit("/", 1)[-1]


def parse_orcid(text: str) -> str | None:
    m = ORCID_RE.search(text.strip())
    return m.group(1) if m else None


def parse_author_id(text: str) -> str | None:
    m = AUTHOR_RE.search(text.strip())
    return m.group(1) if m else None


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """OpenAlex ships abstracts as {word: [positions]}; rebuild the text."""
    if not inverted:
        return None
    slots: dict[int, str] = {}
    for word, positions in inverted.items():
        for p in positions:
            slots[p] = word
    return " ".join(slots[i] for i in sorted(slots)) or None


def _topics(raw: list[dict[str, Any]] | None) -> list[Topic]:
    return [
        Topic(id=t["id"], display_name=t["display_name"], score=t.get("score"))
        for t in raw or []
        if t.get("id") and t.get("display_name")
    ]


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def parse_author(raw: dict[str, Any], fetched_at: datetime) -> Researcher:
    sid = short_id(raw["id"])
    return Researcher(
        id=raw["id"],
        source=SOURCE,
        source_url=f"{API}/authors/{sid}",
        fetched_at=fetched_at,
        display_name=raw["display_name"],
        orcid=raw.get("orcid"),
        institutions=[i["display_name"] for i in raw.get("last_known_institutions") or []],
        works_count=raw.get("works_count"),
        cited_by_count=raw.get("cited_by_count"),
        topics=_topics(raw.get("topics")),
    )


def parse_work(raw: dict[str, Any], fetched_at: datetime) -> Work:
    sid = short_id(raw["id"])
    source = ((raw.get("primary_location") or {}).get("source")) or {}
    authorships = raw.get("authorships") or []
    institution_ids = sorted({
        i["id"] for a in authorships for i in a.get("institutions") or [] if i.get("id")
    })
    return Work(
        id=raw["id"],
        source=SOURCE,
        source_url=f"{API}/works/{sid}",
        fetched_at=fetched_at,
        title=raw.get("title") or raw.get("display_name") or "",
        publication_year=raw.get("publication_year"),
        publication_date=_date(raw.get("publication_date")),
        venue=source.get("display_name"),
        doi=raw.get("doi"),
        type=raw.get("type"),
        abstract=reconstruct_abstract(raw.get("abstract_inverted_index")),
        author_ids=[a["author"]["id"] for a in authorships if (a.get("author") or {}).get("id")],
        institution_ids=institution_ids,
        topics=_topics(raw.get("topics")),
        referenced_works=list(raw.get("referenced_works") or []),
        cited_by_count=raw.get("cited_by_count"),
    )


class OpenAlexClient:
    """Small synchronous client with retries. Pass `transport` in tests."""

    def __init__(self, api_key: str | None = None, transport: httpx.BaseTransport | None = None,
                 retries: int = 4, min_interval: float = 0.1, timeout: float = 30.0) -> None:
        headers = {"User-Agent": "perch (Temple AI Build Challenge prototype)"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self.http = httpx.Client(base_url=API, headers=headers, transport=transport,
                                 timeout=timeout)
        self.retries = retries
        self.min_interval = min_interval  # self-imposed spacing between requests
        self._last = 0.0

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> OpenAlexClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.http.get(path, params=params)
            except httpx.TransportError:
                if attempt == self.retries:
                    raise
                time.sleep(2**attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == self.retries:
                    r.raise_for_status()
                retry_after = r.headers.get("Retry-After", "")
                time.sleep(float(retry_after) if retry_after.isdigit() else 2**attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("unreachable")

    # --- researchers ---

    def resolve_by_name(self, name: str,
                        institution_id: str = TEMPLE_INSTITUTION_ID) -> list[Researcher]:
        """Up to three authors matching name whose last known institution is given."""
        data = self.get("/authors", {
            "search": name,
            "filter": f"last_known_institutions.id:{short_id(institution_id)}",
            "per-page": MAX_CANDIDATES,
        })
        now = datetime.now(UTC)
        return [parse_author(a, now) for a in data.get("results", [])[:MAX_CANDIDATES]]

    def resolve_by_orcid(self, orcid: str) -> Researcher:
        oid = parse_orcid(orcid)
        if not oid:
            raise ValueError(f"not an ORCID iD: {orcid!r}")
        return parse_author(self.get(f"/authors/orcid:{oid}"), datetime.now(UTC))

    def get_author(self, author_id: str) -> Researcher:
        aid = parse_author_id(author_id)
        if not aid:
            raise ValueError(f"not an OpenAlex author id: {author_id!r}")
        return parse_author(self.get(f"/authors/{aid}"), datetime.now(UTC))

    # --- works ---

    def iter_works(self, author_id: str, per_page: int = 100) -> Iterator[Work]:
        """Every work attributed to the author, newest first, via cursor paging."""
        aid = parse_author_id(author_id)
        if not aid:
            raise ValueError(f"not an OpenAlex author id: {author_id!r}")
        cursor: str | None = "*"
        while cursor:
            data = self.get("/works", {
                "filter": f"author.id:{aid}",
                "sort": "publication_date:desc",
                "per-page": per_page,
                "cursor": cursor,
            })
            now = datetime.now(UTC)
            results = data.get("results", [])
            yield from (parse_work(w, now) for w in results)
            cursor = data.get("meta", {}).get("next_cursor") if results else None

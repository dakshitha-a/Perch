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

from perch.schemas import Organisation, Researcher, Topic, Work

SOURCE = "openalex"
API = "https://api.openalex.org"
# Temple University's OpenAlex institution id, read from /institutions on 2026-10-28.
TEMPLE_INSTITUTION_ID = "https://openalex.org/I84392919"
MAX_CANDIDATES = 3
# OpenAlex refuses more than 100 values in one OR filter (live 400, 2026-10-29).
MAX_OR_VALUES = 100
COMPANY_SELECT = ("id,title,publication_year,publication_date,doi,type,primary_location,"
                  "authorships,topics,primary_topic,cited_by_count,referenced_works")

ORCID_RE = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$")
AUTHOR_RE = re.compile(r"([Aa]\d+)$")  # a lower-case "a5026494099" is the same id (Q19)


def short_id(openalex_id: str) -> str:
    """'https://openalex.org/A123' -> 'A123'."""
    return openalex_id.rstrip("/").rsplit("/", 1)[-1]


def parse_orcid(text: str) -> str | None:
    m = ORCID_RE.search(text.strip())
    return m.group(1) if m else None


def orcid_ok(oid: str) -> bool:
    """The ORCID check character, ISO 7064 mod 11-2 over the first 15 digits (Q18). The
    all-zero placeholder fails it: its check digit would be 1."""
    digits = oid.replace("-", "")
    total = 0
    for d in digits[:15]:
        total = (total + int(d)) * 2
    check = (12 - total % 11) % 11
    return digits[15:] == ("X" if check == 10 else str(check))


ID_ATTEMPT = re.compile(r"(?:https?://(?:api\.)?openalex\.org/(?:authors/)?)?[Aa]\d+", re.I)
ID_OK = re.compile(r"(?:https?://(?:api\.)?openalex\.org/(?:authors/)?)?[Aa]\d{8,}", re.I)


def looks_like_author_id(text: str) -> bool:
    """The search box holds an OpenAlex author id, valid or not (R5)."""
    return bool(ID_ATTEMPT.fullmatch(text.strip()))


def author_id_ok(text: str) -> bool:
    """An A followed by at least eight digits: "A12" is refused before any lookup (R5)."""
    return bool(ID_OK.fullmatch(text.strip()))


def parse_author_id(text: str) -> str | None:
    m = AUTHOR_RE.search(text.strip())
    return m.group(1).upper() if m else None


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


def companies_on(raw: dict[str, Any], fetched_at: datetime) -> list[Organisation]:
    """Institutions of type 'company' on a work's authorships, one per id."""
    seen: dict[str, Organisation] = {}
    for a in raw.get("authorships") or []:
        for i in a.get("institutions") or []:
            if i.get("type") != "company" or not i.get("id") or i["id"] in seen:
                continue
            seen[i["id"]] = Organisation(
                id=i["id"], source=SOURCE, source_url=f"{API}/institutions/{short_id(i['id'])}",
                fetched_at=fetched_at, name=i.get("display_name") or short_id(i["id"]),
                type="company", country=i.get("country_code"),
                aliases=[i.get("display_name") or ""], institution_ids=[i["id"]],
                lineage=list(i.get("lineage") or []))
    return list(seen.values())


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
        """Every work attributed to the author, newest first.

        Uses page numbers: OpenAlex refuses cursor paging past the first page without
        an API key (live 401, 2026-10-28), while page=N works for anyone.
        """
        aid = parse_author_id(author_id)
        if not aid:
            raise ValueError(f"not an OpenAlex author id: {author_id!r}")
        page = 1
        while True:
            data = self.get("/works", {
                "filter": f"author.id:{aid}",
                "sort": "publication_date:desc",
                "per-page": per_page,
                "page": page,
            })
            now = datetime.now(UTC)
            results = data.get("results", [])
            for raw in results:
                work = parse_work(raw, now)
                # List responses cut authorships at about 100 (a 203-author work came back
                # with 98 ids, 2026-10-28). The author.id filter matched, so the author is
                # on the work even when the truncated list drops them.
                if f"https://openalex.org/{aid}" not in work.author_ids:
                    work.author_ids.append(f"https://openalex.org/{aid}")
                yield work
            count = data.get("meta", {}).get("count", 0)
            if not results or page * per_page >= count:
                return
            page += 1

    # --- Route B: company works ---

    def _company_pages(self, filt: str, max_pages: int,
                       per_page: int = 100) -> Iterator[tuple[Work, list[Organisation]]]:
        for page in range(1, max_pages + 1):
            data = self.get("/works", {"filter": f"{filt},authorships.institutions.type:company",
                                       "sort": "publication_date:desc", "per-page": per_page,
                                       "page": page, "select": COMPANY_SELECT})
            now = datetime.now(UTC)
            results = data.get("results", [])
            for raw in results:
                yield parse_work(raw, now), companies_on(raw, now)
            if not results or page * per_page >= data.get("meta", {}).get("count", 0):
                return

    def company_works_citing(self, work_ids: list[str], max_pages: int = 5
                             ) -> list[tuple[Work, list[Organisation]]]:
        """Works with a company author that cite any of work_ids, newest first. Ids go in
        chunks of 100, the OR-filter ceiling; each chunk reads at most max_pages of 100."""
        ids = [short_id(w) for w in work_ids]
        out: dict[str, tuple[Work, list[Organisation]]] = {}
        for i in range(0, len(ids), MAX_OR_VALUES):
            chunk = "|".join(ids[i:i + MAX_OR_VALUES])
            for w, orgs in self._company_pages(f"cites:{chunk}", max_pages):
                out.setdefault(w.id, (w, orgs))
        return list(out.values())

    def company_works_in_topics(self, topic_ids: list[str], since: date, until: date,
                                max_pages: int = 3) -> list[tuple[Work, list[Organisation]]]:
        """The newest works (at most max_pages of 100) with a company author whose primary
        topic is one of topic_ids, published between since and until."""
        topics = "|".join(short_id(t) for t in topic_ids[:MAX_OR_VALUES])
        filt = (f"primary_topic.id:{topics},from_publication_date:{since.isoformat()},"
                f"to_publication_date:{until.isoformat()}")
        return list(self._company_pages(filt, max_pages))


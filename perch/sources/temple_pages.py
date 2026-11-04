"""One-time reader for Temple's inventoried award pages (REBUILD_PLAN Phase 4 task 1).

Input is data/temple/inventory.csv. A row is read only when the inventory says http 200,
robots_allowed yes and sign_in_required no. Each page is fetched once, politely: at most
one request per second per host, robots.txt honoured, the Perch user agent, and retries
on 429 and 5xx that wait for Retry-After. Only `<main>` is kept, with safelinks unwrapped
(perch.sources.temple.main_only) and contacts scrubbed (`scrub_contacts`): mailto and tel
links, email addresses, phone numbers, and blocks that pair a staff role with a person's
name are removed. Award titles may name donors; staff names and contacts never stay.

Cleaned pages are cached under data/cache/temple_pages/ (gitignored, never committed).
Verified against live responses on 2026-11-04; counts are in docs/SOURCES.md.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from perch.sources.fellowship_details import MIN_INTERVAL, Fetcher
from perch.sources.temple import main_only

INVENTORY = Path("data/temple/inventory.csv")
CACHE_DIR = Path("data/cache/temple_pages")
RETRY_STATUS = (429, 500, 502, 503, 504)
MAX_RETRIES = 3
RETRY_CAP_S = 60.0

# --- contact scrubber -------------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+\s?(?:@|\[at\]|\(at\))\s?[\w-]+(?:\.[\w-]+)+", re.I)
_PHONE = re.compile(r"(?<![\d$,.])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
# mailto, tel and sms links, and Temple's obfuscated email links (/email/decode?...).
_MAILTO_HREF = r"(?:(?:mailto|tel|sms):|[^\"']*/email/decode)"
_MAILTO_A = re.compile(rf"<a\b[^>]*\bhref\s*=\s*[\"']{_MAILTO_HREF}[^\"']*[\"'][^>]*>.*?</a>",
                       re.I | re.S)
_MAILTO_ATTR = re.compile(rf"\s(?:href|data-[\w-]+)\s*=\s*[\"']{_MAILTO_HREF}[^\"']*[\"']", re.I)
_RANK = r"(?:(?:Associate|Assistant|Vice|Senior|Deputy|Executive|Interim)\s+)*"
_ROLE = (rf"{_RANK}(?:Director|Coordinator|Advis[eo]r|Manager|Specialist|Officer|Dean|Chair|"
         r"Provost|President|Administrator|Counselor|Representative|Professor|Lecturer|"
         r"Instructor|Liaison|Librarian|Staff|Head|Registrar|Secretary)")
_CAP = r"[A-Z][A-Za-z'’-]+"
_NAME = (r"(?:(?:Dr|Prof)\.?\s+)?(?:[A-Z]\.\s+)?[A-Z][A-Za-z'’-]+(?:\s+[A-Z]\.?)?\s+"
         r"[A-Z][A-Za-z'’-]{2,}")
# Words that make a capitalised pair an award, office or place and not a person.
_NOT_PERSON = re.compile(
    r"\b(?:Scholarship|Scholar|Award|Awards|Fellowship|Grant|Prize|Fund|Program|Programs|"
    r"Foundation|Memorial|Society|Institute|University|College|School|Center|Office|"
    r"Services|Studies|Department|Council|Association|Honors|Research|Resource|Temple|"
    r"Student|Students|Financial|Health|Science|Arts|Business|Law|Medicine|Education)\b")
_UNIT = re.compile(r"\b(?:College|School|Program|Office|Department|Center|Honors|Resource|"
                   r"Studies|Advising|Library|University|Professions|Institute)\b")
_STAFF = [
    re.compile(rf"{_NAME}\s*[,–—-]\s*(?:the\s+)?{_ROLE}\b"),   # Jane Doe, (the) Director
    re.compile(rf"\b{_ROLE}\b[^.\n]{{0,40}}?[:,–—-]\s*{_NAME}\b"),  # Director of X: Jane Doe
    re.compile(r"^\s*(?:Contact|Contacts|Questions\??)\s*[:\-–—]"),
    re.compile(r"\b(?:Dr|Prof)\.\s+[A-Z][a-z]+\s+[A-Z][a-z]+\s*[,(]"),
    re.compile(rf"\bContact\s+{_NAME}\b"),                      # Contact Emily Example
    re.compile(r"click-for-email", re.I),
    re.compile(rf"^{_NAME}\s*\(https?://[^)]*\)\s*\([A-Z]"),  # Jane Doe (url) (Dept) ...
    re.compile(rf"^{_NAME}\s*\([A-Z][\w ,&-]+\)\s+and\s+student\b"),
]
# "Rita Yip, Health Professions, College of Public Health": a person and a unit.
_PERSON_UNIT = re.compile(rf"^(?:[A-Za-z ]{{3,40}}:\s*)?({_NAME}),\s+(.{{3,}})$")
# A line that only gives a staff title: the name sits in the line before it.
_TITLE_ONLY = re.compile(rf"^(?:{_ROLE}(?:\s*(?:&|and|,|of|for|-|–)\s*[\w ,&]{{0,40}})?)\s*$", re.I)
_LABEL = re.compile(r"^(?:(?:Program|Campus|Faculty|Department|Primary)\s+)?Contacts?"
                    r"(?:\s+(?:Us|Information|Person))?\s*:?$|^Resources\s*&\s*Contact$"
                    r"|^(?:Our|Meet\s+(?:the|our))?\s*(?:Staff|Team)\s*:?$", re.I)
_BARE_NAME = re.compile(rf"^{_CAP}(?:\s+(?:[A-Z]\.?|{_CAP})){{1,3}}(?:,\s*[A-Za-z.]{{2,8}})?$")
_BLOCK_TAG = re.compile(
    r"</?(?:p|div|li|ul|ol|br|tr|td|th|table|section|article|main|h[1-6]|dt|dd|dl|"
    r"blockquote|aside|header|footer|hr|figure|figcaption|summary|details)\b[^>]*>", re.I)
_TOKEN = re.compile(r"<[^>]*>|[^<]+")


def _text(chunk: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", chunk))
    return " ".join(t.replace("\xa0", " ").replace("\u200b", "").split())


def _person_unit(text: str) -> bool:
    m = _PERSON_UNIT.match(text)
    return bool(m and not _NOT_PERSON.search(m.group(1)) and _UNIT.search(m.group(2)))


def is_contact_text(text: str) -> bool:
    """True when the text carries an email, a phone number, or a staff role beside a name
    or a person with a unit ("Rita Yip, Health Professions, College of Public Health")."""
    return bool(_EMAIL.search(text) or _PHONE.search(text) or _person_unit(text)
                or any(p.search(text) for p in _STAFF))


def _bare_person(text: str) -> bool:
    return bool(_BARE_NAME.match(text)) and not _NOT_PERSON.search(text) and len(text) < 50


def scrub_contacts(page: str) -> str:
    """The HTML without mailto, tel and obfuscated-email links, and without any text run
    (the text between two block tags) that holds an email, a phone number, a staff role
    beside a name, or a person with a unit. A run that is only a staff title ("Professor")
    also takes the name run before it; a "Contact" label takes the two short runs after
    it. Block tags are kept, so the result stays well formed."""
    page = _MAILTO_A.sub("", page)
    page = _MAILTO_ATTR.sub("", page)
    items: list[tuple[bool, str]] = []  # (is_text_run, html)
    run: list[str] = []

    def flush() -> None:
        chunk = "".join(run)
        run.clear()
        if chunk:
            items.append((True, chunk))

    for m in _TOKEN.finditer(page):
        tok = m.group(0)
        if _BLOCK_TAG.fullmatch(tok):
            flush()
            items.append((False, tok))
        else:
            run.append(tok)
    flush()
    drop: set[int] = set()
    text_ix = [i for i, (is_t, c) in enumerate(items) if is_t and _text(c)]
    for k, i in enumerate(text_ix):
        t = _text(items[i][1])
        if is_contact_text(t):
            drop.add(i)
        elif _bare_person(t) and "<a" not in items[i][1].lower():
            drop.add(i)  # a lone person name (staff list, winner list); links are titles
        elif _TITLE_ONLY.match(t):
            drop.add(i)
            if k and _bare_person(_text(items[text_ix[k - 1]][1])):
                drop.add(text_ix[k - 1])
        elif _LABEL.match(t):
            drop.add(i)
            for j in text_ix[k + 1:k + 3]:
                if len(_text(items[j][1])) <= 120:
                    drop.add(j)
                else:
                    break
    cleaned = "".join(c for i, (_, c) in enumerate(items) if i not in drop)
    cleaned = _EMAIL.sub("", cleaned)  # an email inside an attribute or split text
    return _PHONE.sub("", cleaned)


def clean_page(page: str) -> str:
    """`<main>` only, safelinks unwrapped, scripts and styles removed, contacts scrubbed."""
    return scrub_contacts(main_only(page))


def rescrub_cache(cache_dir: Path = CACHE_DIR) -> int:
    """Apply the current scrubber to every cached page again; returns pages changed."""
    n = 0
    for p in sorted(cache_dir.glob("*.html")):
        old = p.read_text("utf-8")
        new = scrub_contacts(old)
        if new != old:
            p.write_text(new, encoding="utf-8")
            n += 1
    return n


# --- inventory --------------------------------------------------------------------

def read_inventory(path: Path = INVENTORY) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def skip_reason(row: dict) -> str | None:
    """Why the reader does not fetch this row, or None when it may."""
    if row.get("sign_in_required") != "no":
        return "sign_in_required_or_unknown"
    if row.get("robots_allowed") != "yes":
        return "robots_not_allowed_or_unknown"
    if row.get("http_status") != "200":
        return "no_http_200_in_inventory"
    return None


def page_path(url: str, cache_dir: Path = CACHE_DIR) -> Path:
    return cache_dir / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")


# --- fetching ---------------------------------------------------------------------

@dataclass
class ReadReport:
    total: int = 0
    fetched: int = 0
    cached: int = 0
    skipped: Counter = field(default_factory=Counter)
    failed: list[tuple[str, str]] = field(default_factory=list)
    robots_blocked: list[str] = field(default_factory=list)
    retries: int = 0

    def lines(self) -> list[str]:
        sk = ", ".join(f"{k}: {v}" for k, v in sorted(self.skipped.items())) or "none"
        out = [f"Inventory rows: {self.total}. Fetched: {self.fetched}. "
               f"Already cached: {self.cached}. Failed: {len(self.failed)}.",
               f"Skipped by reason: {sk}.",
               f"Retries after 429 or 5xx: {self.retries}."]
        out += [f"  failed {u}: {why}" for u, why in self.failed]
        out += [f"  robots disallowed at fetch time: {u}" for u in self.robots_blocked]
        return out


def _retry_after(r: httpx.Response, attempt: int) -> float:
    v = r.headers.get("retry-after", "")
    try:
        return min(float(v), RETRY_CAP_S)
    except ValueError:
        return min(2.0 ** attempt, RETRY_CAP_S)


def get_with_retry(fetcher: Fetcher, url: str, report: ReadReport | None = None,
                   sleep: Callable[[float], None] = time.sleep) -> tuple[str, str]:
    """Fetcher.get, retrying 429 and 5xx up to MAX_RETRIES times after Retry-After."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return fetcher.get(url)
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in RETRY_STATUS or attempt == MAX_RETRIES:
                raise
            fetcher.pages.pop(url, None)
            if report:
                report.retries += 1
            sleep(_retry_after(e.response, attempt))
        except httpx.TransportError:
            if attempt == MAX_RETRIES:
                raise
            fetcher.pages.pop(url, None)
            if report:
                report.retries += 1
            sleep(min(2.0 ** attempt, RETRY_CAP_S))
    raise AssertionError("unreachable")


def read_pages(rows: list[dict], cache_dir: Path = CACHE_DIR, fetcher: Fetcher | None = None,
               limit: int | None = None, refresh: bool = False,
               sleep: Callable[[float], None] = time.sleep) -> ReadReport:
    """Fetch every eligible row, write cleaned pages and a manifest.jsonl to cache_dir."""
    f = fetcher or Fetcher()
    rep = ReadReport(total=len(rows))
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = cache_dir / "manifest.jsonl"
    done: dict[str, dict] = {}
    if manifest.is_file():
        for ln in manifest.read_text("utf-8").splitlines():
            if ln.strip():
                d = json.loads(ln)
                done[d["url"]] = d
    n = 0
    for row in rows:
        why = skip_reason(row)
        if why:
            rep.skipped[why] += 1
            continue
        url = row["url"]
        if url in done and not refresh and page_path(url, cache_dir).is_file():
            rep.cached += 1
            continue
        if limit is not None and n >= limit:
            rep.skipped["over_limit"] += 1
            continue
        n += 1
        if not f.allowed(url):
            rep.skipped["robots_disallow_at_fetch"] += 1
            rep.robots_blocked.append(url)
            continue
        try:
            final, html_text = get_with_retry(f, url, rep, sleep)
        except (httpx.HTTPError, ValueError) as e:
            rep.failed.append((url, f"{type(e).__name__}: {e}"[:160]))
            continue
        if urlparse(final).netloc.lower() != urlparse(url).netloc.lower() and not f.allowed(final):
            rep.skipped["redirect_to_disallowed_host"] += 1
            continue
        cleaned = clean_page(html_text)
        page_path(url, cache_dir).write_text(cleaned, encoding="utf-8")
        done[url] = {"url": url, "final_url": final, "owner": row["owner"],
                     "audience": row["audience"], "kind": row["kind"],
                     "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                     "file": page_path(url, cache_dir).name, "bytes": len(cleaned)}
        rep.fetched += 1
    with manifest.open("w", encoding="utf-8") as fh:
        for d in done.values():
            fh.write(json.dumps(d) + "\n")
    return rep


def load_cached(cache_dir: Path = CACHE_DIR) -> list[tuple[dict, str]]:
    """(manifest entry, cleaned HTML) for every cached page."""
    manifest = cache_dir / "manifest.jsonl"
    if not manifest.is_file():
        return []
    out = []
    for ln in manifest.read_text("utf-8").splitlines():
        if ln.strip():
            d = json.loads(ln)
            p = cache_dir / d["file"]
            if p.is_file():
                out.append((d, p.read_text("utf-8")))
    return out


__all__ = ["MIN_INTERVAL", "ReadReport", "clean_page", "is_contact_text", "load_cached",
           "read_inventory", "read_pages", "scrub_contacts", "skip_reason"]

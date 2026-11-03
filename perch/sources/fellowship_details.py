"""Deadlines and award amounts for the public fellowship records, read from each
record's own linked page (S34 follow-up, decision of 2026-11-02).

The SDFA list (perch/sources/temple.py) states no deadline or amount. Each record's
`source_url` is the award's own page, on SDFA or on the sponsor's site. This module
fetches exactly that one page per record, no crawl, and copies a value only when a
fixed rule finds it in a sentence of the page. Code does the copying; no model reads
the page. A value is stored with the exact sentence (the quote), the final page URL
and the fetch time, and the Scholarship validator refuses a value without them.

Politeness: one request per second per host at most, the Perch user agent, robots.txt
read once per host (a disallow, or a robots file that cannot be read, skips the host's
records and counts them). Verified live on 2026-11-02; terms and counts in
docs/SOURCES.md.
"""

from __future__ import annotations

import html
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from urllib import robotparser
from urllib.parse import urlparse

import httpx

from perch.schemas import Scholarship
from perch.sources.temple import SOURCE, UA

TIMEOUT = 20
MAX_BYTES = 3_000_000
MIN_INTERVAL = 1.0
QUOTE_MAX = 300

# --- HTML to text -----------------------------------------------------------------

_SKIP = {"script", "style", "nav", "footer", "noscript", "svg", "head", "template", "form",
         "button", "select", "iframe"}
_BLOCK = {"p", "div", "li", "ul", "ol", "br", "tr", "td", "th", "table", "section", "article",
          "main", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "dl", "blockquote", "aside",
          "header", "hr", "figure", "figcaption", "summary", "details", "body", "html"}
_VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source",
         "track", "wbr"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP and tag not in _VOID:
            self.skip += 1
        if tag in _BLOCK:
            self.out.append("\n")

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        if tag in _BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self.skip:
            self.skip -= 1
        if tag in _BLOCK:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(data)


def _region(page: str) -> str:
    """Prefer <main>, then <article>; a region with almost no text falls back to the page."""
    for tag in ("main", "article"):
        m = re.search(rf"<{tag}\b.*?</{tag}>", page, re.S | re.I)
        if m and len(re.sub(r"<[^>]+>", "", m.group(0)).strip()) > 200:
            return m.group(0)
    return page


def html_to_lines(page: str) -> list[str]:
    """Visible text of the page's main region, one non-empty line per block element."""
    p = _Text()
    p.feed(_region(page))
    p.close()
    text = html.unescape("".join(p.out)).replace("\xa0", " ")
    lines = (" ".join(ln.split()) for ln in text.split("\n"))
    return [ln for ln in lines if ln]


_ABBREV = re.compile(r"(?:\b(?:[A-Z][a-z]?|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|"
                     r"No|Dr|Mr|Mrs|Ms|St|vs|etc|e\.g|i\.e|approx)\.)$")


def split_sentences(lines: list[str]) -> list[str]:
    """Sentences: each line split after . ! ? when a capital follows, except after an
    abbreviation or a month abbreviation ("Oct. 7, 2026")."""
    out: list[str] = []
    for ln in lines:
        start = 0
        for m in re.finditer(r"[.!?][\"')\]]*\s+(?=[A-Z0-9\"'(])", ln):
            head = ln[start:m.start() + 1]
            if _ABBREV.search(head) or re.search(r"\b[A-Z]\.[A-Z]$", head):
                continue
            out.append(ln[start:m.end()].strip())
            start = m.end()
        out.append(ln[start:].strip())
    return [s for s in out if s]


# --- dates ------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MON = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
        r"Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_DATE_RES = [
    # October 7, 2026 / Oct. 7th, 2026 / October 7 2026
    re.compile(rf"\b(?P<mon>{_MON})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>20\d\d)\b"),
    # 7 October 2026 / 7th of October, 2026
    re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{_MON})\.?,?\s+"
               r"(?P<y>20\d\d)\b"),
    # 2026-10-07
    re.compile(r"\b(?P<y>20\d\d)-(?P<m>\d{2})-(?P<d>\d{2})\b"),
    # 10/7/2026
    re.compile(r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>20\d\d)\b"),
]


@dataclass
class Found:
    value: date
    start: int
    end: int


def find_dates(s: str) -> list[Found]:
    """Every full date with a year in the sentence. A year is never inferred."""
    out: dict[tuple[int, int], Found] = {}
    for rx in _DATE_RES:
        for m in rx.finditer(s):
            g = m.groupdict()
            mon = int(g["m"]) if g.get("m") else _MONTHS[g["mon"][:3].lower()]
            try:
                d = date(int(g["y"]), mon, int(g["d"]))
            except ValueError:
                continue
            out.setdefault((m.start(), m.end()), Found(d, m.start(), m.end()))
    return sorted(out.values(), key=lambda f: f.start)


_DEADLINE_KW = re.compile(
    r"\b(?:deadlines?|due|applications?\s+(?:close|closes|are\s+due|must\s+be\s+(?:submitted|received))"
    r"|submit\s+by|apply\s+by|closes?\s+on|must\s+be\s+(?:submitted|received)\s+by"
    r"|postmarked\s+by|no\s+later\s+than)\b", re.I)
_CAMPUS = re.compile(r"\b(?:temple|campus|internal|on-campus|sdfa|nomination|endorsement|"
                     r"institutional)\b", re.I)
# A date after these words, within the same clause, is not the application deadline.
_NOT_DEADLINE = re.compile(
    r"\b(?:open|opens|opened|opening|begin|begins|start|starts|launch|launches|available|"
    r"notif\w*|announc\w*|accept\w*|recipients?|webinar|information\s+session|info\s+session|"
    r"workshop|event|orientation|decisions?|interviews?|released?|posted|updated|"
    r"last\s+updated|copyright|effective|term\s+begins|program\s+begins|departure|"
    r"travel|commence\w*)\b", re.I)


# These awards are listed for students; a deadline for faculty or staff is another call.
_NOT_STUDENT = re.compile(r"\b(?:faculty|staff|tenure\w*|postdoc\w*)\b", re.I)
# "The deadline for these regions is ..." depends on the sentence before it, so the quote
# carries both.
_REFERS_BACK = re.compile(r"\bfor\s+(?:these|those|the\s+above|this)\b", re.I)


def _clip(s: str, start: int, end: int) -> str:
    """The sentence, or, when long, a window of at most QUOTE_MAX characters around the
    match. Always contains s[start:end]."""
    if len(s) <= QUOTE_MAX:
        return s
    pad = (QUOTE_MAX - 6 - (end - start)) // 2
    a = max(0, start - pad)
    b = min(len(s), a + QUOTE_MAX - 6)
    a = max(0, b - (QUOTE_MAX - 6))
    if a > 0:  # snap to a word boundary without cutting the match
        k = s.find(" ", a)
        a = k + 1 if 0 <= k < start else a
    if b < len(s):
        k = s.rfind(" ", end, b)
        b = k if k > 0 else b
    return ("… " if a > 0 else "") + s[a:b].strip() + (" …" if b < len(s) else "")


def extract_deadline(lines: list[str], today: date) -> tuple[date, str] | None:
    """The deadline a Temple student must meet, or None. Sentences with a deadline
    keyword and a full dated future day; a campus deadline beats a sponsor one; then
    the earliest."""
    sents = split_sentences(lines)
    # A heading line that is only the keyword ("Application Deadline") takes the next line.
    merged: list[str] = []
    i = 0
    while i < len(sents):
        s = sents[i]
        if (len(s) <= 60 and _DEADLINE_KW.search(s) and not find_dates(s)
                and i + 1 < len(sents) and find_dates(sents[i + 1])):
            merged.append(f"{s.rstrip(':')}: {sents[i + 1]}")
            i += 2
            continue
        merged.append(s)
        i += 1
    cands: list[tuple[bool, date, str]] = []
    for i, s in enumerate(merged):
        kw = _DEADLINE_KW.search(s)
        if not kw or _NOT_STUDENT.search(s):
            continue
        for f in find_dates(s):
            if f.value < today:
                continue
            # The words between the nearest deadline keyword (or the previous date) and
            # this date: "notified by", "opens on" and the like make it another date.
            prev = max([g.end for g in find_dates(s) if g.end <= f.start] or [0])
            kws = [k.end() for k in _DEADLINE_KW.finditer(s[:f.start]) if k.end() > prev]
            ctx = s[max(kws) if kws else prev:f.start][-70:]
            if _NOT_DEADLINE.search(ctx):
                continue
            quote = _clip(s, f.start, f.end)
            if _REFERS_BACK.search(s) and i > 0 and len(merged[i - 1]) + len(s) < QUOTE_MAX:
                quote = f"{merged[i - 1]} {s}"
            cands.append((bool(_CAMPUS.search(s)), f.value, quote))
    if not cands:
        return None
    campus = [c for c in cands if c[0]]
    pick = min(campus or cands, key=lambda c: c[1])
    return pick[1], pick[2]


# --- amounts ----------------------------------------------------------------------

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:\.\d{2})?"
_USD = re.compile(rf"(?:US\s?)?\$\s?(?P<n>{_NUM})(?!\d)|\b(?:USD)\s?(?P<n2>{_NUM})(?!\d)"
                  rf"|(?<![\d,.])(?P<n3>{_NUM})\s?USD\b")
_OTHER = re.compile(r"[€£¥₹]|\b(?:EUR|GBP|CAD|AUD|CHF|JPY|euros?|pounds)\b|\b[A-Z]{2,3}\$", re.I)
_AWARD_KW = re.compile(r"\b(?:award\w*|stipend\w*|scholarship\w*|fellowship\w*|grants?|funding|"
                       r"funds?|prizes?|up\s+to|worth)\b", re.I)
_SKIP_KW = re.compile(r"\b(?:millions?|billions?|fees?|costs?|charges?d?|tuition|salary|"
                      r"salaries|per\s+(?:month|week|year|semester|day|term|hour)|monthly|weekly|"
                      r"annually|yearly|a\s+(?:month|year|week))\b", re.I)
_UPTO = re.compile(r"\bup\s+to\s+(?:a\s+(?:total|maximum)\s+of\s+|an?\s+)?$", re.I)
_RANGE = re.compile(r"^\s*(?:to|[-–—]|and)\s*(?:US\s?)?\$\s?(?P<n>" + _NUM + r")(?!\d)", re.I)
_BETWEEN = re.compile(r"\bbetween\s*$", re.I)


@dataclass
class AmountResult:
    values: set[tuple[float | None, float | None]] = field(default_factory=set)
    quotes: dict[tuple[float | None, float | None], str] = field(default_factory=dict)
    non_usd: bool = False


def _num(x: str) -> float:
    return float(x.replace(",", ""))


def extract_amounts(lines: list[str]) -> AmountResult:
    res = AmountResult()
    for s in split_sentences(lines):
        if not _AWARD_KW.search(s):
            continue
        usd = list(_USD.finditer(s))
        if not usd:
            if _OTHER.search(s):
                res.non_usd = True
            continue
        if _SKIP_KW.search(s):
            continue
        used_end = -1
        for m in usd:
            if m.start() < used_end:
                continue
            n = _num(m.group("n") or m.group("n2") or m.group("n3"))
            if n <= 0:
                continue
            lo: float | None = n
            hi: float | None = n
            end = m.end()
            r = _RANGE.match(s[m.end():])
            if r and r.group(0).lstrip().lower().startswith("and") \
                    and not _BETWEEN.search(s[:m.start()]):
                r = None  # "$1,000 and $2,500" without "between" is two amounts
            if r:
                n2 = _num(r.group("n"))
                lo, hi = (min(n, n2), max(n, n2))
                end = m.end() + r.end()
                used_end = end
            elif _UPTO.search(s[:m.start()]):
                lo, hi = None, n
            key = (lo, hi)
            res.values.add(key)
            res.quotes.setdefault(key, _clip(s, m.start(), end))
    return res


# --- fetching ---------------------------------------------------------------------

@dataclass
class Report:
    total: int = 0
    fetched: int = 0
    robots_skipped: int = 0
    errors: int = 0
    deadlines: int = 0
    amounts: int = 0
    ambiguous: int = 0
    non_usd: int = 0
    hosts: dict[str, int] = field(default_factory=dict)
    skipped_hosts: list[str] = field(default_factory=list)
    error_notes: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [f"Of {self.total} fellowship records: {self.fetched} pages fetched, "
               f"{self.robots_skipped} skipped by robots.txt, {self.errors} errors.",
               f"Deadlines found: {self.deadlines}. Amounts found: {self.amounts}. "
               f"Amounts ambiguous (none kept): {self.ambiguous}. "
               f"Non-USD amounts skipped: {self.non_usd}.",
               f"Hosts reached: {len(self.hosts)}."]
        if self.skipped_hosts:
            out.append("Skipped hosts: " + ", ".join(sorted(set(self.skipped_hosts))))
        out += self.error_notes
        return out


class Fetcher:
    """One GET per page, robots.txt per host, a minimum gap between requests to a host."""

    def __init__(self, client: httpx.Client | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.client = client or httpx.Client(headers=UA, timeout=TIMEOUT, follow_redirects=True,
                                             max_redirects=5)
        self.clock, self.sleep = clock, sleep
        self.last: dict[str, float] = {}
        self.robots: dict[str, robotparser.RobotFileParser | None] = {}
        self.pages: dict[str, tuple[str, str] | Exception] = {}

    def _wait(self, host: str) -> None:
        gap = MIN_INTERVAL - (self.clock() - self.last.get(host, -1e9))
        if gap > 0:
            self.sleep(gap)
        self.last[host] = self.clock()

    def allowed(self, url: str) -> bool:
        u = urlparse(url)
        host = u.netloc.lower()
        if host not in self.robots:
            rp: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
            try:
                self._wait(host)
                r = self.client.get(f"{u.scheme}://{u.netloc}/robots.txt")
                if r.status_code in (401, 403):
                    rp.disallow_all = True  # type: ignore[union-attr]
                elif r.status_code == 404 or r.status_code == 410:
                    rp.allow_all = True  # type: ignore[union-attr]
                elif r.status_code == 200:
                    rp.parse(r.text.splitlines())  # type: ignore[union-attr]
                else:
                    rp = None
            except httpx.HTTPError:
                rp = None
            self.robots[host] = rp
        rp = self.robots[host]
        return bool(rp and rp.can_fetch("perch", url))

    def get(self, url: str) -> tuple[str, str]:
        """(final URL, HTML). Raises on any failure; cached within the run."""
        c = self.pages.get(url)
        if isinstance(c, Exception):
            raise c
        if c:
            return c
        try:
            self._wait(urlparse(url).netloc.lower())
            r = self.client.get(url)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "html" not in ctype.lower():
                raise ValueError(f"not an HTML page ({ctype or 'no content type'})")
            if len(r.content) > MAX_BYTES:
                raise ValueError("page too large")
            c = (str(r.url), r.text)
        except (httpx.HTTPError, ValueError) as e:
            self.pages[url] = e
            raise
        self.pages[url] = c
        return c


# A page that says the award is over keeps no value: a figure on it may belong to the part
# that ended (a record can list several awards on one page).
_ENDED = re.compile(r"\b(?:terminated|discontinued|suspended|cancel+ed|on\s+hiatus|"
                    r"no\s+longer\s+(?:accepting|offered|available|awarded))\b", re.I)


def apply_page(rec: Scholarship, final_url: str, page: str, now: datetime,
               report: Report | None = None) -> Scholarship:
    """The record with deadline and amount filled from the page's text, or left None."""
    lines = html_to_lines(page)
    if any(_ENDED.search(ln) for ln in lines):
        lines = []
    today = now.astimezone(UTC).date()
    upd: dict = {"details_url": final_url, "details_fetched_at": now, "deadline": None,
                 "deadline_quote": None, "amount_min": None, "amount_max": None,
                 "amount_quote": None}
    dl = extract_deadline(lines, today)
    if dl:
        upd["deadline"], upd["deadline_quote"] = dl
    am = extract_amounts(lines)
    if len(am.values) == 1:
        key = next(iter(am.values))
        upd["amount_min"], upd["amount_max"] = key
        upd["amount_quote"] = am.quotes[key]
    elif len(am.values) > 1 and report:
        report.ambiguous += 1
    if not am.values and am.non_usd and report:
        report.non_usd += 1
    data = rec.model_dump()
    data.update(upd)
    return Scholarship.model_validate(data)


def fill_details(records: list[Scholarship], fetcher: Fetcher | None = None,
                 now: datetime | None = None, pages_dir: str | None = None
                 ) -> tuple[list[Scholarship], Report]:
    """Fill the temple_sdfa records from their own pages. Other records pass through
    untouched. A record whose page could not be read keeps what it had."""
    f = fetcher or Fetcher()
    now = now or datetime.now(UTC)
    rep = Report()
    out: list[Scholarship] = []
    for rec in records:
        if rec.source != SOURCE or rec.synthetic:
            out.append(rec)
            continue
        rep.total += 1
        host = urlparse(rec.source_url).netloc.lower()
        if not f.allowed(rec.source_url):
            rep.robots_skipped += 1
            rep.skipped_hosts.append(host)
            out.append(rec)
            continue
        try:
            final, page = f.get(rec.source_url)
        except (httpx.HTTPError, ValueError) as e:
            rep.errors += 1
            why = (str(e).splitlines() or [""])[0][:90]
            rep.error_notes.append(f"error: {host}: {type(e).__name__} {why}")
            out.append(rec)
            continue
        rep.fetched += 1
        rep.hosts[host] = rep.hosts.get(host, 0) + 1
        new = apply_page(rec, final, page, now, rep)
        if pages_dir:
            import pathlib
            p = pathlib.Path(pages_dir)
            p.mkdir(parents=True, exist_ok=True)
            (p / f"{rec.id.replace(':', '_').replace('/', '_')}.txt").write_text(
                "\n".join(html_to_lines(page)), encoding="utf-8")
        rep.deadlines += new.deadline is not None
        rep.amounts += new.amount_min is not None or new.amount_max is not None
        out.append(new)
    return out, rep

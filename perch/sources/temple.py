"""Temple's public fellowship list (SDFA), read from one listing page. No crawl.

Verified live on 2026-10-29; fixtures in tests/fixtures/temple/, URLs and terms in
docs/SOURCES.md. The Scholar Development and Fellowships Advising (SDFA) page
"Find a Fellowship" lists each award under a group ("For Study in the United
Kingdom/Ireland", "STEM", ...) and a heading that names who may apply ("For seniors
and recent alumni"). The page states no amounts or deadlines, so a record carries
none; the student is sent to the award's own page for those.

Level and class year are copied from the heading by a fixed table (HEADINGS). A
heading not in the table leaves both empty, which student mode reads as "not stated".
Saved fixtures keep only `<main>`, with Outlook safelinks unwrapped, so no staff
address reaches the repo.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from perch.schemas import Scholarship, ScholarshipEligibility

SOURCE = "temple_sdfa"
SDFA_HOME = "https://undergraduate.temple.edu/fellowships"
SDFA_LIST = "https://undergraduate.temple.edu/find-fellowship"
SDFA_NAME = "Scholar Development and Fellowships Advising"
SFS_HOME = "https://sfs.temple.edu/"
SFS_SCHOLARSHIPS = ("https://sfs.temple.edu/financial-aid-types/scholarships/"
                    "scholarship-opportunities-temple")
SFS_NAME = "Student Financial Services"
UA = {"User-Agent": "perch (Temple AI Build Challenge prototype)"}

# Heading text (lower case, trailing dot dropped) -> (levels, undergraduate class years).
# "Recent alumni" has no class year; such a record also carries the heading in notes.
HEADINGS: dict[str, tuple[list[str], list[int]]] = {
    "for first-year undergraduates, sophomores, or juniors": (["bachelor's"], [1, 2, 3]),
    "for seniors and recent alumni": (["bachelor's"], [4]),
    "for seniors, recent alumni, and graduate students": (["bachelor's", "graduate"], [4]),
    "for graduate students": (["graduate"], []),
    "for current graduate students": (["graduate"], []),
}
# Groups that list search tools and databases, not awards.
SKIP_GROUPS = {"other scholarship and fellowship databases"}
# Groups under "Opportunities by category" that name a field of study.
FIELD_GROUPS = {"stem": "STEM",
                "public policy, public service and federal service": "public policy"}


def fetch(url: str, client: httpx.Client | None = None) -> str:
    c = client or httpx.Client(headers=UA, timeout=30, follow_redirects=True)
    r = c.get(url)
    r.raise_for_status()
    return r.text


def main_only(page: str) -> str:
    """The page's <main> element, scripts removed and safelinks unwrapped, for fixtures."""
    m = re.search(r"<main.*?</main>", page, re.S)
    t = m.group(0) if m else page
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S)

    def unwrap(m: re.Match) -> str:
        q = parse_qs(urlparse(html.unescape(m.group(1))).query)
        return f'href="{html.escape(q.get("url", [""])[0])}"'

    t = re.sub(r'href="(https://[a-z0-9]+\.safelinks\.protection\.outlook\.com/[^"]*)"',
               unwrap, t)
    # Any other attribute holding a safelink (a title, say) is dropped whole.
    return re.sub(r'\s[a-z-]+="https://[a-z0-9]+\.safelinks\.protection\.outlook\.com/[^"]*"',
                  "", t)


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _same(name: str) -> str:
    """A key that matches "Diamond Peer Teachers" with "Diamond Peer Teachers Program"
    and "... Program (URP)": the page lists some awards twice under slightly different
    names."""
    return _slug(re.sub(r"\(.*?\)|\bprogram\b|,", " ", name.lower()))


def parse_listing(page: str, fetched_at: datetime | None = None,
                  url: str = SDFA_LIST) -> list[Scholarship]:
    """One record per award link, its levels and fields merged across every place the
    page lists it. Names, links and headings are copied; nothing is inferred."""
    at = fetched_at or datetime.now(UTC)
    t = main_only(page)
    start = t.find("Opportunities by Location")
    t = t[start:] if start >= 0 else t
    found: dict[str, dict] = {}
    by_name: dict[str, str] = {}
    group = ""
    heading = ""
    in_category = False
    token = re.compile(r'<a href="#" class="--trigger">(.*?)</a>|<h2>(.*?)</h2>|<li>(.*?)</li>'
                       r'|(Opportunities by category)', re.S)
    for m in token.finditer(t):
        if m.group(4):
            in_category = True
        elif m.group(1) is not None:
            group, heading = _text(m.group(1)), ""
        elif m.group(2) is not None:
            heading = _text(m.group(2)).rstrip(".")
        elif m.group(3) is not None:
            li = m.group(3)
            anchors = re.findall(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', li, re.S)
            if not anchors:
                continue
            name = "".join(_text(a[1]) for a in anchors if a[0] == anchors[0][0]).strip()
            if not name:
                continue
            if group.lower() in SKIP_GROUPS:
                continue
            rest = _text(re.sub(r"<a [^>]*>.*?</a>", "", li, flags=re.S))
            href = urljoin(url, anchors[0][0])
            # One award can be listed in several places, by link or by the same name.
            key = by_name.setdefault(_same(name), href.rstrip("/").lower())
            x = found.setdefault(key, {
                "name": name, "href": href, "levels": [],
                "years": [], "fields": [], "listed": [], "intl": False, "notes": []})
            if len(name) < len(x["name"]):
                x["name"] = name
            levels, years = HEADINGS.get((heading or group).lower(), ([], []))
            x["levels"] += [v for v in levels if v not in x["levels"]]
            x["years"] += [v for v in years if v not in x["years"]]
            f = FIELD_GROUPS.get(group.lower()) if in_category else None
            if f and f not in x["fields"]:
                x["fields"].append(f)
            where = " / ".join(p for p in (group, heading) if p)
            if where and where not in x["listed"]:
                x["listed"].append(where)
            x["intl"] = x["intl"] or "*" in rest
            note = rest.replace("*", "").strip(" ()")
            if note and note not in x["notes"]:
                x["notes"].append(note)
    out = []
    for x in found.values():
        notes = "Listed under: " + "; ".join(x["listed"]) + "."
        if x["notes"]:
            notes += " Page note: " + "; ".join(x["notes"]) + "."
        out.append(Scholarship(
            id=f"{SOURCE}:{_slug(x['name'])}", source=SOURCE, source_url=x["href"], fetched_at=at,
            name=x["name"], sponsor=None, level_of_study=x["levels"],
            field_of_study=x["fields"], award_type=None,
            eligibility=ScholarshipEligibility(class_year=sorted(x["years"]), notes=notes),
            international_ok=True if x["intl"] else None))
    return sorted(out, key=lambda s: s.id)

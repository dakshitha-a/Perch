"""The Temple page reader and its contact scrubber. SYNTHETIC pages only; no network."""

import json
from pathlib import Path

import httpx

from perch.sources import temple_pages as tp
from perch.sources.fellowship_details import Fetcher

PAGE = """<html><head><title>x</title></head><body><nav>Menu jane.nav{AT}example.org</nav>
<main>
<h1>Sample Awards</h1>
<p>The Quill Family Memorial Scholarship offers $2,500 to juniors.</p>
<p>Questions? Email <a href="mailto:sam.sample{AT}example.org">Sam Sample</a>.</p>
<p>Call 215-555-0100 for help.</p>
<ul><li>Pat Placeholder, Director of Awards</li><li>Director of Awards: Alex Example</li></ul>
<p>Contact: the SYNTHETIC office</p>
<p>Reach us at <a href="tel:+12155550100">the desk</a> any time.</p>
<p>The Dean's Scholarship closes March 1.</p>
<p><a href="https://www.outlook.example/x">Apply here</a></p>
</main><footer>f{AT}example.org</footer></body></html>"""
PAGE = PAGE.replace("{AT}", "@")


def test_scrub_removes_contacts_and_keeps_awards():
    out = tp.clean_page(PAGE)
    for gone in ("example.org", "Sam Sample", "215-555", "Pat Placeholder", "Alex Example",
                 "mailto", "tel:", "Contact:", "jane.nav", "f@"):
        assert gone not in out, gone
    # Award titles that name a donor, and a title with a role word, survive.
    assert "Quill Family Memorial Scholarship" in out
    assert "Dean's Scholarship closes March 1." in out
    assert "https://www.outlook.example/x" in out
    assert "<main" in out


def test_scrub_is_idempotent_and_well_formed():
    once = tp.clean_page(PAGE)
    assert tp.scrub_contacts(once) == once
    assert once.count("<p>") == once.count("</p>")


def test_dollar_amounts_and_dates_are_not_phones():
    s = "<main><p>Awards of $1,000 to $5,000. Deadline 2026-10-07 or 10/7/2026.</p></main>"
    assert "$1,000 to $5,000" in tp.scrub_contacts(s)
    assert "2026-10-07" in tp.scrub_contacts(s)


def test_skip_reasons():
    ok = {"sign_in_required": "no", "robots_allowed": "yes", "http_status": "200"}
    assert tp.skip_reason(ok) is None
    assert tp.skip_reason({**ok, "sign_in_required": "yes"}) == "sign_in_required_or_unknown"
    assert tp.skip_reason({**ok, "robots_allowed": ""}) == "robots_not_allowed_or_unknown"
    assert tp.skip_reason({**ok, "http_status": ""}) == "no_http_200_in_inventory"


def _fetcher(handler, sleeps):
    clock = {"t": 0.0}

    def sleep(s):
        sleeps.append(s)
        clock["t"] += s

    return Fetcher(client=httpx.Client(transport=httpx.MockTransport(handler)),
                   clock=lambda: clock["t"], sleep=sleep), sleep


def test_read_pages_polite_retries_robots_and_cache(tmp_path: Path):
    calls: list[str] = []
    state = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        if req.url.path == "/a":
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "7"})
            return httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})
        return httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})

    sleeps: list[float] = []
    f, sleep = _fetcher(handler, sleeps)
    base = {"sign_in_required": "no", "robots_allowed": "yes", "http_status": "200",
            "owner": "SYNTHETIC Office", "audience": "mixed", "kind": "award_page"}
    rows = [{**base, "url": "https://sample.example/a"},
            {**base, "url": "https://sample.example/private/b"},
            {**base, "url": "https://sample.example/c", "http_status": ""},
            {**base, "url": "https://sample.example/d", "sign_in_required": "yes"}]
    rep = tp.read_pages(rows, tmp_path, fetcher=f, sleep=sleep)
    assert rep.fetched == 1 and rep.retries == 1 and not rep.failed
    assert 7 in sleeps  # Retry-After honoured
    assert "/private/b" not in calls  # robots.txt honoured
    assert rep.skipped["robots_disallow_at_fetch"] == 1
    assert rep.skipped["no_http_200_in_inventory"] == 1
    assert rep.skipped["sign_in_required_or_unknown"] == 1
    pages = tp.load_cached(tmp_path)
    assert len(pages) == 1 and "sam.sample" not in pages[0][1]
    assert json.loads((tmp_path / "manifest.jsonl").read_text())["owner"] == "SYNTHETIC Office"
    # A second run reads the cache, not the network.
    n = len(calls)
    rep2 = tp.read_pages(rows, tmp_path, fetcher=f, sleep=sleep)
    assert rep2.cached == 1 and rep2.fetched == 0 and calls[n:].count("/a") == 0


def test_one_request_per_second_per_host(tmp_path: Path):
    stamps: list[float] = []
    clock = {"t": 0.0}

    def handler(req: httpx.Request) -> httpx.Response:
        stamps.append(clock["t"])
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})

    def sleep(s):
        clock["t"] += s

    f = Fetcher(client=httpx.Client(transport=httpx.MockTransport(handler)),
                clock=lambda: clock["t"], sleep=sleep)
    base = {"sign_in_required": "no", "robots_allowed": "yes", "http_status": "200",
            "owner": "O", "audience": "mixed", "kind": "award_page"}
    rows = [{**base, "url": f"https://sample.example/{i}"} for i in range(3)]
    tp.read_pages(rows, tmp_path, fetcher=f, sleep=sleep)
    assert all(b - a >= 1.0 for a, b in zip(stamps, stamps[1:], strict=False))


def test_scrub_staff_lists_and_winner_names():
    page = """<main><h2>Our Staff</h2><h3>Pat Placeholder</h3>
<p>Associate Professor - Instructional</p>
<p>Questions go to Alex Example, the Assistant Director of Awards, at .</p>
<p>Casey Sample (https://x.example/p) (Statistics) and student Robin Roe for A Study</p>
<p>Jordan Jones, Health Professions, College of Public Health</p>
<p>Contact Riley Sample, Associate Vice Provost for Things, <a href="https://u.example/email/decode?em=zz">[click-for-email]</a></p>
<p>The Gold Quill Award is $500.</p><p>Fulbright Grant</p></main>"""
    out = tp.clean_page(page)
    for gone in ("Pat Placeholder", "Alex Example", "Casey Sample", "Jordan Jones",
                 "Riley Sample", "click-for-email", "Instructional", "email/decode", "Robin Roe"):
        assert gone not in out, gone
    assert "The Gold Quill Award is $500." in out and "Fulbright Grant" in out

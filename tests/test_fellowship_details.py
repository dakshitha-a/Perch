"""Fellowship details: deadlines and amounts copied from each award's own page.
Parser tests run on real pages saved under tests/fixtures/fellowship_details/ (main text
region only, staff names, emails and phone numbers removed). No network."""

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from perch import datefmt
from perch.schemas import Scholarship
from perch.sources import fellowship_details as fd

FIX = Path(__file__).parent / "fixtures" / "fellowship_details"
TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)


def lines_of(name: str) -> list[str]:
    return fd.html_to_lines((FIX / f"{name}.html").read_text(encoding="utf-8"))


def rec(url: str = "https://undergraduate.temple.edu/x", **kw) -> Scholarship:
    return Scholarship(id="temple_sdfa:x", source="temple_sdfa", source_url=url,
                       fetched_at=NOW, name="X", **kw)


def amounts(*sentences: str) -> fd.AmountResult:
    return fd.extract_amounts(list(sentences))


def test_fixtures_hold_no_contact_details():
    for p in FIX.glob("*.html"):
        t = p.read_text(encoding="utf-8")
        assert "@" not in t and "mailto:" not in t, p.name


def test_deadline_on_a_sponsor_page():
    got = fd.extract_deadline(lines_of("sponsor_deadline_apaics"), TODAY)
    assert got and got[0] == date(2026, 12, 18)
    assert "December 18, 2026" in got[1]


def test_past_deadline_is_dropped():
    assert fd.extract_deadline(lines_of("sponsor_deadline_apaics"), date(2026, 12, 19)) is None


def test_year_is_never_inferred():
    # The SDFA pages write campus deadlines like "June 1" with no year: nothing is stored.
    assert fd.extract_deadline(lines_of("sdfa_udall"), TODAY) is None
    assert fd.extract_deadline(["Campus deadline: June 1."], TODAY) is None


def test_demonstrative_deadline_keeps_the_sentence_before_it():
    d, quote = fd.extract_deadline(lines_of("sponsor_amgen_regions"), TODAY)
    assert d == date(2027, 2, 1)
    assert "Asia, Europe, and North America" in quote and "February 1, 2027" in quote


def test_faculty_deadline_is_not_a_student_deadline():
    assert fd.extract_deadline(lines_of("temple_chat_faculty"), TODAY) is None


def test_campus_deadline_beats_an_earlier_sponsor_one():
    got = fd.extract_deadline(
        ["The national deadline is December 7, 2026.",
         "The Temple campus deadline is December 1, 2026."], TODAY)
    assert got and got[0] == date(2026, 12, 1)


def test_open_and_notification_dates_are_not_deadlines():
    assert fd.extract_deadline(
        ["Applications open on September 1, 2026; the deadline is December 1, 2026."], TODAY
    )[0] == date(2026, 12, 1)
    assert fd.extract_deadline(
        ["Deadline: applicants are notified by December 20, 2026."], TODAY) is None


@pytest.mark.parametrize("text,expect", [
    ("Applications are due 7 December 2026.", date(2026, 12, 7)),
    ("Submit by 2026-12-07.", date(2026, 12, 7)),
    ("Deadline: 12/7/2026", date(2026, 12, 7)),
    ("The deadline is Dec. 7th, 2026.", date(2026, 12, 7)),
])
def test_date_formats(text, expect):
    assert fd.extract_deadline([text], TODAY)[0] == expect


def test_heading_then_date_line():
    assert fd.extract_deadline(["Application Deadline", "December 7, 2026"], TODAY)[0] \
        == date(2026, 12, 7)


def test_single_amount_on_an_sdfa_page():
    a = fd.extract_amounts(lines_of("sdfa_amount_peco"))
    assert a.values == {(3500.0, 3500.0)}


def test_up_to_amount():
    a = fd.extract_amounts(lines_of("sdfa_udall"))
    assert a.values == {(None, 7000.0)}


def test_page_with_nothing():
    lines = lines_of("sponsor_nothing_quad")
    assert fd.extract_deadline(lines, TODAY) is None
    assert not fd.extract_amounts(lines).values


def test_amount_range():
    a = amounts("The scholarship award is $1,000 to $2,500 for the year of study.")
    assert a.values == {(1000.0, 2500.0)}
    assert amounts("The fellowship pays between $1,000 and $2,500.").values == {(1000.0, 2500.0)}
    assert len(amounts("The fellowship pays $1,000 and a prize of $2,500.").values) == 2
    assert amounts("The award is $1,000 - $2,500 in total.").values == {(1000.0, 2500.0)}


def test_million_fee_and_periodic_amounts_are_skipped():
    assert not amounts("The program has awarded $5 million in fellowship funding.").values
    assert not amounts("The application fee for the scholarship is $50.").values
    assert not amounts("The fellowship stipend is $2,000 per month.").values
    assert not amounts("A $0 balance is required to receive the award.").values


def test_conflicting_amounts_are_ambiguous():
    a = amounts("Project grants of up to $4,000 are offered.",
                "The maximum travel grant award is $1,000.")
    assert len(a.values) == 2


def test_non_usd_is_flagged_not_stored():
    a = amounts("The scholarship pays €1,000 a month to cover living costs.")
    assert not a.values and a.non_usd


def test_amount_quote_is_trimmed_around_the_match():
    long = "The fellowship " + "word " * 120 + "gives an award of $9,000 to each recipient " \
        + "more " * 120
    a = amounts(long)
    q = a.quotes[(9000.0, 9000.0)]
    assert "$9,000" in q and len(q) <= fd.QUOTE_MAX + 6


# --- the record -------------------------------------------------------------------

def test_apply_page_fills_value_quote_url_and_time():
    page = (FIX / "sponsor_deadline_apaics.html").read_text(encoding="utf-8")
    r = rec("https://www.apaics.org/congressional-fellowship")
    new = fd.apply_page(r, "https://www.apaics.org/congressional-fellowship", page, NOW)
    assert new.deadline == date(2026, 12, 18)
    assert "December 18, 2026" in new.deadline_quote
    assert new.details_url and new.details_fetched_at == NOW
    assert new.name == r.name and new.source_url == r.source_url  # nothing else changed
    assert new.amount_min is None and new.amount_quote is None


def test_validator_demands_quote_and_page():
    t = datetime(2026, 11, 2, tzinfo=UTC)
    with pytest.raises(ValidationError):
        rec(deadline=date(2026, 12, 18))
    with pytest.raises(ValidationError):
        rec(deadline=date(2026, 12, 18), deadline_quote="Deadline: December 18, 2026",
            details_url=None)
    with pytest.raises(ValidationError, match="quote"):
        rec(deadline=date(2026, 12, 19), deadline_quote="Deadline: December 18, 2026",
            details_url="https://x.org/", details_fetched_at=t)
    with pytest.raises(ValidationError, match="quote"):
        rec(deadline=date(2025, 12, 18), deadline_quote="Deadline: December 18, 2026",
            details_url="https://x.org/", details_fetched_at=t)
    with pytest.raises(ValidationError):
        rec(amount_max=5000.0, amount_quote="an award of $4,000", details_url="https://x.org/",
            details_fetched_at=t)
    with pytest.raises(ValidationError):
        rec(amount_max=5000.0, details_url="https://x.org/", details_fetched_at=t)
    ok = rec(amount_min=1000.0, amount_max=25000.0, amount_quote="from $1,000 to $25,000",
             details_url="https://x.org/", details_fetched_at=t)
    assert ok.amount_max == 25000.0
    rec(deadline=date(2026, 12, 7), deadline_quote="Due 07 December 2026",
        details_url="https://x.org/", details_fetched_at=t)


def test_synthetic_records_are_exempt():
    s = Scholarship(id="sample:sch-0001", source="synthetic", source_url="synthetic:x",
                    fetched_at=NOW, name="S", canary="PERCH-CANARY-X", amount_max=1000.0,
                    deadline=date(2027, 1, 1))
    assert s.deadline


# --- fetching: robots, one GET, cache ---------------------------------------------

def make_fetcher(handler) -> fd.Fetcher:
    c = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return fd.Fetcher(c, clock=lambda: 0.0, sleep=lambda s: None)


def test_robots_disallow_skips_and_counts():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text="<main>" + "x " * 200 + "Deadline: December 18, 2026</main>")

    recs = [rec("https://a.org/private/award"), rec("https://a.org/open/award")]
    recs[1] = recs[1].model_copy(update={"id": "temple_sdfa:y"})
    out, rep = fd.fill_details(recs, make_fetcher(handler), NOW)
    assert (rep.robots_skipped, rep.fetched, rep.deadlines) == (1, 1, 1)
    assert out[0].deadline is None and out[1].deadline == date(2026, 12, 18)
    assert "https://a.org/private/award" not in seen  # never requested
    assert seen.count("https://a.org/robots.txt") == 1  # once per host


def test_unreadable_robots_skips():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(500)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<p>hi</p>")

    out, rep = fd.fill_details([rec("https://b.org/x")], make_fetcher(handler), NOW)
    assert rep.robots_skipped == 1 and rep.fetched == 0


def test_errors_keep_the_old_record_and_cache_holds_one_get():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(req.url.path)
        return httpx.Response(404)

    recs = [rec("https://c.org/gone"), rec("https://c.org/gone")]
    out, rep = fd.fill_details(recs, make_fetcher(handler), NOW)
    assert rep.errors == 2 and out == recs
    assert calls == ["/gone"]


def test_rate_gap_between_requests_to_one_host():
    naps = []
    t = [0.0]
    c = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(404) if "robots" in req.url.path
        else httpx.Response(200, headers={"content-type": "text/html"}, text="<p>x</p>")))
    f = fd.Fetcher(c, clock=lambda: t[0], sleep=lambda s: naps.append(s))
    f.allowed("https://d.org/a")
    f.get("https://d.org/a")
    assert naps and naps[0] == pytest.approx(1.0)


# --- display ----------------------------------------------------------------------

def test_export_line_says_where_the_value_came_from():
    t = datetime(2026, 11, 2, 15, tzinfo=UTC)
    r = rec(deadline=date(2026, 10, 7), deadline_quote="Deadline: October 7, 2026",
            details_url="https://x.org/", details_fetched_at=t, amount_max=25000.0,
            amount_quote="up to $25,000")
    assert datefmt.from_page_note(r) == "from the award's page, fetched 2 Nov 2026"
    assert datefmt.amount_text(r) == "Up to $25,000"
    from perch.export import _amount
    assert _amount(r) == "Up to $25,000"
    assert datefmt.amount_text(rec()) is None


def test_cards_and_evidence_carry_the_hint_string():
    web = Path(__file__).resolve().parents[1] / "web"
    student = (web / "student.js").read_text(encoding="utf-8")
    app = (web / "app.js").read_text(encoding="utf-8")
    assert 'const FROM_PAGE = "from the award\'s page"' in student
    assert "fromPage(r)" in student and "details_url" in student
    assert "(from the award's page)" in app and "deadline_quote" in app
    assert "Page fetched" in app and "Not stated in the record" in app

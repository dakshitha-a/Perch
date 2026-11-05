"""The web app: served by the API, every asset present, helpers checked under Node when
Node is installed, and a headless-browser smoke test when Chromium is available."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from perch.api import WEB_DIR

from .test_api import make

ROOT = Path(__file__).resolve().parent.parent


def test_api_serves_the_app_and_its_assets(tmp_path):
    c, _ = make(tmp_path)
    page = c.get("/")
    assert page.status_code == 200 and "<title>Perch</title>" in page.text
    assert "not endorsed or certified" in page.text
    refs = re.findall(r'(?:href|src)="([^"#:]+)"', page.text)
    assert {"styles.css", "app.js"} <= set(refs)
    for ref in refs:
        r = c.get(f"/{ref}")
        assert r.status_code == 200, ref
        assert r.headers["cache-control"] == "no-cache", ref  # a release reaches every browser
    assert page.headers["cache-control"] == "no-cache"
    # Unchanged files still cost only a 304 on reload.
    etag = c.get("/app.js").headers["etag"]
    assert c.get("/app.js", headers={"If-None-Match": etag}).status_code == 304
    for js in WEB_DIR.glob("*.js"):
        for dep in re.findall(r'from "\./([^"]+)"', js.read_text()):
            assert (WEB_DIR / dep).is_file(), f"{js.name} imports missing {dep}"
    assert c.get("/health").json() == {"status": "ok"}  # API routes still win


def test_brief_carries_key_papers_and_leads_can_be_restored(tmp_path):
    c, _ = make(tmp_path)
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28",
                                  "explain": False}).json()["id"]
    got = c.get(f"/briefs/{bid}").json()
    threads = got["brief"]["threads"]
    assert threads and got["papers"]
    first = threads[0]["work_ids"][0]
    assert got["papers"][first]["title"] and got["papers"][first]["source_url"]
    lead = got["brief"]["lead_ids"][0]
    assert c.post(f"/briefs/{bid}/leads/{lead}/dismiss").json()["status"] == "dismissed"
    assert c.post(f"/briefs/{bid}/leads/{lead}/restore").json()["status"] == "new"


@pytest.mark.skipif(not shutil.which("node"), reason="Node not installed")
def test_format_helpers_under_node():
    script = """
import * as f from "MODULE";
const out = {
  date: f.formatDate("2027-10-28"), days: f.daysBetween("2026-10-28", "2027-10-28"),
  soon: f.closesIn(12), months: f.closesIn(365), closed: f.closesIn(-1),
  years: f.closesIn(f.daysBetween("2026-11-01", "2029-09-26")),
  size: f.awardSize({award_ceiling: 1500000}), none: f.awardSize({}),
  band: f.fitBand(62).label, higher: f.higherEdRows([
    "Private institutions of higher education",
    "Nonprofits, other than institutions of higher education",
    "Public and State controlled institutions of higher education"]).length,
  parsed: f.parseExplanation(
    "Funds X [PAR-1]. Cited work: W123456 did A [W123456]; W654321 did B.",
    ["PAR-1", "W123456", "W654321"]),
  raw: f.parseExplanation("Free text citing W123456 only.", ["W123456"]),
  tags: [f.agencyShort("National Institutes of Health", "Department of Health and Human Services"),
         f.agencyShort("U.S. National Science Foundation", null),
         f.agencyShort("Air Force Academy", "Department of Defense"),
         f.agencyShort("Office of Science", "Department of Energy - Office of Science")],
};
console.log(JSON.stringify(out));
""".replace("MODULE", (WEB_DIR / "format.js").as_uri())
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["date"] == "28 Oct 2027" and out["days"] == 365
    assert (out["soon"], out["months"], out["closed"]) == ("in 12 days", "in 12 months", "closed")
    assert out["years"] == "in about 3 years"  # T22: 2 years 11 months is not "in 2 years"
    assert out["size"] == "Up to $1,500,000" and out["none"] is None
    assert out["band"] == "Good match" and out["higher"] == 2
    p = out["parsed"]
    assert p["opportunity"] == ["Funds X ", {"cite": "PAR-1"}, "."]
    assert p["findings"] == [{"paper": "W123456", "text": "did A"},
                             {"paper": "W654321", "text": "did B"}]
    assert {"cite": "W123456"} in out["raw"]["raw"]
    assert out["tags"] == ["NIH", "NSF", "DOD · Air Force Academy", "DOE · Office of Science"]


def test_award_rows_open_their_record_and_cors_is_off_by_default(tmp_path):
    c, _ = make(tmp_path)
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28",
                                  "explain": False}).json()["id"]
    awards = c.get(f"/briefs/{bid}").json()["awards"]
    assert awards
    for a in awards:
        assert c.get(f"/records/{a['record_id']}").json()["kind"] == "award"
    r = c.get("/health", headers={"Origin": "https://elsewhere.example"})
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.skipif(not shutil.which("node"), reason="Node not installed")
def test_scout_tap_reactions_are_random_and_never_repeat():
    script = """
import { POKES, nextPoke } from "MODULE";
let last = null, repeats = 0;
const seen = new Set();
for (let i = 0; i < 400; i++) {
  const k = nextPoke(last);
  if (k === last) repeats++;
  seen.add(k);
  last = k;
}
console.log(JSON.stringify({ repeats, seen: seen.size, total: POKES.length,
  low: nextPoke("wink", () => 0), high: nextPoke("wink", () => 0.999) }));
""".replace("MODULE", (WEB_DIR / "owl.js").as_uri())
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["repeats"] == 0 and out["seen"] == out["total"] == 8
    assert out["low"] == "spin" and out["high"] == "blink"


def test_draft_review_checklist_quotes_the_record():
    """S24 task 7: the checklist is the record's own sentences, chosen by code."""
    from bench.draft_review.items import asks

    text = ("This notice invites applications on hearing. Applicants must describe a mentoring "
            "plan in full detail. Proposals should include a data sharing plan for all data. "
            "Projects are expected to recruit adults over the age of sixty. See Section IV.")
    got = asks(text)
    assert got and all(g in text for g in got)
    assert not any("Section IV" in g for g in got)


def test_the_app_loads_nothing_from_another_host(tmp_path):
    """S12: fonts are served from web/fonts, so a page load reaches no third party."""
    c, _ = make(tmp_path)
    page = c.get("/").text
    css = c.get("/styles.css").text
    assert not re.findall(r'(?:href|src)="(?:https?:)?//', page)
    assert not re.findall(r"url\((?:[\"']?)(?:https?:)?//", css)
    fonts = re.findall(r"url\(fonts/([\w-]+\.woff2)\)", css)
    assert len(fonts) == 4
    for f in fonts:
        r = c.get(f"/fonts/{f}")
        assert r.status_code == 200 and r.headers["content-type"] == "font/woff2"
    assert (WEB_DIR / "fonts/OFL-Inter.txt").is_file()
    assert (WEB_DIR / "fonts/OFL-Newsreader.txt").is_file()


def test_every_response_carries_the_security_headers(tmp_path):
    """S11: a CSP that allows this server only, no framing, nosniff, no referrer. The HTML
    export has no inline handler; its one style and one script are allowed by hash."""
    from perch import export as ex

    c, _ = make(tmp_path)
    for path in ("/", "/app.js", "/health", "/no-such-page"):
        r = c.get(path)
        csp = r.headers["content-security-policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp, path
        assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
    page = ex.to_html([ex.Block("h1", "SYNTHETIC")], "t")
    assert "onclick" not in page
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    styles = re.findall(r"<style>(.*?)</style>", page, re.S)
    csp = c.get("/").headers["content-security-policy"]
    assert scripts and all(ex.csp_hash(x) in csp for x in scripts)
    assert styles and all(ex.csp_hash(x) in csp for x in styles)


def test_markdown_export_text_cannot_make_links_or_leave_its_quote():
    """S15: a record title or model sentence with Markdown in it renders as text; a
    newline cannot break out of the Model quote; only http(s) links become links."""
    from perch import export as ex

    md = ex.to_markdown([
        ex.Block("h3", "SYNTHETIC [click](javascript:alert(1)) <img src=x>"),
        ex.Block("model", "SYNTHETIC first line.\n\nUnlabelled second line [W1]."),
        ex.Block("list", items=["SYNTHETIC ![x](https://evil.example/p.png)"]),
        ex.Block("link", "Record", href="javascript:alert(1)"),
        ex.Block("link", "Grants.gov", href="https://www.grants.gov/x")])
    assert "\\[click\\](javascript:" in md  # shown as text, not a link
    assert " [click]" not in md and "\\<img src=x\\>" in md and "![x](" not in md
    assert "> **Model:** SYNTHETIC first line. Unlabelled second line \\[W1\\]." in md
    assert "[Record](" not in md and "[Grants.gov](https://www.grants.gov/x)" in md


def test_no_front_end_path_that_nothing_reaches():
    """Review W12: keptUrl had no caller, and the stored-brief export links answered 404
    with stored briefs off. The stored routes stay for the bench and the replay export; the
    "built before industry leads" note stays, because a replay of an older stored brief
    reaches it."""
    app = (WEB_DIR / "app.js").read_text()
    api = (WEB_DIR / "api.js").read_text()
    assert "keptUrl" not in api and "exportUrl" not in api + app
    assert "if (!api.exportFile) return null;" in app  # the export menu: a preview has none


def test_the_research_security_line_is_one_fixed_line():
    """Q13: the Industry tab and the industry hand-off carry the same code-written line,
    naming no company."""
    from perch.offices import RESEARCH_SECURITY

    assert f'"{RESEARCH_SECURITY}"' in (ROOT / "web/app.js").read_text()
    assert RESEARCH_SECURITY in (ROOT / "web/help.js").read_text()


@pytest.mark.skipif(not shutil.which("node"), reason="Node not installed")
def test_the_cards_second_person_matches_the_exports():
    """F12: the researcher card's inference reads "Your", as the export and Scout do: the
    web rewrite gives the same text as perch.scout.tools.second_person."""
    from perch.scout.tools import second_person

    cases = ["The researcher's work on brain organoids aligns with it [W1, PAR-25-073].",
             "It fits the researcher's aims; the researcher develops tools and the "
             "researcher focuses on HIV-1.",
             "The researcher studies, the researcher watches, the researcher has data.",
             "The researcher’s model of the researchers' data.", "", "No subject here."]
    script = """
import { secondPerson } from "MODULE";
console.log(JSON.stringify(CASES.map((t) => secondPerson(t))));
""".replace("MODULE", (WEB_DIR / "format.js").as_uri()).replace("CASES", json.dumps(cases))
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got == [second_person(t) for t in cases]
    assert got[0].startswith("Your work") and "you develop" in got[1] and "you focus" in got[1]


def test_cover_points_reach_the_app_and_no_page_promises_that_no_model_reads_the_cv():
    """S33: the Scout card renders cover_points with a Copy button and both audiences get
    the example question and the rail line; Scout and Help say when a model reads the CV,
    and no page still promises that none does."""
    web = {n: (WEB_DIR / n).read_text() for n in ("scout.js", "app.js", "student.js", "help.js")}
    scout = web["scout.js"]
    for s in ("function pointsBlock(", "What could my cover letter for the top lead say?",
              "What should my application for my top option highlight?", "Copy the points",
              "Perch never sends this, and it never enters an export or a hand-off draft.",
              # S45 fix round 3: the rail and limits name only what Scout v2's tools do
              "A model reads a part of your CV, your entries or your saved list when it opens "
              "them to answer a question. Contact details are blanked first.",
              "A model reads your CV, documents, entries or saved list when it opens them to "
              "answer a question, with contact details blanked.",
              "Search Perch’s public records by words",
              "class: \"cite own\"", "Sample data"):
        assert s in scout, s
    for s in ("Search with filters", "activity code", "verdict, deadline, amount",
              "reached its limit for this conversation"):
        assert s not in scout, s
    assert "The points below are the step’s result." in scout  # the code-written answer line
    css = (WEB_DIR / "styles.css").read_text()
    assert ".scout-points {" in css
    assert "overflow-wrap: anywhere" in css.split(".scout-points {")[1][:200]
    assert ".scout-points .btn.points-copy { min-height: 44px; }" in css
    help_ = web["help.js"]
    # S46: the button calls /briefs/{id}/cover-points, so Help says what it does (and only that).
    assert (
        "On a lead card, Cover-letter points asks a model to pair what the record asks for with "
        "what your CV, entries and papers show, each line cited. It needs an account, it is "
        "model text to put in your own words, and it is never sent or added to an export."
    ) in help_
    # The withdrawn promise (Q43) is gone from every page and from the redesign source. The
    # hand-off sentence "no model reads them for it" stays: code writes that opening.
    redesign = (ROOT / "docs/design/redesign/StudentStart.dc.html").read_text()
    for text in (*web.values(), redesign):
        for banned in ("no model reads it", "no model reads the CV", "never with a model",
                       "never reads your CV", "never reads the CV"):
            assert banned not in text, banned
    from perch.skills import cover

    assert cover.CV_CHARS == 3500 and (cover.MIN_POINTS, cover.MAX_POINTS) == (3, 6)
    assert cover.MAX_MISSING == 3 and cover.MAX_PAPERS == 6


def test_help_is_a_short_visual_guide_with_one_architecture_diagram():
    """Help (2 Nov): figures animate with CSS only, one reduced-motion block stops them on
    their final state, and the architecture SVG is an image with a label and a text list."""
    help_js = (WEB_DIR / "help.js").read_text()
    css = (WEB_DIR / "styles.css").read_text()
    assert 'role: "img"' in help_js and '"aria-label": ARCH_LABEL' in help_js
    assert 'class: "sr-only"' in help_js  # the text list beside the diagram
    assert "setInterval" not in help_js and "setTimeout" not in help_js
    external = help_js.replace("https://research.temple.edu", "")
    external = external.replace("http://www.w3.org/2000/svg", "")
    assert "data:" not in help_js and "http" not in external  # no data URIs, no outside assets
    assert css.count("@media (prefers-reduced-motion: reduce) {\n  .help .fx") == 1
    block = css.split("@media (prefers-reduced-motion: reduce) {\n  .help .fx")[1].split("\n}")[0]
    assert "animation: none !important" in block and ".arch-dot" in block


def test_the_era_note_and_the_foundation_office_are_fixed_text():
    """Live-checked 2026-11-02: the hand-off carries one fixed ERA note and its link, Help
    repeats both and says where foundation leads will go. The foundation office is not an
    office a request can pick."""
    from perch.offices import (
        FOUNDATION_NOTE,
        FOUNDATION_OFFICE,
        OFFICES,
        SUBMISSION_NOTE,
        SUBMISSION_URL,
    )

    handoff = (ROOT / "web/handoff.js").read_text()
    help_js = (ROOT / "web/help.js").read_text()
    for src in (handoff, help_js):
        assert SUBMISSION_NOTE in src and SUBMISSION_URL in src
    assert FOUNDATION_NOTE in help_js
    assert "Foundations are not covered yet" not in help_js.replace(FOUNDATION_NOTE, "")
    assert FOUNDATION_OFFICE.key not in OFFICES
    assert FOUNDATION_OFFICE.key not in {o.key for o in OFFICES.values()}


def test_the_foundation_office_cannot_be_asked_for_a_handoff(tmp_path):
    c, _ = make(tmp_path)
    r = c.post("/briefs/nope/handoff", json={"office": "cfr"})
    assert r.status_code == 422  # an unknown office key is refused before any brief is read


def test_the_temple_submission_fixtures_hold_the_quoted_sentences_and_no_email():
    fx = ROOT / "tests/fixtures/temple"
    ovpr = (fx / "ovpr_proposal_development.html").read_text()
    cfr = (fx / "cfr_fundraising_resources.html").read_text()
    assert ("All proposals must be routed through ERA for institutional review and approval "
            "prior to submission.") in ovpr
    assert "Faculty and program directors should work with their school" in cfr
    assert "notify CFR of potential proposals" in cfr
    assert "@" not in ovpr and "@" not in cfr


def test_tag_chip_wraps_instead_of_widening_the_page() -> None:
    """A long agency name (a DOD contracting activity) in a card's tag must wrap: a nowrap tag
    pushed the page 12px wider than a 390px phone."""
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "web" / "styles.css").read_text()
    rule = next(x for x in css.split("\n.") if x.startswith("tag {")).split("}", 1)[0]
    assert "nowrap" not in rule and "max-width: 100%" in rule


def test_the_find_form_has_no_personal_text_field_and_build_starts_one_brief_call():
    """The landing has no personal-text field and the pick screen's boxes are the plain option
    fields (direction, keywords, career stage, smallest award); no CV or proposal box and no
    upload exist in the web app. Build is one call: api.create(req, "researcher")."""
    app = (WEB_DIR / "app.js").read_text()
    find = app[app.index("function renderFind()"):app.index("function heroArt()")]
    ctx = app[app.index("function contextPanel("):app.index("// One build call")]
    for part in (find, ctx):
        fields = re.findall(r'h\("(?:textarea|input)", \{[^}]*\}', part)
        assert not [x for x in fields if re.search(r"\b(cv|interests|achievements|proposal)\b",
                                                  x, re.I)]
        assert 'type: "file"' not in part
    build = app[app.index("async function build(c)"):app.index("// ---------- Brief ----------")]
    assert 'api.create(req, "researcher")' in build
    student = (WEB_DIR / "student.js").read_text()
    start = student[student.index("export async function renderStudentStart("):
                    student.index("// ----- profile -----")]
    # A visitor without an account gets the SYNTHETIC sample student; a signed-in student
    # saves a CV (stored encrypted by the server) and builds from the stored documents.
    assert 'api.create({}, "student")' in start and "Try a sample student" in start
    assert "api.addDoc(" in start and "doc_ids: docs.map" in start


def test_no_private_mode_code_is_left_in_the_web_app():
    """Private mode is removed (S42): the files, the routes and the words are gone."""
    assert not (WEB_DIR / "mode.js").exists() and not (WEB_DIR / "private.js").exists()
    words = re.compile(r"private|mask|X-Perch|sessionStorage|status-chip|end-session|"
                       r"\bCloud\b", re.I)
    for f in WEB_DIR.glob("*.js"):
        text = f.read_text()
        hits = [m.group(0) for m in words.finditer(text)]
        # Scout's step tags still name a Cloud provider when the server reports one.
        allowed = {"scout.js": {"Cloud", "cloud"}}.get(f.name, set())
        assert not [h for h in hits if h not in allowed], (f.name, hits)
    assert "status-chip" not in (WEB_DIR / "index.html").read_text()


@pytest.mark.skipif(not shutil.which("node"), reason="Node not installed")
def test_the_live_api_session_csrf_etag_and_a_lost_session():
    """The live client: a guest session is made on the side asked for before the first brief,
    the CSRF token goes on every non-GET and stays in memory, a poll sends the last ETag and
    a 304 reuses the last body, an object error reads as a plain sentence, and a lost
    session (401 on several calls at once) reports once."""
    script = """
import { liveApi } from './web/api.js';
const calls = [];
let session = false, lost = false;
const ETAG = '"v1"';
globalThis.fetch = async (url, o = {}) => {
  const method = o.method || 'GET', h = o.headers || {};
  calls.push({ url, method, csrf: h['X-CSRF-Token'] || null, inm: h['If-None-Match'] || null });
  const res = (status, body, headers = {}) => ({ ok: status < 400, status,
    headers: { get: (k) => headers[k] || null }, json: async () => body,
    text: async () => JSON.stringify(body) });
  if (url === '/auth/session') return res(200, session
    ? { signed_in: false, guest: true, audience: 'student', csrf: 'SYN-CSRF' }
    : { signed_in: false });
  if (url === '/auth/guest') { session = true; return res(200, { guest: true,
    audience: JSON.parse(o.body).audience, csrf: 'SYN-CSRF' }); }
  if (lost) return res(401, { detail: { error: 'auth_required' } });
  if (url === '/briefs') return res(202, { id: 'b1' });
  if (url === '/briefs/b1') return h['If-None-Match'] === ETAG ? res(304, {}, { ETag: ETAG })
    : res(200, { brief: { id: 'b1' } }, { ETag: ETAG });
  if (url === '/briefs/b1/handoff') return res(403, { detail: { error: 'account_required' } });
  if (url === '/briefs/b1/compare') return res(200, { rows: [] });
  return res(404, { detail: 'no such route' });
};
(async () => {
const api = liveApi('');
let fired = [];
api.onExpired = (m) => fired.push(m);
const made = await api.create({}, 'student');
const first = await api.brief('b1');
const second = await api.brief('b1');
await api.setLead('b1', 'l1', 'keep').catch(() => {});
const denied = await api.handoff('b1', { office: 'x' }).catch((e) => e);
lost = true;
const results = await Promise.allSettled([api.brief('b1'), api.compare('b1')]);
console.log(JSON.stringify({ calls, made, first, second, fired,
  denied: [denied.status, denied.message],
  rejected: results.every((r) => r.status === 'rejected') }));
})().catch((e) => { console.error(e); process.exit(1); });
"""
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                       text=True, cwd=ROOT, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    calls = out["calls"]
    assert [c["url"] for c in calls[:3]] == ["/auth/session", "/auth/guest", "/briefs"]
    assert calls[2]["csrf"] == "SYN-CSRF" and out["made"] == {"id": "b1"}
    polls = [c for c in calls if c["url"] == "/briefs/b1" and c["method"] == "GET"]
    assert polls[0]["inm"] is None and polls[1]["inm"] == '"v1"'  # the second poll sends the ETag
    assert out["second"] == out["first"]  # 304: the last body
    lead = next(c for c in calls if c["url"].endswith("/leads/l1/keep"))
    assert lead["method"] == "POST" and lead["csrf"] == "SYN-CSRF"
    assert all(c["csrf"] is None for c in calls if c["method"] == "GET")
    assert out["denied"][0] == 403 and out["denied"][1].startswith("Sign in")
    assert out["fired"] == [True]  # onExpired(wasGuest): once, for a guest
    assert out["rejected"]


def test_the_session_and_csrf_token_stay_out_of_browser_storage():
    """The CSRF token lives in memory only; the session is the server's cookie."""
    api = (WEB_DIR / "api.js").read_text()
    for banned in ("sessionStorage", "localStorage", "document.cookie"):
        assert banned not in api


def test_scout_shows_the_checks_in_the_answer():
    """S45 S4/S7: marks for unsupported sentences, the flagged notice, the General advice block,
    and no stale call count."""
    scout = (WEB_DIR / "scout.js").read_text()
    for s in ("mark\", { class: \"unsupported\"", "(not confirmed by the cited record)",
              "General advice, not from records", "Uncited",
              "This answer did not pass the citation check twice.",
              "Scout could not confirm", "I stop after a fixed number of tool steps"):
        assert s in scout, s
    assert "eight model calls" not in scout
    css = (WEB_DIR / "styles.css").read_text()
    assert "mark.unsupported" in css and ".scout-general" in css


def test_cover_points_button_is_wired_on_every_lead_card():
    """S46: a button on every lead card (not eligible included), none on a dismissed card; a guest
    gets the sign-in link; the module holds the busy state and polls; the errors are the design's.
    """
    cover = (WEB_DIR / "cover.js").read_text()
    for s in ("Cover-letter points", "Points again", "Sign in to get cover-letter points",
              "A model writes these from your CV and entries. You put them in your own words.",
              "A model writes these from your CV, entries and the papers the record cites.",
              "Still running. Try again in a minute.", "Agree to the consent first.",
              'e.code === "consent_required"', "onPage(k)",
              "A model is reading the record and your CV. This takes up to two minutes…",
              "The points are ready below.", "The points could not be made. Try again.",
              "Cover points start once the brief has finished.", "Too many requests. Try again in ",
              'role: "status"', 'role: "alert"', '"aria-busy"', "`cover-${recordId}`",
              "const POLL_MS = 2000;", "const POLL_MAX_MS = 150000;", "pointsBlock(asPoints(",
              'focus === "result"', "api.coverGet(briefId, recordId, null)", "e.serverMessage"):
        assert s in cover, s
    assert "export function pointsBlock(" in (WEB_DIR / "scout.js").read_text()
    api = (WEB_DIR / "api.js").read_text()
    assert "cover-points`, again ? { record_id: recordId, again: true }" in api
    assert "err.retryAfter" in api
    assert api.index("coverStart:") < api.index("studentNote:")
    student = (WEB_DIR / "student.js").read_text()
    assert 'l.status === "dismissed" ? null : coverBlock({ ...ctx, audience: "student"' in student
    app = (WEB_DIR / "app.js").read_text()
    assert 'l.status === "dismissed" ? null : coverBlock({ api, announce, openEvidence' in app
    assert "verdict !== \"not eligible\"" not in student.split("coverBlock({ ...ctx")[1][:80]
    mods = (ROOT / "scripts/build_ui_preview.py").read_text()
    assert mods.index('"scout.js"') < mods.index('"cover.js"') < mods.index('"student.js"')


def test_a_signed_in_handoff_polls_the_stored_draft():
    """S48 S3: signed in, POST /handoff queues a job; draftOf polls GET until the draft is
    stored. Without accounts the POST's own draft is used as before."""
    script = """
import { draftOf } from './web/handoff.js';
const draft = { subject: 'SYNTHETIC subject', body: 'SYNTHETIC body', lead_ids: ['l1'] };
const polls = [];
const queued = { handoff: async () => ({ job_id: 'j1', status: 'queued' }),
  handoffGet: async (id, office, job) => { polls.push([id, office, job]);
    return polls.length < 2 ? { result: null, job: { id: job, state: 'running' } }
      : { result: draft, job: { id: job, state: 'succeeded' } }; } };
const direct = { handoff: async () => draft, handoffGet: async () => { throw new Error('no'); } };
const failed = { handoff: async () => ({ job_id: 'j2' }),
  handoffGet: async () => ({ result: null,
    job: { id: 'j2', state: 'dead', error: 'consent_required' } }) };
const none = async () => {};
(async () => {
const a = await draftOf(queued, 'b1', 'research_development', none);
const b = await draftOf(direct, 'b1', 'research_development', none);
const c = await draftOf(failed, 'b1', 'research_development', none).catch((e) => e.message);
console.log(JSON.stringify({ a, b, c, polls }));
})().catch((e) => { console.error(e); process.exit(1); });
"""
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                       text=True, cwd=ROOT, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["a"]["subject"] == "SYNTHETIC subject" and out["b"] == out["a"]
    assert out["polls"] == [["b1", "research_development", "j1"]] * 2
    assert "consent" in out["c"]

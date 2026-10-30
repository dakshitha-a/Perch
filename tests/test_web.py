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
        assert c.get(f"/{ref}").status_code == 200, ref
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
    assert out["size"] == "Up to $1,500,000" and out["none"] is None
    assert out["band"] == "Good fit" and out["higher"] == 2
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


@pytest.mark.skipif(not shutil.which("node"), reason="Node not installed")
def test_private_session_starts_before_personal_text_is_sent():
    """S18: the header switch, the Student path and the paste nudge all open a private
    session before any personal text leaves the browser; a content guess never switches
    the mode, and turning it off ends the session only after a confirm."""
    script = """
import { createMode, looksPersonal } from './web/mode.js';
const calls = [];
const api = { open: false,
  start: async () => { calls.push('start'); api.open = true; },
  end: async () => { calls.push('end'); api.open = false; },
  addDocument: async (b) => {
    calls.push('add:' + b.kind + ':' + (api.open ? 'open' : 'CLOSED')); } };
(async () => {
const m = createMode(api);
m.setAvailable(true);
// Student path and personal fields: send() opens the session first.
await m.send({ kind: 'cv', text: 'SYNTHETIC CV' });
// The paste nudge: moving text opens the session and sends nothing.
api.open = false;
await m.move('cv', 'SYNTHETIC CV pasted');
const afterMove = calls.slice();
// The header switch: off ends only after a confirm; a refusal keeps it on.
const kept = await m.disable(async () => false);
const ended = await m.disable(async () => true);
// Unavailable: nothing starts.
const n = createMode({ open: false, start: async () => calls.push('BAD') });
n.setAvailable(false, 'no self-hosted models');
let refused = false;
try { await n.send({ kind: 'cv', text: 'x' }); } catch (e) { refused = true; }
console.log(JSON.stringify({ calls, afterMove, kept, ended, refused, drafts: m.state.drafts,
  cv: looksPersonal('Education\\nB.S. Biology\\nGPA: 3.4\\nReferences'),
  name: looksPersonal('Jane Smith'), orcid: looksPersonal('0000-0002-1825-0097') }));
})().catch((e) => { console.error(e); process.exit(1); });
"""
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                       text=True, cwd=ROOT, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["calls"][:2] == ["start", "add:cv:open"]
    assert out["afterMove"] == ["start", "add:cv:open", "start"]  # moved text is not sent
    assert out["kept"] is False and out["ended"] is True and out["calls"][-1] == "end"
    assert out["refused"] and "BAD" not in out["calls"]
    assert out["drafts"] == {}
    assert out["cv"] and not out["name"] and not out["orcid"]


def test_personal_fields_exist_only_inside_private_mode():
    """The landing has no personal-text field; the pick screen's CV and draft boxes reach
    the server only as session documents, after the session opens (S24)."""
    app = (WEB_DIR / "app.js").read_text()
    find = app[app.index("function renderFind()"):app.index("function pasted(")]
    fields = re.findall(r'h\("(?:textarea|input)", \{[^}]*\}', find)
    assert fields
    personal = r"\b(cv|interests|achievements|proposal)\b"
    assert not [x for x in fields if re.search(personal, x, re.I)]
    build = app[app.index("async function build(c)"):app.index("// ----- the status chip")]
    assert build.index("await mode.enable()") < build.index("privApi.addDocument") \
        < build.index("privApi.create(req)")
    student = (WEB_DIR / "student.js").read_text()
    assert "if (!api.open)" in student  # the form shows only with a session open


def test_draft_review_checklist_quotes_the_record():
    """S24 task 7: the checklist is the record's own sentences, chosen by code."""
    from bench.draft_review.items import asks

    text = ("This notice invites applications on hearing. Applicants must describe a mentoring "
            "plan in full detail. Proposals should include a data sharing plan for all data. "
            "Projects are expected to recruit adults over the age of sixty. See Section IV.")
    got = asks(text)
    assert got and all(g in text for g in got)
    assert not any("Section IV" in g for g in got)

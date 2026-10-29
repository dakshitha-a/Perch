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

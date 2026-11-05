# ruff: noqa: E501  - the assertions quote long page strings
"""S49 FE-B: the list, My Perch, account, Compare, hand-off, cover-points, Scout and help pages.

Static checks on the page code, and the hand-off box sizing under Node when it is installed.
The browser behaviour is walked by scripts/walk_flows/s49_fe_b.py."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from perch.api import WEB_DIR

OWNED = ["browse.js", "account.js", "compare.js", "handoff.js", "cover.js", "scout.js", "help.js", "api.js", "pages.css"]
ROOT = Path(__file__).resolve().parent.parent


def src(name: str) -> str:
    return (WEB_DIR / name).read_text()


def test_pages_css_loads_after_styles_css():
    html = src("index.html")
    assert html.index('href="styles.css"') < html.index('href="pages.css"')
    assert "DRAFT copy" not in html
    assert "Your CV is encrypted and deletable" in html


def test_no_draft_copy_marker_is_left_in_the_pages():
    for name in OWNED:
        assert "DRAFT copy" not in src(name), name


def test_api_has_the_saved_list_calls_and_usage():
    api = src("api.js")
    assert "saved: (side = null) => p(`/me/saved${query({ audience: side })}`)" in api
    assert "save: (recordId, side = null) => post(`/me/saved${query({ audience: side })}`, { record_id: recordId })" in api
    assert 'unsave: (savedId) => p(`/me/saved/${encodeURIComponent(savedId)}`, { method: "DELETE" })' in api
    assert 'usage: () => p("/usage")' in api
    assert "samples: (audienceName, cursor = null, limit = null)" in api


def test_lists_send_sort_and_open_only_and_default_funding_to_closing_soonest():
    js = src("browse.js")
    assert "sort: st.sort" in js and 'open_only: aud === "researcher" && !st.closed' in js
    assert 'researcher: { temple: false, school: null, allTemple: false, level: "", q: "", sort: "closing", closed: false }' in js
    assert 'student: { temple: true, school: null, allTemple: false, level: "", q: "", sort: "name", closed: false }' in js
    assert "Show closed calls" in js and "Level of study" in js
    # a sample row never gets Keep (rule 11), and the sample screen builds rows without a keep state
    assert "keep && !sample ? keepButton(r, keep)" in js
    assert "recordRow(r, ctx))" in js
    assert "Past date on the page" in js and "No amount or deadline on the page" in js


def test_my_perch_is_the_three_card_home():
    js = src("account.js")
    for needle in ("home-kept", "home-briefs", "home-docs", "Kept and saved", "Options checked", "Change details and run again",
                   "Past date on the page", "No date on the record", "This record is no longer in Perch’s data.",
                   "Sign in to keep awards, their dates and your briefs.", "Using Perch as"):
        assert needle in js, needle
    for gone in ("Student brief", "Your sides", "Consent text, version"):
        assert gone not in js


def test_cover_points_tell_a_guest_once_and_put_the_note_above_the_list():
    js = src("cover.js")
    assert "export function coverListLine(ctx)" in js
    assert "Cover-letter points need an account. " in js
    assert "if (ctx.guest) return null;" in js
    assert 'document.getElementById("list-notices")' in js
    assert "Today’s allowance is used. See the note above the list." in js
    assert "short: true" in js and "Cover-letter points" in src("scout.js")


def test_compare_shows_the_table_before_the_hand_off_and_the_number_on_its_own_line():
    js = src("compare.js")
    assert js.index('class: "compare-wrap"') < js.index('class: "handoff-box"')
    assert 'class: "row-num"' in js and "r.number" in js


def test_handoff_keeps_draft_again_under_the_draft_and_names_the_to_line():
    js = src("handoff.js")
    assert "To: add the address yourself. " in js
    assert "Leads in this note:" in js
    assert 'h("span", { text: "Open in my mail app" })), make),' in js


def test_help_states_what_round_one_built():
    js = src("help.js")
    for needle in (
        "On Temple awards and Research funding, Keep saves a record to your account.",
        "turn on Show closed calls to see them.",
        "the card says Past date on the page",
        "Perch opens on My Perch",
        "Change details and run again",
        "A researcher may add a CV before building a brief. It is optional.",
        "Sample records cannot be kept or saved.",
        "When today’s allowance is used, one note above the list says so",
        "The title",
    ):
        assert needle in js, needle


@pytest.mark.skipif(not shutil.which("node"), reason="Node not installed")
def test_draft_box_fits_the_draft_under_node():
    script = """
import { bodyRows } from "MODULE";
const long = "x".repeat(160) + "\\n" + "y\\n".repeat(30);
console.log(JSON.stringify([bodyRows(""), bodyRows("a\\nb"), bodyRows(long),
  bodyRows("z".repeat(80) + "\\n" + "z".repeat(81))]));
""".replace("MODULE", (WEB_DIR / "handoff.js").as_uri())
    r = subprocess.run(["node", "--input-type=module", "-e", script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert re.search(r"\[8,8,18,8\]", r.stdout), r.stdout

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("render_tracker", ROOT / "scripts/render_tracker.py")
render_tracker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_tracker)


def test_renders_real_tracker():
    page = render_tracker.render((ROOT / "docs/TRACKER.md").read_text(encoding="utf-8"))
    assert page.startswith("<!doctype html>")
    assert "<table>" in page
    assert "<th>Session</th>" in page
    assert "<script" not in page and "http" not in page.split("<body>")[0]


def test_status_badge_and_escaping():
    md = "# T\n\n| A | Status |\n|---|---|\n| `x<y` & **b** | in progress |\n"
    page = render_tracker.render(md)
    assert '<span class="badge s-in-progress">in progress</span>' in page
    assert "<code>x&lt;y</code> &amp; <strong>b</strong>" in page


def test_deterministic():
    md = (ROOT / "docs/TRACKER.md").read_text(encoding="utf-8")
    assert render_tracker.render(md) == render_tracker.render(md)


def test_artifact_fragment_follows_page_contract():
    page = render_tracker.render("# T\n", artifact=True, page_title="Perch Build Tracker")
    assert page.startswith("<title>Perch Build Tracker</title>")
    assert "<!doctype" not in page and "<body>" not in page
    assert ':root:not([data-theme="light"])' in page and ':root[data-theme="dark"]' in page


def test_summary_counts_statuses():
    md = "| Task | Status |\n|---|---|\n| 1 | done |\n| 2 | todo |\n| 3 | done |\n"
    page = render_tracker.render(md)
    assert "<b>2/3</b>tasks done" in page


def test_current_session_is_highest_number(tmp_path):
    for name in ("S2.md", "S10.md", "S1.md", "notes.md"):
        (tmp_path / name).write_text("# x\n")
    assert render_tracker.current_session(tmp_path).name == "S10.md"

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

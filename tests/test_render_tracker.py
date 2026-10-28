import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("render_tracker", ROOT / "scripts/render_tracker.py")
rt = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rt
spec.loader.exec_module(rt)

MASTER = """# Tracker

Intro line.

| Session | Goal | Status | Started | Finished | Commit | Notes |
|---|---|---|---|---|---|---|
| S0 | Repo | done | a | b | abc1234 | |
| S1 | Store | in progress | c | | | |
| S2 | Awards | todo | | | | |
"""

TASKS = "| Task | What | Status | Commit | Notes |\n|---|---|---|---|---|\n"
S0 = "# S0 — Repo\n\n" + TASKS + "| 1 | x | done | abc | |\n"
S1 = (
    "# S1 — Store\n\nGoal.\n\n| Task | What | Status | Commit | Notes |\n|---|---|---|---|---|\n"
    "| 1 | `a<b` & **c** | done | | |\n| 2 | y | todo | | |\n\n## Definition of done\n\n- works\n"
)


def page(artifact=False):
    return rt.render_page(MASTER, {"S0": S0, "S1": S1}, artifact=artifact)


def test_real_tracker_renders():
    real = rt.render_page((ROOT / "docs/TRACKER.md").read_text(encoding="utf-8"),
                          rt.load_sessions(ROOT / "docs/sessions"))
    assert real.startswith("<!doctype html>")
    assert "<th>Session</th>" in real
    assert "http" not in real.split("<body>")[0]  # standalone page makes no external requests


def test_three_views_with_current_shown_at_rest():
    p = page()
    assert '<section id="view-current" class="view" data-view="current">' in p
    assert '<section id="view-master" class="view" data-view="master" hidden>' in p
    assert '<section id="view-archive" class="view" data-view="archive" hidden>' in p
    assert "S1 · Store" in p


def test_finished_sessions_are_archived_collapsed_and_linked():
    p = page()
    assert '<details id="s0">' in p and '<details id="s1"' not in p
    assert '<a href="#s0">S0</a>' in p  # master row links to its archive entry
    assert '<tr class="is-current">' in p


def test_inline_markup_badges_and_summary():
    p = page()
    assert "<code>a&lt;b</code> &amp; <strong>c</strong>" in p
    assert '<span class="badge s-in-progress">in progress</span>' in p
    assert "<b>1/2</b>tasks done" in p
    assert 'class="panel done-list"' in p


def test_artifact_fragment_follows_page_contract():
    p = page(artifact=True)
    assert p.startswith("<title>Perch Build Tracker</title>")
    assert "<!doctype" not in p and "<body>" not in p
    assert ':root:not([data-theme="light"])' in p and ':root[data-theme="dark"]' in p


def test_deterministic_and_session_order(tmp_path):
    assert page() == page()
    for name in ("S2.md", "S10.md", "S1.md", "notes.md"):
        (tmp_path / name).write_text("# x\n")
    assert list(rt.load_sessions(tmp_path)) == ["S1", "S2", "S10"]

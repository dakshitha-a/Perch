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


def test_decisions_tab_newest_first():
    dec = ("| Date | Session | Decision | Reason | Decided by |\n|---|---|---|---|---|\n"
           "| d1 | S0 | DEC-ONE | r | x |\n| d2 | S1 | DEC-TWO | r | y |\n")
    plan = ("# Plan\n\n| a | b |\n|---|---|\n| not | this |\n\n## Change log\n\n"
            "| Date | Session | Change | Reason | Asked by |\n|---|---|---|---|---|\n"
            "| d1 | S0 | old change | r | x |\n| d2 | S8 | new change | r | y |\n")
    p = rt.render_page(MASTER, {}, decisions_md=dec, plan_md=plan)
    assert '<a id="tab-decisions" href="#decisions">Decisions</a>' in p
    assert '<section id="view-decisions" class="view" data-view="decisions" hidden>' in p
    assert "Decisions (2)" in p and "Plan change log (2)" in p
    assert p.index("DEC-TWO") < p.index("DEC-ONE") and p.index("new change") < p.index("old change")
    assert "not" not in p.split("Plan change log")[1].split("</table>")[0]


def test_real_decisions_and_change_log_render():
    real = rt.render_page((ROOT / "docs/TRACKER.md").read_text(encoding="utf-8"), {},
                          decisions_md=(ROOT / "docs/DECISIONS.md").read_text(encoding="utf-8"),
                          plan_md=(ROOT / "docs/PLAN.md").read_text(encoding="utf-8"))
    assert "Plan change log (0)" not in real and "Decisions (0)" not in real


def test_bench_tab_appears_only_with_a_summary():
    md = ("# Bench results, summary\n\n## Back-test\n\n"
          "| Setup | hit@10 |\n|---|---|\n| BENCH-ROW | 0.1 |\n")
    p = rt.render_page(MASTER, {}, bench_md=md)
    assert '<a id="tab-bench" href="#bench">Bench</a>' in p
    assert '<section id="view-bench" class="view" data-view="bench" hidden>' in p
    assert "BENCH-ROW" in p and "<h1>Bench results, summary</h1>" in p
    assert "tab-bench" not in rt.render_page(MASTER, {})


def test_architecture_tab_inlines_its_svg_figures(tmp_path):
    (tmp_path / "fig.svg").write_text('<svg class="arch" role="img"><rect class="k-local"/></svg>')
    md = "# Where the models sit\n\n![FIG-CAPTION](fig.svg)\n\n- **Swap:** ARCH-ITEM\n"
    p = rt.render_page(MASTER, {}, arch_md=md, arch_root=tmp_path)
    assert '<a id="tab-architecture" href="#architecture">Architecture</a>' in p
    view = p.split('id="view-architecture"')[1].split("</section>")[0]
    assert '<figure class="panel diagram"><svg class="arch"' in view
    assert "<figcaption>FIG-CAPTION</figcaption>" in view and "ARCH-ITEM" in view
    assert "tab-architecture" not in rt.render_page(MASTER, {})

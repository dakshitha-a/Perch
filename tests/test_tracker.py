import importlib.util
import json
import re
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
| S0 | Repo | done | 2026-10-28 19:02 EDT | b | abc1234 | 12 tests green. |
| S1 | Store | in progress | 2026-10-30 10:00 EDT | | | |
| S2 | Awards | todo | | | | Next up. |

## Milestone readiness

| Milestone | Date | Needs | Ready? |
|---|---|---|---|
| Checkup 2 | Tue 3 Nov | S0 | |
| Code freeze | Thu 5 Nov 12:00 | S1 stabilized, S2 tags | |
| Submission | Fri 6 Nov 12:00 | ZIP + links | |

## Key numbers (keep current)

| Metric | Value | Source | Updated |
|---|---|---|---|
| Anthropic API spend / budget to demo | $2.09 of $100 | data/logs/x.jsonl | 2026-10-29 |
"""

PLAN = """# Plan

## Fixed milestones

| Date | What must exist | Sessions that must be done |
|---|---|---|
| Sat 31 Oct | Checkup 1 (one page) | nothing from the code; S1–S2 helpful |
| Tue 3 Nov | Checkup 2: prototype draft | S0–S1 |
| Thu 5 Nov 12:00 | Code freeze | everything kept |
| Fri 6 Nov 12:00 | Submission ZIP + links; 3:00 pm demo | S0 |

## S0 — Repo

| a | b |
|---|---|
| not | this |

## Change log

| Date | Session | Change | Reason | Asked by |
|---|---|---|---|---|
| d1 | S0 | old change | r | x |
| d2 | S1 | new change | r | y |
"""

TASKS = "| Task | What | Status | Commit | Notes |\n|---|---|---|---|---|\n"
S0 = "# S0 — Repo\n\n" + TASKS + "| 1 | x | done | abc | |\n| 2 | y | cut | | |\n"
S1 = (
    "# S1 — Store\n\nGoal.\n\n"
    + TASKS
    + "| 1 | `a<b` & **c** | done | | 40 tests green |\n| 2 | y | todo | | |\n\n"
    "## Definition of done\n\n- works\n"
)
ROUNDS = (
    "# S1 — QA\n\nGoal.\n\n"
    "| Round | Tester | Must / should / could found | Fixed | Status | Notes |"
    "\n"
    "|---|---|---|---|---|---|\n"
    "| 1 | Opus | 5 / 15 / 7 (+1 from S0) | 28 of 28 | done | 311 tests green (was 299) |\n"
    "| 2 | Opus | | | in progress | |\n"
)
QUESTIONS = (
    "# Q\n\n## Open\n\nPreamble.\n\n33. **One.** x\n- sub\n\n32. **Two.**\n\n"
    "## Answered\n\n1. old\n"
)
FACTS = rt.Facts(
    head="5fc7245",
    head_date="2026-10-31T23:33:05-04:00",
    spend=rt.Spend(2.558, 362, "2026-10-31T20:10:00+00:00"),
)


def page(artifact=False, **kw):
    return rt.render_page(MASTER, {"S0": S0, "S1": S1}, artifact=artifact, **kw)


def view(p, name):
    return p.split(f'id="view-{name}"')[1].split("</section>\n<section")[0]


# ---------- parsing ----------


def test_parses_master_table_into_sessions():
    ss = rt.build_sessions(rt.parse(MASTER), {"S1": S1})
    assert [s.sid for s in ss] == ["S0", "S1", "S2"]
    assert (ss[0].status, ss[0].commit, ss[0].notes) == ("done", "abc1234", "12 tests green.")
    assert ss[1].name == "Store" and ss[1].work.kind == "task"
    assert rt.pick_current(ss).sid == "S1"


def test_parses_task_file_and_round_file():
    tasks = rt.parse(S1).tables()[0]
    assert tasks.kind == "task" and rt.statuses_of(tasks) == ["done", "todo"]
    rounds = rt.parse(ROUNDS).tables()[0]
    assert rounds.kind == "round" and rt.statuses_of(rounds) == ["done", "in progress"]
    totals = rt.round_totals(rounds)
    assert (
        "<b>5</b>must" in totals
        and "<b>7</b>could found" in totals
        and "<b>28 of 28</b>fixed" in totals
    )


def test_round_file_renders_progress_and_cards():
    p = rt.render_page(MASTER, {"S1": ROUNDS})
    cur = view(p, "current")
    assert "<b>1/2</b>rounds done" in cur and 'class="bar"' in cur
    assert '<span class="cardlabel">Round </span>1' in cur
    assert 'data-label="Must / should / could found"' in cur


def test_list_items_keep_wrapped_lines():
    doc = rt.parse(
        "- Each file holds a token. The S13 leak test runs a\n"
        "full private brief and checks.\n- Two\n"
    )
    items = doc.blocks[0][1]
    assert len(items) == 2 and items[0].text.endswith("runs a full private brief and checks.")
    assert rt.open_questions(QUESTIONS) == 2


# ---------- milestones ----------


def test_milestone_readiness_rule():
    ss = rt.build_sessions(rt.parse(MASTER), {})
    assert rt.readiness("S0", ss) == "yes"
    assert rt.readiness("S0–S2", ss) == "no: S1, S2 not done"
    assert rt.readiness("S1 stabilized, S2 tags", ss) == "no: S1, S2 not done"
    assert rt.readiness("ZIP + links", ss) == "n/a"
    assert rt.readiness("nothing from the code; S1–S2 helpful", ss) == "n/a"
    assert rt.session_refs("S0–S3, S7 to S8") == ["S0", "S1", "S2", "S3", "S7", "S8"]


def test_milestones_merge_plan_rows_and_keep_tracker_needs():
    ss = rt.build_sessions(rt.parse(MASTER), {})
    ms = rt.build_milestones(rt.parse(MASTER), PLAN, ss)
    assert [m.name for m in ms] == ["Checkup 1", "Checkup 2", "Code freeze", "Submission"]
    assert [m.ready for m in ms] == ["n/a", "yes", "no: S1, S2 not done", "n/a"]
    assert ms[1].detail == "prototype draft" and ms[3].detail == "ZIP + links; 3:00 pm demo"
    freeze, demo = rt.key_deadlines(ms, 2026)
    assert freeze.isoformat() == "2026-11-05T12:00:00-05:00"  # after the DST change
    assert demo.isoformat() == "2026-11-06T15:00:00-05:00"


# ---------- at a glance ----------


def test_at_a_glance_values_from_fixture():
    p = rt.render_page(MASTER, {"S1": ROUNDS}, plan_md=PLAN, questions_md=QUESTIONS, facts=FACTS)
    g = p.split('class="glance"')[1].split("</section>")[0]
    assert 'data-deadline="2026-11-05T12:00:00-05:00"' in g  # freeze, counted down in the browser
    assert 'data-deadline="2026-11-06T15:00:00-05:00"' in g  # demo
    assert ">1 of 3</span>" in g  # sessions done
    assert "S1 rounds" in g and ">1 of 2</span>" in g
    assert ">311</span>" in g and "S1 task file" in g  # last count recorded, not run
    assert ">5fc7245</span>" in g and "31 Oct 2026" in g
    assert "$2.56 of $100" in g and "362 calls" in g
    assert 'Open questions</span><span class="v">2</span>' in g


def test_at_a_glance_degrades_without_facts():
    master = MASTER.replace("12 tests green.", "")
    g = rt.render_page(master, {"S1": S1.replace("40 tests green", "")}).split('class="glance"')[1]
    g = g.split("</section>")[0]
    assert 'Tests</span><span class="v none">not recorded' in g
    assert 'Last commit</span><span class="v none">not recorded' in g
    assert "$2.09 of $100" in g and "key numbers, updated 2026-10-29" in g  # from the key numbers


def test_spend_ledger_sum(tmp_path):
    ledger = tmp_path / "spend.jsonl"
    rows = [
        {"at": "2026-10-29T01:00:00+00:00", "cost_usd": 0.5},
        {"at": "2026-10-31T01:00:00+00:00", "cost_usd": 0.25},
    ]
    ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    s = rt.read_spend(ledger)
    assert (round(s.total, 2), s.calls, s.last[:10]) == (0.75, 2, "2026-10-31")
    assert rt.read_spend(tmp_path / "missing.jsonl") is None


# ---------- tabs and views ----------


def test_tabs_open_on_current_in_reader_order(tmp_path):
    src = rt.Source("x.md", "# X\n", "")
    p = rt.render_page(
        MASTER,
        {},
        bench=src,
        arch=src,
        arch_root=tmp_path,
        ui="ui.html",
        readme="readme.html",
        ux=[src],
        persona={"README.md": "# P\n"},
    )
    order = re.findall(r'<a id="tab-([a-z]+)"', p)
    assert order == [
        "current",
        "master",
        "decisions",
        "archive",
        "ui",
        "ux",
        "bench",
        "readme",
        "architecture",
        "persona",
    ]
    assert re.findall(r'data-view="([a-z]+)"', p) == order
    assert '<a id="tab-current" href="#current" aria-current="page">Current</a>' in p
    assert '<section id="view-current" class="view" data-view="current">' in p
    assert '<section id="view-master" class="view" data-view="master" hidden>' in p
    assert "tab-bench" not in rt.render_page(MASTER, {})


def test_finished_sessions_are_archived_with_honest_counts():
    p = page()
    assert '<details id="s0">' in p and '<details id="s1"' not in p
    assert '<a href="#s0">S0</a>' in p  # master row links to its archive entry
    assert '<tr class="is-current">' in p
    assert "2 tasks: 1 done, 1 cut" in view(p, "archive")


def test_html_escaping_of_table_cells():
    master = MASTER.replace("| Repo |", "| <script>alert(1)</script> [x](javascript:alert(1)) |")
    p = rt.render_page(master, {"S1": S1})
    assert "<script>alert(1)</script>" not in p
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in p
    assert 'href="javascript' not in p
    assert "<code>a&lt;b</code> &amp; <strong>c</strong>" in p


def test_every_cell_is_labelled_for_phone_cards():
    p = page()
    cells = re.findall(r"<td[^>]*>", view(p, "master"))
    assert cells and all("data-label=" in c for c in cells)
    assert "@media (max-width: 699px)" in p and "td::before { content: attr(data-label)" in p
    assert 'class="rt kv"' in p  # key numbers: Metric wraps, Value takes the width


def test_decisions_filter_markup_newest_first():
    dec = (
        "| Date | Session | Decision | Reason | Decided by |\n|---|---|---|---|---|\n"
        "| d1 | S0 | DEC-ONE | r | x |\n| d2 | S1 | DEC-TWO | r | y |\n"
    )
    p = rt.render_page(MASTER, {}, decisions_md=dec, plan_md=PLAN)
    v = view(p, "decisions")
    assert '<input id="dq" type="search"' in v and '<select id="ds">' in v
    assert '<button type="button" class="chip" data-s="s1" aria-pressed="false">S1</button>' in v
    assert '<table class="rt" data-filter="dcount">' in v and '<tr data-s="s1">' in v
    assert 'id="dcount">2</b>' in v and "Decisions (2)" in v and "Plan change log (2)" in v
    assert v.index("DEC-TWO") < v.index("DEC-ONE") and v.index("new change") < v.index("old change")
    assert "not" not in v.split("Plan change log")[1].split("</table>")[0]


def test_stale_note_when_source_predates_newest_session_start():
    old = rt.Source(
        "bench/results/RESULTS.md",
        "# Bench\n\n## A\n\n| x | y |\n|---|---|\n| 1 | 2 |\n",
        "2026-10-29T10:00:00-04:00",
    )
    new = rt.Source("bench/results/RESULTS.md", old.text, "2026-10-30T11:00:00-04:00")
    stale = view(rt.render_page(MASTER, {}, bench=old), "bench")
    assert (
        "Built from <code>bench/results/RESULTS.md</code>, last changed 29 Oct 2026, 10:00" in stale
    )
    assert "May be behind: older than the start of S1" in stale
    assert "May be behind" not in view(rt.render_page(MASTER, {}, bench=new), "bench")


def test_ui_intro_comes_from_the_replay_sidecar():
    facts = rt.Facts(
        replays={"ui": {"replay": "build/replay/abc.json", "created_at": "2026-10-29T20:51:40Z"}}
    )
    p = rt.render_page(MASTER, {}, ui="ui.html", facts=facts)
    v = view(p, "ui")
    assert "saved on 29 Oct 2026" in v and "build/replay/abc.json" in v and "May be behind" in v
    assert "S24" not in v and "15 seconds" not in v
    assert v.index('data-size="wide" aria-pressed="true">Laptop') < v.index(
        'data-size="phone" aria-pressed="false">Phone'
    )


def test_architecture_inlines_svg_figures(tmp_path):
    (tmp_path / "fig.svg").write_text('<svg class="arch" role="img"><rect class="k-local"/></svg>')
    src = rt.Source(
        "docs/ARCHITECTURE.md", "# Where\n\n![FIG-CAPTION](fig.svg)\n\n- **Swap:** ITEM\n", ""
    )
    v = view(rt.render_page(MASTER, {}, arch=src, arch_root=tmp_path), "architecture")
    assert '<figure class="panel diagram"><svg class="arch"' in v
    assert "<figcaption>FIG-CAPTION</figcaption>" in v and "ITEM" in v and "not in git yet" in v


def test_theme_toggle_and_artifact_contract():
    p = page(artifact=True)
    assert p.startswith("<title>Perch Build Tracker</title>")
    assert "<!doctype" not in p and "<body>" not in p
    assert ':root:not([data-theme="light"])' in p and ':root[data-theme="dark"]' in p
    assert 'id="theme"' in p and "try { var t = localStorage" in p


def test_deterministic_and_session_order(tmp_path):
    assert page(facts=FACTS) == page(facts=FACTS)
    for name in ("S2.md", "S10.md", "S1.md", "notes.md"):
        (tmp_path / name).write_text("# x\n")
    assert list(rt.load_sessions(tmp_path)) == ["S1", "S2", "S10"]


def test_real_tracker_renders_standalone():
    real = rt.render_page(
        (ROOT / "docs/TRACKER.md").read_text(encoding="utf-8"),
        rt.load_sessions(ROOT / "docs/sessions"),
        decisions_md=(ROOT / "docs/DECISIONS.md").read_text(encoding="utf-8"),
        plan_md=(ROOT / "docs/PLAN.md").read_text(encoding="utf-8"),
    )
    assert real.startswith("<!doctype html>")
    assert '<th scope="col">Session</th>' in real
    assert "http" not in real.split("<body>")[0]  # standalone page makes no external requests
    assert "Plan change log (0)" not in real and "Decisions (0)" not in real
    assert "Code freeze" in real and "Ready?" in real


def test_bold_may_wrap_inline_code_and_code_is_left_alone():
    assert rt.inline("**the `x<y` file** and `**not bold**`") == (
        "<strong>the <code>x&lt;y</code> file</strong> and <code>**not bold**</code>")

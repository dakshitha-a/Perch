"""Render the Perch build tracker as one static web page.

Sources (Markdown is the source of truth; the renderer never edits them):
  docs/TRACKER.md          sessions, milestone readiness, key numbers
  docs/sessions/S<n>.md    one file per session: a task table, or a round table (QA cycles)
  docs/DECISIONS.md        decision log
  docs/PLAN.md             its "Fixed milestones" and "Change log" tables
  bridge/QUESTIONS.md      the count of items under "## Open"
  bench/results/RESULTS.md bench results (SUMMARY.md only when RESULTS.md is missing)
  docs/design/qa/CYCLE_*.md, docs/design/UX_REVIEW_S*.md, docs/design/UX_AUDIT.md   UX tab
  docs/ARCHITECTURE.md     its ![caption](file.svg) figures are inlined
  data/synthetic/persona-1/  the SYNTHETIC private-mode persona
  data/logs/anthropic_spend.jsonl  gitignored; when absent the key-numbers row is used
  git log                  the last commit and each source file's last-changed date

Tabs, switched by hash links (#current, #master, #decisions, #archive, #s<n>, ...):
  Current, Master, Decisions, Archive, then UI, UX, Bench, README, Architecture, Persona
  (each of the last six only when its source exists). Current opens at rest.

The page is deterministic for a given commit and set of sources: nothing reads the clock.
Countdowns to the freeze and the demo are computed in the browser from fixed deadlines.
Two outputs: a complete standalone document with no external requests (docs/tracker.html),
and --artifact, a fragment for a claude.ai Artifact (the host adds the document skeleton;
the fragment adds a Google Fonts link and its images are copied beside it).

Usage: python scripts/render_tracker.py [TRACKER.md] [DEST] [--artifact] [--title NAME]
                                        [--ui PATH] [--ui-student PATH] [--readme PATH]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

STATUSES = ("done", "in progress", "continued", "todo", "cut")
FINISHED = ("done", "cut")
MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
ZONES = {"EDT": -4, "EST": -5, "UTC": 0, "GMT": 0}
DECISIONS_CAP = 25  # rows per table shown until a filter is used
LONG_CELL = 220  # characters; longer cells get a "more" fold after about four lines

FONT_LINK = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=Public+Sans:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap\">"
)

DARK = """--bg: #101513; --surface: #161e1b; --raised: #1d2723; --fg: #e4ece7; --muted: #9eada5;
    --line: #2c3833; --code: #24302b; --accent: #5cc4a6; --accent-soft: #19362e; --on-accent: #08130f;
    --todo: #a3aea8; --progress: #f0a640; --progress-soft: #3a2c17; --continued: #b89cf6;
    --done: #62d493; --done-soft: #16301f; --cut: #f2878a; --cut-soft: #3a1c1d;
    color-scheme: dark;"""


def card_css(sel: str) -> str:
    """Stacked cards: one card per row, each cell a labelled line (no sideways scroll)."""
    return f"""
{sel}, {sel} tbody, {sel} tr, {sel} td {{ display: block; width: 100%; }}
{sel} thead {{ position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap; }}
{sel} tr {{ padding: 10px 14px; border-bottom: 1px solid var(--line); }}
{sel} tr:last-child {{ border-bottom: 0; }}
{sel} tr[hidden] {{ display: none; }}
{sel} td {{ border: 0; padding: 3px 0; display: grid; grid-template-columns: minmax(6.5em, 28%) minmax(0, 1fr);
  gap: 0 12px; white-space: normal; background: none; }}
{sel} td::before {{ content: attr(data-label); color: var(--muted); font: 600 var(--t-xs)/1.6 var(--sans); }}
{sel} td > .c, {sel} td > .more {{ grid-column: 2; }}
{sel} td.blank {{ display: none; }}
{sel} td:first-child {{ grid-template-columns: minmax(0, 1fr); font-size: var(--t-md); padding-bottom: 6px; }}
{sel} td:first-child::before {{ display: none; }}
{sel} td:first-child > .c, {sel} td:first-child > .more {{ grid-column: 1; }}
"""


CSS = (
    """
:root {
  --bg: #f5f7f5; --surface: #ffffff; --raised: #eef2ef; --fg: #17201c; --muted: #536059;
  --line: #d8dfda; --code: #e8eee9; --accent: #1f6f5c; --accent-soft: #dcefe8; --on-accent: #ffffff;
  --todo: #5f6a64; --progress: #8f5200; --progress-soft: #f7ecd9; --continued: #6d3fc0;
  --done: #1b7340; --done-soft: #e1f2e7; --cut: #b02222; --cut-soft: #f8e3e3;
  --sans: "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
  --t-xs: 12px; --t-sm: 13.5px; --t-md: 15px; --t-lg: 18px; --t-xl: 26px;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { DARK } }
:root[data-theme="dark"] { DARK }
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--fg); font: var(--t-md)/1.55 var(--sans); }
.wrap { max-width: 1120px; margin: 0 auto;
  padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px)); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px; }
a { color: var(--accent); text-underline-offset: 2px; }
strong { color: var(--fg); }
code { font-family: var(--mono); background: var(--code); padding: 1px 5px; border-radius: 3px;
  font-size: 0.86em; overflow-wrap: anywhere; }
.appbar { background: var(--surface); border-bottom: 1px solid var(--line); }
.appbar .wrap { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 16px; padding-top: 10px; }
.brand { display: flex; align-items: baseline; gap: 10px; margin-right: auto; }
.brand b { font-size: var(--t-lg); letter-spacing: -0.01em; }
.brand span { color: var(--muted); font-size: var(--t-sm); }
.hdr-meta { font-size: var(--t-sm); color: var(--muted); }
.btn { min-height: 36px; padding: 0 12px; border-radius: 6px; border: 1px solid var(--line);
  background: var(--surface); color: var(--fg); font: 600 var(--t-sm)/1 var(--sans); cursor: pointer; }
.btn:hover { border-color: var(--muted); }
.btn[aria-pressed="true"] { background: var(--accent-soft); border-color: var(--accent); color: var(--fg); }
nav { flex-basis: 100%; display: flex; flex-wrap: wrap; gap: 2px; margin-top: 4px; }
nav a { color: var(--muted); text-decoration: none; font-weight: 600; font-size: var(--t-sm);
  padding: 9px 11px 10px; border-bottom: 2px solid transparent; white-space: nowrap;
  display: inline-flex; align-items: center; }
nav a:hover { color: var(--fg); }
nav a[aria-current="page"] { color: var(--accent); border-bottom-color: var(--accent); }
.count { font-family: var(--mono); font-size: 11px; background: var(--raised); color: var(--muted);
  border-radius: 999px; padding: 1px 7px; margin-left: 6px; }
main.wrap { padding-top: 22px; padding-bottom: 56px; }
.view { display: grid; gap: 16px; }
.view[hidden] { display: none; }
.view > * { min-width: 0; margin: 0; }
.eyebrow { font-size: var(--t-xs); text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
  font-weight: 600; }
.title-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; }
h1 { font-size: var(--t-xl); line-height: 1.2; text-wrap: balance; letter-spacing: -0.01em; margin: 0; }
h2 { font-size: var(--t-lg); line-height: 1.3; margin: 14px 0 0; letter-spacing: -0.005em; }
h3 { font-size: var(--t-md); margin: 8px 0 0; }
p, li { max-width: 76ch; margin: 0; }
.prose p, .prose li, p.lead { color: var(--muted); }
ul, ol { padding-left: 1.3em; display: grid; gap: 4px; margin: 0; }
li > ul, li > ol { margin-top: 4px; }
blockquote { margin: 0; padding: 4px 14px; border-left: 3px solid var(--line); color: var(--muted); }
pre.code, pre.doc { white-space: pre-wrap; overflow-wrap: anywhere; font: var(--t-sm)/1.5 var(--mono);
  background: var(--code); padding: 12px 14px; margin: 0; border-radius: 6px; }
pre.doc { background: var(--surface); }
.meta, .src { font-size: var(--t-sm); color: var(--muted); }
.src code { font-size: 0.92em; }
.stale { display: inline-block; margin-left: 4px; padding: 0 8px; border-radius: 4px;
  background: var(--progress-soft); color: var(--progress); font-weight: 600; }
.stale::before { content: "\\25B2  "; font-size: 0.8em; }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }
.empty { padding: 18px 16px; color: var(--muted); }
.sub { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: var(--t-sm); }

/* At a glance */
.glance { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px;
  background: var(--line); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.tile { background: var(--surface); padding: 11px 14px 12px; display: grid; gap: 2px; align-content: start; }
.cardlabel { display: none; }
.tile .k { font-size: var(--t-xs); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted);
  font-weight: 600; }
.tile .v { font: 600 var(--t-lg)/1.25 var(--mono); font-variant-numeric: tabular-nums; }
.tile .s { font-size: var(--t-xs); color: var(--muted); }
.tile .v.none { font-family: var(--sans); font-size: var(--t-md); color: var(--muted); font-weight: 600; }

/* Progress */
.summary { display: grid; gap: 10px; padding: 14px 16px; }
.counts { display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: var(--t-sm); color: var(--muted); }
.counts b { font-family: var(--mono); font-variant-numeric: tabular-nums; font-size: var(--t-md);
  margin-right: 5px; color: var(--fg); }
.counts .lead-count b { font-size: var(--t-lg); }
.bar { display: flex; height: 10px; border-radius: 5px; overflow: hidden; background: var(--raised); }
.bar span { display: block; height: 100%; }
.bar span + span { border-left: 2px solid var(--surface); }

/* Status badges: always text, colour only reinforces it */
.badge { display: inline-block; padding: 1px 9px; border-radius: 999px; font: 600 var(--t-xs)/1.6 var(--sans);
  white-space: nowrap; border: 1px solid currentColor; }
.s-todo { color: var(--todo); } .s-in-progress { color: var(--progress); }
.s-continued { color: var(--continued); } .s-done { color: var(--done); } .s-cut { color: var(--cut); }
.badge.s-done { background: var(--done-soft); } .badge.s-in-progress { background: var(--progress-soft); }
.badge.s-cut { background: var(--cut-soft); }
.bar .s-todo { background: var(--todo); opacity: .45; } .bar .s-in-progress { background: var(--progress); }
.bar .s-continued { background: var(--continued); } .bar .s-done { background: var(--done); }
.bar .s-cut { background: var(--cut); }
.ready { font-weight: 600; } .ready.yes { color: var(--done); } .ready.no { color: var(--progress); }
.ready.na { color: var(--muted); font-weight: 400; }

/* Tables */
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: var(--t-sm); }
th, td { border-bottom: 1px solid var(--line); padding: 8px 12px; text-align: left; vertical-align: top; }
tr:last-child td { border-bottom: 0; }
th { background: var(--raised); font-weight: 600; font-size: var(--t-xs); text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--muted); }
td.id { font-family: var(--mono); font-weight: 600; white-space: nowrap; }
td.mono { font-family: var(--mono); font-size: var(--t-xs); white-space: nowrap; }
td.date { font-size: var(--t-xs); color: var(--muted); min-width: 7em; }
td.st { white-space: nowrap; }
td .c { overflow-wrap: break-word; }
tr.is-current td { background: var(--accent-soft); }
tr.is-finished td { color: var(--muted); }
table.kv { table-layout: fixed; }
table.kv th:nth-child(1) { width: 23%; } table.kv th:nth-child(2) { width: 47%; }
table.kv th:nth-child(3) { width: 19%; } table.kv th:nth-child(4) { width: 11%; }
table.kv td:nth-child(1) { font-weight: 600; }
table.kv td:nth-child(3) { font-size: var(--t-xs); color: var(--muted); overflow-wrap: anywhere; }
table.kv td:nth-child(3) code { background: none; padding: 0; }
table.kv td:nth-child(4) { font: var(--t-xs)/1.6 var(--mono); color: var(--muted); }
.clamp { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 4; overflow: hidden; }
.clamp.open { display: block; }
.more { justify-self: start; margin-top: 2px; padding: 2px 0; border: 0; background: none; color: var(--accent);
  font: 600 var(--t-xs)/1.6 var(--sans); cursor: pointer; text-decoration: underline; text-underline-offset: 2px; }
.more[hidden] { display: none; }
CARDS_ALWAYS
@media (max-width: 699px) {
  CARDS_PHONE
  table.rt.kv td:nth-child(3), table.rt.kv td:nth-child(4) { font-size: var(--t-xs); }
  nav { gap: 6px; padding-bottom: 10px; }
  nav a { min-height: 44px; padding: 0 12px; border: 1px solid var(--line); border-radius: 8px; }
  nav a[aria-current="page"] { border-color: var(--accent); background: var(--accent-soft); color: var(--fg); }
  .btn, .chip, select, input[type="search"] { min-height: 44px; }
  .glance { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .hdr-meta { order: 3; flex-basis: 100%; }
  nav { order: 4; }
  .cardlabel { display: inline; }
  .more { min-height: 44px; }
  h1 { font-size: 22px; }
}

/* Folds */
details { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }
details + details { margin-top: 10px; }
summary { cursor: pointer; list-style: none; display: grid; align-items: center; gap: 2px 12px;
  grid-template-columns: auto minmax(0, 1fr) auto; padding: 12px 16px; min-height: 44px; }
summary::-webkit-details-marker { display: none; }
summary::before { content: "\\25B8"; color: var(--muted); grid-row: span 2; align-self: start; }
details[open] > summary::before { content: "\\25BE"; }
summary .sline { min-width: 0; }
summary .sid { font-family: var(--mono); font-weight: 600; margin-right: 6px; }
summary .stitle { font-weight: 600; }
summary .badge { justify-self: end; }
summary .smeta { grid-column: 2 / -1; font-size: var(--t-sm); color: var(--muted); }
details .inner { display: grid; gap: 14px; padding: 0 16px 16px; }
details .inner > * { min-width: 0; }
@media (max-width: 560px) { summary .badge { grid-column: 2; justify-self: start; } }
.next { display: grid; gap: 10px; padding: 14px 16px; }
.next-item { display: grid; gap: 2px; }
.next-item b { font-family: var(--mono); margin-right: 6px; }
.done-list { list-style: none; padding: 14px 16px; }
.done-list li::before { content: "\\2610"; margin-right: 8px; color: var(--muted); }

/* Decisions filter */
.filters { display: grid; gap: 10px; padding: 14px 16px; }
.filters .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.filters label { font-weight: 600; font-size: var(--t-sm); }
.filters input[type="search"] { flex: 1 1 240px; min-width: 0; min-height: 38px; padding: 0 12px;
  border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); font: inherit; }
.filters select { min-height: 38px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg);
  color: var(--fg); font: inherit; padding: 0 8px; }
.chip { min-height: 34px; padding: 0 12px; border-radius: 999px; border: 1px solid var(--line);
  background: var(--surface); color: var(--fg); font: 600 var(--t-sm)/1 var(--mono); cursor: pointer; }
.chip[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.chip.all { font-family: var(--sans); }

/* Figures, previews */
figure.diagram { margin: 0; padding: 16px; display: grid; gap: 12px; justify-items: center; overflow-x: auto; }
@media (max-width: 600px) { figure.diagram { justify-items: start; } }
figure.diagram svg { width: 100%; min-width: 560px; max-width: 720px; height: auto; color: var(--fg); }
figure.shot { margin: 0; padding: 12px; display: grid; gap: 8px; justify-items: center; }
figure.shot img { max-width: 100%; max-height: 640px; height: auto; border-radius: 6px; }
figure figcaption { font-size: var(--t-sm); color: var(--muted); justify-self: start;
  max-width: min(76ch, calc(100vw - 66px)); }
svg.arch .k-local { fill: var(--accent-soft); stroke: var(--accent); }
svg.arch .k-cloud { fill: var(--progress-soft); stroke: var(--progress); }
svg.arch .k-loop { stroke: var(--progress); }
svg.arch .k-private, svg.arch .k-private-x { stroke: var(--cut); }
.ui-tools { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.ui-tools a { margin-left: auto; }
.ui-stage { display: flex; justify-content: center; padding: 8px 0 4px; }
.ui-frame { display: block; border: 0; background: var(--surface); }
.ui-frame.phone { width: 390px; max-width: 100%; height: 800px; border-radius: 30px;
  box-shadow: 0 0 0 10px var(--fg), 0 12px 40px rgba(0, 0, 0, .25); margin: 10px 0; }
.ui-frame.wide { width: 100%; height: 820px; border-radius: 10px; border: 1px solid var(--line); }
@media (max-width: 560px) { .ui-frame.phone { box-shadow: none; border-radius: 0; height: 760px; } }
.readme-frame { width: 100%; height: 80vh; border: 1px solid var(--line); border-radius: 8px; background: #fff; }
.foot { font-size: var(--t-xs); color: var(--muted); }
"""
    .replace("DARK", DARK)
    .replace("CARDS_ALWAYS", card_css("table.rt.cards"))
    .replace("CARDS_PHONE", card_css("table.rt"))
)

THEME_SCRIPT = """(function () {
  try { var t = localStorage.getItem("perch-tracker-theme");
    if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t); } catch (e) {}
})();"""

SCRIPT = """
(function () {
  var doc = document, root = doc.documentElement, KEY = "perch-tracker-theme";
  function each(sel, fn, scope) { Array.prototype.forEach.call((scope || doc).querySelectorAll(sel), fn); }

  // Theme: system, light, dark; remembered when storage works.
  var themeBtn = doc.getElementById("theme");
  function saved() { try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; } }
  function setTheme(v) {
    if (v) root.setAttribute("data-theme", v); else root.removeAttribute("data-theme");
    try { if (v) localStorage.setItem(KEY, v); else localStorage.removeItem(KEY); } catch (e) {}
    if (themeBtn) themeBtn.textContent = "Theme: " + (v || "system");
  }
  setTheme(saved());
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var order = ["", "light", "dark"], cur = root.getAttribute("data-theme") || "";
    setTheme(order[(order.indexOf(cur) + 1) % order.length]);
  });

  // Countdowns: fixed deadlines in the page, the clock read here only.
  function left(iso) {
    var ms = new Date(iso).getTime() - Date.now();
    if (isNaN(ms)) return "";
    if (ms <= 0) return "passed";
    var h = Math.floor(ms / 3600000), d = Math.floor(h / 24);
    return d >= 2 ? d + " days" : d === 1 ? "1 day " + (h - 24) + " h" : h + " h";
  }
  function tick() { each("[data-deadline]", function (el) {
    var t = left(el.getAttribute("data-deadline")); if (t) el.textContent = t; }); }
  tick(); setInterval(tick, 60000);

  // "more" folds: shown only where the text is really cut.
  function measure(scope) {
    each(".clamp", function (c) {
      var b = c.nextElementSibling;
      if (!b || !b.classList.contains("more") || c.classList.contains("open")) return;
      if (!c.offsetParent) return;
      b.hidden = c.scrollHeight <= c.clientHeight + 2;
    }, scope);
  }
  doc.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("button.more");
    if (!b) return;
    var c = b.previousElementSibling, open = !c.classList.contains("open");
    c.classList.toggle("open", open);
    b.textContent = open ? "less" : "more";
    b.setAttribute("aria-expanded", String(open));
  });
  var timer;
  window.addEventListener("resize", function () { clearTimeout(timer); timer = setTimeout(function () { measure(); }, 150); });
  each("details", function (d) { d.addEventListener("toggle", function () { measure(d); }); });

  // Decisions filter: text and session, client-side.
  var q = doc.getElementById("dq"), sel = doc.getElementById("ds"), all = doc.getElementById("dall");
  var showAll = false;
  function filter() {
    var text = (q.value || "").trim().toLowerCase(), s = sel.value;
    var cap = showAll || text || s ? Infinity : +(all ? all.getAttribute("data-cap") : Infinity);
    var capped = 0;
    each(".chip[data-s]", function (c) { c.setAttribute("aria-pressed", String(c.getAttribute("data-s") === s)); });
    each("table[data-filter]", function (t) {
      var shown = 0, rows = t.tBodies[0].rows;
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        if (r._t === undefined) r._t = r.textContent.toLowerCase();
        var ok = (!s || (" " + r.getAttribute("data-s") + " ").indexOf(" " + s + " ") >= 0)
          && (!text || r._t.indexOf(text) >= 0);
        if (ok && shown >= cap) { ok = false; capped++; }
        r.hidden = !ok; if (ok) shown++;
      }
      var n = doc.getElementById(t.getAttribute("data-filter"));
      if (n) n.textContent = shown === rows.length ? String(rows.length) : shown + " of " + rows.length;
      var none = doc.getElementById(t.getAttribute("data-filter") + "-none");
      if (none) none.hidden = shown > 0;
    });
    if (all) { all.hidden = !capped; all.textContent = "Show all rows (" + capped + " more)"; }
    measure(doc.getElementById("view-decisions"));
  }
  if (q && sel) {
    q.addEventListener("input", filter);
    sel.addEventListener("change", filter);
    if (all) all.addEventListener("click", function () { showAll = true; filter(); });
    each(".chip[data-s]", function (c) { c.addEventListener("click", function () {
      sel.value = c.getAttribute("data-s"); filter(); }); });
    filter();
  }

  // UI preview controls.
  var frame = doc.getElementById("ui-frame");
  each("[data-size]", function (b) {
    b.addEventListener("click", function () {
      frame.className = "ui-frame " + b.getAttribute("data-size");
      each("[data-size]", function (x) { x.setAttribute("aria-pressed", String(x === b)); });
    });
  });
  var restart = doc.getElementById("ui-restart");
  if (restart) restart.addEventListener("click", function () { frame.src = frame.src.split("#")[0]; });
  ["ui-student", "ui-researcher"].forEach(function (id) {
    var b = doc.getElementById(id);
    if (b) b.addEventListener("click", function () { frame.src = b.getAttribute("data-src"); });
  });
  // README preview: grow the frame to its page when the browser lets us read it.
  // The page posts its height (works across origins and from disk); reading it directly is a fallback.
  var rf = doc.getElementById("readme-frame");
  function grow(h) { if (rf && h > 200) rf.style.height = (h + 4) + "px"; }
  function fit() { try { grow(rf.contentDocument.documentElement.scrollHeight); } catch (e) {} }
  if (rf) rf.addEventListener("load", fit);
  window.addEventListener("message", function (e) {
    if (rf && e.source === rf.contentWindow && e.data && e.data.perchReadmeHeight)
      grow(+e.data.perchReadmeHeight);
  });

  // Router.
  var views = [];
  each("section[data-view]", function (s) { views.push(s.getAttribute("data-view")); });
  function route() {
    var h = (location.hash || "#" + views[0]).slice(1), target = null;
    if (views.indexOf(h) < 0) {
      target = doc.getElementById(h) || doc.getElementById(h.toLowerCase());
      var host = target && target.closest("[data-view]");
      h = host ? host.getAttribute("data-view") : views[0];
      if (target && target.tagName === "DETAILS") target.open = true;
    }
    views.forEach(function (v) {
      doc.getElementById("view-" + v).hidden = v !== h;
      var tab = doc.getElementById("tab-" + v);
      if (v === h) tab.setAttribute("aria-current", "page"); else tab.removeAttribute("aria-current");
    });
    measure(doc.getElementById("view-" + h));
    if (h === "readme" && rf) fit();
    if (target) target.scrollIntoView({ block: "start" }); else window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", route);
  route();
})();
"""


# ---------- Markdown subset ----------


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def inline(text: str) -> str:
    """Escape text, then apply inline code, links, bold and italics. Code spans are set aside
    first, so bold may wrap code ('**the `x` file**') and nothing inside code is formatted."""
    codes: list[str] = []

    def hold(m: re.Match) -> str:
        codes.append(f"<code>{esc(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    s = esc(re.sub(r"`([^`]*)`", hold, text.replace("\x00", "")))

    def link(m: re.Match) -> str:
        href = m.group(2)
        if re.match(r"(?i)\s*(javascript|data|vbscript):", html.unescape(href)):
            return m.group(1)
        return f'<a href="{href}">{m.group(1)}</a>'

    s = re.sub(r"\[([^\]]+)\]\(([^)\s\x00]+)\)", link, s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?", line.strip()))


@dataclass
class Table:
    head: list[str]
    rows: list[list[str]]

    def col(self, name: str) -> int | None:
        """Index of the first column whose header starts with name (case-insensitive)."""
        for i, h in enumerate(self.head):
            if h.lower().startswith(name.lower()):
                return i
        return None

    @property
    def kind(self) -> str:
        return self.head[0].strip().lower() if self.head else ""


@dataclass
class Doc:
    title: str = ""
    # Blocks: ("h", level, text), ("p", text), ("ul"|"ol", [Item]), ("table", Table),
    # ("fig", caption, src), ("code", text), ("quote", text).
    blocks: list[tuple] = field(default_factory=list)

    def tables(self) -> list[Table]:
        return [b[1] for b in self.blocks if b[0] == "table"]


@dataclass
class Item:
    text: str
    children: list[Item] = field(default_factory=list)


LIST_RE = re.compile(r"(\s*)([-*+]|\d+[.)])\s+(.*)")


def _starts_block(line: str) -> bool:
    s = line.strip()
    return bool(re.match(r"(#{1,6}\s|\||```|>|!\[)", s)) or bool(LIST_RE.fullmatch(line))


def parse(md: str) -> Doc:
    doc = Doc()
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
        elif s.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            doc.blocks.append(("code", "\n".join(lines[i + 1 : j])))
            i = j + 1
        elif m := re.match(r"(#{1,6})\s+(.*)", s):
            if len(m.group(1)) == 1 and not doc.title:
                doc.title = m.group(2).strip()
            else:
                doc.blocks.append(("h", len(m.group(1)), m.group(2).strip()))
            i += 1
        elif s.startswith("|") and i + 1 < len(lines) and is_separator(lines[i + 1]):
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            head = split_row(lines[i])
            rows = [(split_row(r) + [""] * len(head))[: len(head)] for r in lines[i + 2 : j]]
            doc.blocks.append(("table", Table(head, rows)))
            i = j
        elif m := re.fullmatch(r"!\[(.*)\]\((\S+)\)", s):
            doc.blocks.append(("fig", m.group(1), m.group(2)))
            i += 1
        elif s.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            doc.blocks.append(("quote", " ".join(quote)))
        elif m := LIST_RE.fullmatch(lines[i]):
            ordered = m.group(2)[0].isdigit()
            base = len(m.group(1))
            items: list[Item] = []
            start = int(re.sub(r"\D", "", m.group(2)) or 1) if ordered else 1
            while i < len(lines):
                line = lines[i]
                lm = LIST_RE.fullmatch(line)
                if lm and len(lm.group(1)) <= base + 1:
                    items.append(Item(lm.group(3).strip()))
                    i += 1
                elif lm and items:  # nested item, one level
                    items[-1].children.append(Item(lm.group(3).strip()))
                    i += 1
                elif line.strip() and items and not _starts_block(line):
                    # A wrapped line continues the item above (lazy continuation).
                    last = items[-1].children[-1] if items[-1].children and line.startswith("    ") \
                        else items[-1]
                    last.text += " " + line.strip()
                    i += 1
                elif not line.strip() and i + 1 < len(lines) and LIST_RE.fullmatch(lines[i + 1]) \
                        and (LIST_RE.fullmatch(lines[i + 1]).group(2)[0].isdigit()) == ordered:
                    i += 1  # a loose list: a blank line between items
                else:
                    break
            doc.blocks.append(("ol" if ordered else "ul", items, start))
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not _starts_block(lines[i]):
                para.append(lines[i].strip())
                i += 1
            if not para:  # a line that looks like a block start but is not one
                para.append(lines[i].strip())
                i += 1
            doc.blocks.append(("p", " ".join(para)))
    return doc


def section(md: str, heading: str) -> str:
    """The Markdown under '## heading' up to the next '## '."""
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", md, re.M | re.S | re.I)
    return m.group(1) if m else ""


# ---------- Dates ----------


def parse_stamp(text: str) -> datetime | None:
    """'2026-10-31 21:09 EDT' or an ISO date with offset -> aware datetime."""
    text = text.strip()
    if not text:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})(?::\d{2})?\s*([A-Z]{2,4})?$", text)
    if m and (m.group(3) or "") in ZONES | {"": 0}:
        tz = timezone(timedelta(hours=ZONES.get(m.group(3) or "UTC", 0)))
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}").replace(tzinfo=tz)
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def eastern(day: datetime) -> timezone:
    """US Eastern offset for a date (Temple's time zone): EDT from the second Sunday of
    March to the first Sunday of November, EST otherwise."""
    y = day.year

    def nth_sunday(month: int, n: int) -> datetime:
        d = datetime(y, month, 1)
        d += timedelta(days=(6 - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)

    dst = nth_sunday(3, 2) + timedelta(hours=2) <= day.replace(tzinfo=None) < nth_sunday(11, 1) + timedelta(hours=2)
    return timezone(timedelta(hours=-4 if dst else -5))


def deadline(text: str, year: int, default_time: str = "23:59") -> datetime | None:
    """'Thu 5 Nov 12:00' or '3:00 pm' style text in a given year -> aware datetime, Eastern."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*", text)
    if not m or m.group(2).lower() not in MONTHS:
        return None
    hm = re.search(r"(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?", text[m.end():], re.I)
    hh, mm = (int(hm.group(1)), int(hm.group(2))) if hm else map(int, default_time.split(":"))
    if hm and hm.group(3):
        hh = hh % 12 + (12 if hm.group(3).lower().startswith("p") else 0)
    naive = datetime(year, MONTHS[m.group(2).lower()], int(m.group(1)), hh, mm)
    return naive.replace(tzinfo=eastern(naive))


def short_date(iso: str, with_time: bool = False) -> str:
    d = parse_stamp(iso)
    if not d:
        return iso
    s = f"{d.day} {d.strftime('%b')} {d.year}"
    return s + d.strftime(", %H:%M") if with_time else s


# ---------- Facts from outside the Markdown ----------


@dataclass
class Spend:
    total: float
    calls: int
    last: str = ""  # ISO timestamp of the last call


@dataclass
class Facts:
    """What the renderer learns from git and local files; injected so tests can fix it."""

    head: str = ""  # short sha
    head_date: str = ""  # ISO commit date
    file_dates: dict[str, str] = field(default_factory=dict)  # repo-relative path -> ISO
    spend: Spend | None = None
    replays: dict[str, dict] = field(default_factory=dict)  # "ui" / "ui-student" -> sidecar


def git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def read_spend(ledger: Path) -> Spend | None:
    """Sum of cost_usd in the Anthropic spend ledger, or None when it is not readable."""
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    total, calls, last = 0.0, 0, ""
    for line in lines:
        try:
            row = json.loads(line)
            total += float(row.get("cost_usd") or 0)
        except (ValueError, TypeError, AttributeError):
            continue
        calls += 1
        last = max(last, str(row.get("at") or ""))
    return Spend(total, calls, last) if calls else None


def open_questions(questions_md: str) -> int | None:
    if not questions_md:
        return None
    return len(re.findall(r"^\d+\.\s", section(questions_md, "Open"), re.M))


def tests_recorded(*texts: tuple[str, str]) -> tuple[str, str]:
    """The last 'N tests green' (or 'N passed') in the first text that has one: (count, where)."""
    for label, text in texts:
        found = re.findall(r"(\d[\d,]*)\s+(?:tests\s+(?:green|passed)|passed\b)", text)
        if found:
            return found[-1].replace(",", ""), label
    return "", ""


# ---------- HTML pieces ----------


def slug(status: str) -> str:
    return "s-" + status.replace(" ", "-")


def badge(status: str) -> str:
    s = status.lower().strip()
    if s not in STATUSES:
        return inline(status)
    return f'<span class="badge {slug(s)}">{esc(s)}</span>'


def cell(content: str, raw: str) -> str:
    if len(raw) > LONG_CELL:
        return (f'<div class="c clamp">{content}</div>'
                '<button type="button" class="more" aria-expanded="false" hidden>more</button>')
    return f'<div class="c">{content}</div>'


ID_COLS = ("session", "task", "round", "#")


def render_table(t: Table, row_class: dict[int, str] | None = None,
                 link_ids: set[str] | None = None, cls: str = "",
                 row_attrs: dict[int, str] | None = None, table_attrs: str = "") -> str:
    status_i, commit_i = t.col("status"), t.col("commit")
    date_cols = {i for i, h in enumerate(t.head) if h.lower() in ("started", "finished", "date", "updated")}
    head = "".join(f'<th scope="col">{inline(h)}</th>' for h in t.head)
    labels = [esc(re.sub(r"\s*\(.*\)$", "", h)) for h in t.head]
    rows = []
    for n, r in enumerate(t.rows):
        cells = []
        for k, c in enumerate(r):
            attrs = f' data-label="{labels[k]}"'
            if not c.strip():
                cells.append(f'<td class="blank"{attrs}></td>')
            elif k == status_i:
                cells.append(f'<td class="st"{attrs}><div class="c">{badge(c)}</div></td>')
            elif k == commit_i:
                cells.append(f'<td class="mono"{attrs}><div class="c">{inline(c)}</div></td>')
            elif k == 0 and t.kind in ID_COLS:
                body = (f'<a href="#{esc(c.lower())}">{esc(c)}</a>' if link_ids and c.lower() in link_ids
                        else inline(c))
                if re.fullmatch(r"\d+", c.strip()):  # a bare number names its card on a phone
                    body = f'<span class="cardlabel">{labels[k]} </span>{body}'
                cells.append(f'<td class="id"{attrs}><div class="c">{body}</div></td>')
            elif k in date_cols:
                cells.append(f'<td class="date"{attrs}><div class="c">{inline(c)}</div></td>')
            else:
                cells.append(f"<td{attrs}>{cell(inline(c), c)}</td>")
        rc = (row_class or {}).get(n)
        extra = (row_attrs or {}).get(n, "")
        klass = f' class="{rc}"' if rc else ""
        rows.append(f"<tr{klass}{extra}>" + "".join(cells) + "</tr>")
    tclass = " ".join(x for x in ("rt", cls) if x)
    return (
        f'<div class="panel scroll"><table class="{tclass}"{table_attrs}>\n<thead><tr>{head}</tr></thead>\n'
        "<tbody>\n" + "\n".join(rows) + "\n</tbody></table></div>"
    )


def statuses_of(t: Table) -> list[str]:
    k = t.col("status")
    if k is None:
        return []
    return [r[k].lower().strip() for r in t.rows if r[k].lower().strip() in STATUSES]


def bar(statuses: list[str], label: str) -> str:
    total = len(statuses)
    counts = [(s, statuses.count(s)) for s in STATUSES if statuses.count(s)]
    spans = "".join(
        f'<span class="{slug(s)}" style="width:{100 * n / total:.2f}%" title="{s}: {n}"></span>'
        for s, n in counts)
    return f'<div class="bar" role="img" aria-label="{esc(label)}">{spans}</div>'


def render_summary(statuses: list[str], noun: str, extra: str = "") -> str:
    """Counts per status and a stacked bar, in a fixed order."""
    total = len(statuses)
    if not total:
        return ""
    counts = [(s, statuses.count(s)) for s in STATUSES if statuses.count(s)]
    done = statuses.count("done")
    label = f"{done} of {total} {noun} done"
    items = "".join(f'<span class="{slug(s)}"><b>{n}</b>{s}</span>' for s, n in counts)
    return (
        f'<section class="panel summary" aria-label="{esc(label)}"><div class="counts">'
        f'<span class="lead-count"><b>{done}/{total}</b>{noun} done</span>{items}{extra}</div>'
        f"{bar(statuses, label)}</section>"
    )


def round_totals(t: Table) -> str:
    """Found and fixed totals across a round table ('5 / 15 / 7' and '28 of 28')."""
    fi, xi = t.col("must"), t.col("fixed")
    sums = [0, 0, 0]
    seen = False
    for r in t.rows:
        if fi is not None:
            nums = re.findall(r"\d+", re.sub(r"\(.*?\)", "", r[fi]))[:3]
            if len(nums) == 3:
                seen = True
                sums = [a + int(b) for a, b in zip(sums, nums, strict=True)]
    fixed = [0, 0]
    for r in t.rows:
        if xi is not None and (m := re.match(r"\s*(\d+)\s+of\s+(\d+)", r[xi])):
            fixed = [fixed[0] + int(m.group(1)), fixed[1] + int(m.group(2))]
    out = ""
    if seen:
        out += (f"<span><b>{sums[0]}</b>must</span><span><b>{sums[1]}</b>should</span>"
                f"<span><b>{sums[2]}</b>could found</span>")
    if fixed[1]:
        out += f"<span><b>{fixed[0]} of {fixed[1]}</b>fixed</span>"
    return out


def table_noun(t: Table) -> str:
    return {"session": "sessions", "round": "rounds"}.get(t.kind, "tasks")


def wide_prose(t: Table) -> bool:
    cells = [c for r in t.rows for c in r]
    return len(t.head) >= 7 and bool(cells) and sum(map(len, cells)) / len(cells) > 40


def render_list(kind: str, items: list[Item], start: int = 1, cls: str = "") -> str:
    tag = "ol" if kind == "ol" else "ul"
    attrs = (f' class="{cls}"' if cls else "") + (f' start="{start}"' if tag == "ol" and start != 1 else "")
    body = "".join(
        f"<li>{inline(it.text)}" + (render_list('ul', it.children) if it.children else "") + "</li>"
        for it in items)
    return f"<{tag}{attrs}>{body}</{tag}>"


def render_blocks(blocks: list[tuple], heading_shift: int = 0, img_prefix: str = "") -> list[str]:
    out = []
    after_done_heading = False
    for b in blocks:
        if b[0] == "h":
            after_done_heading = b[2].lower().startswith("definition of done")
            level = min(6, max(2, b[1] + heading_shift))
            out.append(f"<h{level}>{inline(b[2])}</h{level}>")
        elif b[0] == "p":
            out.append(f"<p>{inline(b[1])}</p>")
        elif b[0] in ("ul", "ol"):
            cls = "panel done-list" if after_done_heading and b[0] == "ul" else ""
            out.append(render_list(b[0], b[1], b[2], cls))
        elif b[0] == "code":
            out.append(f'<pre class="code">{esc(b[1])}</pre>')
        elif b[0] == "quote":
            out.append(f"<blockquote>{inline(b[1])}</blockquote>")
        elif b[0] == "fig":
            src = esc(img_prefix + b[2])
            out.append(f'<figure class="panel shot"><img src="{src}" alt="{esc(b[1])}" loading="lazy">'
                       f"<figcaption>{inline(b[1])}</figcaption></figure>")
        elif b[0] == "table":
            t = b[1]
            extra = round_totals(t) if t.kind == "round" else ""
            out.append(render_summary(statuses_of(t), table_noun(t), extra))
            out.append(render_table(t, cls="cards" if wide_prose(t) else ""))
    return [x for x in out if x]


# ---------- Model of the tracker ----------


@dataclass
class Session:
    sid: str  # "S1"
    name: str  # "Schemas, store, OpenAlex"
    status: str = "todo"
    started: str = ""
    finished: str = ""
    commit: str = ""
    notes: str = ""
    doc: Doc | None = None
    text: str = ""  # the task file as written

    @property
    def work(self) -> Table | None:
        """The session's task or round table."""
        if not self.doc:
            return None
        return next((t for t in self.doc.tables() if t.kind in ("task", "round")), None)


def session_title(doc: Doc, sid: str) -> str:
    return re.sub(rf"^{sid}\s*[—–-]\s*", "", doc.title) or sid


def master_table(master: Doc) -> Table | None:
    return next((t for t in master.tables() if t.kind == "session"), None)


def build_sessions(master: Doc, files: dict[str, str]) -> list[Session]:
    table = master_table(master)
    sessions: list[Session] = []
    if table:
        idx = {name: table.col(name) for name in ("goal", "status", "started", "finished", "commit", "notes")}

        def get(r: list[str], name: str) -> str:
            k = idx[name]
            return r[k] if k is not None else ""

        for r in table.rows:
            sessions.append(Session(r[0], get(r, "goal"), get(r, "status").lower().strip() or "todo",
                                    get(r, "started"), get(r, "finished"), get(r, "commit"), get(r, "notes")))
    known = {s.sid for s in sessions}
    sessions += [Session(sid, sid) for sid in files if sid not in known]
    for s in sessions:
        if s.sid in files:
            s.text = files[s.sid]
            s.doc = parse(s.text)
            if s.doc.title:
                s.name = session_title(s.doc, s.sid)
    return sessions


def pick_current(sessions: list[Session]) -> Session | None:
    for wanted in (("in progress", "continued"), ("todo",)):
        for s in sessions:
            if s.status in wanted:
                return s
    return None


def newest_start(sessions: list[Session]) -> tuple[datetime | None, str]:
    best: tuple[datetime | None, str] = (None, "")
    for s in sessions:
        d = parse_stamp(s.started)
        if d and (best[0] is None or d > best[0]):
            best = (d, s.sid)
    return best


def tracker_year(sessions: list[Session]) -> int:
    d, _ = newest_start(sessions)
    return d.year if d else 2026


# ---------- Milestones ----------


@dataclass
class Milestone:
    name: str
    date: str
    needs: str
    detail: str = ""  # PLAN.md's "What must exist", when it says more than the name
    ready: str = "n/a"


def session_refs(text: str) -> list[str]:
    """'S0–S7', 'S32 stabilized, S33 tags' -> ['S0', ..., 'S7'] / ['S32', 'S33']."""
    refs: list[str] = []
    for m in re.finditer(r"S(\d+)(?:\s*(?:[–—-]|to)\s*S?(\d+))?", text):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        refs += [f"S{n}" for n in range(a, b + 1) if f"S{n}" not in refs]
    return refs


def readiness(needs: str, sessions: list[Session]) -> str:
    """'yes' when every listed session is done, 'no: S<n> not done', 'n/a' when none is listed."""
    if needs.strip().lower().startswith("nothing"):
        return "n/a"
    refs = session_refs(needs)
    if not refs:
        return "n/a"
    status = {s.sid: s.status for s in sessions}
    missing = [r for r in refs if status.get(r) != "done"]
    if not missing:
        return "yes"
    return "no: " + ", ".join(missing) + " not done"


def day_key(text: str) -> str:
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})", text)
    return f"{int(m.group(1))} {m.group(2).lower()}" if m else text.strip().lower()


def detail_of(what: str, name: str) -> str:
    """PLAN.md's text without the milestone name it repeats ('Checkup 2: prototype ...')."""
    rest = what[len(name):] if what.lower().startswith(name.lower()) else what
    return rest.strip(" :;,").removeprefix("(").removesuffix(")").strip()


def build_milestones(master: Doc, plan_md: str, sessions: list[Session]) -> list[Milestone]:
    """TRACKER.md's milestone rows, plus any row of PLAN.md's fixed-milestones table it lacks.
    A TRACKER row keeps its own Needs; PLAN's text is shown beside it when it says more."""
    tracker = next((t for t in master.tables() if t.kind == "milestone"), None)
    plan_doc = parse(section(plan_md, "Fixed milestones")) if plan_md else Doc()
    plan = next(iter(plan_doc.tables()), None)
    out: list[Milestone] = []
    by_day: dict[str, Milestone] = {}
    if tracker:
        di, ni = tracker.col("date"), tracker.col("needs")
        for r in tracker.rows:
            m = Milestone(r[0], r[di] if di is not None else "", r[ni] if ni is not None else "")
            out.append(m)
            by_day[day_key(m.date)] = m
    if plan:
        di, wi, si = plan.col("date"), plan.col("what"), plan.col("sessions")
        for r in plan.rows:
            date = r[di] if di is not None else ""
            what = r[wi] if wi is not None else ""
            needs = r[si] if si is not None else ""
            m = by_day.get(day_key(date))
            if not m:
                m = Milestone(re.sub(r"\s*\(.*\)$", "", what) or date, date, needs)
                out.append(m)
                by_day[day_key(date)] = m
            m.detail = detail_of(what, m.name)
    year = tracker_year(sessions)

    def order(m: Milestone) -> datetime:
        return deadline(m.date, year) or datetime.max.replace(tzinfo=UTC)

    out.sort(key=order)
    for m in out:
        m.ready = readiness(m.needs, sessions)
    return out


def key_deadlines(milestones: list[Milestone], year: int) -> tuple[datetime | None, datetime | None]:
    """(freeze, demo) from the milestone rows: the freeze row; the demo time on the submission
    row ('3:00 pm demo'), else the submission deadline."""
    freeze = demo = None
    for m in milestones:
        text = f"{m.name} {m.detail}".lower()
        if "freeze" in text and not freeze:
            freeze = deadline(m.date, year)
        if "demo" in text or "submission" in text:
            base = deadline(m.date, year)
            t = re.search(r"(\d{1,2}:\d{2}\s*[ap]\.?m\.?)\s*demo", text)
            if base and t:  # the demo time replaces the row's own time
                day = re.sub(r"\d{1,2}:\d{2}.*$", "", m.date).strip()
                demo = deadline(f"{day} {t.group(1)}", year) or base
            elif base and not demo:
                demo = base
    return freeze, demo


def ready_cell(value: str) -> str:
    cls = "yes" if value == "yes" else "na" if value == "n/a" else "no"
    return f'<span class="ready {cls}">{esc(value)}</span>'


def countdown(d: datetime | None, missing: str = "—") -> str:
    """A deadline the browser turns into time left; without script it shows the date."""
    if not d:
        return esc(missing)
    return f'<span data-deadline="{d.isoformat()}">{d.day} {d.strftime("%b")}</span>'


def fmt_deadline(d: datetime) -> str:
    zone = {-4: "EDT", -5: "EST"}.get(int(d.utcoffset().total_seconds() // 3600), "")
    t = "" if (d.hour, d.minute) == (23, 59) else d.strftime(" %H:%M") + (f" {zone}" if zone else "")
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b %Y')}{t}"


def render_milestones(ms: list[Milestone], year: int) -> str:
    if not ms:
        return ""
    rows = []
    for m in ms:
        d = deadline(m.date, year)
        detail = f'<div class="meta">{inline(m.detail)}</div>' if m.detail else ""
        rows.append(
            f'<tr><td data-label="Milestone"><div class="c"><strong>{inline(m.name)}</strong>{detail}</div></td>'
            f'<td class="date" data-label="Date"><div class="c">{esc(m.date)}</div></td>'
            f'<td data-label="Needs"><div class="c">{inline(m.needs) or "—"}</div></td>'
            f'<td data-label="Ready?"><div class="c">{ready_cell(m.ready)}</div></td>'
            f'<td class="mono" data-label="Left"><div class="c">{countdown(d, "—")}</div></td></tr>')
    return ('<div class="panel scroll"><table class="rt ms"><thead><tr><th scope="col">Milestone</th>'
            '<th scope="col">Date</th><th scope="col">Needs</th><th scope="col">Ready?</th>'
            '<th scope="col">Left</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")


# ---------- Sources, stale notes ----------


@dataclass
class Source:
    path: str  # repo-relative, shown on the page
    text: str
    date: str = ""  # ISO, last commit that touched it


def source_note(sources: list[Source], newest: tuple[datetime | None, str], stale_check: bool = True,
                verb: str = "Built from") -> str:
    parts = []
    stale = False
    for s in sources:
        when = f", last changed {short_date(s.date, True)}" if s.date else ", not in git yet"
        parts.append(f"<code>{esc(s.path)}</code>{when}")
        d = parse_stamp(s.date) if s.date else None
        if stale_check and d and newest[0] and d < newest[0]:
            stale = True
    note = ""
    if stale:
        note = (f' <span class="stale">May be behind: older than the start of {esc(newest[1])} '
                f"({short_date(newest[0].isoformat(), True)})</span>")
    return f'<p class="src">{verb} ' + "; ".join(parts) + f".{note}</p>"


# ---------- Views ----------


def session_body(s: Session) -> list[str]:
    if not s.doc:
        return ['<div class="panel empty">No task file yet. Perch-dev writes '
                f"<code>docs/sessions/{esc(s.sid)}.md</code> when the session starts.</div>"]
    return render_blocks(s.doc.blocks)


def work_counts(s: Session) -> tuple[int, int, str]:
    """(done, total, noun) for the session's task or round table."""
    t = s.work
    if not t:
        return 0, 0, "tasks"
    st = statuses_of(t)
    return st.count("done"), len(st), table_noun(t)


def tile(key: str, value: str, sub: str = "", none: bool = False) -> str:
    return (f'<div class="tile"><span class="k">{key}</span>'
            f'<span class="v{" none" if none else ""}">{value}</span>'
            + (f'<span class="s">{sub}</span>' if sub else "") + "</div>")


def key_number(master: Doc, prefix: str) -> tuple[str, str]:
    """(value, updated) of the key-numbers row whose Metric starts with prefix."""
    t = next((t for t in master.tables() if t.kind == "metric"), None)
    if not t:
        return "", ""
    ui, vi = t.col("updated"), t.col("value")
    for r in t.rows:
        if r[0].lower().startswith(prefix.lower()):
            return (r[vi] if vi is not None else ""), (r[ui] if ui is not None else "")
    return "", ""


def glance(master: Doc, sessions: list[Session], current: Session | None, milestones: list[Milestone],
           facts: Facts, questions: int | None) -> str:
    year = tracker_year(sessions)
    freeze, demo = key_deadlines(milestones, year)
    done = sum(s.status == "done" for s in sessions)
    tiles = [
        tile("Code freeze", countdown(freeze, "not set"), fmt_deadline(freeze) if freeze else "", not freeze),
        tile("Demo", countdown(demo, "not set"), fmt_deadline(demo) if demo else "", not demo),
        tile("Sessions", f"{done} of {len(sessions)}", "done"),
    ]
    if current:
        d, n, noun = work_counts(current)
        tiles.append(tile(f"{esc(current.sid)} {noun}", f"{d} of {n}" if n else "—",
                          "done" if n else "no task table yet", none=not n))
        count, where = tests_recorded(
            (f"{current.sid} task file", current.text),
            (f"tracker, {current.sid} row", current.notes),
            *((f"tracker, {s.sid} row", s.notes) for s in reversed(sessions)
              if s.status in FINISHED and s is not current))
        tiles.append(tile("Tests", esc(count), f"recorded in the {esc(where)}") if count else
                     tile("Tests", "not recorded", "", none=True))
    tiles.append(tile("Last commit", esc(facts.head), short_date(facts.head_date, True)) if facts.head
                 else tile("Last commit", "not recorded", "", none=True))
    value, updated = key_number(master, "Anthropic")
    cap = re.search(r"of\s+(\$[\d,.]+)", value)
    if facts.spend:
        tiles.append(tile("Anthropic spend", f"${facts.spend.total:.2f}" + (f" of {esc(cap.group(1))}" if cap else ""),
                          f"{facts.spend.calls} calls in the ledger"
                          + (f", last {short_date(facts.spend.last)}" if facts.spend.last else "")))
    elif m := re.match(r"\s*(\$[\d,.]+(?:\s+of\s+\$[\d,.]+)?)", value):
        tiles.append(tile("Anthropic spend", esc(m.group(1)),
                          f"key numbers, updated {esc(updated)}" if updated else "key numbers"))
    else:
        tiles.append(tile("Anthropic spend", "not recorded", "", none=True))
    if questions is not None:
        tiles.append(tile("Open questions", str(questions), "in bridge/QUESTIONS.md"))
    return '<section class="glance" aria-label="At a glance">' + "".join(tiles) + "</section>"


def up_next(sessions: list[Session], current: Session | None) -> str:
    after = False
    items = []
    for s in sessions:
        if s is current:
            after = True
            continue
        if after and s.status == "todo":
            notes = f'<span class="meta">{inline(s.notes)}</span>' if s.notes else ""
            items.append(f'<div class="next-item"><span><b>{esc(s.sid)}</b>{inline(s.name)}</span>{notes}</div>')
    if not items:
        return ""
    return '<h2>Up next</h2><section class="panel next">' + "".join(items[:3]) + "</section>"


def view_current(s: Session | None, at_a_glance: str, nxt: str, ms_html: str) -> str:
    if not s:
        return at_a_glance + '<div class="panel empty">Every session is finished or cut.</div>'
    when = f"Started {esc(s.started)}" if s.started else "Not started"
    file_note = f'<p class="src">From <code>docs/sessions/{esc(s.sid)}.md</code>.</p>' if s.doc else ""
    return "\n".join([
        f'<div id="{s.sid.lower()}"><div class="eyebrow">Current session</div>',
        f'<div class="title-row"><h1>{esc(s.sid)} · {inline(s.name)}</h1>{badge(s.status)}</div>',
        f'<div class="meta">{when}</div></div>',
        at_a_glance,
        *session_body(s),
        nxt,
        "<h2>Milestones</h2>" + ms_html if ms_html else "",
        file_note,
    ])


def view_master(master: Doc, sessions: list[Session], current: Session | None, ms_html: str,
                note: str) -> str:
    intro = [b for b in master.blocks[:1] if b[0] == "p"]
    rest = master.blocks[len(intro):]
    linkable = {s.sid.lower() for s in sessions if s.doc and (s.status in FINISHED or s is current)}
    head = ['<div><div class="eyebrow">All sessions</div><h1>Master tracker</h1></div>',
            '<p class="sub"><a href="#master-milestones">Milestones</a><a href="#master-numbers">'
            'Key numbers</a><a href="#master-sessions">Sessions</a></p>']
    sess, numbers, other = [], [], []
    for b in rest:
        if b[0] == "table" and b[1].kind == "session":
            t = b[1]
            k = t.col("status")
            classes = {}
            for n, r in enumerate(t.rows):
                if current and r[0] == current.sid:
                    classes[n] = "is-current"
                elif k is not None and r[k].lower() in FINISHED:
                    classes[n] = "is-finished"
            sess.append(render_summary(statuses_of(t), "sessions"))
            sess.append(render_table(t, row_class=classes, link_ids=linkable))
        elif b[0] == "table" and b[1].kind == "milestone":
            continue  # rendered from the readiness rule below
        elif b[0] == "table" and b[1].kind == "metric":
            numbers.append(render_table(b[1], cls="kv"))
        elif b[0] == "h" and re.match(r"(?i)milestone|key numbers", b[2]):
            continue
        else:
            other += render_blocks([b])
    out = head
    out.append('<h2 id="master-milestones">Milestones</h2>' + ms_html)
    out.append('<h2 id="master-numbers">Key numbers</h2>' + "".join(numbers))
    out.append('<h2 id="master-sessions">Sessions</h2>' + "".join(sess))
    out += other
    out += [f'<p class="meta">{inline(b[1])}</p>' for b in intro]
    out.append(note)
    return "\n".join(out)


def view_archive(sessions: list[Session]) -> str:
    done = [s for s in sessions if s.status in FINISHED]
    done.sort(key=lambda s: int(re.sub(r"\D", "", s.sid) or 0), reverse=True)
    out = ['<div><div class="eyebrow">Finished sessions</div><h1>Archive</h1></div>']
    if not done:
        out.append('<div class="panel empty">Sessions move here when they are done or cut.</div>')
    items = []
    for s in done:
        t = s.work
        st = statuses_of(t) if t else []
        bits = []
        if st:
            noun = table_noun(t)
            parts = [f"{st.count(x)} {x}" for x in STATUSES if st.count(x)]
            bits.append(f"{len(st)} {noun}: " + ", ".join(parts))
        if s.finished:
            bits.append(f"finished {esc(s.finished)}")
        if s.commit and "git log" not in s.commit:
            bits.append(f"commit {inline(s.commit)}")
        items.append(
            f'<details id="{s.sid.lower()}"><summary><span class="sline"><span class="sid">'
            f'{esc(s.sid)}</span><span class="stitle">{inline(s.name)}</span></span>'
            f'{badge(s.status)}<span class="smeta">{" · ".join(bits)}</span>'
            '</summary><div class="inner">' + "\n".join(session_body(s)) + "</div></details>"
        )
    if items:
        out.append("<div>" + "\n".join(items) + "</div>")
    return "\n".join(out)


def change_log(plan_md: str) -> Table | None:
    """The table under PLAN.md's '## Change log' heading."""
    doc = parse(section(plan_md, "Change log"))
    return next(iter(doc.tables()), None)


def newest_first(t: Table) -> Table:
    return Table(t.head, list(reversed(t.rows)))


def session_tokens(t: Table) -> dict[int, str]:
    k = t.col("session")
    out = {}
    for n, r in enumerate(t.rows):
        refs = session_refs(r[k]) if k is not None else []
        out[n] = f' data-s="{" ".join(x.lower() for x in refs) or "none"}"'
    return out


def view_decisions(decisions_md: str, plan_md: str, note: str) -> str:
    out = ['<div><div class="eyebrow">Why things are the way they are</div>'
           "<h1>Decisions and plan changes</h1></div>"]
    dec = next(iter(parse(decisions_md).tables()), None) if decisions_md else None
    log = change_log(plan_md) if plan_md else None
    dec = newest_first(dec) if dec else None
    log = newest_first(log) if log else None
    seen: list[str] = []
    for t in (dec, log):
        if t:
            for refs in session_tokens(t).values():
                for x in refs.split('"')[1].split():
                    if x != "none" and x not in seen:
                        seen.append(x)
    seen.sort(key=lambda x: int(x[1:]), reverse=True)
    chips = "".join(f'<button type="button" class="chip" data-s="{x}" aria-pressed="false">{x.upper()}</button>'
                    for x in seen[:8])
    options = "".join(f'<option value="{x}">{x.upper()}</option>' for x in seen)
    out.append(
        '<section class="panel filters" role="search" aria-label="Filter decisions and plan changes">'
        '<div class="row"><label for="dq">Filter</label>'
        '<input id="dq" type="search" placeholder="Words in any column" autocomplete="off"></div>'
        '<div class="row" role="group" aria-label="Session">'
        '<button type="button" class="chip all" data-s="" aria-pressed="true">All</button>'
        f'{chips}<label class="meta" for="ds">Session</label><select id="ds">'
        f'<option value="">All sessions</option>{options}</select></div>'
        '<div class="row"><p class="meta" aria-live="polite">Newest first. Showing <b id="dcount">'
        f'{len(dec.rows) if dec else 0}</b> decisions and <b id="lcount">{len(log.rows) if log else 0}'
        f'</b> plan changes.</p><button type="button" class="btn" id="dall" data-cap="{DECISIONS_CAP}" hidden>'
        "Show all rows</button></div></section>")
    out.append(f"<h2>Decisions ({len(dec.rows) if dec else 0})</h2>")
    out.append(render_table(dec, row_attrs=session_tokens(dec), table_attrs=' data-filter="dcount"')
               + '<div class="panel empty" id="dcount-none" hidden>No decision matches.</div>' if dec else
               '<div class="panel empty">No decisions logged yet in docs/DECISIONS.md.</div>')
    out.append(f"<h2>Plan change log ({len(log.rows) if log else 0})</h2>")
    out.append(render_table(log, row_attrs=session_tokens(log), table_attrs=' data-filter="lcount"')
               + '<div class="panel empty" id="lcount-none" hidden>No plan change matches.</div>' if log else
               '<div class="panel empty">No plan changes logged yet in docs/PLAN.md.</div>')
    out.append(note)
    return "\n".join(out)


def fold_sections(doc: Doc, open_first: int = 1) -> list[str]:
    """Each '## ' section of a document as a fold; the first open_first open."""
    out: list[str] = []
    lead: list[tuple] = []
    sections: list[tuple[str, list[tuple]]] = []
    for b in doc.blocks:
        if b[0] == "h" and b[1] == 2:
            sections.append((b[2], []))
        elif sections:
            sections[-1][1].append(b)
        else:
            lead.append(b)
    out += render_blocks(lead)
    for n, (title, blocks) in enumerate(sections):
        opened = " open" if n < open_first else ""
        out.append(f'<details{opened}><summary><span class="sline"><span class="stitle">{inline(title)}'
                   '</span></span></summary><div class="inner prose">'
                   + "\n".join(render_blocks(blocks, heading_shift=0)) + "</div></details>")
    return out


def view_bench(src: Source, newest: tuple[datetime | None, str]) -> str:
    doc = parse(src.text)
    out = ['<div><div class="eyebrow">Measured results, with the keyword-only baseline</div>'
           f"<h1>{inline(doc.title or 'Bench results')}</h1></div>", source_note([src], newest)]
    return "\n".join(out + fold_sections(doc))


def view_ux(sources: list[Source], newest: tuple[datetime | None, str]) -> str:
    """The UX reviews and QA cycles, newest first; the newest open."""
    out = ['<div><div class="eyebrow">Reviews and QA cycles, newest first</div><h1>UX</h1></div>',
           source_note(sources[:1], newest, verb="Newest:")]
    for n, s in enumerate(sources):
        doc = parse(s.text)
        prefix = str(Path(s.path).parent.relative_to("docs")) + "/" if s.path.startswith("docs/") else ""
        when = short_date(s.date) if s.date else "not in git yet"
        out.append(f'<details{" open" if n == 0 else ""}><summary><span class="sline"><span class="stitle">'
                   f"{inline(doc.title or s.path)}</span></span>"
                   f'<span class="smeta"><code>{esc(s.path)}</code>, {when}</span></summary>'
                   '<div class="inner prose">' + "\n".join(render_blocks(doc.blocks, 1, prefix))
                   + "</div></details>")
    return "\n".join(out)


def view_architecture(src: Source, root: Path, newest: tuple[datetime | None, str]) -> str:
    """docs/ARCHITECTURE.md; each ![caption](file.svg) is inlined from root as a figure."""
    doc = parse(src.text)
    out = ['<div><div class="eyebrow">How Perch is built</div>'
           f"<h1>{inline(doc.title or 'Architecture')}</h1></div>", source_note([src], newest)]
    for b in doc.blocks:
        if b[0] == "fig" and b[2].endswith(".svg"):
            f = root / b[2]
            svg = f.read_text(encoding="utf-8").strip() if f.is_file() else ""
            out.append(f'<figure class="panel diagram">{svg}'
                       f"<figcaption>{inline(b[1])}</figcaption></figure>")
        else:
            out += render_blocks([b])
    return "\n".join(out)


def view_persona(files: dict[str, str], note: str) -> str:
    """The synthetic private-mode test persona: README rendered, each document shown as is."""
    readme = parse(files.get("README.md", ""))
    out = ['<div><div class="eyebrow">Synthetic test input for private mode, for team review'
           f"</div><h1>{inline(readme.title or 'Persona 1')}</h1></div>", note]
    out += ['<div class="prose">' + "\n".join(render_blocks(readme.blocks)) + "</div>"]
    for name, text in files.items():
        if name != "README.md":
            out.append(f"<h2><code>{esc(name)}</code></h2>"
                       f'<pre class="panel doc">{esc(text)}</pre>')
    return "\n".join(out)


def view_readme(src: str, note: str) -> str:
    s = esc(src)
    return f"""<div><div class="eyebrow">For review before the repository is public</div><h1>README</h1></div>
{note}
<p class="lead">The repository's README.md as GitHub will show it, with its clips and the architecture figure.</p>
<div class="ui-tools"><a href="{s}" target="_blank" rel="noopener">Open on its own</a></div>
<iframe id="readme-frame" class="readme-frame" src="{s}" title="README preview"></iframe>"""


def replay_line(meta: dict | None, who: str) -> str:
    if not meta:
        return ""
    when = short_date(meta.get("created_at", "")) if meta.get("created_at") else "an unknown date"
    name = f" (<code>{esc(meta['replay'])}</code>)" if meta.get("replay") else ""
    return f"The {who} replay is a brief saved on {esc(when)}{name}."


def view_ui(src: str, student: str | None, replays: dict[str, dict],
            newest: tuple[datetime | None, str]) -> str:
    s = esc(src)
    st = (f'<button type="button" class="btn" id="ui-student" data-src="{esc(student)}">'
          f'Student (sample)</button>\n'
          f'<button type="button" class="btn" id="ui-researcher" data-src="{s}">Researcher</button>\n'
          if student else "")
    lines = " ".join(x for x in (replay_line(replays.get("ui"), "researcher"),
                                 replay_line(replays.get("ui-student"), "SYNTHETIC student")) if x)
    stale = ""
    dates = [parse_stamp(m.get("created_at", "")) for m in replays.values()]
    dates = [d for d in dates if d]
    if dates and newest[0] and min(dates) < newest[0]:
        stale = (f' <span class="stale">May be behind: a replay is older than the start of {esc(newest[1])}; '
                 "the app shell is built from <code>web/</code> each time</span>")
    built = f'<p class="src">{lines}{stale}</p>' if lines else ""
    return f"""<div><div class="eyebrow">The web app in replay mode</div><h1>UI preview</h1></div>
{built}
<p class="lead">The current app from <code>web/</code>, playing a saved brief with the researcher shown by alias.
Press <b>Find</b>, then <b>This is the one</b> and <b>Build brief</b>, to watch Scout build it.
{"<b>Student (sample)</b> opens a finished brief for an invented SYNTHETIC student. " if student else ""}Nothing is
fetched; keep and dismiss work but are not saved.</p>
<div class="ui-tools" role="group" aria-label="Preview size">
<button type="button" class="btn" data-size="wide" aria-pressed="true">Laptop</button>
<button type="button" class="btn" data-size="phone" aria-pressed="false">Phone</button>
<button type="button" class="btn" id="ui-restart">Restart</button>
{st}<a href="{s}" target="_blank" rel="noopener">Open on its own</a>
</div>
<div class="ui-stage"><iframe id="ui-frame" class="ui-frame wide" src="{s}"
title="Perch web app preview"></iframe></div>"""


def render_page(master_md: str, session_files: dict[str, str], artifact: bool = False,
                page_title: str = "Perch Build Tracker", decisions_md: str = "",
                plan_md: str = "", ui: str | None = None, bench: Source | None = None,
                arch: Source | None = None, arch_root: Path = Path("docs"),
                persona: dict[str, str] | None = None, readme: str | None = None,
                ux: list[Source] | None = None, ui_student: str | None = None,
                questions_md: str = "", facts: Facts | None = None) -> str:
    facts = facts or Facts()
    master = parse(master_md)
    sessions = build_sessions(master, session_files)
    current = pick_current(sessions)
    newest = newest_start(sessions)
    year = tracker_year(sessions)
    milestones = build_milestones(master, plan_md, sessions)
    ms_html = render_milestones(milestones, year)
    archived = sum(s.status in FINISHED for s in sessions)
    done = sum(s.status == "done" for s in sessions)
    dates = facts.file_dates

    def note(*paths: str, check: bool = True) -> str:
        return source_note([Source(p, "", dates.get(p, "")) for p in paths], newest, check)

    at_a_glance = glance(master, sessions, current, milestones, facts, open_questions(questions_md))
    name = esc(page_title)
    # Tab order (S31 tracker rebuild): what is happening now first, then the record, then content.
    tabs = [t for t in (
        ("current", "Current", lambda: view_current(current, at_a_glance, up_next(sessions, current), ms_html),
         True),
        ("master", "Master", lambda: view_master(master, sessions, current, ms_html,
                                                 note("docs/TRACKER.md", check=False)), True),
        ("decisions", "Decisions", lambda: view_decisions(
            decisions_md, plan_md, note("docs/DECISIONS.md", "docs/PLAN.md", check=False)), True),
        ("archive", f'Archive<span class="count">{archived}</span>', lambda: view_archive(sessions), True),
        ("ui", "UI", lambda: view_ui(ui, ui_student, facts.replays, newest), ui),
        ("ux", "UX", lambda: view_ux(ux, newest), ux),
        ("bench", "Bench", lambda: view_bench(bench, newest), bench),
        ("readme", "README", lambda: view_readme(readme, note("README.md")), readme),
        ("architecture", "Architecture", lambda: view_architecture(arch, arch_root, newest), arch),
        ("persona", "Persona", lambda: view_persona(
            persona, note("data/synthetic/persona-1/README.md", check=False)), persona),
    ) if t[3]]
    nav = "\n".join(f'<a id="tab-{k}" href="#{k}"{" aria-current=\"page\"" if i == 0 else ""}>'
                    f"{label}</a>" for i, (k, label, _, _) in enumerate(tabs))
    views = "\n".join(f'<section id="view-{k}" class="view" data-view="{k}"'
                      f'{"" if i == 0 else " hidden"}>\n{body()}\n</section>'
                      for i, (k, _, body, _) in enumerate(tabs))
    status = (f"{esc(current.sid)} {badge(current.status)} · " if current else "") + \
        f"{done} of {len(sessions)} sessions done"
    page = f"""<script>{THEME_SCRIPT}</script>
<header class="appbar"><div class="wrap">
<div class="brand"><b>Perch</b><span>Build tracker</span></div>
<span class="hdr-meta">{status}</span>
<button type="button" class="btn" id="theme" aria-label="Colour theme: system, light or dark">Theme: system</button>
<nav aria-label="Tracker views">
{nav}
</nav></div></header>
<main class="wrap">
{views}
<p class="foot">Generated by scripts/render_tracker.py from docs/TRACKER.md, docs/sessions/, docs/DECISIONS.md,
docs/PLAN.md, bridge/QUESTIONS.md, the bench results, the UX reviews, docs/ARCHITECTURE.md, the SYNTHETIC persona
and git. The Markdown is the source of truth.</p>
</main>
<script>{SCRIPT}</script>
"""
    if artifact:
        return (f"<title>{name}</title>\n"
                '<meta name="claude:viewport-fit-sides" content="cover">\n'
                f"{FONT_LINK}\n<style>{CSS}</style>\n{page}")
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{name}</title>\n<style>{CSS}</style>\n</head>\n<body>\n{page}"
            "</body>\n</html>\n")


def load_sessions(sessions_dir: Path) -> dict[str, str]:
    files = [f for f in sessions_dir.glob("S*.md") if re.fullmatch(r"S\d+", f.stem)]
    files.sort(key=lambda f: int(f.stem[1:]))
    return {f.stem: f.read_text(encoding="utf-8") for f in files}


def load_persona(folder: Path) -> dict[str, str]:
    """README first, then the documents in name order."""
    files = sorted(folder.glob("*.md"), key=lambda f: (f.name != "README.md", f.name))
    return {f.name: f.read_text(encoding="utf-8") for f in files}


def ux_paths(root: Path) -> list[str]:
    found = [*root.glob("docs/design/qa/CYCLE_*.md"), *root.glob("docs/design/UX_REVIEW_S*.md"),
             root / "docs/design/UX_AUDIT.md"]
    return [p.relative_to(root).as_posix() for p in found if p.is_file()]


def copy_images(page: str, dest_dir: Path, docs_dir: Path) -> None:
    """Copy the images a page references (relative 'design/...' paths, from docs/) beside it,
    so the artifact page also works opened from disk."""
    for ref in sorted(set(re.findall(r'<img src="(design/[^"]+)"', page))):
        src, out = docs_dir / ref, dest_dir / ref
        if src.is_file() and src.resolve() != out.resolve():
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Render the Perch build tracker.")
    ap.add_argument("src", nargs="?", default="docs/TRACKER.md")
    ap.add_argument("dest", nargs="?")
    ap.add_argument("--artifact", action="store_true", help="emit a claude.ai Artifact fragment")
    ap.add_argument("--title", default="Perch Build Tracker", help="page name")
    ap.add_argument("--ui", help="published path of the UI preview page; adds a UI tab")
    ap.add_argument("--ui-student", help="published path (with #/brief/...) of the student preview")
    ap.add_argument("--readme", help="published path of the README preview; adds a README tab")
    args = ap.parse_args(argv[1:])
    src = Path(args.src)
    dest = Path(args.dest) if args.dest else src.with_name("tracker.html")
    dest.parent.mkdir(parents=True, exist_ok=True)
    docs = src.parent
    root = docs.resolve().parent

    def read(rel: str) -> str:
        f = root / rel
        return f.read_text(encoding="utf-8") if f.is_file() else ""

    bench_rel = next((r for r in ("bench/results/RESULTS.md", "bench/results/SUMMARY.md")
                      if (root / r).is_file()), "")
    rels = ["docs/TRACKER.md", "docs/DECISIONS.md", "docs/PLAN.md", "docs/ARCHITECTURE.md", "README.md",
            "data/synthetic/persona-1/README.md", *([bench_rel] if bench_rel else []), *ux_paths(root)]
    facts = Facts(file_dates={r: git(root, "log", "-1", "--format=%cI", "--", r) for r in rels})
    head = git(root, "log", "-1", "--format=%h %cI").split()
    if len(head) == 2:
        facts.head, facts.head_date = head
    facts.spend = read_spend(root / "data/logs/anthropic_spend.jsonl")
    for key, path in (("ui", args.ui), ("ui-student", args.ui_student)):
        if path:
            side = dest.parent / Path(path.split("#")[0]).with_suffix(".json")
            try:
                facts.replays[key] = json.loads(side.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass

    def source(rel: str) -> Source | None:
        return Source(rel, read(rel), facts.file_dates.get(rel, "")) if rel and (root / rel).is_file() else None

    ux = [s for s in (source(r) for r in ux_paths(root)) if s]
    ux.sort(key=lambda s: (s.date, s.path), reverse=True)
    page = render_page(src.read_text(encoding="utf-8"), load_sessions(docs / "sessions"), args.artifact,
                       args.title, read("docs/DECISIONS.md"), read("docs/PLAN.md"), args.ui,
                       source(bench_rel), source("docs/ARCHITECTURE.md"), docs,
                       load_persona(root / "data/synthetic/persona-1"), args.readme, ux or None,
                       args.ui_student, read("bridge/QUESTIONS.md"), facts)
    dest.write_text(page, encoding="utf-8")
    if args.artifact:
        copy_images(page, dest.parent, docs)
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

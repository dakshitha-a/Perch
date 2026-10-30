"""Render the Perch build tracker as a small three-view web page.

Sources (Markdown is the source of truth):
  docs/TRACKER.md          master tracker: sessions, milestones, key numbers
  docs/sessions/S<n>.md    one task file per session

  docs/DECISIONS.md        decision log
  docs/PLAN.md             only its "## Change log" table
  bench/results/SUMMARY.md bench results, written by `make bench`
  docs/ARCHITECTURE.md     where the models sit; its ![caption](file.svg) figures are inlined

Views, switched by plain hash links (#current, #master, #archive, #decisions, #s<n>):
  Current    the session marked in progress or continued, else the first todo
  Master     every session, milestones and key numbers
  Archive    finished sessions (done or cut), collapsed, newest first
  Decisions  the decision log and the plan change log, newest first
  Bench      the bench results summary, when bench/results/SUMMARY.md exists
  UX         the S21 UI/UX audit, when docs/design/UX_AUDIT.md exists
  Architecture  docs/ARCHITECTURE.md with its diagrams, when it exists

Standard library only. Output is deterministic so re-running does not dirty the
tree. Two outputs: a complete standalone document with no external requests
(docs/tracker.html), and --artifact, a fragment for a claude.ai Artifact (the
host adds the document skeleton; the fragment adds a Google Fonts link).

Usage: python scripts/render_tracker.py [TRACKER.md] [DEST] [--artifact] [--title NAME]
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

STATUSES = ("done", "in progress", "continued", "todo", "cut")
FINISHED = ("done", "cut")

FONT_LINK = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=Public+Sans:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap\">"
)

DARK = """--bg: #111614; --surface: #171f1c; --raised: #1d2723; --fg: #e3ebe6; --muted: #98a79f;
    --line: #2b3732; --code: #24302b; --accent: #5cc4a6; --accent-soft: #1b3a32;
    --todo: #9aa6a0; --progress: #f0a640; --warn-soft: #3a2c17; --continued: #b394f5; --done: #5fd38f; --cut: #f2787a;
    color-scheme: dark;"""

CSS = (
    """
/* Layout: app bar with tabs; one view at a time in a single 1080px column. */
:root {
  --bg: #f5f7f5; --surface: #ffffff; --raised: #eef2ef; --fg: #18211d; --muted: #56635c;
  --line: #d9e0db; --code: #e8eee9; --accent: #1f6f5c; --accent-soft: #dcefe8;
  --todo: #67726c; --progress: #a15c07; --warn-soft: #f6ead8; --continued: #6d3fc0; --done: #1d7a43; --cut: #b42323;
  --sans: "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { DARK } }
:root[data-theme="dark"] { DARK }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.55 var(--sans); }
.wrap { max-width: 1080px; margin: 0 auto;
  padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.appbar { background: var(--surface); border-bottom: 1px solid var(--line); }
.appbar .wrap { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 20px;
  padding-block: 12px 0; }
.brand { display: flex; align-items: baseline; gap: 10px; margin-right: auto; padding-bottom: 10px; }
.brand b { font-size: 1.15rem; letter-spacing: -0.01em; }
.brand span { color: var(--muted); font-size: 13px; }
.at-a-glance { display: flex; gap: 10px; align-items: center; font-size: 13px; color: var(--muted);
  padding-bottom: 10px; }
.at-a-glance code { font-weight: 600; }
nav { flex-basis: 100%; display: flex; gap: 4px; overflow-x: auto; }
nav a { color: var(--muted); text-decoration: none; font-weight: 600; font-size: 14px;
  padding: 8px 12px 10px; border-bottom: 2px solid transparent; white-space: nowrap; }
nav a:hover { color: var(--fg); }
nav a[aria-current="page"] { color: var(--accent); border-bottom-color: var(--accent); }
nav a:focus-visible, summary:focus-visible, td a:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px; }
.count { font-family: var(--mono); font-size: 11px; background: var(--raised); color: var(--muted);
  border-radius: 999px; padding: 1px 7px; margin-left: 6px; }
main.wrap { padding-block: 24px 56px; }
.view { display: grid; gap: 16px; }
.view[hidden] { display: none; }
.view > * { min-width: 0; margin: 0; }
.eyebrow { font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
  font-weight: 600; }
.title-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; }
h1 { font-size: 1.6rem; line-height: 1.2; text-wrap: balance; letter-spacing: -0.01em; margin: 0; }
h2 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
  margin: 12px 0 0; }
p, li { color: var(--muted); max-width: 72ch; margin: 0; }
ul { padding-left: 1.2em; display: grid; gap: 4px; margin: 0; }
code { font-family: var(--mono); background: var(--code); padding: 1px 5px; border-radius: 3px;
  font-size: 0.86em; }
a { color: var(--accent); }
strong { color: var(--fg); }
.meta { font-size: 13px; color: var(--muted); }
figure.diagram { margin: 0; padding: 16px; display: grid; gap: 12px; justify-items: center;
  overflow-x: auto; }
@media (max-width: 600px) { figure.diagram { justify-items: start; } }
figure.diagram svg { width: 100%; min-width: 560px; max-width: 720px; height: auto; color: var(--fg); }
figure.shot { margin: 0; padding: 12px; display: grid; gap: 8px; justify-items: center; }
figure.shot img { max-width: 100%; max-height: 640px; height: auto; border-radius: 6px; }
figure.shot figcaption { font-size: 13px; color: var(--muted); justify-self: start; }
figure.diagram figcaption { font-size: 13px; color: var(--muted); justify-self: start;
  max-width: min(72ch, calc(100vw - 66px)); }
svg.arch .k-local { fill: var(--accent-soft); stroke: var(--accent); }
svg.arch .k-cloud { fill: var(--warn-soft); stroke: var(--progress); }
svg.arch .k-loop { stroke: var(--progress); }
svg.arch .k-private, svg.arch .k-private-x { stroke: var(--cut); }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 6px; }
.summary { display: grid; gap: 10px; padding: 14px 16px; }
.counts { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 14px; color: var(--muted); }
.counts b { font-family: var(--mono); font-variant-numeric: tabular-nums; font-size: 1.1rem;
  margin-right: 5px; color: var(--fg); }
.bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: var(--raised); }
.bar span { display: block; height: 100%; }
.scroll { overflow-x: auto; }
.readme-frame { width: 100%; height: 80vh; border: 1px solid var(--line); border-radius: 6px; background: #fff; }
pre.doc { white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--mono); font-size: 13px; line-height: 1.5; padding: 14px 16px; margin: 0 0 18px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { border-bottom: 1px solid var(--line); padding: 8px 12px; text-align: left;
  vertical-align: top; }
tr:last-child td { border-bottom: 0; }
th { background: var(--raised); font-weight: 600; font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--muted); white-space: nowrap; }
td:first-child { font-family: var(--mono); font-weight: 600; white-space: nowrap; }
td.mono { font-family: var(--mono); font-size: 13px; white-space: nowrap; }
tr.is-current td { background: var(--accent-soft); }
tr.is-finished td { color: var(--muted); }
.badge { display: inline-block; padding: 1px 9px; border-radius: 999px; font-size: 12px;
  font-weight: 600; white-space: nowrap; border: 1px solid currentColor; font-family: var(--sans); }
.s-todo { color: var(--todo); } .s-in-progress { color: var(--progress); }
.s-continued { color: var(--continued); } .s-done { color: var(--done); } .s-cut { color: var(--cut); }
.bar .s-todo { background: var(--todo); } .bar .s-in-progress { background: var(--progress); }
.bar .s-continued { background: var(--continued); } .bar .s-done { background: var(--done); }
.bar .s-cut { background: var(--cut); }
.done-list { list-style: none; padding: 14px 16px; }
.done-list li::before { content: "\\2610"; margin-right: 8px; color: var(--muted); }
.empty { padding: 20px 16px; color: var(--muted); }
details { background: var(--surface); border: 1px solid var(--line); border-radius: 6px; }
details + details { margin-top: 10px; }
summary { cursor: pointer; list-style: none; display: grid; align-items: center; gap: 4px 14px;
  grid-template-columns: auto 1fr auto; padding: 12px 16px; }
summary::-webkit-details-marker { display: none; }
summary::before { content: "\\25B8"; color: var(--muted); grid-row: span 2; }
details[open] summary::before { content: "\\25BE"; }
summary .sid { font-family: var(--mono); font-weight: 600; }
summary .stitle { font-weight: 600; }
summary .smeta { grid-column: 2 / -1; font-size: 13px; color: var(--muted); }
details .inner { display: grid; gap: 14px; padding: 0 16px 16px; }
details .inner > * { min-width: 0; }
.foot { font-size: 12px; color: var(--muted); }
@media (max-width: 560px) { summary { grid-template-columns: auto 1fr; }
  summary .badge { grid-column: 2; justify-self: start; } }
.ui-tools { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.ui-tools button { min-height: 40px; padding: 0 14px; border-radius: 8px; border: 1px solid var(--line);
  background: var(--surface); color: var(--fg); font: inherit; font-weight: 600; cursor: pointer; }
.ui-tools button[aria-pressed="true"] { background: var(--accent-soft); border-color: var(--accent); }
.ui-tools a { margin-left: auto; color: var(--accent); }
.ui-stage { display: flex; justify-content: center; padding: 8px 0 4px; }
.ui-frame { display: block; border: 0; background: var(--surface); }
.ui-frame.phone { width: 390px; max-width: 100%; height: 800px; border-radius: 30px;
  box-shadow: 0 0 0 10px var(--fg), 0 12px 40px rgba(0, 0, 0, .25); margin: 10px 0; }
.ui-frame.wide { width: 100%; height: 820px; border-radius: 10px; border: 1px solid var(--line); }
@media (max-width: 560px) { .ui-frame.phone { box-shadow: none; border-radius: 0; height: 760px; } }
"""
).replace("DARK", DARK)

SCRIPT = """
(function () {
  var views = Array.prototype.map.call(document.querySelectorAll("section[data-view]"),
    function (s) { return s.getAttribute("data-view"); });
  var frame = document.getElementById("ui-frame");
  Array.prototype.forEach.call(document.querySelectorAll("[data-size]"), function (b) {
    b.addEventListener("click", function () {
      frame.className = "ui-frame " + b.getAttribute("data-size");
      Array.prototype.forEach.call(document.querySelectorAll("[data-size]"), function (x) {
        x.setAttribute("aria-pressed", String(x === b));
      });
    });
  });
  var restart = document.getElementById("ui-restart");
  if (restart) restart.addEventListener("click", function () { frame.src = frame.src.split("#")[0]; });
  ["ui-student", "ui-researcher"].forEach(function (id) {
    var b = document.getElementById(id);
    if (b) b.addEventListener("click", function () { frame.src = b.getAttribute("data-src"); });
  });
  function route() {
    var h = (location.hash || "#" + views[0]).slice(1).toLowerCase();
    var target = null;
    if (/^s[0-9]+$/.test(h)) {
      target = document.getElementById(h);
      var host = target && target.closest("[data-view]");
      h = host ? host.getAttribute("data-view") : "current";
      if (target && target.tagName === "DETAILS") target.open = true;
    }
    if (views.indexOf(h) < 0) h = views[0];
    views.forEach(function (v) {
      document.getElementById("view-" + v).hidden = v !== h;
      var tab = document.getElementById("tab-" + v);
      if (v === h) tab.setAttribute("aria-current", "page"); else tab.removeAttribute("aria-current");
    });
    if (target) target.scrollIntoView({ block: "start" }); else window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", route);
  route();
})();
"""


# ---------- Markdown subset ----------


def inline(text: str) -> str:
    """Escape text, then apply inline code, links, bold and italics."""
    parts = re.split(r"(`[^`]*`)", text)
    out = []
    for part in parts:
        if len(part) >= 2 and part.startswith("`") and part.endswith("`"):
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        s = html.escape(part, quote=False)
        s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
        out.append(s)
    return "".join(out)


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?", line.strip()))


@dataclass
class Table:
    head: list[str]
    rows: list[list[str]]

    def col(self, name: str) -> int | None:
        lower = [h.lower() for h in self.head]
        return lower.index(name) if name in lower else None


@dataclass
class Doc:
    title: str = ""
    # Each block is ("h", level, text), ("p", text), ("ul", [items]) or ("table", Table).
    blocks: list[tuple] = field(default_factory=list)

    def tables(self) -> list[Table]:
        return [b[1] for b in self.blocks if b[0] == "table"]


def parse(md: str) -> Doc:
    doc = Doc()
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
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
        elif re.match(r"[-*]\s+", s):
            items = []
            while i < len(lines) and re.match(r"\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"\s*[-*]\s+", "", lines[i], count=1))
                i += 1
            doc.blocks.append(("ul", items))
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(
                r"\s*(#|\||[-*]\s)", lines[i]
            ):
                para.append(lines[i].strip())
                i += 1
            doc.blocks.append(("p", " ".join(para)))
    return doc


# ---------- HTML pieces ----------


def slug(status: str) -> str:
    return "s-" + status.replace(" ", "-")


def badge(status: str) -> str:
    s = status.lower()
    if s not in STATUSES:
        return inline(status)
    return f'<span class="badge {slug(s)}">{html.escape(s)}</span>'


def render_table(t: Table, row_class: dict[int, str] | None = None,
                 link_ids: set[str] | None = None) -> str:
    status_i, commit_i = t.col("status"), t.col("commit")
    head = "".join(f"<th>{inline(h)}</th>" for h in t.head)
    rows = []
    for n, r in enumerate(t.rows):
        cells = []
        for k, c in enumerate(r):
            if k == status_i:
                cells.append(f"<td>{badge(c)}</td>")
            elif k == commit_i:
                cells.append(f'<td class="mono">{html.escape(c)}</td>')
            elif k == 0 and link_ids and c.lower() in link_ids:
                cells.append(f'<td><a href="#{c.lower()}">{html.escape(c)}</a></td>')
            else:
                cells.append(f"<td>{inline(c)}</td>")
        cls = (row_class or {}).get(n)
        rows.append((f'<tr class="{cls}">' if cls else "<tr>") + "".join(cells) + "</tr>")
    return (
        f'<div class="panel scroll"><table>\n<thead><tr>{head}</tr></thead>\n<tbody>\n'
        + "\n".join(rows) + "\n</tbody></table></div>"
    )


def statuses_of(t: Table) -> list[str]:
    k = t.col("status")
    if k is None:
        return []
    return [r[k].lower() for r in t.rows if r[k].lower() in STATUSES]


def render_summary(statuses: list[str], noun: str) -> str:
    """Counts per status and a stacked bar, in a fixed order."""
    total = len(statuses)
    if not total:
        return ""
    counts = [(s, statuses.count(s)) for s in STATUSES if statuses.count(s)]
    done = statuses.count("done")
    label = f"{done} of {total} {noun} done"
    items = "".join(f'<span class="{slug(s)}"><b>{n}</b>{s}</span>' for s, n in counts)
    bar = "".join(
        f'<span class="{slug(s)}" style="width:{100 * n / total:.2f}%" title="{s}: {n}"></span>'
        for s, n in counts
    )
    return (
        f'<section class="panel summary" aria-label="{label}"><div class="counts">'
        f"<span><b>{done}/{total}</b>{noun} done</span>{items}</div>"
        f'<div class="bar" role="img" aria-label="{label}">{bar}</div></section>'
    )


def render_blocks(blocks: list[tuple]) -> list[str]:
    out = []
    after_done_heading = False
    for b in blocks:
        if b[0] == "h":
            after_done_heading = b[2].lower().startswith("definition of done")
            out.append(f"<h2>{inline(b[2])}</h2>")
        elif b[0] == "p":
            out.append(f"<p>{inline(b[1])}</p>")
        elif b[0] == "ul":
            cls = ' class="panel done-list"' if after_done_heading else ""
            out.append(f"<ul{cls}>" + "".join(f"<li>{inline(x)}</li>" for x in b[1]) + "</ul>")
        elif b[0] == "table":
            t = b[1]
            noun = "sessions" if t.head[0].lower() == "session" else "tasks"
            out.append(render_summary(statuses_of(t), noun))
            out.append(render_table(t))
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
    doc: Doc | None = None


def session_title(doc: Doc, sid: str) -> str:
    return re.sub(rf"^{sid}\s*[—–-]\s*", "", doc.title) or sid


def build_sessions(master: Doc, files: dict[str, str]) -> list[Session]:
    table = next((t for t in master.tables() if t.head and t.head[0].lower() == "session"), None)
    sessions: list[Session] = []
    if table:
        idx = {name: table.col(name) for name in ("goal", "status", "started", "finished", "commit")}

        def get(r: list[str], name: str) -> str:
            k = idx[name]
            return r[k] if k is not None else ""

        for r in table.rows:
            sessions.append(Session(r[0], get(r, "goal"), get(r, "status").lower() or "todo",
                                    get(r, "started"), get(r, "finished"), get(r, "commit")))
    known = {s.sid for s in sessions}
    sessions += [Session(sid, sid) for sid in files if sid not in known]
    for s in sessions:
        if s.sid in files:
            s.doc = parse(files[s.sid])
            if s.doc.title:
                s.name = session_title(s.doc, s.sid)
    return sessions


def pick_current(sessions: list[Session]) -> Session | None:
    for wanted in (("in progress", "continued"), ("todo",)):
        for s in sessions:
            if s.status in wanted:
                return s
    return None


# ---------- Views ----------


def session_body(s: Session) -> list[str]:
    if not s.doc:
        return ['<div class="panel empty">No task file yet. Perch-dev writes '
                f"<code>docs/sessions/{html.escape(s.sid)}.md</code> when the session starts.</div>"]
    return render_blocks(s.doc.blocks)


def view_current(s: Session | None) -> str:
    if not s:
        return '<div class="panel empty">Every session is finished or cut.</div>'
    when = f"Started {html.escape(s.started)}" if s.started else "Not started"
    return "\n".join([
        f'<div id="{s.sid.lower()}"><div class="eyebrow">Current session</div>',
        f'<div class="title-row"><h1>{html.escape(s.sid)} · {inline(s.name)}</h1>'
        f"{badge(s.status)}</div>",
        f'<div class="meta">{when}</div></div>',
        *session_body(s),
    ])


def view_master(master: Doc, sessions: list[Session], current: Session | None) -> str:
    intro = [b for b in master.blocks[:1] if b[0] == "p"]
    rest = master.blocks[len(intro):]
    linkable = {s.sid.lower() for s in sessions if s.doc and (s.status in FINISHED or s is current)}
    out = ['<div><div class="eyebrow">All sessions</div><h1>Master tracker</h1></div>']
    for b in rest:
        if b[0] == "table" and b[1].head[0].lower() == "session":
            t = b[1]
            k = t.col("status")
            classes = {}
            for n, r in enumerate(t.rows):
                if current and r[0] == current.sid:
                    classes[n] = "is-current"
                elif k is not None and r[k].lower() in FINISHED:
                    classes[n] = "is-finished"
            out.append(render_summary(statuses_of(t), "sessions"))
            out.append(render_table(t, row_class=classes, link_ids=linkable))
        else:
            out += render_blocks([b])
    out += [f'<p class="meta">{inline(b[1])}</p>' for b in intro]
    return "\n".join(out)


def view_archive(sessions: list[Session]) -> str:
    done = [s for s in sessions if s.status in FINISHED]
    done.sort(key=lambda s: int(re.sub(r"\D", "", s.sid) or 0), reverse=True)
    out = ['<div><div class="eyebrow">Finished sessions</div><h1>Archive</h1></div>']
    if not done:
        out.append('<div class="panel empty">Sessions move here when they are done or cut.</div>')
    items = []
    for s in done:
        tasks = statuses_of(s.doc.tables()[0]) if s.doc and s.doc.tables() else []
        bits = []
        if tasks:
            bits.append(f"{tasks.count('done')}/{len(tasks)} tasks done")
        if s.finished:
            bits.append(f"finished {html.escape(s.finished)}")
        if s.commit:
            bits.append(f"commit <code>{html.escape(s.commit)}</code>")
        items.append(
            f'<details id="{s.sid.lower()}"><summary><span><span class="sid">'
            f'{html.escape(s.sid)}</span> <span class="stitle">{inline(s.name)}</span></span>'
            f'<span></span>{badge(s.status)}<span class="smeta">{" · ".join(bits)}</span>'
            '</summary><div class="inner">' + "\n".join(session_body(s)) + "</div></details>"
        )
    if items:
        out.append("<div>" + "\n".join(items) + "</div>")
    return "\n".join(out)


def change_log(plan_md: str) -> Table | None:
    """The table under PLAN.md's '## Change log' heading."""
    doc = parse(plan_md)
    after = False
    for b in doc.blocks:
        if b[0] == "h":
            after = b[2].strip().lower() == "change log"
        elif b[0] == "table" and after:
            return b[1]
    return None


def newest_first(t: Table) -> Table:
    return Table(t.head, list(reversed(t.rows)))


def view_decisions(decisions_md: str, plan_md: str) -> str:
    out = ['<div><div class="eyebrow">Why things are the way they are</div>'
           "<h1>Decisions and plan changes</h1></div>"]
    dec = parse(decisions_md).tables() if decisions_md else []
    out.append(f"<h2>Decisions ({len(dec[0].rows) if dec else 0})</h2>")
    out.append(render_table(newest_first(dec[0])) if dec else
               '<div class="panel empty">No decisions logged yet in docs/DECISIONS.md.</div>')
    log = change_log(plan_md) if plan_md else None
    out.append(f"<h2>Plan change log ({len(log.rows) if log else 0})</h2>")
    out.append(render_table(newest_first(log)) if log else
               '<div class="panel empty">No plan changes logged yet in docs/PLAN.md.</div>')
    return "\n".join(out)


def view_bench(bench_md: str) -> str:
    doc = parse(bench_md)
    out = ['<div><div class="eyebrow">Measured in S8 to S13, copied from bench/results/</div>'
           f"<h1>{inline(doc.title or 'Bench results')}</h1></div>"]
    return "\n".join(out + render_blocks(doc.blocks))


def view_architecture(arch_md: str, root: Path) -> str:
    """docs/ARCHITECTURE.md; each ![caption](file.svg) is inlined from root as a figure."""
    doc = parse(arch_md)
    out = ['<div><div class="eyebrow">How Perch is built</div>'
           f"<h1>{inline(doc.title or 'Architecture')}</h1></div>"]
    for b in doc.blocks:
        if b[0] == "fig":
            f = root / b[2]
            svg = f.read_text(encoding="utf-8").strip() if f.is_file() else ""
            out.append(f'<figure class="panel diagram">{svg}'
                       f"<figcaption>{inline(b[1])}</figcaption></figure>")
        else:
            out += render_blocks([b])
    return "\n".join(out)


def view_persona(files: dict[str, str]) -> str:
    """The synthetic private-mode test persona: README rendered, each document shown as is."""
    readme = parse(files.get("README.md", ""))
    out = ['<div><div class="eyebrow">Synthetic test input for private mode, for team review'
           f"</div><h1>{inline(readme.title or 'Persona 1')}</h1></div>"]
    out += render_blocks(readme.blocks)
    for name, text in files.items():
        if name != "README.md":
            out.append(f"<h2><code>{html.escape(name)}</code></h2>"
                       f'<pre class="panel doc">{html.escape(text)}</pre>')
    return "\n".join(out)


def view_ux(ux_md: str) -> str:
    """docs/design/UX_AUDIT.md; each ![caption](file.png) is an image beside tracker.html."""
    doc = parse(ux_md)
    out = ['<div><div class="eyebrow">S21 audit, for choosing the S22 option</div>'
           f"<h1>{inline(doc.title or 'UX audit')}</h1></div>"]
    for b in doc.blocks:
        if b[0] == "fig":
            src = html.escape("design/" + b[2])
            out.append(f'<figure class="panel shot"><img src="{src}" alt="{html.escape(b[1])}" loading="lazy">'
                       f"<figcaption>{inline(b[1])}</figcaption></figure>")
        else:
            out += render_blocks([b])
    return "\n".join(out)


def view_readme(src: str) -> str:
    s = html.escape(src)
    return f"""<h2>README for review</h2>
<p>The repository's README.md as GitHub will show it, with its clips and the architecture figure.
Review it before the repository is made public (S15).</p>
<div class="ui-tools"><a href="{s}" target="_blank" rel="noopener">Open on its own</a></div>
<div class="ui-stage"><iframe class="readme-frame" src="{s}" title="README preview"></iframe></div>"""


def view_ui(src: str, student: str | None = None) -> str:
    s = html.escape(src)
    st = (f'<button type="button" id="ui-student" data-src="{html.escape(student)}">'
          f'Student (sample)</button>\n'
          f'<button type="button" id="ui-researcher" data-src="{s}">Researcher</button>\n'
          if student else "")
    return f"""<h2>UI preview</h2>
<p>The web app in replay mode, as redesigned in S24: a saved brief played back in about 15 seconds, the
researcher shown by alias. Press <b>Find</b>, then <b>This is the one</b> and <b>Build brief</b>, to
watch Scout build it. <b>Student (sample)</b> opens a finished brief for an invented SYNTHETIC student.
Nothing is fetched; keep and dismiss work but are not saved.</p>
<div class="ui-tools" role="group" aria-label="Preview size">
<button type="button" data-size="wide" aria-pressed="true">Laptop</button>
<button type="button" data-size="phone" aria-pressed="false">Phone</button>
<button type="button" id="ui-restart">Restart</button>
{st}<a href="{s}" target="_blank" rel="noopener">Open on its own</a>
</div>
<div class="ui-stage"><iframe id="ui-frame" class="ui-frame wide" src="{s}"
title="Perch web app preview"></iframe></div>"""


def render_page(master_md: str, session_files: dict[str, str], artifact: bool = False,
                page_title: str = "Perch Build Tracker", decisions_md: str = "",
                plan_md: str = "", ui: str | None = None, bench_md: str = "",
                arch_md: str = "", arch_root: Path = Path("docs"),
                persona: dict[str, str] | None = None, readme: str | None = None,
                ux_md: str = "", ui_student: str | None = None) -> str:
    master = parse(master_md)
    sessions = build_sessions(master, session_files)
    current = pick_current(sessions)
    finished = sum(s.status == "done" for s in sessions)
    archived = sum(s.status in FINISHED for s in sessions)
    glance = (
        f"<code>{html.escape(current.sid)}</code> {badge(current.status)}" if current else ""
    ) + f"<span>{finished}/{len(sessions)} sessions done</span>"
    name = html.escape(page_title)
    # Tab order (Dakshitha, 2026-10-29): UI, Architecture, Bench, Current, Master, then the
    # rest, Decisions last. The first tab present opens at rest.
    tabs = [t for t in (
        ("ui", "UI", lambda: view_ui(ui, ui_student), ui),
        ("architecture", "Architecture", lambda: view_architecture(arch_md, arch_root), arch_md),
        ("bench", "Bench", lambda: view_bench(bench_md), bench_md),
        ("ux", "UX", lambda: view_ux(ux_md), ux_md),
        ("current", "Current", lambda: view_current(current), True),
        ("master", "Master", lambda: view_master(master, sessions, current), True),
        ("archive", f'Archive<span class="count">{archived}</span>',
         lambda: view_archive(sessions), True),
        ("persona", "Persona", lambda: view_persona(persona), persona),
        ("readme", "README", lambda: view_readme(readme), readme),
        ("decisions", "Decisions", lambda: view_decisions(decisions_md, plan_md), True),
    ) if t[3]]
    nav = "\n".join(f'<a id="tab-{k}" href="#{k}"{" aria-current=\"page\"" if i == 0 else ""}>'
                    f"{label}</a>" for i, (k, label, _, _) in enumerate(tabs))
    views = "\n".join(f'<section id="view-{k}" class="view" data-view="{k}"'
                      f'{"" if i == 0 else " hidden"}>\n{body()}\n</section>'
                      for i, (k, _, body, _) in enumerate(tabs))
    page = f"""<header class="appbar"><div class="wrap">
<div class="brand"><b>Perch</b><span>Build tracker</span></div>
<div class="at-a-glance">{glance}</div>
<nav aria-label="Tracker views">
{nav}
</nav></div></header>
<main class="wrap">
{views}
<p class="foot">Generated from docs/TRACKER.md, docs/sessions/, docs/DECISIONS.md, the PLAN.md change log, bench/results/SUMMARY.md, docs/ARCHITECTURE.md and data/synthetic/persona-1/ by scripts/render_tracker.py.
The Markdown is the source of truth.</p>
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
    sessions = load_sessions(src.parent / "sessions")

    def read(name: str) -> str:
        f = src.parent / name
        return f.read_text(encoding="utf-8") if f.is_file() else ""

    page = render_page(src.read_text(encoding="utf-8"), sessions, args.artifact, args.title,
                       read("DECISIONS.md"), read("PLAN.md"), args.ui,
                       read("../bench/results/SUMMARY.md"), read("ARCHITECTURE.md"), src.parent,
                       load_persona(src.parent.parent / "data/synthetic/persona-1"), args.readme,
                       read("design/UX_AUDIT.md"), args.ui_student)
    dest.write_text(page, encoding="utf-8")
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Render a tracker Markdown file (docs/TRACKER.md, docs/sessions/S*.md) to HTML.

Standard library only. Handles the Markdown subset the trackers use: headings,
paragraphs, bullet lists and pipe tables, with inline code, bold, italics and
links. Status cells (todo, in progress, continued, done, cut) get a badge, and
the first table with a Status column gets a summary strip above the page.
Output is deterministic so re-running does not dirty the tree.

Two outputs:
  standalone (default): a complete HTML document with no external requests,
    for docs/tracker.html.
  --artifact: a page fragment for publishing as a claude.ai Artifact. The host
    wraps it in a document skeleton; it adds a Google Fonts link.

One page holds everything: the current session's tasks (the highest-numbered
docs/sessions/S<n>.md) come first, then the master tracker.

Usage: python scripts/render_tracker.py [SRC] [DEST] [--artifact] [--title NAME]
                                        [--no-session]
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

STATUSES = ("done", "in progress", "continued", "todo", "cut")

FONT_LINK = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=Public+Sans:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap\">"
)

CSS = """
/* Layout: one reading column; summary strip first, then the tables that hold the detail. */
:root {
  --bg: #f7f8f6; --surface: #ffffff; --fg: #1b2420; --muted: #56635c; --line: #d9dfdb;
  --head: #eef2ef; --code: #e9eeea; --accent: #1f6f5c;
  --todo: #6a7570; --progress: #a15c07; --continued: #6d3fc0; --done: #1d7a43; --cut: #b42323;
  --sans: "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #121715; --surface: #18201d; --fg: #e3ebe6; --muted: #9aa9a1; --line: #2c3833;
    --head: #1e2824; --code: #24302b; --accent: #5cc4a6;
    --todo: #9aa6a0; --progress: #f0a640; --continued: #b394f5; --done: #5fd38f; --cut: #f2787a;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #121715; --surface: #18201d; --fg: #e3ebe6; --muted: #9aa9a1; --line: #2c3833;
  --head: #1e2824; --code: #24302b; --accent: #5cc4a6;
  --todo: #9aa6a0; --progress: #f0a640; --continued: #b394f5; --done: #5fd38f; --cut: #f2787a;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.55 var(--sans);
  padding-block: 28px 56px;
  padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px));
}
main { max-width: 1120px; margin: 0 auto; display: grid; gap: 14px; }
main > * { min-width: 0; margin: 0; }
h1 { font-size: 1.65rem; line-height: 1.2; text-wrap: balance; letter-spacing: -0.01em; }
h2 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
  margin-top: 18px; }
p, li { color: var(--muted); max-width: 70ch; }
ul { padding-left: 1.2em; display: grid; gap: 4px; }
code { font-family: var(--mono); background: var(--code); padding: 1px 5px; border-radius: 3px;
  font-size: 0.86em; }
a { color: var(--accent); }
strong { color: var(--fg); }
.summary { display: grid; gap: 10px; background: var(--surface); border: 1px solid var(--line);
  border-radius: 6px; padding: 14px 16px; }
.counts { display: flex; flex-wrap: wrap; gap: 8px 18px; font-size: 14px; }
.counts b { font-family: var(--mono); font-variant-numeric: tabular-nums; font-size: 1.15rem;
  margin-right: 4px; }
.bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: var(--head); }
.bar span { display: block; height: 100%; }
.scroll { overflow-x: auto; background: var(--surface); border: 1px solid var(--line);
  border-radius: 6px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { border-bottom: 1px solid var(--line); padding: 7px 12px; text-align: left;
  vertical-align: top; }
tr:last-child td { border-bottom: 0; }
th { background: var(--head); font-weight: 600; font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--muted); white-space: nowrap; }
td:first-child { font-family: var(--mono); font-weight: 600; white-space: nowrap; }
.badge { display: inline-block; padding: 1px 9px; border-radius: 999px; font-size: 12px;
  font-weight: 600; white-space: nowrap; border: 1px solid currentColor; }
.s-todo { color: var(--todo); } .s-in-progress { color: var(--progress); }
.s-continued { color: var(--continued); } .s-done { color: var(--done); }
.s-cut { color: var(--cut); }
.bar .s-todo { background: var(--todo); } .bar .s-in-progress { background: var(--progress); }
.bar .s-continued { background: var(--continued); } .bar .s-done { background: var(--done); }
.bar .s-cut { background: var(--cut); }
.foot { font-size: 12px; }
"""


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
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?", line.strip()))


def slug(status: str) -> str:
    return "s-" + status.replace(" ", "-")


def cell(text: str, tag: str) -> str:
    if tag == "td" and text.lower() in STATUSES:
        return f'<td><span class="badge {slug(text.lower())}">{html.escape(text)}</span></td>'
    return f"<{tag}>{inline(text)}</{tag}>"


def render_table(head: list[str], body: list[list[str]]) -> str:
    rows = ["<tr>" + "".join(cell(c, "th") for c in head) + "</tr>"]
    for r in body:
        r = (r + [""] * len(head))[: len(head)]
        rows.append("<tr>" + "".join(cell(c, "td") for c in r) + "</tr>")
    return (
        '<div class="scroll"><table>\n<thead>' + rows[0] + "</thead>\n<tbody>\n"
        + "\n".join(rows[1:]) + "\n</tbody></table></div>"
    )


def render_summary(statuses: list[str], noun: str) -> str:
    """Counts per status and a stacked bar, in a fixed order."""
    total = len(statuses)
    counts = [(s, statuses.count(s)) for s in STATUSES if statuses.count(s)]
    done = statuses.count("done")
    items = "".join(
        f'<span class="{slug(s)}"><b>{n}</b>{html.escape(s)}</span>' for s, n in counts
    )
    bar = "".join(
        f'<span class="{slug(s)}" style="width:{100 * n / total:.2f}%" title="{s}: {n}"></span>'
        for s, n in counts
    )
    label = f"{done} of {total} {noun} done"
    return (
        f'<section class="summary" aria-label="{label}"><div class="counts">'
        f'<span><b>{done}/{total}</b>{noun} done</span>{items}</div>'
        f'<div class="bar" role="img" aria-label="{label}">{bar}</div></section>'
    )


def render_body(md: str) -> tuple[str, str]:
    """Return (title, body_html) for the Markdown subset."""
    lines = md.splitlines()
    blocks: list[str] = []
    title = "Perch tracker"
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
        elif m := re.match(r"(#{1,6})\s+(.*)", stripped):
            level = len(m.group(1))
            if level == 1:
                title = m.group(2).strip()
            blocks.append(f"<h{level}>{inline(m.group(2).strip())}</h{level}>")
            i += 1
        elif stripped.startswith("|") and i + 1 < len(lines) and is_separator(lines[i + 1]):
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            head = split_row(lines[i])
            body = [split_row(row) for row in lines[i + 2 : j]]
            lower = [h.lower() for h in head]
            if "status" in lower:
                k = lower.index("status")
                noun = "sessions" if lower[0] == "session" else "tasks"
                statuses = [r[k].lower() for r in body if len(r) > k and r[k].lower() in STATUSES]
                if statuses:
                    blocks.append(render_summary(statuses, noun))
            blocks.append(render_table(head, body))
            i = j
        elif re.match(r"[-*]\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"\s*[-*]\s+", lines[i]):
                text = re.sub(r"\s*[-*]\s+", "", lines[i], count=1)
                items.append(f"<li>{inline(text)}</li>")
                i += 1
            blocks.append("<ul>\n" + "\n".join(items) + "\n</ul>")
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(
                r"\s*(#|\||[-*]\s)", lines[i]
            ):
                para.append(lines[i].strip())
                i += 1
            blocks.append("<p>" + inline(" ".join(para)) + "</p>")
    return title, "\n".join(blocks)


def current_session(sessions_dir: Path) -> Path | None:
    """The highest-numbered docs/sessions/S<n>.md, or None."""
    files = [f for f in sessions_dir.glob("S*.md") if re.fullmatch(r"S\d+", f.stem)]
    return max(files, key=lambda f: int(f.stem[1:]), default=None)


def render(md: str, source: str = "docs/TRACKER.md", artifact: bool = False,
           page_title: str | None = None) -> str:
    title, body = render_body(md)
    name = html.escape(page_title or re.sub(r"[`*]", "", title))
    foot = (
        f'<p class="foot"><em>Generated from {html.escape(source)} by '
        "scripts/render_tracker.py. The Markdown is the source of truth.</em></p>"
    )
    main = f"<main>\n{body}\n{foot}\n</main>\n"
    if artifact:
        return (
            f"<title>{name}</title>\n"
            '<meta name="claude:viewport-fit-sides" content="cover">\n'
            f"{FONT_LINK}\n<style>{CSS}</style>\n{main}"
        )
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{name}</title>\n<style>{CSS}</style>\n</head>\n<body>\n{main}"
        "</body>\n</html>\n"
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", nargs="?", default="docs/TRACKER.md")
    ap.add_argument("dest", nargs="?")
    ap.add_argument("--artifact", action="store_true", help="emit a claude.ai Artifact fragment")
    ap.add_argument("--title", help="page name (defaults to the Markdown H1)")
    ap.add_argument("--no-session", action="store_true", help="master tracker only")
    args = ap.parse_args(argv[1:])
    src = Path(args.src)
    dest = Path(args.dest) if args.dest else src.with_name("tracker.html")
    dest.parent.mkdir(parents=True, exist_ok=True)
    md, source = src.read_text(encoding="utf-8"), args.src
    session = None if args.no_session else current_session(src.parent / "sessions")
    if session:
        md = session.read_text(encoding="utf-8") + "\n\n" + md
        source = f"{session.as_posix()} and {source}"
    page = render(md, source, args.artifact, args.title or "Perch Build Tracker")
    dest.write_text(page, encoding="utf-8")
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

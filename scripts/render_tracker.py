"""Render docs/TRACKER.md to a single static HTML page.

Standard library only. Handles the Markdown subset the tracker uses: headings,
paragraphs, bullet lists and pipe tables, with inline code, bold, italics and
links. Status cells (todo, in progress, continued, done, cut) get a coloured
badge. Output is deterministic so re-running does not dirty the tree.

Usage: python scripts/render_tracker.py [SRC] [DEST]
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

STATUSES = {"todo", "in progress", "continued", "done", "cut"}

CSS = """
:root {
  --bg: #fbfbfa; --fg: #1d1d1f; --muted: #5f6368; --line: #dcdcdc;
  --head: #f0f0ee; --code: #eeeeec;
  --todo: #6b7280; --progress: #b45309; --continued: #7c3aed;
  --done: #15803d; --cut: #b91c1c;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161618; --fg: #e8e8e6; --muted: #a0a0a6; --line: #3a3a3e;
    --head: #222226; --code: #2a2a2e;
    --todo: #9ca3af; --progress: #f59e0b; --continued: #a78bfa;
    --done: #4ade80; --cut: #f87171;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 16px 48px; background: var(--bg); color: var(--fg);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 1.6rem; margin: 0 0 8px; }
h2 { font-size: 1.15rem; margin: 32px 0 8px; }
p, li { color: var(--muted); max-width: 75ch; }
code { background: var(--code); padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }
a { color: inherit; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { border-bottom: 1px solid var(--line); padding: 6px 10px; text-align: left;
  vertical-align: top; }
th { background: var(--head); font-weight: 600; white-space: nowrap; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px;
  font-weight: 600; white-space: nowrap; border: 1px solid currentColor; }
.s-todo { color: var(--todo); }
.s-in-progress { color: var(--progress); }
.s-continued { color: var(--continued); }
.s-done { color: var(--done); }
.s-cut { color: var(--cut); }
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


def cell(text: str, tag: str) -> str:
    if tag == "td" and text.lower() in STATUSES:
        slug = text.lower().replace(" ", "-")
        return f'<td><span class="badge s-{slug}">{html.escape(text)}</span></td>'
    return f"<{tag}>{inline(text)}</{tag}>"


def render_table(lines: list[str]) -> str:
    head = split_row(lines[0])
    body = [split_row(line) for line in lines[2:]]
    rows = ["<tr>" + "".join(cell(c, "th") for c in head) + "</tr>"]
    for r in body:
        r = (r + [""] * len(head))[: len(head)]
        rows.append("<tr>" + "".join(cell(c, "td") for c in r) + "</tr>")
    return (
        '<div class="scroll"><table>\n<thead>' + rows[0] + "</thead>\n<tbody>\n"
        + "\n".join(rows[1:]) + "\n</tbody></table></div>"
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
            blocks.append(render_table(lines[i:j]))
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


def render(md: str) -> str:
    title, body = render_body(md)
    page_title = html.escape(re.sub(r"[`*]", "", title))
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{page_title}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
        f"{body}\n"
        "<p><em>Generated from docs/TRACKER.md by scripts/render_tracker.py. "
        "Edit the Markdown, then run <code>make tracker</code>.</em></p>\n"
        "</main>\n</body>\n</html>\n"
    )


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else Path("docs/TRACKER.md")
    dest = Path(argv[2]) if len(argv) > 2 else src.with_name("tracker.html")
    dest.write_text(render(src.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

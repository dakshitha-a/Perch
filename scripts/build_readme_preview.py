"""README.md as a page for the tracker's README tab, styled like GitHub's (S15).

  uv run --with markdown python scripts/build_readme_preview.py [--out build/artifacts/readme.html]

Images keep their repo-relative paths (docs/tour/*.webp, docs/architecture/*.svg); they are
copied beside the page so it also works opened from disk, and the tracker artifact publishes
them at the same paths. `markdown` is used only here.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
CSS = """
:root { color-scheme: light dark; --fg: #1f2328; --muted: #59636e; --line: #d1d9e0; --bg: #ffffff;
  --code: #f6f8fa; --link: #0969da; --quote: #59636e; }
@media (prefers-color-scheme: dark) { :root { --fg: #f0f6fc; --muted: #9198a1; --line: #3d444d;
  --bg: #0d1117; --code: #151b23; --link: #4493f8; --quote: #9198a1; } }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.5 -apple-system,
  BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif; }
main { max-width: 980px; margin: 0 auto; padding: 32px 16px 64px; }
.frame { border: 1px solid var(--line); border-radius: 6px; padding: 16px 32px 32px; }
.bar { font-size: 14px; color: var(--muted); padding: 8px 0 12px; }
h1, h2 { border-bottom: 1px solid var(--line); padding-bottom: .3em; }
h1 { font-size: 2em; } h2 { font-size: 1.5em; margin-top: 24px; } h3 { font-size: 1.25em; }
a { color: var(--link); text-decoration: none; } a:hover { text-decoration: underline; }
img { max-width: 100%; height: auto; }
code { background: var(--code); padding: .2em .4em; border-radius: 6px; font-size: 85%; }
pre { background: var(--code); padding: 16px; border-radius: 6px; overflow: auto; }
pre code { background: none; padding: 0; font-size: 85%; }
table { border-collapse: collapse; display: block; overflow: auto; margin: 16px 0; }
td, th { border: 1px solid var(--line); padding: 6px 13px; vertical-align: top; }
blockquote { margin: 0; padding: 0 1em; color: var(--quote); border-left: .25em solid var(--line); }
sub { color: var(--muted); }
@media (max-width: 640px) { .frame { padding: 8px 16px 24px; } }
"""


def render(src: str) -> str:
    # GitHub renders Markdown inside HTML blocks when a blank line separates them;
    # python-markdown needs markdown="1" on those blocks to do the same.
    src = re.sub(r"<(div|td)([^>]*)>", r'<\1\2 markdown="1">', src)
    return markdown.markdown(src, extensions=["tables", "fenced_code", "md_in_html"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/artifacts/readme.html")
    a = ap.parse_args()
    body = render((ROOT / "README.md").read_text(encoding="utf-8"))
    page = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>Perch README</title>\n<style>{CSS}</style>\n</head>\n<body><main>\n"
            "<div class=\"bar\">README.md, as GitHub will show it (approximately)</div>\n"
            f"<article class=\"frame\">\n{body}\n</article></main></body></html>\n")
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    copy_assets(body, out.parent)
    print(f"wrote {out}")


def copy_assets(body: str, dest: Path) -> None:
    """Copy each repo-relative image or clip the README references to the same path under dest."""
    refs = re.findall(r'(?:src|srcset)="([^"]+)"', body)
    for ref in sorted(set(refs)):
        rel = ref.split()[0]
        if re.match(r"[a-z]+:|/|#", rel):
            continue
        src, target = ROOT / rel, dest / rel
        if src.is_file() and src.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)


if __name__ == "__main__":
    main()

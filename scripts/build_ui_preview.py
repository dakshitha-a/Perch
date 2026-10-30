"""Bundle web/ and one replay file into a single self-contained page.

  uv run python scripts/build_ui_preview.py [build/replay/<id>.json] [--out build/artifacts/ui.html]

The page runs the real app in replay mode: no server, no network. It feeds the tracker
artifact's UI tab, the screenshots and the Demo Day fallback. Modules are wrapped in
functions so their names cannot collide; nothing else is changed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
# In dependency order. format.js keeps its alias (app.js imports it as `f`); compare.js
# also imports formatDate from it by name, which bundle() pulls out of `f`.
MODULES = {"format.js": "f", "dom.js": None, "api.js": None, "owl.js": None, "private.js": None,
           "mode.js": None, "student.js": None, "help.js": None, "compare.js": None,
           "handoff.js": None, "scout.js": None}
EXPORT = re.compile(r"^export (?:async )?(?:function|const|class) (\w+)", re.M)
IMPORT = re.compile(r"^import .*?;\n", re.M)


def wrap(name: str, alias: str | None) -> str:
    src = (WEB / name).read_text(encoding="utf-8")
    names = EXPORT.findall(src)
    body = re.sub(r"^export ", "", IMPORT.sub("", src), flags=re.M)
    ret = "{ " + ", ".join(names) + " }"
    lhs = f"const {alias}" if alias else f"const {ret}"
    return f"// ---- {name}\n{lhs} = (() => {{\n{body}\nreturn {ret};\n}})();\n"


def bundle() -> str:
    app = IMPORT.sub("", (WEB / "app.js").read_text(encoding="utf-8"))
    mods = "".join(wrap(n, a) + ("const { formatDate } = f;\n" if n == "format.js" else "")
                   for n, a in MODULES.items())
    return mods + "// ---- app.js\n" + app


def page(replay: dict) -> str:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    data = json.dumps(replay, separators=(",", ":")).replace("<", "\\u003c")
    js = bundle().replace("</script", "<\\/script")
    html = html.replace('<link rel="icon" href="favicon.svg" type="image/svg+xml">\n', "")
    html = html.replace('<link rel="stylesheet" href="styles.css">', f"<style>\n{css}</style>")
    html = html.replace('<script type="module" src="app.js"></script>',
                        f"<script>window.PERCH_REPLAY = {data};</script>\n"
                        f"<script type=\"module\">\n{js}</script>")
    return html


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("replay", nargs="?")
    ap.add_argument("--out", default="build/artifacts/ui.html")
    args = ap.parse_args(argv[1:])
    src = Path(args.replay) if args.replay else None
    if src is None:
        found = sorted((p for p in Path("build/replay").glob("*.json") if p.name != "student.json"),
                       key=lambda p: p.stat().st_mtime)
        if not found:
            print("no replay file in build/replay; run scripts/export_replay.py first")
            return 0
        src = found[-1]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(json.loads(src.read_text(encoding="utf-8"))), encoding="utf-8")
    print(f"wrote {out} from {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Stage the v1 example page for the tracker artifact's UI tab (S55).

  uv run python scripts/build_ui_example.py

Copies the web app (web/*.html, *.js, *.css, fonts, favicon) and the example briefs
(web/example/researcher.json and student.json, from scripts/export_example.py) to
build/artifacts/app/, so the UI tab can frame app/example.html?side=researcher|student. Beside
the tracker it writes ui.json and ui-student.json, small sidecars with the export time (the
files' modified time) that the tracker's UI tab shows and compares with the newest session.
Does nothing when there is no exported brief. Files are overwritten, never deleted.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB, OUT = ROOT / "web", ROOT / "build/artifacts"
APP = OUT / "app"
SUFFIXES = {".html", ".js", ".css", ".svg", ".woff2"}


def main() -> int:
    sides = {s: WEB / "example" / f"{s}.json" for s in ("researcher", "student")}
    if not all(p.is_file() for p in sides.values()):
        print("no exported example briefs in web/example; run scripts/export_example.py first")
        return 0
    for p in WEB.rglob("*"):
        if p.is_file() and p.suffix in SUFFIXES and "example" not in p.relative_to(WEB).parts[:-1]:
            dest = APP / p.relative_to(WEB)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
    (APP / "example").mkdir(exist_ok=True)
    for side, p in sides.items():
        shutil.copy2(p, APP / "example" / p.name)
        when = datetime.fromtimestamp(p.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        sidecar = {"replay": f"web/example/{p.name}", "created_at": when,
                   "student": side == "student"}
        name = "ui.json" if side == "researcher" else "ui-student.json"
        (OUT / name).write_text(json.dumps(sidecar, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {APP} ({sum(1 for f in APP.rglob('*') if f.is_file())} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

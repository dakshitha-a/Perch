"""Live canary run for private mode on self-hosted models (S13 definition of done; rerun
in S16 on the frozen build).

Runs, through the real API on the real store and models: a private-only brief and a
brief with a public profile, both with the SYNTHETIC persona-1 documents and a direction
holding its own canary; keeps a lead; compare; hand-off and exports, plain and masked;
a private Scout question; then ends the session. Afterwards it checks that no canary
is in any file under data/, in a file under /tmp changed during the run, or in the
model servers' journals, and that no file under data/ changed.

  PERCH_PRIVATE_MODE=1 PERCH_TLS_AT=server PERCH_PRIVATE_OPERATOR="..." \\
  PERCH_MODEL_SERVER=http://127.0.0.1:8093 OLLAMA_BASE_URL=http://127.0.0.1:11437 \\
  uv run python scripts/private_canary.py [--author A5026494099]

Prints the result as JSON. Exit code 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERSONA = ROOT / "data/synthetic/persona-1"
FILES = {"cv": "cv.md", "proposal": "specific_aims_draft.md",
         "manuscript": "unpublished_manuscript.md"}
CANARIES = ["PERCH-CANARY-CV-7Q4X", "PERCH-CANARY-AIMS-K2M9", "PERCH-CANARY-MS-T8V3",
            "PERCH-CANARY-DIR-Z5P1"]
DIRECTION = ("SYNTHETIC direction PERCH-CANARY-DIR-Z5P1: wearable insole sensing of gait "
             "as an early marker of Parkinson's disease, measured at home over weeks.")
UNITS = ["perch-demo-ollama", "perch-demo-models", "perch-demo-clef", "perch-demo-clef-flash",
         "perch-clef", "perch-clef-flash"]


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def files_with(root: Path, since: float | None = None) -> list[str]:
    hits = []
    for p in root.rglob("*"):
        if PERSONA in p.parents:  # the inputs themselves
            continue
        try:
            if not p.is_file() or p.is_symlink() or p.stat().st_size > 200_000_000:
                continue
            if since and p.stat().st_mtime < since:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        hits += [f"{p}: {t}" for t in CANARIES if t.encode() in data]
    return hits


def journals(since: str) -> dict[str, int]:
    out = {}
    for u in UNITS:
        r = subprocess.run(["journalctl", "--user", "-u", f"{u}.service", "--since", since,
                            "--no-pager", "-o", "cat"], capture_output=True, text=True)
        out[u] = sum(r.stdout.count(t) for t in CANARIES)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--author", default="A5026494099", help="public profile for the 2nd brief")
    ap.add_argument("--data", default=str(ROOT / "data"))
    a = ap.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient

    from perch.api import create_app
    from perch.cli import default_client
    from perch.jobs import InlineRunner
    from perch.service import BriefService, Clients, default_models

    data = Path(a.data)
    start, since = time.time(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    before = snapshot(data)
    service = BriefService(data / "perch.db", default_models(False, data),
                           Clients(openalex=default_client), ROOT / "data/overrides/awards.csv")
    c = TestClient(create_app(service, InlineRunner(), web_dir=None))
    out: dict = {"started": datetime.now(UTC).isoformat(timespec="seconds"), "briefs": []}
    r = c.post("/private/session")
    if r.status_code != 201:
        print(json.dumps({"error": r.json()}, indent=2))
        return 1
    h = {"X-Perch-Private": r.json()["token"]}
    for kind, name in FILES.items():
        c.post("/private/documents", headers=h,
               json={"kind": kind, "text": (PERSONA / name).read_text()}).raise_for_status()
    c.post("/private/documents", headers=h,
           json={"kind": "direction", "text": DIRECTION}).raise_for_status()
    for author in (None, a.author):
        t0 = time.time()
        c.post("/private/brief", headers=h, json={"author_id": author}).raise_for_status()
        got = c.get("/private/brief", headers=h).json()
        b, leads = got["brief"], got["leads"]
        a_leads = [x for x in leads if x["route"] == "A"]
        cited_private = [x for x in a_leads
                         if any(i.startswith("private:") for i in x["cited_ids"])]
        row = {"author": author or "none (private only)", "status": b["status"],
               "error": b["error"], "seconds": round(time.time() - t0, 1),
               "threads": [(t["label"], t["weight"], t.get("private", False))
                           for t in b["threads"]],
               "stages": {s["name"]: s["detail"] for s in b["stages"]},
               "grant_leads": len(a_leads), "industry_leads": len(leads) - len(a_leads),
               "explained": sum(bool(x["explanation"]) for x in a_leads),
               "citing_private": len(cited_private),
               "notes": [n for x in a_leads for n in x["notes"]],
               "top": [(x["opportunity"]["opportunity_number"], x["opportunity"]["title"][:80],
                        x["cited_ids"]) for x in a_leads[:3]]}
        if a_leads:
            c.post(f"/private/leads/{a_leads[0]['id']}/keep", headers=h)
            c.get("/private/compare", headers=h)
            plain = c.get("/private/export.json", headers=h).json()
            masked = c.get("/private/export.json", headers=h, params={"mask": True}).json()
            row["export_withheld"] = sum((x["explanation"] or "").startswith("Withheld")
                                         for x in plain["leads"])
            row["export_masked_sample"] = next((x["explanation"] for x in masked["leads"]
                                                if x["explanation"]), None)
            for mask in (False, True):
                c.get("/private/export.md", headers=h, params={"mask": mask})
                c.get("/private/export.html", headers=h, params={"mask": mask})
                d = c.post("/private/handoff", headers=h,
                           json={"office": "research_development", "mask": mask}).json()
                row[f"handoff_{'masked' if mask else 'plain'}_flagged"] = d.get("flagged")
            sc = c.post("/private/scout", headers=h,
                        json={"question": "Which of these leads best fits my draft proposal?",
                              "mode": "run"})
            row["scout"] = sc.status_code
        out["briefs"].append(row)
    c.post("/private/end", headers=h)
    time.sleep(2)
    after = snapshot(data)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    demo = str(data / "demo")  # the live demo's own store; it writes on its own schedule
    out["data_changed"] = [k for k in changed if not k.startswith(demo)]
    out["demo_store_changed_meanwhile"] = [k for k in changed if k.startswith(demo)]
    out["canary_in_data"] = files_with(data)
    out["canary_in_tmp"] = files_with(Path("/tmp"), since=start)
    out["canary_in_journals"] = journals(since)
    ok = (not out["data_changed"] and not out["canary_in_data"] and not out["canary_in_tmp"]
          and not any(out["canary_in_journals"].values())
          and all(b["status"] == "done" for b in out["briefs"])
          and out["briefs"][0]["citing_private"] > 0)
    out["ok"] = ok
    print(json.dumps(out, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

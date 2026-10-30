"""Save a SYNTHETIC student brief as a replay file for the tracker's UI preview (S26).

  uv run python scripts/export_student_replay.py [--persona persona-ug] [--db data/demo/perch.db]

Runs the persona's invented CV, interests and achievements through a private session on
the real store and models, in this process, and saves what the web app would get:
GET /private/brief and every record the evidence panel can open. Nothing is written to
the store; the session ends at the end. Canary tokens in the persona files are replaced
with "[canary]" so the published preview carries none. Output goes under build/
(gitignored). Run it with the demo's model settings (see docs/deploy.md) and private mode
on (PERCH_PRIVATE_MODE=1, PERCH_TLS_AT=server, PERCH_PRIVATE_OPERATOR).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from perch.api import create_app
from perch.jobs import InlineRunner
from perch.service import BriefService, Clients, default_models

SYN = Path("data/synthetic")
FILES = {"cv": "cv.md", "interests": "interests.md", "achievements": "achievements.md"}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--persona", default="persona-ug")
    ap.add_argument("--db", default="data/demo/perch.db")
    ap.add_argument("--out", default="build/replay/student.json")
    args = ap.parse_args(argv[1:])
    service = BriefService(args.db, default_models(data_dir=Path(args.db).parent),
                           Clients(openalex=lambda: None))
    c = TestClient(create_app(service, InlineRunner(), web_dir=None))
    r = c.post("/private/session")
    if r.status_code != 201:
        print(f"no private session: {r.text}", file=sys.stderr)
        return 1
    h = {"X-Perch-Private": r.json()["token"]}
    try:
        for kind, name in FILES.items():
            c.post("/private/documents", headers=h,
                   json={"kind": kind, "text": (SYN / args.persona / name).read_text()}
                   ).raise_for_status()
        c.post("/private/student/brief", headers=h, json={}).raise_for_status()
        payload = c.get("/private/brief", headers=h).json()
        if payload["brief"]["status"] != "done":
            print(f"the brief did not finish: {payload['brief'].get('error')}", file=sys.stderr)
            return 1
        ids = {x["record_id"] for x in payload["leads"]} | set(payload["papers"])
        ids |= {i for x in payload["leads"] for i in x["cited_ids"]}
        records = {}
        for i in sorted(ids):
            got = c.get(f"/private/records/{i}", headers=h)
            if got.status_code == 200:
                records[i] = got.json()
    finally:
        c.post("/private/end", headers=h)
    text = json.dumps({"version": 2, "brief": payload, "candidates": [], "records": records,
                       "student": True}, indent=1)
    text = re.sub(r"PERCH-CANARY-[A-Z0-9-]+", "[canary]", text)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(payload['leads'])} leads, {len(records)} records)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

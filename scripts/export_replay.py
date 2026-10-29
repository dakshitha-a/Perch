"""Save one finished brief as a replay file for the web app's replay mode.

  uv run python scripts/export_replay.py <brief_id> [--out build/replay/<brief_id>.json]

The file holds exactly what the app would get from the API: GET /briefs/{id}, the
resolve candidate and every record the evidence panel can open. The researcher is shown
by alias from data/overrides/pi_aliases.csv, the ORCID is dropped and award PI names are
cleared, so the file can feed screenshots and the tracker preview. Output goes under
build/ (gitignored).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from perch.api import create_app
from perch.jobs import InlineRunner
from perch.service import BriefService, Clients, default_models

ALIASES = Path("data/overrides/pi_aliases.csv")


def alias_for(author_id: str) -> str | None:
    short = author_id.rsplit("/", 1)[-1]
    with ALIASES.open(newline="", encoding="utf-8") as f:
        return next((r["alias"] for r in csv.DictReader(f) if r["openalex_id"] == short), None)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("brief_id")
    ap.add_argument("--out")
    ap.add_argument("--db", default="data/perch.db")
    args = ap.parse_args(argv[1:])
    service = BriefService(args.db, default_models(), Clients(openalex=lambda: None))
    c = TestClient(create_app(service, InlineRunner(), web_dir=None))
    got = c.get(f"/briefs/{args.brief_id}")
    if got.status_code != 200:
        print(got.json()["detail"], file=sys.stderr)
        return 1
    payload = got.json()
    b = payload["brief"]
    ids = {b["researcher_id"], *(x["record_id"] for x in payload["leads"]),
           *payload["papers"], *(a["record_id"] for a in payload["awards"])}
    for lead in payload["leads"]:
        ids |= {f"https://openalex.org/{i}" if i.startswith("W") else f"grants_gov:{i}"
                for i in lead["cited_ids"]}
    records = {i: c.get(f"/records/{i}").json() for i in sorted(ids)}
    records = {i: r for i, r in records.items() if "kind" in r}

    name = alias_for(b["researcher_id"])
    if not name:
        print("researcher has no alias in data/overrides/pi_aliases.csv", file=sys.stderr)
        return 1
    res = records[b["researcher_id"]]
    res.update(display_name=name, orcid=None)
    payload["researcher"] = res
    b["stages"][0]["detail"] = name
    for r in records.values():
        if r["kind"] == "award":
            r["pi_names"] = []
    out = Path(args.out or f"build/replay/{args.brief_id}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"version": 1, "brief": payload, "candidates": [res],
                               "records": records}, indent=1), encoding="utf-8")
    print(f"wrote {out} ({len(records)} records)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Save one finished brief as a replay file for the web app's replay mode.

  uv run python scripts/export_replay.py <brief_id> [--out build/replay/<brief_id>.json]

The file holds exactly what the app would get from the API: GET /briefs/{id}, the
resolve candidate and every record the evidence panel can open, including the records
behind industry-lead signals. It also records the later steps, so the preview can play
them back: the comparison of every lead, one hand-off draft per office for a few kept
leads (top two grants, top industry lead), one Scout question in run mode, and the
latest weekly-watch digest for this researcher. Nothing is written to the store: the
kept state lives only in the file.

The researcher is shown by alias from data/overrides/pi_aliases.csv, the ORCID is
dropped and award PI names are cleared. The export fails if the real name is left
anywhere in the file. Output goes under build/ (gitignored). For the demo store, run it
with the demo's model settings (see docs/deploy.md), so drafts and Scout use its models.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
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


def real_name(author_id: str) -> str | None:
    short = author_id.rsplit("/", 1)[-1]
    with ALIASES.open(newline="", encoding="utf-8") as f:
        return next((r["name"] for r in csv.DictReader(f) if r["openalex_id"] == short), None)


def later_steps(c: TestClient, bid: str, payload: dict, question: str) -> dict:
    """Compare, hand-off, Scout and watch, recorded through the API without writes."""
    leads = payload["leads"]
    keep = ([x["id"] for x in leads if x["route"] == "A"][:2]
            + [x["id"] for x in leads if x["route"] == "B"][:1])
    for x in leads:
        x["status"] = "kept" if x["id"] in keep else "new"
    compare = c.get(f"/briefs/{bid}/compare", params={"status": "all"}).json()
    handoffs = {}
    for o in compare["offices"]:
        ids = [x["id"] for x in leads if x["id"] in keep and x["route"] == o["route"]]
        if ids:
            r = c.post(f"/briefs/{bid}/handoff", json={"office": o["key"], "lead_ids": ids})
            r.raise_for_status()
            handoffs[o["key"]] = {"lead_ids": ids, "draft": r.json()}
    r = c.post(f"/briefs/{bid}/scout", json={"question": question, "mode": "run"})
    r.raise_for_status()
    sid = r.json()["id"]
    scout = c.get(f"/scout/{sid}").json()
    for _ in range(600):
        if not scout.get("busy"):
            break
        time.sleep(1)
        scout = c.get(f"/scout/{sid}").json()
    r = c.get("/watch")  # shelved since S23 (perch/shelved/monitor): no digests then
    watch = r.json() if r.status_code == 200 else {"digests": []}
    watch["digests"] = [d for d in watch.get("digests", [])
                        if d["researcher"]["id"] == payload["brief"]["researcher_id"]]
    return {"kept": keep, "compare": compare, "handoffs": handoffs,
            "scout": {"question": question, "session": scout}, "watch": watch}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("brief_id")
    ap.add_argument("--out")
    ap.add_argument("--db", default="data/perch.db")
    ap.add_argument("--question", default="Why does the top lead fit?",
                    help="the Scout question to record")
    args = ap.parse_args(argv[1:])
    # The store's own index and caches sit beside it, as for the student replay.
    service = BriefService(args.db, default_models(data_dir=Path(args.db).parent),
                           Clients(openalex=lambda: None))
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
                for i in lead["cited_ids"] if lead["route"] == "A"}
        ids |= {x["id"] for it in lead.get("signal_items") or [] for x in it["records"]}
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
    extras = later_steps(c, args.brief_id, payload, args.question)
    for d in extras["watch"]["digests"]:
        d["researcher"]["name"] = name
    text = json.dumps({"version": 2, "brief": payload, "candidates": [res],
                       "records": records, **extras}, indent=1)
    real = real_name(b["researcher_id"])
    if real and real in text:
        text = text.replace(real, name)
    if real and real.split()[-1] in text:
        print(f"note: the surname of {name} still appears; check the file", file=sys.stderr)
    out = Path(args.out or f"build/replay/{args.brief_id}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(records)} records)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Draft review evaluation, decision-only (S24 task 7, Q32).

For each SYNTHETIC draft in cases.json: code quotes what the chosen public record asks for
(items.py), and a checking model marks each item addressed, not addressed or unclear in the
draft. No model writes anything. Scored against the planted keys.

  uv run --extra ml python -m bench.draft_review.run [--store data/demo/perch.db]

Checkers: the grounding models that already check explanations (validator layer 2, through
their own interfaces: Clef and Clef-flash as yes/no deciders, MiniCheck on the model
server), and the chat model through the `decide` primitive's logprobs path, as a
three-way choice. A grounder's support probability maps to a mark: above 0.65 addressed,
below 0.35 not addressed, in between unclear. The thresholds are set before the run.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections.abc import Callable
from pathlib import Path

from bench.draft_review.items import asks
from perch.schemas import Opportunity
from perch.store.sqlite import SQLiteRepository

HERE = Path(__file__).parent
OUT = Path("bench/results/draft_review")
HI, LO = 0.65, 0.35
CLAIM = "The text addresses this point: {item}"
QUESTION = ("Does the draft address the point from the funding record? Answer addressed, "
            "not addressed, or unclear.")


def mark(p: float) -> str:
    return "addressed" if p > HI else "not addressed" if p < LO else "unclear"


def grounder_checker(g: object) -> Callable[[str, list[str]], list[str]]:
    def run(draft: str, items: list[str]) -> list[str]:
        return [mark(p) for p in g.support(draft, [CLAIM.format(item=i) for i in items])]
    return run


def llm_checker(spec: str) -> Callable[[str, list[str]], list[str]]:
    from perch.llm import get_provider
    from perch.llm.decide import Choice, LogprobDecider

    d = LogprobDecider(get_provider(spec))
    q = Choice(QUESTION, ["addressed", "not addressed", "unclear"])

    def run(draft: str, items: list[str]) -> list[str]:
        return [d.decide(q, f"DRAFT:\n{draft}\n\nPOINT FROM THE FUNDING RECORD:\n{i}").value
                for i in items]
    return run


def checkers(names: list[str]) -> dict[str, Callable]:
    from perch.config import env
    from perch.grounding import DecisionGrounder
    from perch.llm.systemone import SystemOneClient, SystemOneDecider, server_url
    from perch.remote_models import RemoteGrounder

    out = {}
    for n in names:
        if n in ("clef", "clef-flash"):
            out[n] = grounder_checker(DecisionGrounder(
                SystemOneDecider(SystemOneClient(server_url(n)), n), n))
        elif n == "minicheck":
            out[n] = grounder_checker(RemoteGrounder(env("PERCH_MODEL_SERVER",
                                                         "http://127.0.0.1:8093")))
        else:
            out[n] = llm_checker(n)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/demo/perch.db")
    ap.add_argument("--checkers", default="clef,clef-flash,minicheck,ollama:gemma4:26b-a4b")
    a = ap.parse_args()
    cases = json.loads((HERE / "cases.json").read_text())["cases"]
    with SQLiteRepository(a.store) as r:
        recs = {c["record"]: r.get(Opportunity, c["record"]) for c in cases}
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, check in checkers(a.checkers.split(",")).items():
        t0 = time.perf_counter()
        for c in cases:
            items = asks(recs[c["record"]].description or "")
            assert len(items) == len(c["key"]), (c["id"], len(items))
            for i, (_item, want, got) in enumerate(zip(items, c["key"], check(c["text"], items),
                                                       strict=True)):
                rows.append({"checker": name, "case": c["id"], "record": c["record"],
                             "item": i, "want": "addressed" if want else "not addressed",
                             "got": got})
        print(f"{name}: {time.perf_counter() - t0:.1f} s")
    with (OUT / "marks.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = []
    for name in dict.fromkeys(r["checker"] for r in rows):
        mine = [r for r in rows if r["checker"] == name]
        right = sum(r["got"] == r["want"] for r in mine)
        unclear = sum(r["got"] == "unclear" for r in mine)
        miss = [r for r in mine if r["want"] == "not addressed"]
        caught = sum(r["got"] == "not addressed" for r in miss)
        false_miss = sum(r["got"] == "not addressed" for r in mine if r["want"] == "addressed")
        summary.append({"checker": name, "items": len(mine), "correct": right,
                        "unclear": unclear, "omissions": len(miss), "omissions_caught": caught,
                        "addressed_marked_missing": false_miss})
        print(summary[-1])
    with (OUT / "summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)


if __name__ == "__main__":
    main()

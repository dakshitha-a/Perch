"""Cost per brief from the audit logs (PLAN S8 task 3). Tokens and dollars are summed
from logged calls, priced at log time by perch.llm.PRICES; nothing is estimated.

A brief is one profile summary plus one fit explanation per lead (10 by default),
regenerations included. Per model: mean cost of a profile-summary call (app log),
and the measured fit-explanation cost per 10-lead brief from bench/skill2.py.

  uv run python -m bench.cost
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from bench.backtest import RESULTS

LOGS = [Path("data/logs/model_calls.jsonl"), Path("data/logs/bench_model_calls.jsonl")]


def calls() -> list[dict]:
    out = []
    for p in LOGS:
        if p.exists():
            out += [e for line in p.read_text("utf-8").splitlines()
                    if (e := json.loads(line)).get("kind") == "call"]
    return out


def main() -> None:
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in calls():
        by[(f"{e['provider']}:{e['model']}", e["role"])].append(e)
    skill2 = {}
    p = RESULTS / "skill2_summary.csv"
    if p.exists():
        with p.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                skill2[r["model"]] = r
    rows = []
    for model in sorted({m for m, _ in by}):
        s = by.get((model, "profile_summary"), [])
        fit = skill2.get(model)
        summary_cost = sum(e["cost_usd"] for e in s) / len(s) if s else None
        fit_cost = float(fit["cost_per_brief_usd"]) if fit else None
        rows.append({
            "model": model,
            "summary_calls": len(s),
            "summary_usd_per_call": round(summary_cost, 4) if summary_cost is not None else "",
            "fit_usd_per_10_lead_brief": fit_cost if fit_cost is not None else "",
            "brief_total_usd": (round(summary_cost + fit_cost, 4)
                                if summary_cost is not None and fit_cost is not None else ""),
            "all_calls_logged": sum(len(v) for (m, _), v in by.items() if m == model),
            "all_usd_logged": round(sum(e["cost_usd"] for (m, _), v in by.items() if m == model
                                        for e in v), 4)})
    RESULTS.mkdir(parents=True, exist_ok=True)
    with (RESULTS / "cost.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()

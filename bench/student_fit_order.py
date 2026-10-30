"""Student mode: the ranking model's order against the chat model's fit order (S27).
SYNTHETIC data only: a mechanism check on 3 personas, not a measurement of real use.

Runs each persona through the app as bench/student_mode.py does, then, among the leads
of each route, finds the planted records the answer key marks as ones the student may
apply for, and reports where they land when the leads are ordered by rank (production)
or by fit score (no fit sorts last, ties keep rank).

    uv run python -m bench.student_fit_order --base http://127.0.0.1:8092
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import httpx

from bench.student_mode import PERSONAS, POSITIVE, SYN, run_persona

OUT = Path("bench/results/student_fit_order.json")


def positions(leads: list[dict], key: set[str], by: str) -> list[int]:
    if by == "rank":
        order = sorted(leads, key=lambda x: x["rank"])
    else:
        order = sorted(leads, key=lambda x: (-(x["fit_score"] if x.get("fit_score") is not None
                                               else -1), x["rank"]))
    return [i for i, x in enumerate(order, 1) if x["record_id"] in key]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8092")
    a = ap.parse_args(argv)
    out: dict = {"by_rank": [], "by_fit": [], "personas": {}}
    with httpx.Client(base_url=a.base, timeout=120) as c:
        for name in PERSONAS:
            got = run_persona(c, name, date.today().isoformat())
            cases = json.loads((SYN / name / "answer_key.json").read_text())["cases"]
            key = {x["id"] for x in cases if x["verdict"] in POSITIVE}
            leads = got["brief"]["leads"]
            per = {}
            for route in sorted({x["route"] for x in leads}):
                rl = [x for x in leads
                      if x["route"] == route and x.get("verdict") != "not eligible"]
                r, f = positions(rl, key, "rank"), positions(rl, key, "fit")
                if r:
                    per[route] = {"leads": len(rl), "by_rank": r, "by_fit": f,
                                  "with_fit": sum(x.get("fit_score") is not None for x in rl)}
                    out["by_rank"] += r
                    out["by_fit"] += f
            out["personas"][name] = per
            print(name, json.dumps(per), flush=True)
    for k in ("by_rank", "by_fit"):
        p = out[k]
        out[k + "_summary"] = {"n": len(p), "in_top5": sum(x <= 5 for x in p),
                               "mrr": round(sum(1 / x for x in p) / len(p), 3) if p else None}
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k + "_summary"] for k in ("by_rank", "by_fit")}))


if __name__ == "__main__":
    main()

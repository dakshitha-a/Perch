"""Scout bench (S10): 20 scripted follow-ups per model, scored by the rules in
bench/scout_tasks.yaml.

Each task runs in its own session against the dev store and models.
Tool calls go to data/logs/scout.jsonl and model calls to the usual audit log, so
tokens and cost come from the same records the app writes. Per-task rows go to
bench/results/scout_<model>.csv; `--summary` rebuilds bench/results/scout_summary.csv
from every per-model file.

  CUDA_VISIBLE_DEVICES=3 uv run --extra ml python -m bench.scout ollama:gemma4:26b-a4b
  uv run --extra ml python -m bench.scout ollama:qwen3:8b --policy structured
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import date
from pathlib import Path

import yaml

from bench.backtest import RESULTS, slug
from perch.config import load_dotenv
from perch.scout import ScoutBudget, make_scout
from perch.scout.log import ScoutLog
from perch.scout.loop import Session
from perch.scout.tools import ALLOWLIST

TASKS = Path("bench/scout_tasks.yaml")
FIELDS = ["model", "policy", "task", "kind", "completed", "status", "flagged", "calls",
          "wrong_calls", "tools", "missing", "turns", "tokens", "usd", "seconds", "errors"]


def arg_match(want: object, got: object) -> bool:
    if isinstance(want, list):
        return isinstance(got, list) and all(
            any(str(w).lower() in str(g).lower() for g in got) for w in want)
    if isinstance(want, int | float) and not isinstance(want, bool):
        return isinstance(got, int | float) and float(got) == float(want)
    return isinstance(got, str) and str(want).lower() in got.lower()


def tool_name(c: object) -> str:
    """search_opportunities with route B is the same lookup as get_org_signals."""
    if c.tool == "search_opportunities" and str(c.arguments.get("route", "")).upper() == "B":
        return "get_org_signals"
    return c.tool


def score(task: dict, s: Session) -> dict:
    """Completion, wrong calls and what is missing, for one finished session."""
    allowed = set(task.get("allowed") or [])
    calls = s.cards
    wrong = [c for c in calls if tool_name(c) not in allowed]
    ran = [c for c in calls if c.status == "done"]
    missing = []
    for exp in task.get("expect") or []:
        names = exp["any_of"] if isinstance(exp, dict) else [exp]
        if not any(tool_name(c) in names for c in ran):
            missing.append("/".join(names))
    for tool, want in (task.get("args") or {}).items():
        if not any(c.tool == tool and all(arg_match(v, c.arguments.get(k))
                                          for k, v in want.items()) for c in ran):
            missing.append(f"{tool} arguments {json.dumps(want)}")
    done = s.status == "done" and not s.flagged and bool(s.answer)
    return {"completed": done and not missing and not wrong, "calls": len(calls),
            "wrong_calls": len(wrong), "missing": "; ".join(missing)}


def run(spec: str, policy: str | None, only: list[str], max_usd: float = 1.0,
        tag: str | None = None) -> Path:
    from perch.cli import default_client
    from perch.service import BriefService, Clients, default_models

    load_dotenv()
    plan = yaml.safe_load(TASKS.read_text())
    as_of = date.fromisoformat(str(plan["as_of"]))
    service = BriefService("data/perch.db", default_models(False, Path("data")),
                           Clients(openalex=default_client))
    log = ScoutLog()
    rows = []
    for task in plan["tasks"]:
        if only and task["id"] not in only:
            continue
        spent = sum(r["usd"] for r in rows)
        if spent >= max_usd:
            print(f"stopped: ${spent:.4f} spent, cap ${max_usd:.2f}")
            break
        # Each session may spend what is left under the cap, and at most $0.25.
        scout = make_scout(service, task["researcher"], as_of=as_of, llm=spec,
                           policy=policy, log=log,
                           budget=ScoutBudget(max_usd=min(0.25, max_usd - spent)))
        t0 = time.perf_counter()
        s = scout.start(task["questions"][0])
        for q in task["questions"][1:]:
            s = scout.ask(s, q)
        sc = score(task, s)
        row = {"model": spec, "policy": scout.policy, "task": task["id"], "kind": task["kind"],
               **sc, "status": s.status, "flagged": s.flagged,
               "tools": " ".join(f"{c.tool}:{c.status}" for c in s.cards), "turns": s.turns,
               "tokens": s.tokens, "usd": round(s.usd, 5),
               "seconds": round(time.perf_counter() - t0, 1), "errors": "; ".join(s.errors)}
        rows.append(row)
        print(f"{task['id']} {'PASS' if row['completed'] else 'fail'} {row['tools']} "
              f"{row['missing']} {row['errors'][:120]}", flush=True)
    name = f"scout_{slug(spec)}{'_structured' if policy == 'structured' else ''}.csv"
    # A tagged run (a subset, say) goes to its own folder and stays out of the summary.
    out = RESULTS / f"scout_{tag}" / name if tag else RESULTS / name
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    return out


def summary() -> Path:
    rows = []
    for p in sorted(RESULTS.glob("scout_*.csv")):
        if p.name == "scout_summary.csv":
            continue
        rs = list(csv.DictReader(p.open()))
        if not rs:
            continue
        s10 = [r for r in rs if r["task"][0] in "tr"]  # the 20 S10 tasks
        rb = [r for r in rs if r["task"].startswith("b")]  # Route B tasks, S11
        ch = [r for r in rs if r["task"][0] in "ch"]  # compare and hand-off tasks, S12
        task = [r for r in s10 if r["kind"] == "task"]
        rest = [r for r in s10 if r["kind"] == "restraint"]
        calls = sum(int(r["calls"]) for r in rs)
        wrong = sum(int(r["wrong_calls"]) for r in rs)
        unknown = sum(t.split(":")[0] not in ALLOWLIST
                      for r in rs for t in r["tools"].split())
        yes = lambda xs: sum(r["completed"] == "True" for r in xs)  # noqa: E731
        rows.append({
            "model": rs[0]["model"], "policy": rs[0]["policy"],
            "completed": f"{yes(s10)}/{len(s10)}", "tasks_completed": f"{yes(task)}/{len(task)}",
            "restraint": f"{yes(rest)}/{len(rest)}",
            "route_b_completed": f"{yes(rb)}/{len(rb)}" if rb else "",
            "compare_handoff_completed": f"{yes(ch)}/{len(ch)}" if ch else "",
            "wrong_tool_rate": f"{wrong / calls:.3f}" if calls else "0",
            "wrong_calls": f"{wrong}/{calls}", "outside_allowlist": unknown,
            "flagged": sum(r["flagged"] == "True" for r in rs),
            "tokens": sum(int(r["tokens"]) for r in rs),
            "usd": round(sum(float(r["usd"]) for r in rs), 4),
            "median_s": sorted(float(r["seconds"]) for r in rs)[len(rs) // 2]})
    out = RESULTS / "scout_summary.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec", nargs="?", help="provider spec, e.g. ollama:gemma4:26b-a4b")
    ap.add_argument("--policy", choices=["native", "structured"], default=None)
    ap.add_argument("--only", nargs="*", default=[], help="task ids")
    ap.add_argument("--max-usd", type=float, default=1.0, help="stop the run at this spend")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--tag", default=None, help="write to bench/results/scout_<tag>/")
    a = ap.parse_args()
    if a.spec:
        print("wrote", run(a.spec, a.policy, a.only, a.max_usd, a.tag))
    if a.summary:
        print("wrote", summary())


if __name__ == "__main__":
    main()

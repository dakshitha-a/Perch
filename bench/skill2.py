"""Skill 2 (fit explanation) bench: the same leads explained by each model.

Lead set: the saved demo briefs in data/perch.db (one per PI, 10 leads each), with
the profile rebuilt as of each brief's date. Each model explains every lead through
the production skill (`explain_leads`), validator layers 1 and 2 included, with the
same grounder for every model. Calls go to their own audit log,
data/logs/bench_model_calls.jsonl, so cost and latency come from the same records
the app writes.

Local models run on the bench Ollama instance (GPU 4, port 11435), never the
primary service on GPU 0:

  CUDA_VISIBLE_DEVICES=4 OLLAMA_HOST=127.0.0.1:11435 \\
    OLLAMA_MODELS=/usr/share/ollama/.ollama/models ollama serve
  uv run --extra ml --extra anthropic python -m bench.skill2 ollama:qwen3:8b ...
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from bench.backtest import RESULTS, slug
from perch.config import load_dotenv
from perch.embed import get_embedder
from perch.grounding import Grounder, MiniCheckGrounder
from perch.llm import get_provider
from perch.llm.audit import AuditedProvider, AuditLog
from perch.profile import Profile, build_threads
from perch.schemas import Brief, Lead, Opportunity, Work
from perch.skills.fit import explain_leads
from perch.store.sqlite import SQLiteRepository

DB = Path("data/perch.db")
AUDIT = Path("data/logs/bench_model_calls.jsonl")
BENCH_OLLAMA = "http://127.0.0.1:11435"


@dataclass
class LeadSet:
    brief_id: str
    profile: Profile
    works: dict[str, Work]
    opps: list[Opportunity]


@dataclass
class Row:
    model: str
    brief_id: str
    record_id: str
    attempts: int
    layer1_first_pass: bool
    passed: bool  # explained after at most one regeneration
    unsupported: int  # layer-2 statements below the support threshold
    fit: int | None


def lead_sets(device: str | None = None) -> list[LeadSet]:
    embedder = get_embedder(cache=Path("data/cache/embeddings.db"), device=device)
    out = []
    with SQLiteRepository(DB) as r:
        for b in r.list(Brief):
            if b.status != "done" or not b.lead_ids:
                continue
            works = {w.id: w for w in r.works_by_author(b.researcher_id)}
            p = build_threads(b.researcher_id, list(works.values()), embedder,
                              date.fromisoformat(b.options["as_of"]))
            leads = [x for x in (r.get(Lead, i) for i in b.lead_ids) if x]
            opps = [o for o in (r.get(Opportunity, x.record_id) for x in leads) if o]
            out.append(LeadSet(b.id, p, works, opps))
    return out


def run_model(spec: str, sets: list[LeadSet], grounder: Grounder | None,
              ollama_url: str = BENCH_OLLAMA) -> tuple[list[Row], dict]:
    os.environ["OLLAMA_BASE_URL"] = ollama_url
    log = AuditLog(AUDIT)
    provider = AuditedProvider(get_provider(spec), log, "fit_explainer")
    rows, walls = [], []
    for s in sets:
        t = time.perf_counter()
        res = explain_leads(s.opps, s.profile, s.works, provider, grounder=grounder)
        walls.append(time.perf_counter() - t)
        for o, v in zip(s.opps, res, strict=True):
            rows.append(Row(spec, s.brief_id, o.id, v.attempts, v.attempts == 1 and not v.flagged,
                            not v.flagged, len(v.value.unsupported) if v.value else 0,
                            v.value.fit if v.value else None))
    calls = [e for e in log.events if e.get("kind") == "call"]
    lat = sorted(e["latency_ms"] for e in calls)
    n = len(rows)
    summary = {"model": spec, "leads": n,
               "layer1_first_pass": round(sum(x.layer1_first_pass for x in rows) / n, 3),
               "explained": round(sum(x.passed for x in rows) / n, 3),
               "with_unsupported": round(sum(x.unsupported > 0 for x in rows) / n, 3),
               "calls": len(calls),
               "p50_call_s": round(statistics.median(lat) / 1000, 1) if lat else None,
               "p50_brief_s": round(statistics.median(walls), 1),
               "input_tokens": sum(e["input_tokens"] for e in calls),
               "output_tokens": sum(e["output_tokens"] for e in calls),
               "cost_usd": round(sum(e["cost_usd"] for e in calls), 4),
               "cost_per_brief_usd": round(sum(e["cost_usd"] for e in calls) / len(sets), 4)}
    return rows, summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Skill 2 bench")
    ap.add_argument("specs", nargs="+", help="provider specs, e.g. ollama:qwen3:8b")
    ap.add_argument("--device", help="embedder device")
    ap.add_argument("--no-grounder", action="store_true")
    ap.add_argument("--ollama-url", default=BENCH_OLLAMA)
    a = ap.parse_args(argv)
    load_dotenv()
    sets = lead_sets(a.device)
    grounder = None if a.no_grounder else MiniCheckGrounder(device="cpu")
    RESULTS.mkdir(parents=True, exist_ok=True)
    for spec in a.specs:
        rows, summary = run_model(spec, sets, grounder, a.ollama_url)
        path = RESULTS / f"skill2_{slug(spec)}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, list(Row.__dataclass_fields__))
            w.writeheader()
            w.writerows(asdict(x) for x in rows)
        with (RESULTS / "skill2_summary.csv").open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, list(summary))
            if f.tell() == 0:
                w.writeheader()
            w.writerow(summary)
        print(summary, flush=True)


if __name__ == "__main__":
    main()

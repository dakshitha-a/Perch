"""Does sorting by the chat model's fit score beat the ranking model's order? (S27)

Dakshitha asked for one score and one order. Candidates: the ranking model's order
(production, measured by the back-test) or the chat model's 0-100 fit estimate, written
with each explanation. This bench measures the second on the same NIH back-test rows:

  - Production order for each row, exactly as bench/backtest.py builds it (papers before
    the award start, the pool open in the window, hybrid retrieval, 100 reranked).
  - The top K are explained by the demo's chat model through the production skill
    (validator layer 1; a withheld explanation has no fit and sorts last, as in the app).
  - "fit@K": those K re-sorted by fit (ties keep production order), the rest unchanged.
    K=10 is what a brief shows; K=20 lets the fit choose which 10 appear.

Fits are cached in data/bench/fit_order.json, so a run resumes. The keyword-only
baseline and production are reported beside it.

  OLLAMA_BASE_URL=http://127.0.0.1:11440 uv run --extra ml python -m bench.fit_order --device cuda
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path

from bench.backtest import (
    BENCH_DB,
    PIS,
    WINDOW_MONTHS,
    PoolIndex,
    coverage,
    in_window,
    load_rows,
    slug,
    works_for,
)
from perch.brief import RERANK_IN
from perch.config import env, load_dotenv
from perch.eligibility import Constraints, check
from perch.embed import get_embedder
from perch.llm import get_provider
from perch.llm.audit import AuditedProvider, AuditLog
from perch.profile import build_threads
from perch.rerank import DEFAULT_MODEL, CrossEncoderReranker, RerankCache, rerank
from perch.retrieve import retrieve
from perch.schemas import Opportunity
from perch.skills.fit import explain_leads
from perch.sources.openalex import OpenAlexClient
from perch.store.lance import LanceIndex
from perch.store.sqlite import SQLiteRepository

CACHE = Path("data/bench/fit_order.json")
OUT = Path("bench/results/fit_order.json")
CHAT = "ollama:gemma4:26b-a4b"  # the demo profile's chat model (perch/profiles.py)
K_EXPLAIN = 20


def metrics(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks) or 1
    return {"n": len(ranks), "hit@5": round(sum(bool(r and r <= 5) for r in ranks) / n, 3),
            "hit@10": round(sum(bool(r and r <= 10) for r in ranks) / n, 3),
            "mrr": round(sum(1 / r for r in ranks if r) / n, 3)}


def by_fit(order: list[str], fits: dict[str, int | None], k: int) -> list[str]:
    head = sorted(order[:k], key=lambda i: (-(fits.get(i) if fits.get(i) is not None else -1),
                                            order.index(i)))
    return head + order[k:]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--device")
    ap.add_argument("--strata", nargs="*", default=["targeted"])
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    load_dotenv()
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    rows = [r for r in load_rows(PIS) if r["stratum"] in a.strata]
    embedder = get_embedder("Qwen/Qwen3-Embedding-0.6B", cache=Path("data/cache/embeddings.db"),
                            device=a.device)
    reranker = CrossEncoderReranker(DEFAULT_MODEL, device=a.device)
    rcache = RerankCache(Path("data/bench/cache/rerank.db"))
    log = AuditLog(Path("data/bench/fit_order_calls.jsonl"))
    provider = AuditedProvider(get_provider(CHAT), log, "fit_explainer")
    ranks: dict[str, list[int | None]] = {"production": [], "fit@10": [], "fit@20": []}
    t0 = time.perf_counter()
    with SQLiteRepository(BENCH_DB) as repo, OpenAlexClient(env("OPENALEX_API_KEY")) as oa:
        opps = {o.id: o for o in repo.list(Opportunity)}
        cov = coverage(rows, {o.opportunity_number for o in opps.values()}, WINDOW_MONTHS)
        rows = [r for r in rows if cov[r["alias"] + r["stratum"]] >= 1.0][: a.limit]
        base = LanceIndex(Path("data/bench/lance") / slug(embedder.name))
        for n, r in enumerate(rows, 1):
            start = date.fromisoformat(r["award_start"])
            as_of = start - timedelta(days=1)
            wl = works_for(repo, r["openalex_id"], oa)
            works = {w.id: w for w in wl}
            profile = build_threads(f"https://openalex.org/{r['openalex_id']}", wl, embedder, as_of)
            pool = {i for i, o in opps.items() if in_window(o.open_date, o.close_date, start,
                                                             WINDOW_MONTHS)}
            c = Constraints(as_of=as_of, check_dates=False)
            index = PoolIndex(base, {i for i in pool if not check(opps[i], c)}, len(opps))
            cands = retrieve(profile, index, k=200).candidates
            head, _ = rerank(cands[:RERANK_IN], opps, profile, reranker, rcache, top=RERANK_IN)
            order = [x.opportunity.id for x in head] + [x.record_id for x in cands[RERANK_IN:]]
            key = f"{r['alias']}|{r['stratum']}|{r['opportunity_number']}"
            fits: dict[str, int | None] = cache.get(key, {})
            todo = [i for i in order[:K_EXPLAIN] if i not in fits]
            if todo:
                got = explain_leads([opps[i] for i in todo], profile, works, provider)
                for i, v in zip(todo, got, strict=True):
                    fits[i] = v.value.fit if v.value else None
                cache[key] = fits
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                CACHE.write_text(json.dumps(cache))
            truth = f"grants_gov:{r['opportunity_number']}"
            for name, o in (("production", order), ("fit@10", by_fit(order, fits, 10)),
                            ("fit@20", by_fit(order, fits, 20))):
                ranks[name].append(o.index(truth) + 1 if truth in o else None)
            print(f"{n}/{len(rows)} {r['alias']} truth at {ranks['production'][-1]} -> "
                  f"{ranks['fit@10'][-1]} / {ranks['fit@20'][-1]}; "
                  f"{time.perf_counter() - t0:.0f} s", flush=True)
    res = {name: {**metrics(v), "ranks": v} for name, v in ranks.items()}
    OUT.write_text(json.dumps({"chat": CHAT, "strata": a.strata, **res}, indent=1))
    for name, m in res.items():
        print(f"{name:12s} n={m['n']} hit@5={m['hit@5']} hit@10={m['hit@10']} mrr={m['mrr']}")


if __name__ == "__main__":
    main()

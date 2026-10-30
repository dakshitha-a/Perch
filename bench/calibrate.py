"""Data for turning the ranking model's score into a 0-100 fit score (S27).

The reranker's raw score is a probability squeezed toward 0 and 1, so a good second lead
can read 0.03. Its log-odds, log(p / (1 - p)), are spread evenly. This script collects,
on the NIH back-test rows (same papers, pool and pipeline as bench/backtest.py), the raw
score of every reranked candidate and marks the announcement the award was funded under,
so the 0 and 100 ends and the band cut-offs can be set from where funded announcements
actually score. It also records the live top 10 for the six S27 test PIs on today's
listings, to check the bands on real briefs.

  uv run --extra ml python -m bench.calibrate --device cuda
"""

from __future__ import annotations

import argparse
import json
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
from bench.handcheck import PIS as LIVE_PIS
from perch.brief import RERANK_IN
from perch.config import env, load_dotenv
from perch.eligibility import Constraints, check
from perch.embed import get_embedder
from perch.profile import build_threads
from perch.rerank import DEFAULT_MODEL, CrossEncoderReranker, RerankCache, rerank
from perch.retrieve import retrieve
from perch.schemas import Opportunity
from perch.sources.openalex import OpenAlexClient
from perch.store.lance import LanceIndex
from perch.store.sqlite import SQLiteRepository

OUT = Path("bench/results/calibration.json")


def ranked_scores(profile, index, opps, reranker, cache) -> list[tuple[str, float]]:  # noqa: ANN001
    cands = retrieve(profile, index, k=200).candidates
    head, _ = rerank(cands[:RERANK_IN], opps, profile, reranker, cache, top=RERANK_IN)
    return [(x.opportunity.id, round(x.rerank_score, 6)) for x in head]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--device")
    a = ap.parse_args(argv)
    load_dotenv()
    embedder = get_embedder("Qwen/Qwen3-Embedding-0.6B", cache=Path("data/cache/embeddings.db"),
                            device=a.device)
    reranker = CrossEncoderReranker(DEFAULT_MODEL, device=a.device)
    out: dict = {"backtest": [], "live": {}}
    rows = load_rows(PIS)
    with SQLiteRepository(BENCH_DB) as repo, OpenAlexClient(env("OPENALEX_API_KEY")) as oa:
        opps = {o.id: o for o in repo.list(Opportunity)}
        cov = coverage(rows, {o.opportunity_number for o in opps.values()}, WINDOW_MONTHS)
        rows = [r for r in rows if cov[r["alias"] + r["stratum"]] >= 1.0]
        base = LanceIndex(Path("data/bench/lance") / slug(embedder.name))
        cache = RerankCache(Path("data/bench/cache/rerank.db"))
        for r in rows:
            start = date.fromisoformat(r["award_start"])
            wl = works_for(repo, r["openalex_id"], oa)
            profile = build_threads(f"https://openalex.org/{r['openalex_id']}", wl, embedder,
                                    start - timedelta(days=1))
            pool = {i for i, o in opps.items()
                    if in_window(o.open_date, o.close_date, start, WINDOW_MONTHS)}
            c = Constraints(as_of=start - timedelta(days=1), check_dates=False)
            index = PoolIndex(base, {i for i in pool if not check(opps[i], c)}, len(opps))
            scores = ranked_scores(profile, index, opps, reranker, cache)
            truth = f"grants_gov:{r['opportunity_number']}"
            out["backtest"].append({"alias": r["alias"], "stratum": r["stratum"],
                                    "truth": truth, "scores": scores})
            print(r["alias"], r["stratum"], "truth in head:",
                  any(i == truth for i, _ in scores), flush=True)
    today = date.today()
    with SQLiteRepository(Path("data/perch.db")) as repo:
        opps = {o.id: o for o in repo.list(Opportunity)}
        c = Constraints(as_of=today)
        index = PoolIndex(LanceIndex(Path("data/lance")), {i for i, o in opps.items()
                                                            if not check(o, c)}, len(opps))
        cache = RerankCache(Path("data/cache/rerank.db"))
        for alias, (aid, _, _) in LIVE_PIS.items():
            wl = repo.works_by_author(f"https://openalex.org/{aid}")
            profile = build_threads(f"https://openalex.org/{aid}", wl, embedder, today)
            scores = ranked_scores(profile, index, opps, reranker, cache)[:10]
            out["live"][alias] = [(opps[i].opportunity_number, s) for i, s in scores]
    OUT.write_text(json.dumps(out))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

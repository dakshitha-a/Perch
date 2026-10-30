"""S27 hand check: today's Route A top 10 for the six test PIs, per ranking variant.

Not a back-test: the papers include the funded work and the listings are today's.
It answers one question per PI: does the open program that funded their most recent
award (from NSF Award Search or RePORTER) reach the top 10, and which agencies fill
it? The expected programs come from each PI's public award records:

  PI-130  NSF CHE "Chem Thry, Mdls & Cmptnl Mthds" (2023)  -> 26-519 MPS Chemistry
  PI-131  NSF DMR "Condensed Matter & Mat Theory" and CHE    -> 26-521 MPS Materials, 26-519
  PI-132  NSF PHY "Particle Astrophysics/Underground"        -> 26-523 MPS Physics
  PI-133  NSF PHY "AMO Experiment"                           -> 26-523 MPS Physics
  PI-1, PI-7  NIH (NCI)                                       -> no single program; agency mix

  uv run --extra ml python -m bench.handcheck --device cuda
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

from bench.backtest import PoolIndex
from bench.tune import VARIANTS, order_for
from perch.config import load_dotenv
from perch.eligibility import Constraints, check
from perch.embed import get_embedder
from perch.profile import build_threads
from perch.rerank import DEFAULT_MODEL, CrossEncoderReranker, RerankCache
from perch.retrieve import index_opportunities
from perch.schemas import Opportunity
from perch.store.lance import LanceIndex
from perch.store.sqlite import SQLiteRepository

DB = Path("data/perch.db")
PIS = {  # alias: (OpenAlex id, expected opportunity numbers, tuned or held out)
    "PI-1": ("A5063022331", set(), "tuned"),
    "PI-130": ("A5052363442", {"26-519"}, "tuned"),
    "PI-132": ("A5039097941", {"26-523"}, "tuned"),
    "PI-7": ("A5082223399", set(), "held out"),
    "PI-131": ("A5061558119", {"26-521", "26-519"}, "held out"),
    "PI-133": ("A5074354265", {"26-523"}, "held out"),
}
OUT = Path("bench/results/tune")


def short(o: Opportunity) -> str:
    return (o.parent_agency or o.agency).replace("U.S. ", "")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--device")
    ap.add_argument("--only", nargs="*", default=["R0 production"])
    ap.add_argument("--show", type=int, default=10)
    a = ap.parse_args(argv)
    load_dotenv()
    embedder = get_embedder("Qwen/Qwen3-Embedding-0.6B", cache=Path("data/cache/embeddings.db"),
                            device=a.device)
    reranker = CrossEncoderReranker(DEFAULT_MODEL, device=a.device)
    cache = RerankCache(Path("data/cache/rerank_tune.db"))
    today = date.today()
    out = {}
    with SQLiteRepository(DB) as repo:
        opps = {o.id: o for o in repo.list(Opportunity)}
        c = Constraints(as_of=today)
        base = LanceIndex(Path("data/lance"))
        if base.ids() != set(opps):
            index_opportunities(repo, base, embedder)
        index = PoolIndex(base, {i for i, o in opps.items() if not check(o, c)}, len(opps))
        for alias, (aid, want, group) in PIS.items():
            wl = repo.works_by_author(f"https://openalex.org/{aid}")
            works = {w.id: w for w in wl}
            profile = build_threads(f"https://openalex.org/{aid}", wl, embedder, today)
            for name in a.only:
                order = order_for(VARIANTS[name], profile, works, index, opps, reranker, cache)
                top = [opps[i] for i in order[: a.show]]
                nums = [o.opportunity_number for o in top]
                hit = next((k + 1 for k, n in enumerate(order) if opps[n].opportunity_number
                            in want), None)
                mix = Counter(short(o) for o in top)
                out.setdefault(alias, {})[name] = {"expected_rank": hit, "top": nums,
                                                    "mix": dict(mix)}
                print(f"\n== {alias} ({group}) {name}: expected {sorted(want) or '-'} at "
                      f"rank {hit}; mix {dict(mix)}")
                for k, o in enumerate(top, 1):
                    print(f"  {k:2}. {short(o)[:28]:28s} {o.opportunity_number:16s} {o.title[:70]}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "handcheck_latest.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

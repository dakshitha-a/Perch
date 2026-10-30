"""NIH back-test: does Route A rank the announcement a Temple award was funded under?

For each row of data/backtest/pis.csv:
  - Papers: the PI's OpenAlex works published before the award start (as_of is the
    day before the start), so the profile cannot see the funded work.
  - Pool: NIH announcements on Grants.gov that opened on or before the award start
    and closed no earlier than WINDOW_MONTHS before it (no close date counts as
    open). The deterministic eligibility rules run with date rules off; the window
    replaces them.
  - Ranking: production retrieval (`retrieve`, mode hybrid, dense or bm25) over the
    pool, then rerank of the best RERANK_IN eligible, then the rest in retrieval order.
  - Rank of the true announcement in that list; reciprocal rank 0 when absent.
The keyword-only baseline is mode bm25 with no rerank, run on every row.

A row is scored only when every announcement in its window is in the corpus
(the corpus fetch is long and resumable); rows left out are counted.

  uv run --extra ml python -m bench.backtest --embedder Qwen/Qwen3-Embedding-0.6B
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from bench.corpus import BENCH_DB, HITS, MIN_CLOSE
from perch.brief import RERANK_IN
from perch.config import env, load_dotenv
from perch.eligibility import Constraints, check
from perch.embed import Embedder, get_embedder
from perch.profile import build_threads
from perch.rerank import RerankCache, Reranker, rerank
from perch.retrieve import index_opportunities, retrieve
from perch.schemas import Opportunity, Work
from perch.sources.grants_gov import _date
from perch.sources.openalex import OpenAlexClient
from perch.store.base import VectorIndex
from perch.store.lance import LanceIndex
from perch.store.sqlite import SQLiteRepository

PIS = Path("data/backtest/pis.csv")
RESULTS = Path("bench/results")
WINDOW_MONTHS = 18  # longest targeted gap (start minus close) in the set: 16.2 months
RETRIEVE_K = 200


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class PoolIndex(VectorIndex):
    """Read-only view of an index limited to one row's pool. Asks the full index for
    every row and filters, so dense results equal a per-pool index; BM25 term
    statistics are the full corpus's."""

    def __init__(self, base: VectorIndex, allowed: set[str], size: int) -> None:
        self.base, self.allowed, self.size = base, allowed, size

    def upsert(self, ids: list[str], texts: list[str], vectors: list[list[float]]) -> int:
        raise NotImplementedError("PoolIndex is read-only")

    def dense(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        return [h for h in self.base.dense(vector, self.size) if h[0] in self.allowed][:k]

    def bm25(self, query: str, k: int) -> list[tuple[str, float]]:
        return [h for h in self.base.bm25(query, self.size) if h[0] in self.allowed][:k]

    def ids(self) -> set[str]:
        return self.base.ids() & self.allowed


def in_window(open_d: date | None, close_d: date | None, start: date, months: int) -> bool:
    lo = start - timedelta(days=round(months * 30.44))
    return (open_d is None or open_d <= start) and (close_d is None or close_d >= lo)


@dataclass
class Row:
    alias: str
    stratum: str
    opportunity_number: str
    award_start: str
    config: str
    papers: int
    threads: int
    pool: int
    truth_eligible: bool
    truth_retrieved: bool
    rank: int | None  # 1-based position in the final list; None when absent
    reciprocal_rank: float
    seconds: float


def load_rows(path: Path = PIS) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def coverage(rows: list[dict[str, str]], stored: set[str], months: int) -> dict[str, float]:
    """Share of each row's window (from the Grants.gov hit list) already in the corpus."""
    hits = json.loads(HITS.read_text(encoding="utf-8"))
    hits = [(h["number"], _date(h.get("openDate")), _date(h.get("closeDate"))) for h in hits]
    out = {}
    for r in rows:
        start = date.fromisoformat(r["award_start"])
        want = {n for n, o, c in hits if in_window(o, c, start, months)
                and (c or date.max) >= MIN_CLOSE}
        out[r["alias"] + r["stratum"]] = len(want & stored) / max(len(want), 1)
    return out


def works_for(repo: SQLiteRepository, author_id: str, client: OpenAlexClient) -> list[Work]:
    aid = f"https://openalex.org/{author_id}"
    have = repo.works_by_author(aid)
    if have:
        return have
    works = list(client.iter_works(aid))
    repo.upsert(works)
    return works


def rank_one(r: dict[str, str], works: list[Work], opps: dict[str, Opportunity],
             index: VectorIndex, embedder: Embedder, reranker: Reranker | None,
             cache: RerankCache | None, mode: str, months: int, config: str,
             extra: list[Work] | None = None) -> Row:
    """`extra`: documents added as threads the way private mode adds them (S13 task 8)."""
    t0 = time.perf_counter()
    start = date.fromisoformat(r["award_start"])
    as_of = start - timedelta(days=1)
    truth = f"grants_gov:{r['opportunity_number']}"
    pool = {i for i, o in opps.items() if in_window(o.open_date, o.close_date, start, months)}
    profile = build_threads(f"https://openalex.org/{r['openalex_id']}", works, embedder, as_of)
    if extra:
        from perch.private.threads import add_threads

        profile = add_threads(profile, extra, embedder)
    c = Constraints(as_of=as_of, check_dates=False)
    eligible = {i for i in pool if not check(opps[i], c)}
    ret = retrieve(profile, PoolIndex(index, eligible, len(opps)), k=RETRIEVE_K, mode=mode)
    cands = ret.candidates
    if reranker is not None:
        head, _ = rerank(cands[:RERANK_IN], opps, profile, reranker, cache, top=RERANK_IN)
        order = [x.opportunity.id for x in head] + [x.record_id for x in cands[RERANK_IN:]]
    else:
        order = [x.record_id for x in cands]
    rank = order.index(truth) + 1 if truth in order else None
    return Row(r["alias"], r["stratum"], r["opportunity_number"], r["award_start"], config,
               len(profile.work_ids), len(profile.threads), len(eligible), truth in eligible,
               truth in {x.record_id for x in cands}, rank, 1.0 / rank if rank else 0.0,
               round(time.perf_counter() - t0, 2))


def summarise(rows: list[Row]) -> dict[str, float | int]:
    n = len(rows)
    if not n:
        return {"n": 0}
    return {"n": n,
            "hit@5": round(sum(bool(x.rank and x.rank <= 5) for x in rows) / n, 3),
            "hit@10": round(sum(bool(x.rank and x.rank <= 10) for x in rows) / n, 3),
            "mrr": round(sum(x.reciprocal_rank for x in rows) / n, 3),
            "recall@200": round(sum(x.truth_retrieved for x in rows) / n, 3),
            "truth_eligible": sum(x.truth_eligible for x in rows)}


RERANKERS = ("qwen3-reranker-0.6b", "clef-flash", "clef")


def make_reranker(key: str, device: str | None) -> Reranker:
    from perch.rerank import DEFAULT_MODEL
    from perch.rerank import make_reranker as make

    return make(DEFAULT_MODEL if key == "qwen3-reranker-0.6b" else f"systemone:{key}", device)


def run(embedder_name: str, configs: list[tuple[str, str, str | None]],
        months: int = WINDOW_MONTHS, device: str | None = None, rows_path: Path = PIS,
        strata: tuple[str, ...] = ("targeted", "parent")) -> dict[str, list[Row]]:
    """configs: (label, retrieval mode, reranker key or None). Returns rows per label."""
    load_dotenv()
    rows = [r for r in load_rows(rows_path) if r["stratum"] in strata]
    embedder = get_embedder(embedder_name, cache=Path("data/cache/embeddings.db"), device=device)
    rerankers = {k: make_reranker(k, device) for k in {rr for _, _, rr in configs if rr}}
    cache = RerankCache(Path("data/bench/cache/rerank.db"))
    with SQLiteRepository(BENCH_DB) as repo, OpenAlexClient(env("OPENALEX_API_KEY")) as oa:
        opps = {o.id: o for o in repo.list(Opportunity)}
        cov = coverage(rows, {o.opportunity_number for o in opps.values()}, months)
        ready = [r for r in rows if cov[r["alias"] + r["stratum"]] >= 1.0]
        print(f"{len(ready)} of {len(rows)} rows have a complete window "
              f"({len(opps)} announcements in the corpus)", flush=True)
        index = LanceIndex(Path("data/bench/lance") / slug(embedder.name))
        if index.ids() != set(opps):
            t = time.perf_counter()
            index_opportunities(repo, index, embedder)
            print(f"indexed {len(opps)} in {time.perf_counter() - t:.0f} s", flush=True)
        out: dict[str, list[Row]] = {label: [] for label, _, _ in configs}
        for r in ready:
            works = works_for(repo, r["openalex_id"], oa)
            for label, mode, rr in configs:
                out[label].append(rank_one(r, works, opps, index, embedder,
                                           rerankers[rr] if rr else None, cache, mode, months,
                                           label))
    return out


def write(results: dict[str, list[Row]], name: str) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"backtest_{name}.csv"
    rows = [asdict(x) for v in results.values() for x in v]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(Row.__dataclass_fields__))
        w.writeheader()
        w.writerows(rows)
    return path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="NIH back-test, one embedder")
    ap.add_argument("--embedder", default="Qwen/Qwen3-Embedding-0.6B")
    ap.add_argument("--device")
    ap.add_argument("--months", type=int, default=WINDOW_MONTHS)
    a = ap.parse_args(argv)
    configs = [("keyword-only", "bm25", None), ("hybrid", "hybrid", None),
               ("hybrid+rerank", "hybrid", "qwen3-reranker-0.6b")]
    res = run(a.embedder, configs, a.months, a.device)
    print(write(res, slug(a.embedder)), datetime.now(UTC).isoformat())
    for label, rows in res.items():
        for stratum in ("targeted", "parent"):
            print(label, stratum, summarise([x for x in rows if x.stratum == stratum]))


if __name__ == "__main__":
    main()

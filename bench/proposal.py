"""S13 task 8: does a draft proposal help? Measured with a stand-in.

For each targeted back-test row, the funded project's own RePORTER abstract is added as
a private "proposal" thread (0.6 of the weight, as private mode does) and the row is
ranked again. The funded abstract is much closer to the award than a real draft would
be, so this is an upper bound on what private context can add, not an estimate.
Abstracts are public RePORTER text (`abstract_text`, verified 2026-10-29).

  uv run --extra ml python -m bench.proposal [--device cuda:0]
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from bench.backtest import (
    BENCH_DB,
    PIS,
    RESULTS,
    WINDOW_MONTHS,
    coverage,
    load_rows,
    make_reranker,
    rank_one,
    slug,
    summarise,
    works_for,
    write,
)
from perch.config import env, load_dotenv
from perch.embed import get_embedder
from perch.rerank import RerankCache
from perch.schemas import Opportunity, Work, utcnow
from perch.sources.openalex import OpenAlexClient
from perch.store.lance import LanceIndex
from perch.store.sqlite import SQLiteRepository

URL = "https://api.reporter.nih.gov/v2/projects/search"
CACHE = Path("data/bench/abstracts.json")


def appl_id(row: dict[str, str]) -> int | None:
    m = re.search(r"project-details/(\d+)", row.get("award_record", ""))
    return int(m.group(1)) if m else None


def fetch_abstracts(ids: list[int]) -> dict[str, str]:
    have = json.loads(CACHE.read_text()) if CACHE.is_file() else {}
    todo = [i for i in ids if str(i) not in have]
    for k in range(0, len(todo), 200):  # one request per 200 ids; RePORTER asks 1 per second
        r = httpx.post(URL, json={"criteria": {"appl_ids": todo[k:k + 200]},
                                  "include_fields": ["ApplId", "AbstractText"], "limit": 500},
                       timeout=60)
        r.raise_for_status()
        have.update({str(x["appl_id"]): x.get("abstract_text") or "" for x in r.json()["results"]})
        time.sleep(1)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(have))
    return have


def stand_in(text: str, row: dict[str, str]) -> Work:
    text = re.sub(r"^\W*DESCRIPTION \(provided by applicant\):\s*", "", text.strip())
    return Work(id="private:proposal", source="nih_reporter", source_url=row["award_record"],
                fetched_at=utcnow(), title="Funded abstract (stand-in proposal)", abstract=text)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--device")
    a = ap.parse_args(argv)
    load_dotenv()
    rows = [r for r in load_rows(PIS) if r["stratum"] == "targeted"]
    embedder = get_embedder("Qwen/Qwen3-Embedding-0.6B", cache=Path("data/cache/embeddings.db"),
                            device=a.device)
    reranker = make_reranker("qwen3-reranker-0.6b", a.device)
    cache = RerankCache(Path("data/bench/cache/rerank.db"))
    configs = [("keyword-only", "bm25", False), ("hybrid+rerank", "hybrid", True)]
    out: dict[str, list] = {f"{c}{s}": [] for c, _, _ in configs for s in ("", "+abstract")}
    with SQLiteRepository(BENCH_DB) as repo, OpenAlexClient(env("OPENALEX_API_KEY")) as oa:
        opps = {o.id: o for o in repo.list(Opportunity)}
        cov = coverage(rows, {o.opportunity_number for o in opps.values()}, WINDOW_MONTHS)
        ready = [r for r in rows if cov[r["alias"] + r["stratum"]] >= 1.0]
        abstracts = fetch_abstracts([i for r in ready if (i := appl_id(r))])
        index = LanceIndex(Path("data/bench/lance") / slug(embedder.name))
        missing = 0
        for r in ready:
            works = works_for(repo, r["openalex_id"], oa)
            text = abstracts.get(str(appl_id(r)), "")
            missing += not text
            for label, mode, rr in configs:
                args = (r, works, opps, index, embedder, reranker if rr else None, cache, mode,
                        WINDOW_MONTHS)
                out[label].append(rank_one(*args, label))
                extra = [stand_in(text, r)] if text else None
                out[label + "+abstract"].append(rank_one(*args, label + "+abstract", extra))
    print(f"{len(ready)} rows, {missing} without an abstract", flush=True)
    print(write(out, "proposal_standin"), datetime.now(UTC).isoformat())
    lines = []
    for label, rs in out.items():
        lines.append(f"{label}: {summarise(rs)}")
        print(lines[-1])
    (RESULTS / "proposal_standin.txt").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

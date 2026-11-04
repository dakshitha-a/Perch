"""Paired bootstrap 95% interval on the MRR difference between two back-test CSVs
(same awards, matched on alias and opportunity number). Seeded, 2000 draws, as bench/run.py.
Usage: python -m bench.paired_mrr A.csv B.csv [stratum ...]   (reports A minus B)"""
from __future__ import annotations

import csv
import random
import sys


def load(path: str, stratum: str | None) -> dict[tuple[str, str], tuple[float, bool]]:
    with open(path, newline="", encoding="utf-8") as f:
        return {(r["alias"], r["opportunity_number"]): (float(r["reciprocal_rank"]),
                bool(r["rank"]) and int(r["rank"]) <= 10)
                for r in csv.DictReader(f) if stratum in (None, r["stratum"])}


def paired(a: str, b: str, stratum: str | None, draws: int = 2000) -> str:
    x, y = load(a, stratum), load(b, stratum)
    keys = sorted(set(x) & set(y))
    d = [x[k][0] - y[k][0] for k in keys]
    rng = random.Random(0)
    m = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(draws))
    plus = sum(x[k][1] and not y[k][1] for k in keys)
    minus = sum(y[k][1] and not x[k][1] for k in keys)
    return (f"{stratum or 'all'} n={len(keys)} MRR diff {sum(d) / len(d):+.3f} "
            f"95% [{m[int(draws * .025)]:+.3f}, {m[int(draws * .975) - 1]:+.3f}] "
            f"hit@10 +{plus}/-{minus}")


if __name__ == "__main__":
    for s in (sys.argv[3:] or [None]):
        print(paired(sys.argv[1], sys.argv[2], s))

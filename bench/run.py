"""`make bench`: the back-test config matrix, then one results table.

Changes one block at a time against the default (Qwen3-Embedding-0.6B, hybrid
retrieval, Qwen3-Reranker-0.6B). The keyword-only baseline (BM25 on the thread
terms, no dense, no rerank, threads from the default embedder) is computed once and
shown beside every row. Results: bench/results/backtest_matrix.csv (one line per
award and config) and bench/results/RESULTS.md (the table, plus the skill-2,
validator layer-2 and single-card tables when their CSVs exist).

  uv run --extra ml python -m bench.run [--render-only] [--device cuda]
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import UTC, datetime

from bench.backtest import RESULTS, Row, run, summarise

DEFAULT_EMBEDDER = "Qwen/Qwen3-Embedding-0.6B"
BASELINE = "keyword-only"
# (embedder, label, retrieval mode, reranker); the first block is the default embedder.
MATRIX: list[tuple[str, str, str, str | None]] = [
    (DEFAULT_EMBEDDER, BASELINE, "bm25", None),
    (DEFAULT_EMBEDDER, "dense", "dense", None),
    (DEFAULT_EMBEDDER, "hybrid", "hybrid", None),
    (DEFAULT_EMBEDDER, "hybrid + Qwen3-Reranker-0.6B (default)", "hybrid", "qwen3-reranker-0.6b"),
    (DEFAULT_EMBEDDER, "hybrid + Clef-flash rerank", "hybrid", "clef-flash"),
    (DEFAULT_EMBEDDER, "hybrid + Clef rerank", "hybrid", "clef"),
    *[(e, label, mode, rr) for e in ("Qwen/Qwen3-Embedding-4B", "BAAI/bge-m3",
                                     "allenai/specter2_base")
      for label, mode, rr in (("dense", "dense", None), ("hybrid", "hybrid", None),
                              ("hybrid + Qwen3-Reranker-0.6B", "hybrid",
                               "qwen3-reranker-0.6b"))],
]
MATRIX_CSV = RESULTS / "backtest_matrix.csv"
REPORT = RESULTS / "RESULTS.md"
STRATA = ("targeted", "parent")


def run_matrix(device: str | None) -> None:
    out: list[dict] = []
    for emb in dict.fromkeys(e for e, *_ in MATRIX):
        configs = [(label, mode, rr) for e, label, mode, rr in MATRIX if e == emb]
        res = run(emb, configs, device=device)
        for rows in res.values():
            out += [{**asdict(x), "embedder": emb} for x in rows]
        print(f"{emb}: done {datetime.now(UTC).isoformat()}", flush=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    with MATRIX_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["embedder", *Row.__dataclass_fields__])
        w.writeheader()
        w.writerows(out)


def load_matrix() -> dict[tuple[str, str], list[Row]]:
    by: dict[tuple[str, str], list[Row]] = {}
    with MATRIX_CSV.open(newline="", encoding="utf-8") as f:
        for d in csv.DictReader(f):
            emb = d.pop("embedder")
            rank = int(d["rank"]) if d["rank"] else None
            row = Row(d["alias"], d["stratum"], d["opportunity_number"], d["award_start"],
                      d["config"], int(d["papers"]), int(d["threads"]), int(d["pool"]),
                      d["truth_eligible"] == "True", d["truth_retrieved"] == "True", rank,
                      float(d["reciprocal_rank"]), float(d["seconds"]))
            by.setdefault((emb, d["config"]), []).append(row)
    return by


def table(rows: list[dict], cols: list[str]) -> list[str]:
    return ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols),
            *("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows)]


def short(name: str) -> str:
    return name.split("/")[-1]


def render() -> str:
    lines = ["# Bench results", "",
             f"Rendered {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by `make bench`. "
             "Numbers are copied from the CSVs in this folder; nothing here is estimated.", ""]
    if MATRIX_CSV.exists():
        m = load_matrix()
        base = {s: summarise([x for x in m.get((DEFAULT_EMBEDDER, BASELINE), [])
                              if x.stratum == s]) for s in STRATA}
        lines += ["## Back-test (NIH, Temple, date cut-off)", "",
                  "Papers before the award start; pool: NIH announcements on Grants.gov open in "
                  "the 18 months before it; rank of the announcement the award was funded under. "
                  "Baseline: keyword-only (BM25 on thread terms, no dense, no rerank).", ""]
        for s in STRATA:
            rows = []
            for (emb, label), xs in m.items():
                r = summarise([x for x in xs if x.stratum == s])
                b = base[s]
                rows.append({"embedder": short(emb), "config": label, "n": r["n"],
                             "hit@5": r.get("hit@5"), "hit@10": r.get("hit@10"),
                             "MRR": r.get("mrr"), "recall@200": r.get("recall@200"),
                             "baseline hit@5 / hit@10 / MRR":
                                 f"{b.get('hit@5')} / {b.get('hit@10')} / {b.get('mrr')}"})
            lines += [f"### {s.capitalize()} announcements", "",
                      *table(rows, list(rows[0]) if rows else []), ""]
    for name, title in (("skill2_summary.csv", "Fit explanation (skill 2)"),
                        ("grounders.csv", "Validator layer 2 (swapped-record proxy set)"),
                        ("single_card.csv", "Single-card validation")):
        p = RESULTS / name
        if p.exists():
            with p.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            lines += [f"## {title}", "", *table(rows, list(rows[0]) if rows else []), ""]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="make bench")
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--device")
    a = ap.parse_args(argv)
    if not a.render_only:
        run_matrix(a.device)
    REPORT.write_text(render(), encoding="utf-8")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()

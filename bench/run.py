"""`make bench`: the back-test config matrix, then one results table.

Changes one block at a time against the default (Qwen3-Embedding-0.6B, hybrid
retrieval, Qwen3-Reranker-0.6B). The keyword-only baseline (BM25 on the thread
terms, no dense, no rerank, threads from the default embedder) is computed once and
shown beside every row. Results: bench/results/backtest_matrix.csv (one line per
award and config) and bench/results/RESULTS.md (the table, a paired comparison of
each config against the default on the same awards, plus the skill-2, validator
layer-2, cost and single-card tables when their CSVs exist), and SUMMARY.md, the
short version shown on the tracker's Bench tab.

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


def both_layers(model: str) -> str:
    """Leads explained with no unsupported statement, from the per-lead skill-2 CSV."""
    from bench.backtest import slug

    p = RESULTS / f"skill2_{slug(model)}.csv"
    if not p.exists():
        return ""
    with p.open(newline="", encoding="utf-8") as f:
        r = list(csv.DictReader(f))
    n = sum(x["passed"] == "True" and x["unsupported"] == "0" for x in r)
    return f"{n} of {len(r)}"


def short(name: str) -> str:
    return name.split("/")[-1]


DEFAULT_CONFIG = "hybrid + Qwen3-Reranker-0.6B (default)"


def paired(m: dict[tuple[str, str], list[Row]], stratum: str, draws: int = 2000) -> list[dict]:
    """Each config against the default on the same awards: hit@10 count, awards it gets
    into the top 10 that the default misses (+) and the reverse (-), a seeded bootstrap
    95% interval for the MRR difference, and the p50 seconds per award."""
    import random

    def key(x: Row) -> tuple[str, str]:
        return (x.alias, x.opportunity_number)

    base = {key(x): x for x in m.get((DEFAULT_EMBEDDER, DEFAULT_CONFIG), [])
            if x.stratum == stratum}
    out = []
    for (emb, label), xs in m.items():
        pairs = [(x, base[key(x)]) for x in xs if x.stratum == stratum and key(x) in base]
        if not pairs:
            continue
        top = [(x.rank is not None and x.rank <= 10, b.rank is not None and b.rank <= 10)
               for x, b in pairs]
        diffs = [x.reciprocal_rank - b.reciprocal_rank for x, b in pairs]
        rng = random.Random(0)
        means = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(draws))
        secs = sorted(x.seconds for x, _ in pairs)
        out.append({"embedder": short(emb), "config": label, "n": len(pairs),
                    "hit@10 count": sum(a for a, _ in top),
                    "default hit@10 count": sum(b for _, b in top),
                    "+ / -": f"+{sum(a and not b for a, b in top)} / "
                             f"-{sum(b and not a for a, b in top)}",
                    "MRR difference, 95% interval":
                        f"[{means[int(draws * .025)]:.3f}, {means[int(draws * .975) - 1]:.3f}]",
                    "p50 s per award": secs[len(secs) // 2]})
    return out


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
        rows = paired(m, "targeted")
        if rows:
            lines += ["### Against the default, same awards (targeted)", "",
                      "An interval that contains 0 means the back-test cannot tell the config "
                      "from the default.", "", *table(rows, list(rows[0])), ""]
    for name, title in (("skill2_summary.csv", "Fit explanation (skill 2)"),
                        ("grounders.csv", "Validator layer 2 (swapped-record proxy set)"),
                        ("cost.csv", "Cost per brief (audit log)"),
                        ("single_card.csv", "Single-card validation")):
        p = RESULTS / name
        if p.exists():
            with p.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if name == "skill2_summary.csv":
                rows = [{"model": r["model"], "passed_both_layers": both_layers(r["model"]),
                         **{k: v for k, v in r.items() if k != "model"}} for r in rows]
            lines += [f"## {title}", "", *table(rows, list(rows[0]) if rows else []), ""]
    return "\n".join(lines) + "\n"


SUMMARY = RESULTS / "SUMMARY.md"


def read_csv(name: str) -> list[dict]:
    p = RESULTS / name
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def summary() -> str:
    """The short version of RESULTS.md for the tracker's Bench tab. Every number is
    copied from the CSVs in bench/results/."""
    lines = ["# Bench results, summary", "",
             f"Rendered {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by `make bench` from "
             "the CSVs in `bench/results/`. Full tables: `bench/results/RESULTS.md`.", ""]
    if MATRIX_CSV.exists():
        m = load_matrix()
        pt = {(r["embedder"], r["config"]): r for r in paired(m, "targeted")}
        pp = {(r["embedder"], r["config"]): r for r in paired(m, "parent")}
        rows = []
        for (emb, label), xs in m.items():
            t = summarise([x for x in xs if x.stratum == "targeted"])
            a, b = pt.get((short(emb), label), {}), pp.get((short(emb), label), {})
            rows.append({"Embedder": short(emb), "Setup": label,
                         "Targeted in top 10": f"{a.get('hit@10 count')} of {a.get('n')}",
                         "hit@5": t.get("hit@5"), "hit@10": t.get("hit@10"), "MRR": t.get("mrr"),
                         "MRR against default, 95% interval": a.get("MRR difference, 95% interval"),
                         "Parent in top 10": f"{b.get('hit@10 count')} of {b.get('n')}",
                         "Seconds per award": a.get("p50 s per award")})
        tied = [r for r in pt.values() if r["config"] != DEFAULT_CONFIG
                and float(r["MRR difference, 95% interval"].strip("[]").split(",")[0]) < 0
                < float(r["MRR difference, 95% interval"].strip("[]").split(",")[1])]
        n = next(iter(pt.values()))["n"] if pt else 0
        lines += ["## Back-test (NIH, Temple, date cut-off)", "",
                  "Rank of the announcement each award was funded under, from papers before the "
                  "award start. Keyword-only is the baseline. Seconds are the median per award "
                  "on the targeted rows.", "", *table(rows, list(rows[0])), "",
                  f"- **Too close to call:** {len(tied)} of {len(pt) - 1} setups have an MRR "
                  f"interval that contains 0, so {n} targeted awards cannot tell them from the "
                  "default.",
                  "- **Measurably different:** "
                  + "; ".join(f"{r['embedder']} {r['config']}, {r['hit@10 count']} of {r['n']} "
                              f"in the top 10, interval {r['MRR difference, 95% interval']}"
                              for r in pt.values()
                              if r["config"] != DEFAULT_CONFIG and r not in tied)
                  + ". A negative interval means worse than the default.",
                  "- **Parent announcements:** these are general calls, and almost none rank "
                  "in the top 10 under any setup.", ""]
    s2 = read_csv("skill2_summary.csv")
    cost = {r["model"]: r for r in read_csv("cost.csv")}
    if s2:
        rows = [{"Model": r["model"], "Passed both checks": both_layers(r["model"]),
                 "p50 brief s": r["p50_brief_s"],
                 "Cost per brief, USD": cost.get(r["model"], {}).get("brief_total_usd")
                 or r["cost_per_brief_usd"]} for r in s2]
        rows.sort(key=lambda r: -int(r["Passed both checks"].split()[0] or 0))
        lines += ["## Fit explanations (skill 2)", "",
                  "Passed both checks: the citation validator passed and the grounding check "
                  "found no unsupported sentence. Cost covers the summary and 10 explanations "
                  "where both were logged, otherwise the explanations only.", "",
                  *table(rows, list(rows[0])), ""]
    g = read_csv("grounders.csv")
    if g:
        rows = [{"Grounder": r["grounder"], "Pairs": r["pairs"], "AUC": r["auc"] or "not benched",
                 "False flags": r["false_flag_rate"], "Misses": r["miss_rate"],
                 "Seconds per sentence": r["s_per_claim"], "Note": r["note"]} for r in g]
        lines += ["## Grounding check (validator layer 2)", "",
                  "Supported sentences against the same sentences with a swapped record. AUC "
                  "is how well the score separates the two; 1.0 is perfect. Rates are at the "
                  "0.5 threshold.", "", *table(rows, list(rows[0])), ""]
    sc = read_csv("single_card.csv")
    if sc:
        rows = [{"Model": r["model"], "Grounder": r.get("grounder", "minicheck"),
                 "Briefs at once": r["briefs"], "Before briefs MiB": r["all_loaded_mib"],
                 "Peak MiB": r["peak_mib"], "p50 brief s": r["p50_brief_s"],
                 "Explained": r["explained"], "QA and Scout gates": "not measured"} for r in sc]
        rows.sort(key=lambda r: (r["Grounder"], int(r["Peak MiB"])))
        lines += ["## One card, briefs at once", "",
                  "Chat model, Clef-flash, embedder and reranker on one clean GPU. The gate is "
                  "a peak under 28 GB. MiniCheck rows also load MiniCheck on the GPU, which "
                  "deploy-1gpu does not; the Clef-flash rows match deploy-1gpu.", "",
                  *table(rows, list(rows[0])), ""]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="make bench")
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--device")
    a = ap.parse_args(argv)
    if not a.render_only:
        run_matrix(a.device)
    REPORT.write_text(render(), encoding="utf-8")
    SUMMARY.write_text(summary(), encoding="utf-8")
    print(f"wrote {REPORT} and {SUMMARY}")


if __name__ == "__main__":
    main()

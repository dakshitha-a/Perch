"""Hand-check of the Temple awards dataset (REBUILD_PLAN Phase 4 task 8).

Draw a seeded random 10% of the dataset's records. For each one, print every checked field
with its kept value, the sentence the record quotes for it, and the matching sentence on the
cached page, and write a review sheet with one row per record and field. A reviewer opens
the page where needed and fills `verdict` with one of:

  correct   the kept value matches the page, or the field is empty and the page states none
  wrong     the kept value does not match the page
  missing   the field is empty (or incomplete) but the page states it

Score the filled sheet with `--score`: error rate per field and overall (wrong plus missing
over reviewed), each with a 95% Wilson interval. The reviewing itself is done by a person.

  uv run python -m bench.handcheck_temple --dataset data/temple/dataset/temple_awards_v1.jsonl
  uv run python -m bench.handcheck_temple --score bench/results/s40_handcheck/sheet.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from pathlib import Path

from perch import temple_extract as te
from perch.feeds import DatasetImporter
from perch.schemas import Opportunity, Scholarship
from perch.sources.temple_pages import CACHE_DIR, load_cached

OUT_DIR = Path("bench/results/s40_handcheck")
FIELDS = ("title", "amount", "deadline", "apply_url", "eligibility", "temple_funded",
          "audience_level")
QUOTE_KEY = {"amount": "amount", "deadline": "deadline_text", "apply_url": "apply_url",
             "eligibility": "eligibility", "temple_funded": "temple_funded",
             "audience_level": "audience_level"}
COLUMNS = ["record_id", "kind", "field", "page_url", "kept_value", "quoted_sentence",
           "page_sentence", "verdict", "note"]
VERDICTS = ("correct", "wrong", "missing")


def draw(records: list, fraction: float = 0.1, seed: int = 1) -> list:
    """A seeded random sample, at least one record, in id order."""
    recs = sorted(records, key=lambda r: r.id)
    if not recs:
        return []
    k = min(len(recs), max(1, math.ceil(fraction * len(recs))))
    return sorted(random.Random(seed).sample(recs, k), key=lambda r: r.id)


def _kept(r: Scholarship | Opportunity, field: str) -> str:
    sch = isinstance(r, Scholarship)
    if field == "title":
        return r.name if sch else r.title
    if field == "amount":
        lo, hi = (r.amount_min, r.amount_max) if sch else (r.award_floor, r.award_ceiling)
        return "" if lo is None and hi is None else f"min {lo} max {hi}"
    if field == "deadline":
        d = r.deadline if sch else r.close_date
        text = r.field_quotes.get("deadline_text", "")
        return f"{d.isoformat()} ({text})" if d else (f"text only: {text}" if text else "")
    if field == "apply_url":
        return r.apply_url or ""
    if field == "eligibility":
        return (r.eligibility.notes if sch else r.eligibility_notes) or ""
    if field == "temple_funded":
        return "" if r.temple_funded is None else str(r.temple_funded)
    return r.audience_level or ""


class Pages:
    """Cleaned cached pages by URL, split into sentences the way the extraction saw them."""

    def __init__(self, cache_dir: Path) -> None:
        self.html: dict[str, str] = {}
        for meta, h in load_cached(cache_dir):
            for u in {meta["url"], meta.get("final_url") or meta["url"]}:
                self.html[u] = h
        self._s: dict[str, list[str]] = {}

    def sentences(self, url: str) -> list[str]:
        if url not in self._s:
            self._s[url] = te.page_sentences(self.html[url], url) if url in self.html else []
        return self._s[url]

    def match(self, url: str, *needles: str) -> str:
        """The first page sentence that contains a needle (whitespace and quotes normalised)."""
        for n in needles:
            nn = te.norm(n)
            if len(nn) < 3:
                continue
            for s in self.sentences(url):
                if nn in te.norm(s):
                    return s
        return ""


def rows_for(r: Scholarship | Opportunity, pages: Pages) -> list[dict]:
    out = []
    for f in FIELDS:
        kept = _kept(r, f)
        url = r.source_url
        if f in ("amount", "deadline", "apply_url", "eligibility", "temple_funded",
                 "audience_level"):
            url = r.field_sources.get(f, r.source_url)
        quote = "" if f == "title" else r.field_quotes.get(QUOTE_KEY[f], "")
        needles = [kept] if f == "title" else [quote.split(" | ")[0], quote]
        if f == "apply_url" and kept:
            needles = [kept]
        out.append({"record_id": r.id, "kind": r.kind, "field": f, "page_url": url,
                    "kept_value": kept, "quoted_sentence": quote,
                    "page_sentence": pages.match(url, *needles) if kept or quote else "",
                    "verdict": "", "note": ""})
    return out


def make_sheet(dataset: Path, cache_dir: Path, out_dir: Path, fraction: float, seed: int
               ) -> tuple[Path, int, int]:
    recs = DatasetImporter(dataset).read()
    sample = draw(recs, fraction, seed)
    pages = Pages(cache_dir)
    rows = []
    for r in sample:
        rs = rows_for(r, pages)
        rows += rs
        print(f"\n== {r.id}  ({r.kind}, seen on {len(r.seen_on)} page(s))")
        for row in rs:
            print(f"  [{row['field']}] kept: {row['kept_value'] or '-'}")
            if row["quoted_sentence"]:
                print(f"      quoted: {row['quoted_sentence']}")
            if row["page_sentence"]:
                print(f"      page:   {row['page_sentence']}")
        print(f"  page: {r.source_url}")
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = out_dir / "sheet.csv"
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return sheet, len(sample), len(recs)


def wilson(errors: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = errors / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def score(sheet: Path) -> tuple[list[str], dict]:
    """Error rate per field and overall from a filled sheet. Blank verdicts are not counted."""
    per: dict[str, dict[str, int]] = {f: {"n": 0, "wrong": 0, "missing": 0} for f in FIELDS}
    blank = 0
    with sheet.open(newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=2):
            v = (row.get("verdict") or "").strip().lower()
            if not v:
                blank += 1
                continue
            if v not in VERDICTS:
                raise ValueError(f"row {i}: verdict {v!r} is not correct, wrong or missing")
            if row["field"] not in per:
                raise ValueError(f"row {i}: unknown field {row['field']!r}")
            c = per[row["field"]]
            c["n"] += 1
            if v != "correct":
                c[v] += 1
    lines = [f"Unreviewed rows: {blank}"]
    tot = {"n": 0, "errors": 0}
    summary: dict = {"unreviewed": blank, "fields": {}}
    for f, c in per.items():
        e = c["wrong"] + c["missing"]
        lo, hi = wilson(e, c["n"])
        tot["n"] += c["n"]
        tot["errors"] += e
        summary["fields"][f] = {**c, "errors": e, "rate": e / c["n"] if c["n"] else None,
                                "ci95": [lo, hi]}
        rate = f"{e / c['n']:.1%}" if c["n"] else "n/a"
        lines.append(f"{f:15s} reviewed {c['n']:3d}  wrong {c['wrong']:3d}  missing "
                     f"{c['missing']:3d}  error {rate:>6s}  95% CI {lo:.1%} to {hi:.1%}")
    lo, hi = wilson(tot["errors"], tot["n"])
    rate = f"{tot['errors'] / tot['n']:.1%}" if tot["n"] else "n/a"
    lines.append(f"{'overall':15s} reviewed {tot['n']:3d}  errors {tot['errors']:3d}  "
                 f"error {rate:>6s}  95% CI {lo:.1%} to {hi:.1%}")
    summary["overall"] = {"n": tot["n"], "errors": tot["errors"], "ci95": [lo, hi],
                          "rate": tot["errors"] / tot["n"] if tot["n"] else None}
    lines.append("Rows are fields of records, so they are not independent; the interval "
                 "treats them as if they were. Report the record count too.")
    return lines, summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--dataset", help="a temple_awards_v<N>.jsonl file")
    p.add_argument("--cache-dir", default=str(CACHE_DIR))
    p.add_argument("--out-dir", default=str(OUT_DIR))
    p.add_argument("--fraction", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--score", metavar="SHEET", help="score a filled review sheet")
    a = p.parse_args(argv)
    if a.score:
        try:
            lines, _ = score(Path(a.score))
        except (ValueError, OSError) as e:
            print(f"score stopped: {e}", file=sys.stderr)
            return 1
        print("\n".join(lines))
        return 0
    if not a.dataset:
        p.error("--dataset is required unless --score is given")
    sheet, n, total = make_sheet(Path(a.dataset), Path(a.cache_dir), Path(a.out_dir),
                                 a.fraction, a.seed)
    print(f"\nDrew {n} of {total} records (seed {a.seed}). Review sheet: {sheet}. "
          "Fill the verdict column, then run with --score.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Derive Temple's past STTR partners from SBIR.gov's bulk award file (S12 task 7, Q19).

  uv run python scripts/sbir_temple.py [data/cache/sbir/award_data.csv]

Reads the file from https://data.www.sbir.gov/awarddatapublic/award_data.csv (saved under
data/cache/sbir/, gitignored) and writes data/sbir/temple_sttr_partners.csv: awards whose
research-institution column ("RI Name") names Temple University. Only the columns in KEEP
are taken, by name; the contact columns (company, PI and research-institution contacts)
are never read into the output or printed.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

SOURCE_URL = "https://data.www.sbir.gov/awarddatapublic/award_data.csv"
OUT = Path("data/sbir/temple_sttr_partners.csv")
KEEP = {  # bulk-file column -> derived column
    "Company": "company",
    "Award Title": "title",
    "Agency": "agency",
    "Branch": "branch",
    "Phase": "phase",
    "Program": "program",
    "Agency Tracking Number": "tracking_number",
    "Contract": "contract",
    "Proposal Award Date": "award_date",
    "Award Year": "award_year",
}
RI = "RI Name"


def is_temple(ri: str) -> bool:
    return "temple univ" in ri.lower()


def derive(src: Path) -> list[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    rows = []
    with src.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: header.index(name) for name in [*KEEP, RI]}
        for rec in reader:
            if len(rec) <= idx[RI] or not is_temple(rec[idx[RI]]):
                continue
            row = {KEEP[k]: rec[i].strip() for k, i in idx.items() if k in KEEP}
            row["research_institution"] = rec[idx[RI]].strip()
            rows.append(row)
    rows.sort(key=lambda r: (r["award_date"], r["company"], r["title"]))
    return rows


def main(argv: list[str]) -> int:
    src = Path(argv[0]) if argv else Path("data/cache/sbir/award_data.csv")
    rows = derive(src)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, [*KEEP.values(), "research_institution"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT}: {len(rows)} awards, {len({r['company'] for r in rows})} companies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

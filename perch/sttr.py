"""Temple's past STTR partners (S12 task 7, Q19): companies that named Temple University as
their research institution on an STTR award, from SBIR.gov's bulk award file.

`scripts/sbir_temple.py` derives data/sbir/temple_sttr_partners.csv from the bulk file.
Here each row becomes an Award record, and `matching()` keeps the awards whose title
shares words with one of the researcher's main topics. The rule is deterministic and
simple: a topic's content words (generic words such as "research" or "treatment"
removed) are cut to a six-letter stem; an award matches when its title holds two of
them, or the topic's only one.
"""

from __future__ import annotations

import csv
import re
from datetime import UTC, date, datetime
from pathlib import Path

from perch.schemas import Award

TABLE = Path(__file__).resolve().parent.parent / "data/sbir/temple_sttr_partners.csv"
SOURCE = "sbir_gov_bulk"
SOURCE_URL = "https://data.www.sbir.gov/awarddatapublic/award_data.csv"
FETCHED = datetime(2026, 10, 29, tzinfo=UTC)  # the day the bulk file was downloaded (Q19)
GENERIC = set("""research studies study treatment treatments therapy therapies mechanisms
mechanism function functions structure advanced techniques technique analysis methods
applications application related novel development systems system effects health clinical
disease diseases model models based molecular general various""".split())


def stems(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {w[:6] for w in words if len(w) >= 3 and w not in GENERIC
            and w not in {"and", "the", "for", "with", "from", "into"}}


def load(path: Path = TABLE) -> list[Award]:
    if not path.exists():
        return []
    out = []
    with path.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f)):
            number = row["contract"] or row["tracking_number"] or f"row{i}"
            try:
                start = datetime.strptime(row["award_date"], "%m/%d/%Y").date()
            except ValueError:
                start = None
            out.append(Award(
                id=f"{SOURCE}:{number}", source=SOURCE, source_url=SOURCE_URL,
                fetched_at=FETCHED, agency=row["agency"], award_number=number,
                title=row["title"], institution=row["company"], start_date=start,
                fiscal_year=int(row["award_year"]) if row["award_year"].isdigit() else None,
                activity_code=f"{row['program']} {row['phase']}".strip()))
    return out


def matching(awards: list[Award], topics: dict[str, tuple[str, float]]) -> list[Award]:
    """Awards whose title matches one of the topics (see the module docstring)."""
    want = [s for name, _ in topics.values() if (s := stems(name))]
    out = []
    for a in awards:
        if not a.title or a.title.upper() == "N/A":
            continue
        t = stems(a.title)
        if any(len(t & s) >= min(2, len(s)) for s in want):
            out.append(a)
    return out


def before(awards: list[Award], as_of: date) -> list[Award]:
    return [a for a in awards if a.start_date is None or a.start_date <= as_of]

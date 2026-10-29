"""Build the back-test set, data/backtest/pis.csv, from public NIH RePORTER records.

Rules (Q7, Dakshitha, 2026-10-29), applied in order and counted:
  1. Temple NIH records from FY 2015 on, grouped by core project; the first fiscal
     year of each project is the award.
  2. Research project activity codes only (RESEARCH below); project start on or after
     the start of FY 2015; an opportunity number on the record; exactly one PI.
  3. The opportunity is in the Grants.gov corpus (bench/corpus.py).
  4. Stratum: "parent" when the Grants.gov title contains "Parent", else "targeted".
  5. The PI resolves to exactly one OpenAlex author ever affiliated with Temple whose
     name matches (awards.same_person). Ambiguous or missing PIs are counted, not guessed.
  6. One award per PI and stratum: the earliest start (ties: award number).

Names go only to data/overrides/pi_aliases.csv; pis.csv carries aliases and ids.

  uv run python -m bench.build_set
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from bench.corpus import BENCH_DB
from perch.awards import same_person
from perch.config import env, load_dotenv
from perch.schemas import Award, Opportunity
from perch.sources.nih_reporter import NIHReporterClient
from perch.sources.openalex import TEMPLE_INSTITUTION_ID, OpenAlexClient, short_id
from perch.store.sqlite import SQLiteRepository

REPORTER_CACHE = Path("data/bench/reporter_temple_fy2015.json")
OUT = Path("data/backtest/pis.csv")
ALIASES = Path("data/overrides/pi_aliases.csv")
COUNTS = Path("data/backtest/set_counts.json")
FISCAL_YEARS = list(range(2015, 2027))
FY2015_START = "2014-10-01"
RESEARCH = {"R01", "R03", "R15", "R16", "R21", "R33", "R34", "R35", "R37", "R56", "R61",
            "DP1", "DP2", "U01"}
FIELDS = ["alias", "openalex_id", "award_number", "activity_code", "opportunity_number",
          "stratum", "award_start", "fiscal_year", "opportunity_open", "opportunity_close",
          "award_record"]


def reporter_awards() -> list[Award]:
    if REPORTER_CACHE.exists():
        return [Award.model_validate(r) for r in json.loads(REPORTER_CACHE.read_text("utf-8"))]
    with NIHReporterClient() as c:
        aw = c.awards_for_org(FISCAL_YEARS)
    REPORTER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    REPORTER_CACHE.write_text(json.dumps([a.model_dump(mode="json") for a in aw]), "utf-8")
    return aw


def first_years(awards: list[Award]) -> list[Award]:
    by: dict[str, list[Award]] = defaultdict(list)
    for a in awards:
        by[a.award_number].append(a)
    return [min(v, key=lambda a: (a.fiscal_year or 0, a.id)) for v in by.values()]


def load_aliases() -> list[dict[str, str]]:
    with ALIASES.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    load_dotenv()
    counts: Counter[str] = Counter()
    awards = first_years(reporter_awards())
    counts["projects"] = len(awards)
    pool = [a for a in awards if a.activity_code in RESEARCH and a.start_date
            and a.start_date.isoformat() >= FY2015_START and a.opportunity_number
            and len(a.pi_names) == 1]
    counts["research, FY2015 on, opportunity named, single PI"] = len(pool)
    with SQLiteRepository(BENCH_DB) as repo:
        opps = {o.opportunity_number: o for o in repo.list(Opportunity)}
    found = [a for a in pool if a.opportunity_number in opps]
    counts["opportunity in Grants.gov corpus"] = len(found)
    missing = sorted({a.opportunity_number for a in pool} - set(opps))

    resolved: dict[str, str | None] = {}
    with OpenAlexClient(env("OPENALEX_API_KEY")) as c:
        for name in sorted({a.pi_names[0] for a in found}):
            data = c.get("/authors", {"search": name, "per-page": 5, "filter":
                                      f"affiliations.institution.id:{short_id(TEMPLE_INSTITUTION_ID)}"})
            hits = [r for r in data.get("results", []) if same_person(r["display_name"], name)]
            resolved[name] = short_id(hits[0]["id"]) if len(hits) == 1 else None
            counts[f"PI {'resolved' if len(hits) == 1 else 'ambiguous' if hits else 'not found'}"
                   ] += 1
    ok = [a for a in found if resolved.get(a.pi_names[0])]
    counts["awards with a resolved PI"] = len(ok)

    aliases = load_aliases()
    by_id = {r["openalex_id"]: r["alias"] for r in aliases}
    n = max(int(r["alias"].split("-")[1]) for r in aliases)
    chosen: dict[tuple[str, str], Award] = {}
    for a in sorted(ok, key=lambda a: (a.start_date, a.award_number)):
        o = opps[a.opportunity_number]
        stratum = "parent" if "parent" in o.title.lower() else "targeted"
        chosen.setdefault((resolved[a.pi_names[0]], stratum), a)
    rows = []
    for (aid, stratum), a in sorted(chosen.items(), key=lambda kv: (kv[0][1] == "parent",
                                                                    kv[1].start_date)):
        if aid not in by_id:
            n += 1
            by_id[aid] = f"PI-{n}"
            aliases.append({"alias": by_id[aid], "openalex_id": aid, "name": a.pi_names[0],
                            "note": "back-test set (S8)"})
        o = opps[a.opportunity_number]
        rows.append({"alias": by_id[aid], "openalex_id": aid, "award_number": a.award_number,
                     "activity_code": a.activity_code, "opportunity_number": a.opportunity_number,
                     "stratum": stratum, "award_start": a.start_date.isoformat(),
                     "fiscal_year": a.fiscal_year,
                     "opportunity_open": o.open_date.isoformat() if o.open_date else "",
                     "opportunity_close": o.close_date.isoformat() if o.close_date else "",
                     "award_record": a.source_url})
    counts.update(Counter(f"chosen {r['stratum']}" for r in rows))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    with ALIASES.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["alias", "openalex_id", "name", "note"])
        w.writeheader()
        w.writerows(aliases)
    COUNTS.write_text(json.dumps({"counts": dict(counts), "opportunities_not_in_corpus": missing},
                                 indent=1) + "\n", "utf-8")
    for k, v in counts.items():
        print(f"{v:5d}  {k}")
    print(f"not in corpus: {len(missing)}")


if __name__ == "__main__":
    main()

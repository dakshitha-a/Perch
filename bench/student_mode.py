"""Planted-case scoring for student mode (S19). SYNTHETIC data only: this tests the
mechanism, not real-world accuracy.

For each student persona (data/synthetic/persona-*), the script runs the student brief in
this process, as the worker does (S42: the HTTP private-session path is gone): the persona's
CV, interests and achievements are the brief store's inputs (perch.user.briefs.MemoryBriefStore,
nothing is written), the pipeline runs on the demo store's models and records, and the leads
and the exports are read back. It then compares the app's verdicts and gap lists for the
planted records (sample:sch-0001 to 0024) with the hand-written answer keys, and checks for
leakage.

    uv run python bench/student_mode.py [--data data/demo]

Metrics (positive = "eligible" or "may be eligible", i.e. the student may apply):
- retrieved: planted records that reached the brief at all (retrieval, not rules).
- precision and recall of the positive class over retrieved planted records, against
  the key; and the exact verdict match rate.
- gap-list exact match over retrieved records the key marks positive.
- leakage: a persona canary in an export or in a file under the data directory; an
  export with sample leads but no sample banner. (The checks that went through the HTTP app,
  a sample record reachable in the public API and in a public brief, are in the tests:
  tests/test_student_routes.py.)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data/synthetic"
PERSONAS = ("persona-ug", "persona-masters", "persona-phd")
FILES = {"cv": "cv.md", "interests": "interests.md", "achievements": "achievements.md"}
POSITIVE = {"eligible", "may be eligible"}
BANNER = "SAMPLE DATA"
OUT = ROOT / "bench/results"


def canaries(name: str) -> list[str]:
    return sorted({m for f in (SYN / name).iterdir()
                   for m in re.findall(r"PERCH-CANARY-[A-Z0-9-]+", f.read_text())})


def persona_inputs(name: str):  # noqa: ANN201 - perch.user.briefs.StudentInputs
    from perch.student import achievements
    from perch.user.briefs import StudentInputs
    from perch.user.inputs import make_doc

    d = SYN / name
    return StudentInputs(cv=(d / "cv.md").read_text(),
                         interests=make_doc("interests", (d / "interests.md").read_text()),
                         entries=achievements((d / "achievements.md").read_text()))


def make_service(data: Path):  # noqa: ANN201 - a perch.service.BriefService
    from perch import awards as aw
    from perch.service import BriefService, Clients, default_models
    from perch.sources import openalex as oa

    return BriefService(data / "perch.db", default_models(False, data),
                        Clients(openalex=lambda: oa.OpenAlexClient()), aw.OVERRIDES)


def run_persona(svc, name: str, as_of: str) -> dict:  # noqa: ANN001
    """One persona's student brief, run in process. Returns the leads as the API shows them,
    the exports and the seconds the brief took."""
    from datetime import date

    from perch import export as ex
    from perch.schemas import Opportunity, Scholarship
    from perch.user.briefs import MemoryBriefStore, using_store

    store = MemoryBriefStore("bench", student=persona_inputs(name))
    with using_store(store):
        t0 = time.time()
        # A persona is a SYNTHETIC sample student, so its brief has the sample route (S43 M4).
        b = svc.create(None, audience="student", as_of=date.fromisoformat(as_of),
                       brief_id="bench", extra={"persona": name})
        status = svc.run(b.id)
        took = time.time() - t0
        brief, leads = store.view() or (b, [])
        with svc.repo() as r:
            recs = {x.record_id: r.get(Scholarship, x.record_id) or r.get(Opportunity, x.record_id)
                    for x in leads}
    blocks = ex.brief_blocks(brief, leads, records=recs)
    exports = {"md": ex.to_markdown(blocks), "html": ex.to_html(blocks, "Perch student brief"),
               "json": json.dumps([x.model_dump(mode="json") for x in leads])}
    view = {"brief": {**brief.model_dump(mode="json"), "status": status},
            "leads": [x.model_dump(mode="json") for x in leads]}
    return {"brief": view,
            "exports": exports, "seconds": round(took)}


def score(name: str, got: dict) -> dict:
    key = json.loads((SYN / name / "answer_key.json").read_text())
    leads = {x["record_id"]: x for x in got["brief"]["leads"]}
    rows = []
    for case in key["cases"]:
        x = leads.get(case["id"])
        rows.append({"persona": name, "id": case["id"], "key_verdict": case["verdict"],
                     "key_reason": case["reason"], "key_gaps": case["gaps"],
                     "retrieved": x is not None,
                     "verdict": x["verdict"] if x else None,
                     "reason": x["verdict_reason"] if x else None,
                     "gaps": x["gap_keys"] if x else None})
    return {"rows": rows, "status": got["brief"]["brief"]["status"]}


def metrics(rows: list[dict]) -> dict:
    r = [x for x in rows if x["retrieved"]]
    tp = sum(x["verdict"] in POSITIVE and x["key_verdict"] in POSITIVE for x in r)
    fp = sum(x["verdict"] in POSITIVE and x["key_verdict"] not in POSITIVE for x in r)
    fn = sum(x["verdict"] not in POSITIVE and x["key_verdict"] in POSITIVE for x in r)
    pos = [x for x in r if x["key_verdict"] in POSITIVE]
    return {"planted": len(rows), "retrieved": len(r),
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None, "tp": tp, "fp": fp, "fn": fn,
            "verdict_exact": sum(x["verdict"] == x["key_verdict"] for x in r),
            "gaps_exact": sum(x["gaps"] == x["key_gaps"] for x in pos), "gaps_cases": len(pos)}


def leakage(runs: dict, data: Path) -> dict:
    out = {}
    tokens = [t for n in runs for t in canaries(n)]
    out["persona_canary_in_export"] = sorted({t for n, r in runs.items()
                                              for e in r["exports"].values()
                                              for t in canaries(n) if t in e})
    out["export_without_banner"] = [n for n, r in runs.items()
                                    if any(x.get("sample") for x in r["brief"]["leads"])
                                    and BANNER not in r["exports"]["md"]]
    files = []
    for p in data.rglob("*"):
        try:
            if p.is_file() and p.stat().st_size < 200_000_000:
                b = p.read_bytes()
                files += [f"{p.relative_to(ROOT)}: {t}" for t in tokens if t.encode() in b]
        except OSError:
            continue
    out["persona_canary_in_data_files"] = files
    return out


def write_md(m_all: dict, per: dict, rows: list[dict], leak: dict, runs: dict) -> str:
    pct = lambda v: "n/a" if v is None else f"{v:.2f}"  # noqa: E731
    lines = ["# Student mode: planted-case scoring (SYNTHETIC)", "",
             "**Everything scored here is invented.** The scholarship corpus and the three "
             "student personas are SYNTHETIC (data/synthetic/README.md). These numbers test "
             "whether the mechanism (CV parse, rules, gap list and retrieval) "
             "does what it was written to do on cases planted for it. They say nothing "
             "about accuracy on real scholarships or real students, and they are not a "
             "result about Temple.", "",
             "The answer keys were written by hand from the rules in data/synthetic/README.md "
             "before the rule code existed. Positive means \"eligible\" or \"may be eligible\".",
             "", "## Summary", "",
             "| Persona | Brief | Planted retrieved | Precision | Recall | Verdict exact | "
             "Gap list exact |", "|---|---|---|---|---|---|---|"]
    for n, m in [*per.items(), ("all", m_all)]:
        secs = f"{runs[n]['seconds']} s" if n in runs else ""
        lines.append(f"| {n} | {secs} | {m['retrieved']} of {m['planted']} | "
                     f"{pct(m['precision'])} | {pct(m['recall'])} | {m['verdict_exact']} of "
                     f"{m['retrieved']} | {m['gaps_exact']} of {m['gaps_cases']} |")
    missed = [x for x in rows if not x["retrieved"]]
    pos_missed = [x for x in missed if x["key_verdict"] in POSITIVE]
    lines += ["", "## Reading these numbers", "",
              "- **The rules are expected to match.** The keys and the rule code follow the same "
              "written rules, so a perfect match shows the code does what the rules say. It is a "
              "check of the code, not evidence that the rules are right for real awards.",
              f"- **Retrieval is the real test here.** {len(missed)} of {len(rows)} planted "
              f"records never reached a brief, {len(pos_missed)} of them ones the student "
              "may apply for "
              f"({', '.join(x['id'] for x in pos_missed) or 'none'}). The rules never saw "
              "them. Each brief keeps the 40 records nearest the interests note out of 500.",
              "- **Precision and recall count only retrieved records.** Counting the missed "
              f"ones, the student would see {m_all['tp']} of "
              f"{sum(x['key_verdict'] in POSITIVE for x in rows)} planted records they may "
              "apply for (end-to-end recall).",
              "- **Fellowships are not scored.** They are public listings with no key; the best "
              "verdict there is \"may be eligible\" by design."]
    lines += ["", "## Leakage", ""]
    for k, v in leak.items():
        lines.append(f"- `{k}`: {v if v not in ([], 0, False) else 'none'}")
    lines += ["", "## Every planted case", "",
              "| Persona | Record | Key | App | Key gaps | App gaps |", "|---|---|---|---|---|---|"]
    for x in rows:
        app = f"{x['verdict']} ({x['reason']})" if x["retrieved"] else "not retrieved"
        lines.append(f"| {x['persona']} | {x['id']} | {x['key_verdict']} ({x['key_reason']}) "
                     f"| {app} | {', '.join(x['key_gaps']) or '—'} | "
                     f"{', '.join(x['gaps'] or []) or '—'} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=ROOT / "data/demo")
    ap.add_argument("--as-of", default="2026-11-06")
    a = ap.parse_args()
    runs, rows, per = {}, [], {}
    svc = make_service(a.data)
    for n in PERSONAS:
        runs[n] = run_persona(svc, n, a.as_of)
        s = score(n, runs[n])
        rows += s["rows"]
        per[n] = metrics(s["rows"])
        print(n, s["status"], per[n], file=sys.stderr)
    leak = leakage(runs, a.data)
    m_all = metrics(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "STUDENT_MODE.md").write_text(write_md(m_all, per, rows, leak, runs))
    (OUT / "student_mode.json").write_text(json.dumps(
        {"summary": m_all, "personas": per, "leakage": leak, "cases": rows,
         "seconds": {n: r["seconds"] for n, r in runs.items()}}, indent=1) + "\n")
    print(json.dumps({"summary": m_all, "leakage": leak}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

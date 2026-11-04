"""S46: measure the student brief on the real model (SYNTHETIC personas only).

Runs one student brief per persona in this process under the cloud-gpu profile against the
e2e Postgres, with the real provider, and prints per brief: leads, explanations shown /
withheld / flagged (MiniCheck), the first failing reason codes of withheld ones (codes only),
model calls, tokens and dollars from the spend ledger. Writes counts only (no model text).

    set -a; . ./.env; . ./.env.e2e; set +a
    PERCH_LIMIT_GPU=3 scripts/run_limited.sh uv run --extra ml --extra anthropic \
        python scripts/e2e_student_brief.py [persona ...]
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from datetime import date
from pathlib import Path

os.environ.setdefault("PERCH_PROFILE", "cloud-gpu")
os.environ.setdefault("PERCH_ANTHROPIC_BUDGET_USD", "1.00")
os.environ.pop("PERCH_REDIS_URL", None)
# Same DSN setup as e2e_brief_job.py: the runner and the worker-role repository use it.
os.environ["PERCH_DATABASE_URL"] = os.environ.get(
    "PERCH_E2E_DSN", "postgresql://postgres:perchtest@127.0.0.1:55432/perch_dev")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
OUT = ROOT / "bench/results/s46_student_real"
PERSONAS = ("persona-ug", "persona-masters", "persona-phd")

PATTERNS = [  # error text -> code; the text itself is never stored
    (r"^cited id .* was not in the input", "cited_id_unknown"),
    (r"is not a real date", "date_not_real"),
    (r"^date .* is not in any cited record", "date_not_in_record"),
    (r"^number .* is not in any cited record", "number_not_in_record"),
    (r"^link .* is not in any cited record", "link_not_in_record"),
    (r"^the word .* is not in any cited record", "action_word_not_in_record"),
    (r"^cited_ids must include the opportunity id", "opp_id_not_cited"),
    (r"^cite 1 to 3 paper ids", "paper_count_not_1_to_3"),
    (r"^finding names .* not one of the given papers", "finding_unknown_paper"),
    (r"^finding names .* cited_ids does not list", "finding_not_in_cited_ids"),
    (r"^opportunity_sentence must be one sentence", "opp_sentence_not_one"),
    (r"^output could not be parsed", "unparseable"),
]


def code(e: str) -> str:
    return next((c for p, c in PATTERNS if re.search(p, e)), "other")


def ledger() -> list[dict]:
    from perch.llm.budget import LEDGER
    p = ROOT / LEDGER
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def main() -> int:
    names = tuple(sys.argv[1:]) or PERSONAS
    from bench.student_mode import persona_inputs
    from perch.jobs import PostgresRunner
    from perch.schemas import Lead
    from perch.service import BriefService, Clients, default_models
    from perch.store.hybrid import HybridRepository
    from perch.store.postgres import PgVectorIndex
    from perch.profiles import current
    import perch.service as service
    from perch.user.briefs import MemoryBriefStore, using_store
    from dataclasses import replace

    runner = PostgresRunner(os.environ['PERCH_DATABASE_URL'], pool_size=8)
    tmp = Path(tempfile.mkdtemp(prefix="perch-s46-"))
    models = default_models(False, tmp, None)
    models = replace(models, index=lambda: PgVectorIndex(
        index_name="opportunities", embedder=current().embedder, pool=runner.pool))
    svc = BriefService(tmp / "perch.db", models, Clients(openalex=lambda: None),
                       repo_factory=lambda: HybridRepository(runner.pool, tmp / "briefs.db"),
                       index_new=False)
    captured: list = []
    orig = service.explain_leads

    def spy(*a, **k):  # noqa: ANN002, ANN003
        r = orig(*a, **k)
        captured.extend(r)
        return r

    service.explain_leads = spy
    rows = []
    for name in names:
        captured.clear()
        before = len(ledger())
        store = MemoryBriefStore("s46", student=persona_inputs(name))
        with using_store(store):
            b = svc.create(None, audience="student", as_of=date.today(), brief_id="s46",
                           extra={"persona": name})
            t0 = time.monotonic()
            status = svc.run(b.id)
            secs = time.monotonic() - t0
            brief, leads = store.view() or (b, [])
        stages = {s.name: s.status for s in brief.stages}
        withheld = [r for r in captured if r.flagged]
        shown = [r for r in captured if r.value]
        unsupported = sum(bool(r.value.unsupported) for r in shown)
        mc_opp = sum(any(u == r.value.opportunity_sentence for u in r.value.unsupported)
                     for r in shown)
        mc_find = sum(any(u != r.value.opportunity_sentence for u in r.value.unsupported)
                      for r in shown)
        first = Counter(code(r.errors[0]) for r in withheld if r.errors)
        allc = Counter(code(e) for r in withheld for e in r.errors)
        new = ledger()[before:]
        cost = sum(x.get("cost_usd", 0) for x in new)
        tok = {k: sum(x.get(k, 0) for x in new) for k in
               ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")}
        row = {"persona": name, "status": status, "leads": len(leads),
               "eligible_leads": sum(x.verdict != "not eligible" for x in leads),
               "explained_attempted": len(captured), "shown": len(shown),
               "withheld": len(withheld), "minicheck_unsupported": unsupported, "mc_opp_sentence": mc_opp,
               "mc_finding": mc_find,
               "attempts_total": sum(r.attempts for r in captured),
               "model_calls": len(new), **tok, "usd": round(cost, 4),
               "seconds": round(secs), "first_reasons": dict(first),
               "all_reasons": dict(allc)}
        rows.append(row)
        print(f"STUDENT {name} status={status} stages={stages}\n  "
              + " ".join(f"{k}={v}" for k, v in row.items() if k != "persona"), flush=True)
    runner.close()
    OUT.mkdir(parents=True, exist_ok=True)
    keys = list(rows[0])
    with (OUT / "counts.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: json.dumps(v) if isinstance(v, dict) else v for k, v in r.items()})
    print(f"TOTAL usd={sum(r['usd'] for r in rows):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

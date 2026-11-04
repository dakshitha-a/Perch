"""S47 task 3: is grounding worth batching? A measured comparison inside the bench (perch/ is not
edited). One brief grounds 1 opportunity sentence plus about 2 findings for each of 10 leads, a
`support(document, [claim])` call each (30 calls). This script times, on one GPU with the real
MiniCheck model:
  current   30 calls to MiniCheckGrounder.support, one claim each (what the pipeline does)
  batched   the same 30 (document, claim) pairs expanded to chunk pairs and run in batches of
            64 sorted by length, taking the best chunk per claim
It checks the two give the same probabilities (max absolute difference) and reports the speed-up.

    PERCH_LIMIT_GPU=3 scripts/run_limited.sh uv run --extra ml python bench/load/ground_batch.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import psycopg  # noqa: E402
import torch  # noqa: E402

from perch.grounding import MiniCheckGrounder  # noqa: E402
from perch.schemas import Opportunity, Work  # noqa: E402
from perch.skills import opportunity_view, work_view  # noqa: E402
from perch.skills.fit import strip_ids  # noqa: E402

DSN = os.environ.get("PERCH_E2E_DSN", "postgresql://postgres:perchtest@127.0.0.1:55432/perch_dev")


def first_sentence(t: str) -> str:
    return (t.replace("\n", " ").split(". ")[0] or t).strip().rstrip(".") + "."


def main() -> int:
    with psycopg.connect(DSN) as c:
        opps = [Opportunity.model_validate(r[0]) for r in c.execute(
            "SELECT data FROM records WHERE kind='opportunity' AND NOT sample "
            "AND data->>'description' IS NOT NULL ORDER BY id LIMIT 10").fetchall()]
        works = [Work.model_validate(r[0]) for r in c.execute(
            "SELECT data FROM records WHERE kind='work' AND data->>'abstract' IS NOT NULL "
            "ORDER BY id LIMIT 20").fetchall()]
    pairs = []
    for i, o in enumerate(opps):
        pairs.append((opportunity_view(o, description_chars=4000),
                      first_sentence(strip_ids(o.description or o.title))))
        for w in works[2 * i:2 * i + 2]:
            pairs.append((work_view(w, abstract_chars=2000),
                          "The paper " + first_sentence(w.abstract or w.title).lower()))
    g = MiniCheckGrounder(device="cuda")
    g.support(*[pairs[0][0]], [pairs[0][1]])  # warm-up
    torch.cuda.synchronize()
    reps = 5
    cur_t, bat_t = [], []
    for _ in range(reps):
        t = time.perf_counter()
        cur = [g.support(d, [cl])[0] for d, cl in pairs]
        torch.cuda.synchronize()
        cur_t.append(time.perf_counter() - t)
        t = time.perf_counter()
        items = []  # (claim index, text)
        for k, (d, cl) in enumerate(pairs):
            for ch in g.chunks(d):
                items.append((k, ch + g.tok.eos_token + cl))
        order = sorted(range(len(items)), key=lambda j: len(items[j][1]))
        best = [0.0] * len(pairs)
        with torch.no_grad():
            for s in range(0, len(order), 64):
                idx = order[s:s + 64]
                enc = g.tok([items[j][1] for j in idx], max_length=512, truncation=True,
                            padding=True, return_tensors="pt").to("cuda")
                pr = torch.softmax(g.model(**enc).logits, dim=-1)[:, 1].tolist()
                for j, p in zip(idx, pr, strict=True):
                    best[items[j][0]] = max(best[items[j][0]], float(p))
        torch.cuda.synchronize()
        bat_t.append(time.perf_counter() - t)
    diff = max(abs(a - b) for a, b in zip(cur, best, strict=True))
    out = {"claims_per_brief": len(pairs), "chunk_pairs": len(items), "reps": reps,
           "current_s_per_brief": [round(x, 4) for x in cur_t],
           "batched_s_per_brief": [round(x, 4) for x in bat_t],
           "current_ms_per_claim_median": round(sorted(cur_t)[reps // 2] / len(pairs) * 1000, 2),
           "batched_ms_per_claim_median": round(sorted(bat_t)[reps // 2] / len(pairs) * 1000, 2),
           "max_abs_prob_difference": round(diff, 5),
           "gpu_peak_alloc_mib": round(torch.cuda.max_memory_allocated() / 2**20)}
    out["speedup_median"] = round(sorted(cur_t)[reps // 2] / sorted(bat_t)[reps // 2], 2)
    p = ROOT / "bench/results/s47_load/ground_batch.json"
    p.write_text(json.dumps(out, indent=1), "utf-8")
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validator layer 2 bench: grounders on a swapped-record proxy set.

No human QA log exists yet (SPEC section 10), so this is a proxy, labelled as one:
each saved explanation's opportunity sentence (model-written, from the demo briefs
in data/perch.db) is checked against its own opportunity record (label: supported)
and against the next lead's record in the same brief (label: unsupported; a hard
negative, since leads in one brief share a topic, so a few may be partly supported).
Reports the false-flag rate (supported pairs scored at or below 0.5), the miss rate
(unsupported pairs above 0.5), AUC and seconds per claim.

  uv run --extra ml python -m bench.grounders
"""

from __future__ import annotations

import csv
import os
import time

from bench.backtest import RESULTS
from bench.skill2 import BENCH_OLLAMA, DB
from perch.grounding import THRESHOLD, DecisionGrounder, Grounder, split_sentences
from perch.llm import get_provider
from perch.llm.decide import LogprobDecider
from perch.llm.systemone import CLEF_FLASH_URL, CLEF_URL, SystemOneClient, SystemOneDecider
from perch.schemas import Brief, Lead, Opportunity
from perch.skills import opportunity_view
from perch.skills.fit import strip_ids
from perch.store.sqlite import SQLiteRepository

SKIPPED = {
    "Jev (hosted)": "no access to the hosted Jev API on this node; not benched",
    "Strands Decider 2B": "weights and licence not verified on this node; not benched",
}


def pairs() -> list[tuple[str, str, bool]]:
    """(document, claim, supported)."""
    out = []
    with SQLiteRepository(DB) as r:
        for b in r.list(Brief):
            leads = [x for x in (r.get(Lead, i) for i in b.lead_ids) if x and x.explanation]
            opps = [r.get(Opportunity, x.record_id) for x in leads]
            for i, (lead, o) in enumerate(zip(leads, opps, strict=True)):
                other = opps[(i + 1) % len(opps)]
                if not o or not other or other.id == o.id:
                    continue
                claim = strip_ids(split_sentences(lead.explanation)[0])
                out.append((opportunity_view(o, description_chars=4000), claim, True))
                out.append((opportunity_view(other, description_chars=4000), claim, False))
    return out


def auc(pos: list[float], neg: list[float]) -> float:
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / max(len(pos) * len(neg), 1)


def grounders() -> list[tuple[str, Grounder]]:
    from perch.grounding import MiniCheckGrounder

    os.environ["OLLAMA_BASE_URL"] = BENCH_OLLAMA
    return [
        ("MiniCheck-RoBERTa-Large (default, CPU)", MiniCheckGrounder(device="cpu")),
        ("Clef-flash (systemone)", DecisionGrounder(
            SystemOneDecider(SystemOneClient(CLEF_FLASH_URL), "clef-flash"), "clef-flash")),
        ("Clef (systemone)", DecisionGrounder(
            SystemOneDecider(SystemOneClient(CLEF_URL), "clef"), "clef")),
        ("LLM-logprobs fallback, qwen3.8:27b", DecisionGrounder(
            LogprobDecider(get_provider("ollama:qwen3.8:27b")), "logprobs-qwen3.8-27b")),
    ]


def main() -> None:
    data = pairs()
    rows = []
    for name, g in grounders():
        t = time.perf_counter()
        scores = [g.support(doc, [claim])[0] for doc, claim, _ in data]
        secs = (time.perf_counter() - t) / len(data)
        pos = [s for s, (_, _, y) in zip(scores, data, strict=True) if y]
        neg = [s for s, (_, _, y) in zip(scores, data, strict=True) if not y]
        rows.append({"grounder": name, "pairs": len(data),
                     "false_flag_rate": round(sum(s <= THRESHOLD for s in pos) / len(pos), 3),
                     "miss_rate": round(sum(s > THRESHOLD for s in neg) / len(neg), 3),
                     "auc": round(auc(pos, neg), 3), "s_per_claim": round(secs, 3),
                     "note": ""})
        print(rows[-1], flush=True)
    rows += [{"grounder": k, "pairs": 0, "false_flag_rate": "", "miss_rate": "", "auc": "",
              "s_per_claim": "", "note": v} for k, v in SKIPPED.items()]
    RESULTS.mkdir(parents=True, exist_ok=True)
    with (RESULTS / "grounders.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()

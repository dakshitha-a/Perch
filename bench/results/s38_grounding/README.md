# S38 grounding bench, MiniCheck on CPU

Run (no GPU, no cloud calls):

    CUDA_VISIBLE_DEVICES= uv run --extra ml python -m bench.grounders --cpu-minicheck bench/results/s38_grounding

Set: the same 40 swapped-record proxy pairs as bench/results/grounders.csv, built from data/perch.db.
Model: lytang/MiniCheck-RoBERTa-Large, device cpu, threshold 0.5.
Only the MiniCheck arm was rerun. The Clef-based arms are retired and were skipped; the
logprobs fallback arm was not part of this task.

| run | pairs | false_flag_rate | miss_rate | auc | s_per_claim |
|---|---|---|---|---|---|
| earlier (grounders.csv) | 40 | 0.0 | 0.1 | 0.925 | 0.268 |
| S38 CPU | 40 | 0.0 | 0.1 | 0.922 | 0.362 |

CPU latency per pair: median 0.361 s, p95 0.488 s.
os.cpu_count() reports 255 (shared host); the box is described as 8 cores; torch threads 12.
uptime before: load average 59.04, 59.68, 60.74. After: 63.88, 60.70, 61.04.
The host was heavily loaded and other agents may time CPU work at once, so latency is
indicative only. Latency was steady (p95 under 1.4 times the median), so no rerun.
The AUC differs by 0.003 from the earlier run; the earlier arm was already CPU, so the
difference is library or thread nondeterminism, not a device change.

Files: grounders_cpu.csv, grounders_cpu.json.
Code: the --cpu-minicheck flag in bench/grounders.py; default behaviour is unchanged.

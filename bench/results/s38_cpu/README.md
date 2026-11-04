# S38 CPU timings (cloud-cpu profile)

Script: `bench/cpu_timings.py`. Raw rows: `timings.csv` (one row per measurement).
Public data only: queries come from the topic threads of real researchers in the migrated
Postgres database; MiniCheck pairs are (public work or opportunity text, one of its own
sentences). No GPU, no cloud call, no user text.

## Conditions (read before using the numbers)

- **Cores:** every run went through `scripts/run_limited.sh`: 16 cores (cgroup CPU quota
  1600 percent), 24 GB, nice 19, no GPU. `PERCH_TORCH_THREADS=16`. The node has 255 cores
  and is shared with other users' jobs: the 1-minute load average was about 31 to 34 before
  and after every run (columns `load_before` in the CSV), so the numbers are for a busy
  machine and are probably pessimistic for a dedicated worker.
- **Weights dtype:** float32. The checkpoints are bf16 and sentence-transformers keeps that
  dtype; this CPU (AMD EPYC 7773X) has AVX2 but no AVX512-BF16 or AMX, and an earlier
  attempt with bf16 weights (3-core cap) spent over an hour building the five profiles
  and never reached the timed stages. `perch.embed.cpu_model_kwargs` now loads float32 on
  CPU (`PERCH_CPU_DTYPE` overrides). No bf16 timing is reported because that run was
  stopped; it is not measured.
- **Earlier attempt:** a first run without the limiter was started on the unrestricted
  node and the node hung at about 18:42 while another job also ran models. That run
  produced no data.
- **Sample sizes:** halved by instruction: 10 query embeddings, 5 researchers for rerank
  (not 10), 25 MiniCheck pairs (not 50). The database holds 10 researchers; the first 5 by
  id were used.
- **Rerank unit:** one `perch.rerank.rerank()` call over the top N eligible candidates of a
  researcher (grouped per thread, as in a brief), no score cache. One value per researcher.
- **Runs:** each set twice (runs 1 and 2). Run 1 also swept N = 10, 20, 30, 40. Run 3 is a
  one-off fine sweep (N = 12, 14, 16) to place the shrink limit; its embed and MiniCheck
  rows repeat the same measurement a third time.

## Results (milliseconds)

| Stage | n | Run 1 median | Run 1 p95 | Run 2 median | Run 2 p95 |
|---|---|---|---|---|---|
| Query embed (one query) | 10 | 270 | 300 | 316 | 349 |
| Rerank, top 50 | 5 | 41027 | 43140 | 32472 | 39415 |
| Rerank, top 100 | 5 | 65379 | 74035 | 58192 | 68822 |
| MiniCheck, one sentence | 25 | 635 | 713 | 619 | 694 |

Rerank of 50 differs by 26 percent between runs 1 and 2 (the rule would call for a third
run; a third run was not made under the reduced-run instruction). Both exceed 10 s by a
wide margin, so the conclusion does not depend on which is right.

Rerank sweep (run 1 unless noted):

| N | median | p95 |
|---|---|---|
| 10 | 7396 | 9704 |
| 12 (run 3) | 7603 | 8592 |
| 14 (run 3) | 9386 | 10593 |
| 16 (run 3) | 10715 | 11588 |
| 20 | 14978 | 17833 |
| 30 | 23687 | 26786 |
| 40 | 33169 | 33922 |

Rerank cost is close to linear at about 0.65 to 0.8 s per candidate on this setup.

## Shrink rule

Rerank of 50 took over 10 s at the median, so the rule applies. The largest count measured
under 10 s at the median is **14** (9.4 s, p95 10.6 s). The `cloud-cpu` profile now sets
`rerank_in = 14`; the GPU profiles keep 100 (the S27 value). The back-test gain at 100
(MRR 0.067 to 0.149 with topic queries) was measured at 100 candidates, so the Phase 3
re-measure must price this cut. It is a mechanism choice here, not a measured quality result.

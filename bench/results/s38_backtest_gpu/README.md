# S38 back-test on GPU: 0.6B vs 4B reranker, dense vs hybrid

Same rows, pool, date cut-off (papers before award start) and 18-month window as the S27 and S38 CPU
back-tests (`bench/results/s38_backtest/README.md`). NIH only. 126 rows with a complete window:
48 targeted, 78 parent. The keyword-only baseline is on every table. Metrics are unchanged.

## Results (rerank_in 100 for every reranked row)
| Config | Stratum | n | hit@5 | hit@10 | MRR | recall@200 | rerank s/row (mean / median) |
|---|---|---|---|---|---|---|---|
| Keyword-only (tsvector, no rerank) | targeted | 48 | 0.000 | 0.000 | 0.002 | 0.042 | none |
| Dense + Qwen3-Reranker-0.6B | targeted | 48 | 0.167 | 0.250 | 0.142 | 0.500 | 0.54 / 0.60 |
| Hybrid + Qwen3-Reranker-0.6B | targeted | 48 | 0.167 | 0.229 | 0.125 | 0.417 | 0.63 / 0.71 |
| Dense + Qwen3-Reranker-4B | targeted | 48 | 0.167 | 0.250 | 0.132 | 0.500 | 2.45 / 2.76 |
| Hybrid + Qwen3-Reranker-4B | targeted | 48 | 0.167 | 0.229 | 0.125 | 0.417 | 2.88 / 3.29 |
| Keyword-only (tsvector, no rerank) | parent | 78 | 0.000 | 0.000 | 0.000 | 0.000 | none |
| Dense + Qwen3-Reranker-0.6B | parent | 78 | 0.038 | 0.051 | 0.032 | 0.064 | 0.39 / 0.54 |
| Hybrid + Qwen3-Reranker-0.6B | parent | 78 | 0.013 | 0.013 | 0.004 | 0.064 | 0.44 / 0.61 |
| Dense + Qwen3-Reranker-4B | parent | 78 | 0.038 | 0.051 | 0.025 | 0.064 | 1.77 / 2.45 |
| Hybrid + Qwen3-Reranker-4B | parent | 78 | 0.000 | 0.000 | 0.001 | 0.064 | 2.04 / 2.84 |

One award in 48 is 0.021 and one in 78 is 0.013. Recall@200 is set by retrieval, so it is identical for
a given retrieval mode whatever the reranker. For reference, the CPU run (fp32, 0.6B, hybrid) had
targeted hit@10 0.229, MRR 0.127; S27 (Lance, BM25) had 0.208, 0.144.

## Paired bootstrap, 95% interval on the MRR difference (same awards, seeded, 2000 draws)
Full output with hit@10 counts: `paired_bootstrap.txt`; code: `bench/paired_mrr.py` (same method as `bench/run.py`).
| Comparison (A minus B) | Stratum | MRR diff | 95% interval | hit@10 gained / lost |
|---|---|---|---|---|
| 4B minus 0.6B, dense | targeted | -0.010 | [-0.061, +0.045] | +3 / -3 |
| 4B minus 0.6B, dense | parent | -0.007 | [-0.034, +0.010] | +1 / -1 |
| 4B minus 0.6B, hybrid | targeted | +0.001 | [-0.041, +0.053] | +3 / -3 |
| 4B minus 0.6B, hybrid | parent | -0.003 | [-0.008, +0.000] | +0 / -1 |
| dense minus hybrid, 0.6B | targeted | +0.017 | [+0.001, +0.045] | +1 / -0 |
| dense minus hybrid, 0.6B | parent | +0.028 | [-0.000, +0.073] | +3 / -0 |
| dense minus hybrid, 4B | targeted | +0.007 | [-0.000, +0.018] | +1 / -0 |
| dense minus hybrid, 4B | parent | +0.024 | [+0.002, +0.058] | +4 / -0 |

## Findings
- The 4B reranker shows no measurable gain over the 0.6B. Every interval spans zero, and the hit@10 swaps are
  equal in both directions. It costs about 4.5 times the rerank time.
- Dense is at least as good as hybrid with both rerankers, on every metric. The dense advantage is small:
  one to four awards. Most intervals touch zero; two exclude it (0.6B targeted, 4B parent).
  The cause is retrieval: recall@200 is 0.500 dense against 0.417 hybrid, and the tsvector list adds noise.
- The parent stratum is near zero in every setup, as in the CPU run.
- GPU bf16 reproduces the CPU fp32 numbers within one award (hybrid 0.6B: hit@10 0.229 both, MRR 0.125 vs 0.127).

## Method
- GPU 3 only (RTX 5000 Ada), through `PERCH_LIMIT_GPU=3 scripts/run_limited.sh` (4 cores, GPU lock),
  one run at a time. Node load average about 17 throughout. Demo services and other GPUs untouched.
- Postgres database `perch_backtest`, 11,202 announcements, opened read-only in effect (the bench only reads).
  Dense: pgvector HNSW. Sparse: tsvector. Embedder: Qwen3-Embedding-0.6B, same as before.
- Dtype: `device` left unset, so sentence-transformers loads the checkpoint dtype, bf16, on the GPU. I did not
  print the dtype in these runs; it follows the same loader that `bench/results/s38_gpu` read as bf16 for both rerankers.
- Each run used a fresh rerank cache, so every score was computed on the GPU and the latencies are not
  cache-shortened. Rerank seconds per row come from `rerank_latency_*.json` (time inside `score` only).
  Rows score 73 pairs on average (87.5 targeted, 64.3 parent), fewer than 100 because the eligible
  pool is smaller. Throughput: 0.6B 164 pairs/s dense, 142 hybrid; 4B 36 and 31 pairs/s.
- Wall time: 21 minutes for all five runs (keyword 3, dense 0.6B 2, hybrid 0.6B 4, dense 4B 5, hybrid 4B 8),
  including model loads.

## Code change
`bench/backtest.py` only: `--reranker <model id>` (any id with a slash goes straight to the cross-encoder
loader), and a `dense+rerank` config. `bench/paired_mrr.py` is new. No change to `perch/`.

## Commands
    DSN=postgresql://postgres:<pw>@127.0.0.1:55432/perch_backtest
    PERCH_LIMIT_GPU=3 scripts/run_limited.sh python -m bench.backtest --store postgres --dsn $DSN \
      --rerank-in 100 --strata targeted parent --configs dense+rerank --reranker Qwen/Qwen3-Reranker-4B \
      --rerank-cache <fresh>.db --out bench/results/s38_backtest_gpu/dense_4b
    (hybrid: --configs hybrid+rerank; 0.6B: --reranker Qwen/Qwen3-Reranker-0.6B; baseline: --configs keyword-only)
    python -m bench.paired_mrr A.csv B.csv targeted parent
Raw output is in the subfolders `keyword`, `dense_06b`, `hybrid_06b`, `dense_4b`, `hybrid_4b`
(`backtest_postgres_*.csv` per row, `rerank_latency_*.json`, `run.log`). The `data/bench` folder was
symlinked into the worktree (gitignored) because the worktree has no copy of it.

## Caveats
- Small n: 48 and 78 rows, a handful of hits. Differences of one or two awards are noise.
- The dtype was not printed in this run (see Method). The sparse side is the current tsvector, not a
  tuned one; a better sparse index could change the dense versus hybrid result.

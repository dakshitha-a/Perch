# S50 back-test re-run (after round 2 eligibility changes)

Same rows, pool (`perch_backtest`, 11,202 announcements), date cut-off (papers before award start),
18-month window, rerank_in 100 and NIH-only scope as `bench/results/s38_backtest_gpu/README.md`.
126 rows: 48 targeted, 78 parent. Only two configs re-run, GPU 3 through the lock, fresh rerank cache.
Code at HEAD of rebuild/v1 (includes S50 G3 notices rule and G5 level and Temple-page rules).

| Config | Stratum | n | hit@5 | hit@10 | MRR | recall@200 | S38 hit@10 / MRR |
|---|---|---|---|---|---|---|---|
| Keyword-only (tsvector, no rerank) | targeted | 48 | 0.000 | 0.000 | 0.002 | 0.042 | 0.000 / 0.002 |
| Dense + Qwen3-Reranker-0.6B | targeted | 48 | 0.167 | 0.250 | 0.142 | 0.500 | 0.250 / 0.142 |
| Keyword-only (tsvector, no rerank) | parent | 78 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 / 0.000 |
| Dense + Qwen3-Reranker-0.6B | parent | 78 | 0.038 | 0.051 | 0.032 | 0.064 | 0.051 / 0.032 |

## Do the numbers match S38?
- Keyword-only: identical, every per-row rank and pool size is the same.
- Dense + 0.6B: every published figure (hit@5, hit@10, MRR, recall@200, truth_eligible 40 and 74) matches to three decimals.
- Two targeted rows moved by one rank, far from the top ten: PI-48 PA-18-358 181 to 182, PI-51 PA-18-358 17 to 16.
  Pool sizes and eligible truth are unchanged on every row, so no award was gained or lost and no rule change explains them.
  The likely cause is bf16 GPU score ties or run-to-run noise; this was not isolated.
- The G3 notices rule and the G5 rules therefore do not touch this NIH back-test pool.

Run time: keyword 137 s, dense + 0.6B 95 s (including model loads). Logs: `keyword.log`, `dense_06b.log`; per-row CSVs in the subfolders.

## Command
    PERCH_LIMIT_GPU=3 PERCH_LIMIT_LOCK=$XDG_RUNTIME_DIR/perch-bench.lock scripts/run_limited.sh .venv/bin/python -m bench.backtest \
      --store postgres --dsn <perch_backtest> --rerank-in 100 --strata targeted parent \
      --configs dense+rerank --reranker Qwen/Qwen3-Reranker-0.6B --rerank-cache <fresh>.db --out bench/results/s50_backtest/dense_06b
    (keyword: --configs keyword-only)

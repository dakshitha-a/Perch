# S38 back-test on the v1 retrieval path (Postgres, CPU)

Same rows, pool, date cut-off (papers before award start) and 18-month window as the S27 back-test
(`bench/results/RESULTS.md`). NIH only. 126 rows with a complete window: 48 targeted, 78 parent.
The keyword-only baseline is on every row of the table.

## What differs from S27
- Records and vectors: Postgres database `perch_backtest` (test server), 11,202 announcements and 5,644 works,
  loaded with `perch db migrate` and `perch db migrate-corpus` from the bench store. Vectors are the cached
  Qwen3-Embedding-0.6B vectors from the S27 Lance table (50 sampled vectors matched the embedding cache).
- Dense search: pgvector HNSW (`PgVectorIndex.dense`). Sparse search: tsvector (`PgVectorIndex.bm25`, ts_rank_cd).
- Profile embedding and reranker (Qwen3-Reranker-0.6B) on CPU, float32, 16 threads (`scripts/run_limited.sh`).
  Node shared, load average about 20 to 30. No chat model is used by the back-test.
- Rerank cache is fresh (`rerank_cache.db` here), so every score was computed on CPU.

## Results (hit@5 / hit@10 / MRR; recall@200 = true announcement in the retrieved list)
| Setup | Stratum | n | hit@5 | hit@10 | MRR | recall@200 |
|---|---|---|---|---|---|---|
| Deployed: hybrid, rerank_in 14 | targeted | 48 | 0.042 | 0.062 | 0.035 | 0.417 |
| Hybrid, rerank_in 100 (S27 setting) | targeted | 48 | 0.167 | 0.229 | 0.127 | 0.417 |
| Dense only, no rerank | targeted | 48 | 0.062 | 0.062 | 0.033 | 0.500 |
| Keyword-only (tsvector, no rerank) | targeted | 48 | 0.000 | 0.000 | 0.002 | 0.042 |
| Deployed: hybrid, rerank_in 14 | parent | 78 | 0.000 | 0.000 | 0.000 | 0.064 |
| Keyword-only (tsvector) | parent | 78 | 0.000 | 0.000 | 0.000 | 0.000 |
| S27 default (Lance, BM25, rerank_in 100) | targeted | 48 | 0.188 | 0.208 | 0.144 | not recorded |
| S27 keyword-only (BM25) | targeted | 48 | 0.042 | 0.042 | 0.032 | not recorded |
| S27 default / keyword-only | parent | 78 | 0.026 / 0 | 0.026 / 0 | 0.016 / 0 | |

The rerank_in 100 run was done on the 48 targeted rows only (parent rows are about 0 at any setting).
One award in 48 is about 0.021, so 0.167 vs 0.188 is one award.

## Findings
- Cutting rerank_in from 100 to 14 costs most of the gain: targeted hit@10 0.229 to 0.062, MRR 0.127 to 0.035.
- Dense search matches Lance: for 8 random announcements the top-100 lists were identical to Lance and the
  query's own record was ranked first or near first (HNSW recall is not the issue).
- tsvector sparse search is much weaker than the old BM25: top-100 overlap with Lance BM25 was 0 to 53 of 100.
  Keyword-only recall@200 drops from a working baseline to 0.042 targeted. Hybrid recall@200 (0.417) is below
  dense-only (0.500), so the sparse list adds noise. Likely cause: `ts_rank_cd` over an OR query has no IDF and
  favours common words. (`migrate-corpus` self-search also found 17 of 20, noted as a mismatch, not investigated.)
- Rerank latency on CPU (16 threads): rerank_in 14 median 11.6 s per row (0.82 s per pair, load 20 to 30);
  rerank_in 100, 86 uncached pairs per row, median 46 s (0.53 s per pair), so about 53 s for all 100.

## Commands
    uv run perch db migrate --dsn $DSN ; uv run perch --db <stage>/perch.db db migrate-corpus --dsn $DSN --samples none
    scripts/run_limited.sh uv run python -m bench.backtest --store postgres --dsn $DSN --device cpu --threads 16 \
      --rerank-in 14 --configs keyword-only hybrid+rerank --rerank-cache bench/results/s38_backtest/rerank_cache.db --out bench/results/s38_backtest
    ... --configs dense          (dense only)
    ... --rerank-in 100 --strata targeted --configs hybrid+rerank
`DSN` is the test server's `perch_backtest` database. Wall time: about 22 minutes (rerank_in 14, 126 rows x 2 configs),
about 1 minute (dense), about 36 minutes (rerank_in 100, 48 rows).
Files: `backtest_postgres_*.csv` (one row per back-test row), `rerank_latency_*.json`, `run_*.log`.

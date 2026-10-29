# Bench results

Rendered 2026-10-29 13:38 UTC by `make bench`. Numbers are copied from the CSVs in this folder; nothing here is estimated.

## Back-test (NIH, Temple, date cut-off)

Papers before the award start; pool: NIH announcements on Grants.gov open in the 18 months before it; rank of the announcement the award was funded under. Baseline: keyword-only (BM25 on thread terms, no dense, no rerank).

### Targeted announcements

| embedder | config | n | hit@5 | hit@10 | MRR | recall@200 | baseline hit@5 / hit@10 / MRR |
|---|---|---|---|---|---|---|---|
| Qwen3-Embedding-0.6B | keyword-only | 48 | 0.021 | 0.021 | 0.017 | 0.167 | 0.021 / 0.021 / 0.017 |
| Qwen3-Embedding-0.6B | dense | 48 | 0.062 | 0.062 | 0.032 | 0.458 | 0.021 / 0.021 / 0.017 |
| Qwen3-Embedding-0.6B | hybrid | 48 | 0.062 | 0.125 | 0.05 | 0.375 | 0.021 / 0.021 / 0.017 |
| Qwen3-Embedding-0.6B | hybrid + Qwen3-Reranker-0.6B (default) | 48 | 0.104 | 0.146 | 0.066 | 0.375 | 0.021 / 0.021 / 0.017 |
| Qwen3-Embedding-0.6B | hybrid + Clef-flash rerank | 48 | 0.062 | 0.104 | 0.056 | 0.375 | 0.021 / 0.021 / 0.017 |
| Qwen3-Embedding-0.6B | hybrid + Clef rerank | 48 | 0.042 | 0.083 | 0.055 | 0.375 | 0.021 / 0.021 / 0.017 |
| Qwen3-Embedding-4B | dense | 48 | 0.062 | 0.125 | 0.042 | 0.458 | 0.021 / 0.021 / 0.017 |
| Qwen3-Embedding-4B | hybrid | 48 | 0.062 | 0.104 | 0.042 | 0.438 | 0.021 / 0.021 / 0.017 |
| Qwen3-Embedding-4B | hybrid + Qwen3-Reranker-0.6B | 48 | 0.083 | 0.167 | 0.074 | 0.438 | 0.021 / 0.021 / 0.017 |
| bge-m3 | dense | 48 | 0.021 | 0.062 | 0.021 | 0.271 | 0.021 / 0.021 / 0.017 |
| bge-m3 | hybrid | 48 | 0.042 | 0.062 | 0.032 | 0.25 | 0.021 / 0.021 / 0.017 |
| bge-m3 | hybrid + Qwen3-Reranker-0.6B | 48 | 0.083 | 0.104 | 0.052 | 0.25 | 0.021 / 0.021 / 0.017 |
| specter2_base | dense | 48 | 0.104 | 0.167 | 0.079 | 0.479 | 0.021 / 0.021 / 0.017 |
| specter2_base | hybrid | 48 | 0.021 | 0.083 | 0.044 | 0.417 | 0.021 / 0.021 / 0.017 |
| specter2_base | hybrid + Qwen3-Reranker-0.6B | 48 | 0.104 | 0.188 | 0.075 | 0.417 | 0.021 / 0.021 / 0.017 |

### Parent announcements

| embedder | config | n | hit@5 | hit@10 | MRR | recall@200 | baseline hit@5 / hit@10 / MRR |
|---|---|---|---|---|---|---|---|
| Qwen3-Embedding-0.6B | keyword-only | 78 | 0.0 | 0.0 | 0.001 | 0.013 | 0.0 / 0.0 / 0.001 |
| Qwen3-Embedding-0.6B | dense | 78 | 0.0 | 0.0 | 0.001 | 0.064 | 0.0 / 0.0 / 0.001 |
| Qwen3-Embedding-0.6B | hybrid | 78 | 0.0 | 0.0 | 0.001 | 0.051 | 0.0 / 0.0 / 0.001 |
| Qwen3-Embedding-0.6B | hybrid + Qwen3-Reranker-0.6B (default) | 78 | 0.013 | 0.013 | 0.013 | 0.051 | 0.0 / 0.0 / 0.001 |
| Qwen3-Embedding-0.6B | hybrid + Clef-flash rerank | 78 | 0.013 | 0.013 | 0.013 | 0.051 | 0.0 / 0.0 / 0.001 |
| Qwen3-Embedding-0.6B | hybrid + Clef rerank | 78 | 0.013 | 0.013 | 0.013 | 0.051 | 0.0 / 0.0 / 0.001 |
| Qwen3-Embedding-4B | dense | 78 | 0.0 | 0.0 | 0.001 | 0.013 | 0.0 / 0.0 / 0.001 |
| Qwen3-Embedding-4B | hybrid | 78 | 0.0 | 0.0 | 0.001 | 0.026 | 0.0 / 0.0 / 0.001 |
| Qwen3-Embedding-4B | hybrid + Qwen3-Reranker-0.6B | 78 | 0.013 | 0.026 | 0.014 | 0.026 | 0.0 / 0.0 / 0.001 |
| bge-m3 | dense | 78 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 / 0.0 / 0.001 |
| bge-m3 | hybrid | 78 | 0.0 | 0.0 | 0.0 | 0.013 | 0.0 / 0.0 / 0.001 |
| bge-m3 | hybrid + Qwen3-Reranker-0.6B | 78 | 0.0 | 0.0 | 0.0 | 0.013 | 0.0 / 0.0 / 0.001 |
| specter2_base | dense | 78 | 0.013 | 0.013 | 0.013 | 0.051 | 0.0 / 0.0 / 0.001 |
| specter2_base | hybrid | 78 | 0.0 | 0.013 | 0.002 | 0.051 | 0.0 / 0.0 / 0.001 |
| specter2_base | hybrid + Qwen3-Reranker-0.6B | 78 | 0.013 | 0.013 | 0.007 | 0.051 | 0.0 / 0.0 / 0.001 |

### Against the default, same awards (targeted)

An interval that contains 0 means the back-test cannot tell the config from the default.

| embedder | config | n | hit@10 count | default hit@10 count | + / - | MRR difference, 95% interval | p50 s per award |
|---|---|---|---|---|---|---|---|
| Qwen3-Embedding-0.6B | keyword-only | 48 | 1 | 7 | +0 / -6 | [-0.115, -0.001] | 1.03 |
| Qwen3-Embedding-0.6B | dense | 48 | 3 | 7 | +1 / -5 | [-0.101, 0.014] | 1.25 |
| Qwen3-Embedding-0.6B | hybrid | 48 | 6 | 7 | +1 / -2 | [-0.091, 0.047] | 1.96 |
| Qwen3-Embedding-0.6B | hybrid + Qwen3-Reranker-0.6B (default) | 48 | 7 | 7 | +0 / -0 | [0.000, 0.000] | 2.27 |
| Qwen3-Embedding-0.6B | hybrid + Clef-flash rerank | 48 | 5 | 7 | +0 / -2 | [-0.039, 0.017] | 5.15 |
| Qwen3-Embedding-0.6B | hybrid + Clef rerank | 48 | 4 | 7 | +0 / -3 | [-0.023, -0.001] | 12.11 |
| Qwen3-Embedding-4B | dense | 48 | 6 | 7 | +1 / -2 | [-0.092, 0.023] | 3.82 |
| Qwen3-Embedding-4B | hybrid | 48 | 5 | 7 | +1 / -3 | [-0.097, 0.035] | 4.29 |
| Qwen3-Embedding-4B | hybrid + Qwen3-Reranker-0.6B | 48 | 8 | 7 | +2 / -1 | [-0.050, 0.059] | 4.75 |
| bge-m3 | dense | 48 | 3 | 7 | +2 / -6 | [-0.114, 0.005] | 1.42 |
| bge-m3 | hybrid | 48 | 3 | 7 | +1 / -5 | [-0.109, 0.026] | 1.65 |
| bge-m3 | hybrid + Qwen3-Reranker-0.6B | 48 | 5 | 7 | +2 / -4 | [-0.089, 0.054] | 1.97 |
| specter2_base | dense | 48 | 8 | 7 | +5 / -4 | [-0.069, 0.086] | 0.97 |
| specter2_base | hybrid | 48 | 4 | 7 | +1 / -4 | [-0.099, 0.037] | 1.19 |
| specter2_base | hybrid + Qwen3-Reranker-0.6B | 48 | 9 | 7 | +5 / -3 | [-0.052, 0.065] | 1.61 |

## Fit explanation (skill 2)

| model | passed_both_layers | leads | layer1_first_pass | explained | with_unsupported | calls | p50_call_s | p50_brief_s | input_tokens | output_tokens | cost_usd | cost_per_brief_usd |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ollama:qwen3:8b | 23 of 30 | 30 | 0.967 | 0.967 | 0.2 | 31 | 15.9 | 48.5 | 59348 | 12024 | 0.0 | 0.0 |
| ollama:gemma4:26b-a4b | 28 of 30 | 30 | 0.8 | 0.933 | 0.0 | 36 | 10.9 | 42.9 | 68122 | 16657 | 0.0 | 0.0 |
| ollama:qwen3.8:27b | 28 of 30 | 30 | 0.933 | 0.933 | 0.0 | 32 | 26.3 | 78.5 | 61385 | 14607 | 0.0 | 0.0 |
| anthropic:claude-sonnet-5-5 | 24 of 30 | 30 | 0.967 | 0.967 | 0.167 | 31 | 4.7 | 25.7 | 10832 | 17528 | 0.2377 | 0.0792 |
| ollama:qwen3:14b | 26 of 30 | 30 | 0.967 | 0.967 | 0.1 | 31 | 25.0 | 74.4 | 59348 | 11122 | 0.0 | 0.0 |

## Validator layer 2 (swapped-record proxy set)

| grounder | pairs | false_flag_rate | miss_rate | auc | s_per_claim | note |
|---|---|---|---|---|---|---|
| MiniCheck-RoBERTa-Large (default, CPU) | 40 | 0.0 | 0.1 | 0.925 | 0.268 |  |
| Clef-flash (systemone) | 40 | 0.0 | 0.1 | 0.948 | 0.063 |  |
| Clef (systemone) | 40 | 0.0 | 0.1 | 0.998 | 0.194 |  |
| LLM-logprobs fallback, qwen3.8:27b | 40 | 0.0 | 0.1 | 0.985 | 0.898 |  |
| Jev (hosted) | 0 |  |  |  |  | no access to the hosted Jev API on this node; not benched |
| Strands Decider 2B | 0 |  |  |  |  | weights and licence not verified on this node; not benched |

## Cost per brief (audit log)

| model | summary_calls | summary_usd_per_call | fit_usd_per_10_lead_brief | brief_total_usd | all_calls_logged | all_usd_logged |
|---|---|---|---|---|---|---|
| anthropic:claude-sonnet-5-5 | 2 | 0.0123 | 0.0792 | 0.0915 | 39 | 0.3219 |
| ollama:gemma4:26b-a4b | 0 |  | 0.0 |  | 36 | 0.0 |
| ollama:qwen3.8:27b | 8 | 0.0 | 0.0 | 0.0 | 124 | 0.0 |
| ollama:qwen3:14b | 0 |  | 0.0 |  | 31 | 0.0 |
| ollama:qwen3:8b | 0 |  | 0.0 |  | 31 | 0.0 |

## Single-card validation

| model | gpu | grounder | briefs | briefs_done | leads | explained | p50_brief_s | max_brief_s | idle_mib_chat_and_clef | all_loaded_mib | peak_mib | qa_agreement | scout_gates |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3:14b | 5 | minicheck | 3 | 3 | 30 | 0.967 | 267.9 | 289.0 | 17769 | 21731 | 22679 | not measured: no QA log yet | not measured: Scout is S10 |
| qwen3:30b | 5 | minicheck | 3 | 3 | 30 | 0.033 | 332.0 | 335.6 | 26265 | 30873 | 31471 | not measured: no QA log yet | not measured: Scout is S10 |
| qwen3.8:27b | 5 | minicheck | 3 | 3 | 30 | 0.933 | 271.8 | 280.0 | 26097 | 30705 | 31149 | not measured: no QA log yet | not measured: Scout is S10 |
| qwen3:8b | 5 | minicheck | 3 | 3 | 30 | 0.967 | 160.8 | 174.3 | 13785 | 18393 | 19083 | not measured: no QA log yet | not measured: Scout is S10 |
| gemma4:26b-a4b | 5 | minicheck | 3 | 3 | 30 | 0.933 | 144.3 | 148.0 | 26683 | 31291 | 31729 | not measured: no QA log yet | not measured: Scout is S10 |
| gemma4:26b-a4b | 5 | clef-flash | 1 | 1 | 10 | 0.9 | 52.2 | 52.2 | 26683 | 29939 | 30259 | not measured: no QA log yet | not measured: Scout is S10 |
| gemma4:26b-a4b | 5 | clef-flash | 2 | 2 | 20 | 0.95 | 83.9 | 85.5 | 26683 | 29939 | 30271 | not measured: no QA log yet | not measured: Scout is S10 |
| gemma4:26b-a4b | 5 | clef-flash | 3 | 3 | 30 | 0.967 | 136.2 | 139.9 | 26683 | 29939 | 30553 | not measured: no QA log yet | not measured: Scout is S10 |
| qwen3.8:27b | 5 | clef-flash | 1 | 1 | 10 | 0.9 | 96.7 | 96.7 | 26097 | 29353 | 29681 | not measured: no QA log yet | not measured: Scout is S10 |
| qwen3.8:27b | 5 | clef-flash | 3 | 3 | 30 | 0.933 | 243.7 | 272.7 | 26097 | 29353 | 29975 | not measured: no QA log yet | not measured: Scout is S10 |


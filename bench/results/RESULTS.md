# Bench results

Rendered 2026-10-29 05:02 UTC by `make bench`. Numbers are copied from the CSVs in this folder; nothing here is estimated.

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

| model | gpu | briefs | briefs_done | leads | explained | p50_brief_s | max_brief_s | idle_mib_chat_and_clef | all_loaded_mib | peak_mib | qa_agreement | scout_gates |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3:14b | 5 | 3 | 3 | 30 | 0.967 | 267.9 | 289.0 | 17769 | 21731 | 22679 | not measured: no QA log yet | not measured: Scout is S10 |
| qwen3:30b | 5 | 3 | 3 | 30 | 0.033 | 332.0 | 335.6 | 26265 | 30873 | 31471 | not measured: no QA log yet | not measured: Scout is S10 |
| qwen3.8:27b | 5 | 3 | 3 | 30 | 0.933 | 271.8 | 280.0 | 26097 | 30705 | 31149 | not measured: no QA log yet | not measured: Scout is S10 |
| qwen3:8b | 5 | 3 | 3 | 30 | 0.967 | 160.8 | 174.3 | 13785 | 18393 | 19083 | not measured: no QA log yet | not measured: Scout is S10 |
| gemma4:26b-a4b | 5 | 3 | 3 | 30 | 0.933 | 144.3 | 148.0 | 26683 | 31291 | 31729 | not measured: no QA log yet | not measured: Scout is S10 |


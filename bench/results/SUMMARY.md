# Bench results, summary

Rendered 2026-10-29 19:08 UTC by `make bench` from the CSVs in `bench/results/`. Full tables: `bench/results/RESULTS.md`.

## Back-test (NIH, Temple, date cut-off)

Rank of the announcement each award was funded under, from papers before the award start. Keyword-only is the baseline. Seconds are the median per award on the targeted rows.

| Embedder | Setup | Targeted in top 10 | hit@5 | hit@10 | MRR | MRR against default, 95% interval | Parent in top 10 | Seconds per award |
|---|---|---|---|---|---|---|---|---|
| Qwen3-Embedding-0.6B | keyword-only | 1 of 48 | 0.021 | 0.021 | 0.017 | [-0.115, -0.001] | 0 of 78 | 1.03 |
| Qwen3-Embedding-0.6B | dense | 3 of 48 | 0.062 | 0.062 | 0.032 | [-0.101, 0.014] | 0 of 78 | 1.25 |
| Qwen3-Embedding-0.6B | hybrid | 6 of 48 | 0.062 | 0.125 | 0.05 | [-0.091, 0.047] | 0 of 78 | 1.96 |
| Qwen3-Embedding-0.6B | hybrid + Qwen3-Reranker-0.6B (default) | 7 of 48 | 0.104 | 0.146 | 0.066 | [0.000, 0.000] | 1 of 78 | 2.27 |
| Qwen3-Embedding-0.6B | hybrid + Clef-flash rerank | 5 of 48 | 0.062 | 0.104 | 0.056 | [-0.039, 0.017] | 1 of 78 | 5.15 |
| Qwen3-Embedding-0.6B | hybrid + Clef rerank | 4 of 48 | 0.042 | 0.083 | 0.055 | [-0.023, -0.001] | 1 of 78 | 12.11 |
| Qwen3-Embedding-4B | dense | 6 of 48 | 0.062 | 0.125 | 0.042 | [-0.092, 0.023] | 0 of 78 | 3.82 |
| Qwen3-Embedding-4B | hybrid | 5 of 48 | 0.062 | 0.104 | 0.042 | [-0.097, 0.035] | 0 of 78 | 4.29 |
| Qwen3-Embedding-4B | hybrid + Qwen3-Reranker-0.6B | 8 of 48 | 0.083 | 0.167 | 0.074 | [-0.050, 0.059] | 2 of 78 | 4.75 |
| bge-m3 | dense | 3 of 48 | 0.021 | 0.062 | 0.021 | [-0.114, 0.005] | 0 of 78 | 1.42 |
| bge-m3 | hybrid | 3 of 48 | 0.042 | 0.062 | 0.032 | [-0.109, 0.026] | 0 of 78 | 1.65 |
| bge-m3 | hybrid + Qwen3-Reranker-0.6B | 5 of 48 | 0.083 | 0.104 | 0.052 | [-0.089, 0.054] | 0 of 78 | 1.97 |
| specter2_base | dense | 8 of 48 | 0.104 | 0.167 | 0.079 | [-0.069, 0.086] | 1 of 78 | 0.97 |
| specter2_base | hybrid | 4 of 48 | 0.021 | 0.083 | 0.044 | [-0.099, 0.037] | 1 of 78 | 1.19 |
| specter2_base | hybrid + Qwen3-Reranker-0.6B | 9 of 48 | 0.104 | 0.188 | 0.075 | [-0.052, 0.065] | 1 of 78 | 1.61 |

- **Too close to call:** 12 of 14 setups have an MRR interval that contains 0, so 48 targeted awards cannot tell them from the default.
- **Measurably different:** Qwen3-Embedding-0.6B keyword-only, 1 of 48 in the top 10, interval [-0.115, -0.001]; Qwen3-Embedding-0.6B hybrid + Clef rerank, 4 of 48 in the top 10, interval [-0.023, -0.001]. A negative interval means worse than the default.
- **Parent announcements:** these are general calls, and almost none rank in the top 10 under any setup.

## Fit explanations (skill 2)

Passed both checks: the citation validator passed and the grounding check found no unsupported sentence. Cost covers the summary and 10 explanations where both were logged, otherwise the explanations only.

| Model | Passed both checks | p50 brief s | Cost per brief, USD |
|---|---|---|---|
| ollama:gemma4:26b-a4b | 28 of 30 | 42.9 | 0.0 |
| ollama:qwen3.8:27b | 28 of 30 | 78.5 | 0.0 |
| ollama:qwen3:14b | 26 of 30 | 74.4 | 0.0 |
| anthropic:claude-sonnet-5-5 | 24 of 30 | 25.7 | 0.0915 |
| ollama:qwen3:8b | 23 of 30 | 48.5 | 0.0 |

## Grounding check (validator layer 2)

Supported sentences against the same sentences with a swapped record. AUC is how well the score separates the two; 1.0 is perfect. Rates are at the 0.5 threshold.

| Grounder | Pairs | AUC | False flags | Misses | Seconds per sentence | Note |
|---|---|---|---|---|---|---|
| MiniCheck-RoBERTa-Large (default, CPU) | 40 | 0.925 | 0.0 | 0.1 | 0.268 |  |
| Clef-flash (systemone) | 40 | 0.948 | 0.0 | 0.1 | 0.063 |  |
| Clef (systemone) | 40 | 0.998 | 0.0 | 0.1 | 0.194 |  |
| LLM-logprobs fallback, qwen3.8:27b | 40 | 0.985 | 0.0 | 0.1 | 0.898 |  |
| Jev (hosted) | 0 | not benched |  |  |  | no access to the hosted Jev API on this node; not benched |
| Strands Decider 2B | 0 | not benched |  |  |  | weights and licence not verified on this node; not benched |

## Private context, stand-in proposal (upper bound)

Each targeted award's own funded NIH abstract added as a private proposal thread at 0.6 of the weight, as private mode does. A funded abstract is far closer to the award than a real draft, so this bounds the gain from above; it does not estimate it. Details: `bench/results/PROPOSAL_STANDIN.md`.

| Setup | Targeted in top 10 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|
| keyword-only | 1 of 48 | 0.021 | 0.021 | 0.027 |
| keyword-only + funded abstract | 4 of 48 | 0.042 | 0.083 | 0.06 |
| hybrid+rerank | 7 of 48 | 0.104 | 0.146 | 0.067 |
| hybrid+rerank + funded abstract | 16 of 48 | 0.25 | 0.333 | 0.191 |

- **Default setup, paired:** 24 awards ranked higher with the abstract, 6 lower, 18 the same. MRR difference 95% interval [0.042, 0.218].

## Scout agent

Scripted follow-ups in `bench/scout_tasks.yaml`, newest run per model. A task passes when Scout used an allowed tool with the right arguments and its answer passed the validator. Small sets: they show the follow-ups work, they do not estimate a failure rate. Details: `bench/results/RESULTS.md`.

| Model | Policy | S10 tasks | Restraint | Route B tasks | Compare and hand-off | Wrong-tool calls | Answers withheld | Cost, USD | Median s |
|---|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5-5 | native | 20/20 | 6/6 | 5/5 | 3/3 | 0/27 | 0 | 0.4074 | 8.1 |
| gemma4:26b-a4b | native | 18/20 | 6/6 | 5/5 | 2/3 | 1/26 | 1 | 0.0 | 4.4 |
| qwen3:8b | native | 17/20 | 5/6 | not run | not run | 1/14 | 1 | 0.0 | 36.9 |
| qwen3:8b | structured | 12/20 | 6/6 | not run | not run | 1/14 | 5 | 0.0 | 12.4 |

## One card, briefs at once

Chat model, Clef-flash, embedder and reranker on one clean GPU. The gate is a peak under 28 GB. MiniCheck rows also load MiniCheck on the GPU, which deploy-1gpu does not; the Clef-flash rows match deploy-1gpu.

| Model | Grounder | Briefs at once | Before briefs MiB | Peak MiB | p50 brief s | Explained | QA and Scout gates |
|---|---|---|---|---|---|---|---|
| qwen3.8:27b | clef-flash | 1 | 29353 | 29681 | 96.7 | 0.9 | not measured |
| qwen3.8:27b | clef-flash | 3 | 29353 | 29975 | 243.7 | 0.933 | not measured |
| gemma4:26b-a4b | clef-flash | 1 | 29939 | 30259 | 52.2 | 0.9 | not measured |
| gemma4:26b-a4b | clef-flash | 2 | 29939 | 30271 | 83.9 | 0.95 | not measured |
| gemma4:26b-a4b | clef-flash | 3 | 29939 | 30553 | 136.2 | 0.967 | not measured |
| qwen3:8b | minicheck | 3 | 18393 | 19083 | 160.8 | 0.967 | not measured |
| qwen3:14b | minicheck | 3 | 21731 | 22679 | 267.9 | 0.967 | not measured |
| qwen3.8:27b | minicheck | 3 | 30705 | 31149 | 271.8 | 0.933 | not measured |
| qwen3:30b | minicheck | 3 | 30873 | 31471 | 332.0 | 0.033 | not measured |
| gemma4:26b-a4b | minicheck | 3 | 31291 | 31729 | 144.3 | 0.933 | not measured |


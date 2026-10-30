# Bench results

Rendered 2026-10-29 20:50 UTC by `make bench`. Numbers are copied from the CSVs in this folder; nothing here is estimated.

## S27 ranking tune (2026-10-30)

Rounds scored with `bench/tune.py` on the NIH back-test (same rows, pool and date cut-off as above, eligibility rules as of S27). One award in 48 is about 0.021, so differences of one or two awards are noise.

| round | change | targeted n | hit@5 | hit@10 | MRR | parent n | parent hit@10 | parent MRR |
|---|---|---|---|---|---|---|---|---|
| baseline | keyword-only (BM25, no rerank) | 48 | 0.021 | 0.021 | 0.027 | 78 | 0.0 | 0.001 |
| R0 | production before S27 | 48 | 0.104 | 0.146 | 0.067 | 78 | 0.013 | 0.013 |
| R1 | blend retrieval score into rerank (0.7, 0.5, 0.3) | 48 | 0.104 / 0.104 / 0.083 | 0.146 / 0.167 / 0.167 | 0.060 / 0.053 / 0.045 | | | |
| R2 | thread query adds OpenAlex topic names | 48 | 0.146 | 0.167 | 0.109 | | | |
| R3 | rerank 100 candidates (was 50) | 48 | 0.188 | 0.188 | 0.109 | | | |
| R3 | retrieval depth 200 per list | 48 | 0.125 | 0.146 | 0.077 | | | |
| R4 | topics + rerank 100 (**new default**) | 48 | 0.188 | 0.208 | 0.149 | 78 | 0.026 | 0.016 |
| R4 | topics + rerank 150 / 200 | 48 | 0.188 / 0.188 | 0.208 / 0.208 | 0.138 / 0.134 | | | |

**Hand check, not a measurement.** Six Temple PIs on today's listings, all agencies. Papers include the funded work, so this is a sanity check only. The NSF program behind each NSF PI's latest award ranks first under R4 for PI-130 and PI-131 (MPS Chemistry) and PI-132 and PI-133 (MPS Physics); PI-131 and PI-133 were held out of tuning. PI-1 and PI-7 get NIH cancer programs. There is no NSF back-test: Grants.gov's NSF archive lacks most 2015 to 2021 listings and carries a bulk open date of 2025-06-06 on 291 of them.

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


<!-- Written by hand below this line; make bench keeps it. -->

## Scout agent (S10)

20 scripted follow-ups in `bench/scout_tasks.yaml`: 14 tasks and 6 restraint cases, on three researchers, as of 2026-10-29. Run with `python -m bench.scout <model>`; per-task rows in `scout_<model>.csv`, totals in `scout_summary.csv`. Every session ran in "run" mode on the dev store.

How each number is defined:
- **Completed:** the session ended with an answer that passed the citation validator, every expected tool ran with matching arguments, and no wrong tool ran.
- **Wrong-tool rate:** calls to a tool outside the task's allowed list, including names outside the allowlist, divided by all calls.
- **Restraint:** the six cases where the right move is to decline or to say a value is not in the record (send email, foundations, an amount the record lacks, an unpublished draft, a percentage chance, a web search). A case passes with no wrong call and an answer that passed the validator. This checks that nothing was done or invented; it does not judge the wording of the refusal.

| Model | Policy | Completed | Tasks | Restraint | Wrong-tool rate | Answers withheld | Tokens | Cost | Median s |
|---|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5-5 | native | 20/20 | 14/14 | 6/6 | 0 of 18 calls | 0 | 70,686 | $0.26 | 6.4 |
| gemma4:26b-a4b | native | 20/20 | 14/14 | 6/6 | 0 of 17 calls | 0 | 82,094 | $0 | 3.9 |
| qwen3:8b | native | 17/20 | 12/14 | 5/6 | 1 of 14 calls (0.071) | 1 | 73,765 | $0 | 36.9 |
| qwen3:8b | structured fallback | 12/20 | 6/14 | 6/6 | 1 of 14 calls (0.071) | 5 | 82,675 | $0 | 12.4 |

Reading it:
- **The fallback is not a gain on qwen3:8b.** It completed 12 of 20 against 17 of 20 with native tool calls. Most of its failures were answers withheld by the validator, or answers given without calling a tool. It stays as the path for models with no tool calling at all; it is not the default for any model that has it.
- **qwen3:8b timings are not comparable.** It shared GPU 0's Ollama with Gemma and a browser test during its native run, so models were swapped in and out.
- **Twenty tasks is a small set.** A 20 of 20 says these follow-ups work; it does not estimate a failure rate.

First runs, kept in `scout_first_runs/`: Gemma completed 18 of 20 and Sonnet 17 of 20 before three fixes, after which every model above was rerun on all 20 tasks.
- **Researcher id not citable:** the profile tool showed the researcher's id without registering it as a record, so a correct citation was rejected (Gemma t06).
- **Three filters had no description:** Gemma said it had no way to leave out terms (t04).
- **Strict tool use:** with Anthropic's strict schemas, Sonnet left out `min_amount` and `closes_by` and repeated the same search up to nine times (t01, t02, t11). Two direct calls showed it: strict mode sent `{"agencies": ["NIH"], "exclude_agencies": [], "top": 20}`, and non-strict mode sent `{"agencies": ["NIH"], "min_amount": 500000}`. Scout's tools now go without strict mode; Scout checks every call's arguments itself.

API spend for S10: about $0.93 under a $1.00 cap approved by Dakshitha (Q17), including the first run and the two diagnostic calls. The ledger total to the demo is $1.25 of $100.

## Scout after S11: Route B and the repeated-call guard

Rerun of every task in `bench/scout_tasks.yaml` on 2026-10-29: the 20 S10 tasks, unchanged, plus 5 Route B tasks (b01 to b05; b05 is a restraint case, "will BioNTech fund this lab? yes or no"). The summary reports the two sets separately. `search_opportunities` with route B scores as `get_org_signals`.

| Model | Policy | S10 tasks completed | Tasks | Restraint | Route B tasks | Wrong-tool rate | Answers withheld | Tokens | Cost | Median s |
|---|---|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5-5 | native | 20/20 | 14/14 | 6/6 | 5/5 | 0 of 22 calls | 0 | 83,446 | $0.34 | 7.3 |
| gemma4:26b-a4b | native | 19/20 | 13/14 | 6/6 | 5/5 | 0 of 21 calls | 1 | 106,715 | $0 | 3.9 |

Reading it:
- **The repeated-call guard never fired.** Neither model repeated a call in these runs, so the bench says nothing about the guard. A unit test covers it in run and ask modes.
- **Gemma t06 failed, and it fails on the S10 code too.** The S10 commit, run today on the same store and model, also wrote a "1" that no record supports in its answer about research threads. So this is not a regression from S11 code. Why it passed in S10 is not known.
- **An added Scout rule broke Gemma t04.** A rules line telling Scout to call Route B leads inferred made Gemma answer t04 ("drop anything that mentions clinical trials") without searching, three runs in three. With the S10 rules text it searched and passed. The rules are back to the S10 text; the "inferred, not verified" label travels in every Route B tool result instead.
- **Sonnet ran with that extra rule line.** Its row above is from the run before the line was removed. A second Sonnet run would have gone past the $0.60 cap Dakshitha approved for S11.
- **Five Route B tasks is a small set.** 5 of 5 says these follow-ups work; it does not estimate a failure rate.

API spend for S11: $0.34 under a $0.60 cap approved by Dakshitha. The ledger total to the demo is $1.62 of $100.

## Scout after S12: compare and hand-off

Rerun of all 28 tasks in `bench/scout_tasks.yaml` on 2026-10-29: the 20 S10 tasks, the 5 Route B tasks, and 3 new ones. The new ones are c01 (compare the top two R21s), h01 (a hand-off to Technology Commercialization about the top industry lead) and h02, a restraint case ("send an email to Research Development"). The summary reports each set separately.

| Model | S10 tasks completed | Tasks | Restraint | Route B tasks | Compare and hand-off | Wrong-tool rate | Answers withheld | Tokens | Cost | Median s |
|---|---|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5-5 | 20/20 | 14/14 | 6/6 | 5/5 | 3/3 | 0 of 27 calls | 0 | 103,516 | $0.41 | 8.1 |
| gemma4:26b-a4b | 18/20 | 12/14 | 6/6 | 5/5 | 2/3 | 1 of 26 calls | 1 | 147,940 | $0 | 4.4 |

- **Gemma c01 failed on a wrong tool.** It called `build_profile` before searching, and the task does not allow it. The task was kept as written.
- **Gemma t06 still fails, as in S11.** It writes a "1" that no record supports.
- **Gemma t04 failed this time and passed in S11.** It searched without the "clinical trial" exclusion. The Scout rules are unchanged. The tool list now has two working tools in place of two "not built" ones, and that may matter, but this was not tested. It could also be run-to-run variation.
- **The drafts' opening paragraphs were written by Gemma in both runs.** `draft_handoff` uses the configured hand-off model (`PERCH_LLM_HANDOFF`, here the profile's Gemma), not the Scout model. The audit log shows `gemma4:26b-a4b` for every hand-off call in the Sonnet run. So the compare and hand-off column measures Scout's tool choice, not Sonnet's drafting.
- **h02's wording was not checked.** Sonnet drafted a hand-off in h02, which the task allows. A pass means its answer passed the validator and used no wrong tool. The Scout log keeps only a hash of each answer, so whether the answer also said that Perch cannot send email was not read.
- **Three new tasks is a small set.** 3 of 3 says these follow-ups work; it does not estimate a failure rate.

API spend for S12: the ledger rose $0.43, under a $0.50 cap approved by Dakshitha. The bench rows sum to $0.41. The ledger total to the demo is $2.05 of $100.

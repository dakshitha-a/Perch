# Perch results

Written 2026-11-01 (S32) for the Demo Day deck and extended on 2026-11-04 with the v1 sections (S38 and S47). The sections before "S38 rebuild" measure the fallback build (tag `v0.1-demo-fallback`: local models, in-memory sessions, SQLite). They are not measurements of the v1 stack with accounts, except where a row says `cloud-gpu`. Every number below is copied from the file named beside it. Where a number is not in the record, the page says UNVERIFIED.

Perch reads a Temple researcher's public papers, or a student's CV, and lays out the routes to fund the work: open federal grants and industry leads for a researcher, fellowships and scholarships for a student, every claim cited to its record, then a hand-off draft or note for the right Temple office. Nothing is sent. This page reports four things that were measured (retrieval on an NIH back-test, citation grounding, the Scout agent, speed and cost) and two that are mechanism tests on invented data (student mode, draft review). The student side has its own section of equal weight; its numbers are mechanism checks on SYNTHETIC data and never mix with the measured tables (standing rule 11). The keyword-only baseline sits beside every retrieval number.

## Retrieval, NIH back-test

For each of 126 Temple NIH awards, Perch sees only papers published before the award start. It searches the NIH announcements open on Grants.gov in the 18 months before that date and we record the rank of the announcement the award was funded under. The 126 rows are the ones with a fully fetched window: 48 targeted and 78 parent (`docs/TRACKER.md`, S8 row; `bench/results/RESULTS.md`).

| Setup | Stratum | n | hit@5 | hit@10 | MRR |
|---|---|---|---|---|---|
| Default (topic queries, 100 reranked) | targeted | 48 | 0.188 | 0.208 | 0.144 |
| Keyword-only baseline (same query) | targeted | 48 | 0.042 | 0.042 | 0.032 |
| Default | parent | 78 | 0.026 | 0.026 | 0.016 |
| Keyword-only baseline | parent | 78 | 0 | 0 | 0 |

- **Sources:** targeted rows and keyword-only rows are in `bench/results/RESULTS.md` (S27 section) and `docs/TRACKER.md` (key numbers). Parent default hit@5 is in `bench/results/tune/tune_20261030T1706.json`. Keyword-only parent MRR is 0.001 there, shown as 0 in the tracker.
- **In awards:** the default puts the funded announcement in the top 10 for 10 of 48 targeted awards and 2 of 78 parent awards. Keyword-only gets 2 of 48 and 0 of 78. Before the S27 tune the default was 0.104 / 0.146 / 0.067, and keyword-only without topic names was 0.021 / 0.021 / 0.027 (`bench/results/RESULTS.md`).
- **The tuning used the same 48 rows.** Part of the gain from 0.146 to 0.208 is fitted to them. One award in 48 is about 0.021, so a difference of one or two awards is noise (`bench/results/RESULTS.md`).
- **Stand-in proposal, upper bound:** adding each award's own funded abstract as a draft raised the default to hit@5 0.271, hit@10 0.354 (17 of 48) and MRR 0.206, against 0.042 to 0.083 for keyword-only in the same section. A real draft is further from the funded call than that abstract, so this is a ceiling, not a gain (`bench/results/RESULTS.md`; the earlier S13 run is `bench/results/PROPOSAL_STANDIN.md`).
- **Match score:** on the 126 rows, 12 put the funded announcement in the top 10. The 10 targeted ones scored 80 or more and the 2 parent ones scored 55 and 70. The calibration data is all NIH, and there is no NSF back-test (`bench/results/RESULTS.md`).

## Grounding

Every model sentence passes a citation validator, and a second grounding check looks for unsupported sentences. Passed both, on 30 leads (3 researchers, 10 leads each), run in S8 (`bench/results/RESULTS.md`, `bench/results/SUMMARY.md`):

| Model | Passed both checks | Cost per brief |
|---|---|---|
| Gemma 4 26B-A4B (local, demo model) | 28 of 30 | $0 |
| qwen3.8:27b (local) | 28 of 30 | $0 |
| qwen3:14b (local) | 26 of 30 | $0 |
| claude-sonnet-5-5 (API) | 24 of 30 | $0.0915 |
| qwen3:8b (local) | 23 of 30 | $0 |

- **Reading it:** the API model passed fewer leads than the best local models. Sonnet had unsupported sentences in 0.167 of leads; Gemma had none (`bench/results/RESULTS.md`).
- **Grounding model check:** on 40 swapped-record pairs, Clef separated them with AUC 0.998 and MiniCheck with 0.925. Both missed 0.1 of the swaps and falsely flagged none (`bench/results/SUMMARY.md`). This is a proxy set, not real model output.
- **Not rerun since S8:** these pass rates predate the S27 to S31 changes.

## Scout

Scripted follow-up questions, checked for the right tool, the right arguments and a validated answer (`bench/results/scout_summary.csv`, `bench/results/RESULTS.md`). Wrong-tool rate is wrong calls over all calls.

| Run | Model | Completed | Wrong-tool rate | Source |
|---|---|---|---|---|
| S10, 20 tasks | Sonnet / Gemma | 20/20 / 20/20 | 0 of 18 / 0 of 17 | `bench/results/RESULTS.md` |
| S12, 28 tasks | Sonnet / Gemma | 28/28 / 25/28 | 0 of 27 / 1 of 26 | `bench/results/scout_summary.csv` |
| S28, 28 tasks | Sonnet | 28/28 | 0 of 27 | `bench/results/scout_s28/` |
| S28, 28 tasks | Gemma | 23/28 | 2 of 29 | `bench/results/scout_s28/` |
| After QA round 3, 28 tasks | Gemma | 25/28 | 1 of 30 | `bench/results/scout_qa3/` |
| Latest (round 5), 29 tasks | Gemma | 28/29 | 1 of 31 (0.032) | `bench/results/scout_qa5/` |

- **Latest runs:** Sonnet was last run in S28 and not rerun after. Gemma's latest is `scout_qa5`, whose one miss is the compare task c01, a wrong-tool call. The task set grew from 20 to 29, so rows are not strictly comparable. The S28 and later rows come from per-task CSVs; the rates were counted from those rows.
- **Restraint cases** (decline, or say a value is not in the record): 8 of 8 in the latest Gemma run and in both S28 runs.
- **Rehearsal gate:** the three demo questions are run on the researcher, student and documents paths, on three variants of the demo brief. Before the context fix in QA round 3 the gate passed 0 of 9. It passed 45 of 45 at the end of S31 (`docs/sessions/S31.md`).
- **Cause of the earlier failures:** the demo model's 8,192-token context truncated Scout's rules. History compaction now keeps every call under 6,400 tokens, and 0 of 3,502 calls were truncated in round 5 (`docs/sessions/S31.md`, `docs/design/qa/CYCLE_5.md`).
- **Small sets.** 28 of 29 says these follow-ups work. It does not estimate a failure rate.

## Speed and cost

- **Warm brief (v0, fallback build only; warm briefs are retired in v1):** the demo researchers' briefs are held in memory and open in 17 ms. The full warm click path (5 screens, 14 clicks, a hand-off draft and a Scout answer) took 17.6 s wall (`docs/TRACKER.md` S24 row; `docs/design/WORKFLOW_REVIEW.md`, path tables).
- **Live brief:** 41.9 s after the S30 fixes, from 46.6 s (`docs/TRACKER.md`, S30 row). The QA rounds saw 36 s on a quiet server and 41 s beside another build (`docs/design/qa/CYCLE_5.md`). Under load a second brief waits in line. Live build time on the rebuilt demo: 38.7 s for a live brief on a phone through the public URL after the rebuild, with the researcher's record already cached (`docs/sessions/S32.md`).
- **Two model slots:** the same brief took 42.7 s with one slot and 38.6 s with two, measured on a spare card (`docs/design/WORKFLOW_REVIEW.md`, P1 measurement). The demo unit now runs two slots (`docs/sessions/S32.md`).
- **S30 speed changes:** student polls fell from 8.06 MB to 0.41 MB, static files from 326 KB to 95 KB, and a cached rerank takes about 1 ms (`docs/TRACKER.md`, S30 row).
- **Cost per 10-lead brief:** $0.0915 on claude-sonnet-5-5 ($0.0792 explanations, $0.0123 summary), $0 on local models (`bench/results/cost.csv`). The demo runs local by default. Scout's 28-task bench cost $0.46 on Sonnet (`bench/results/scout_s28/`). Anthropic spend to date: $2.09 of $100 (`docs/TRACKER.md`, key numbers, as of 2026-10-29).

## Student mode (SYNTHETIC, mechanism test)

A student brief reads a CV by rule, lists public fellowships and sample scholarships with a verdict and a Still needed list for each, and drafts a note to Scholar Development and Fellowships Advising or Student Financial Services (S18). All scholarships and personas here are invented sample data. These numbers check that the code does what the written rules say. They say nothing about real scholarships or real students, and they are not a result about Temple (`bench/results/STUDENT_MODE.md`).

**What was planted.** 500 SYNTHETIC scholarships with 105 fictional sponsors and 0 real-name hits; 24 of them planted by hand as test cases for 3 personas, with hand-written keys of 7 eligible, 5 may be eligible and 12 not eligible. The fellowship side reads Temple's public SDFA list, 76 award records with no amounts or deadlines on the page (`docs/TRACKER.md`, key numbers and S17 row).

| Persona | Brief | Planted retrieved | Precision | Recall | Verdict exact | Gap list exact |
|---|---|---|---|---|---|---|
| persona-ug | 57 s | 7 of 8 | 1.00 | 1.00 | 7 of 7 | 3 of 3 |
| persona-masters | 45 s | 8 of 8 | 1.00 | 1.00 | 8 of 8 | 4 of 4 |
| persona-phd | 45 s | 8 of 8 | 1.00 | 1.00 | 8 of 8 | 4 of 4 |
| all | | 23 of 24 | 1.00 | 1.00 | 23 of 23 | 11 of 11 |

- **Planted records retrieved:** 23 of 24 across 3 personas (`bench/results/STUDENT_MODE.md`). At the earlier retrieval depth of 40 it was 19 of 24 (`bench/results/RESULTS.md`). The one miss is sample:sch-0008, which never reached a brief, so the rules never saw it.
- **Precision and recall of "may apply":** 1.00 and 1.00, counted on the retrieved records only. Verdicts matched the hand-written key on 23 of 23, and gap lists on 11 of 11.
- **End to end:** the student would see 11 of the 12 planted records they may apply for.
- **The key and the code follow the same rules,** so a perfect match is a check of the code, not evidence the rules suit real awards. Fellowships are real public listings with no key and are not scored; their best verdict is "may be eligible" by design.
- **Leakage:** none on seven checks: no sample record in the public API, none in public briefs, no persona canary in an export, data file or app log, and no export without the sample banner. (Since 2 Nov 2026 a plain private-session export is meant to carry the user's own document text, so the export part of the third check now applies to hand-off drafts and to stores, logs and caches, not to the user's own export.) Rerun over HTTP on the rebuilt demo in S32, clean (`docs/TRACKER.md`, key numbers). The export check ran before 2 Nov 2026, when private-session exports began to give the full brief; since then a plain export is meant to carry the user's own document text, so the export check no longer applies to it. The canary rerun on the dev server on 2 Nov 2026 was clean: no canary token on disk, in /tmp or in the six model journals, no data file changed, and 0 new cache keys; the exports held 10 and 15 full explanations. Briefs took 45 to 57 s.
- **Scout on the student path:** the rehearsal gate's student runs are part of the 45 of 45 above, and the student export fell from 1,391 lines to about 410 in QA round 5 (`docs/TRACKER.md`, key numbers).
- **Cover points (S33):** the `cover_points` skill serves both audiences. Measured on the dev stack with the local chat model (gemma4:26b-a4b, no cloud call, no spend), `bench/results/scout_s33_1/`:
  - **Bench:** the full Scout task set, now 30 tasks with the new cover-points task p01, completed 30 of 30 with 0 wrong-tool calls and 0 withheld answers. p01 built a profile, searched, then called `cover_points` once, which returned a checked set of points with the answer line written by code (23.4 s). The bench runs researcher sessions only, so there is no student bench task. One run each, so this shows the step works, not a failure rate.
  - **Rehearsal:** scripts/demo_rehearsal.py, three runs per question, all pass: researcher cover letter question 3 of 3 (10 to 18 s, one step, 3 to 6 points, each asks half cited to the record alone, each you half cited to at least one applicant record, answer line by code), student application question on the SYNTHETIC persona-ug 3 of 3 (9 to 10 s), and the existing questions 3 of 3 each. 21 of 21 in all.
  - **Sample record, live:** on the SYNTHETIC student persona, points for a sample scholarship by name returned 4 points, 3 of the step's sentences flagged by the grounder, the Sample data badge on the card and the line "This is an invented sample record." written by code.
  - **Privacy canary:** clean. The CV goes to the chat model for this tool with contact details blanked; after a cover-points question in a documents session on the SYNTHETIC persona-1, no canary token was in `data/`, in `/tmp` or in the model servers' journals.
  - **Walk:** the full walk with axe on the dev server, 227 states, 0 errors, 0 axe violations, 0 sideways scroll; 86 targets under 24 px, all inline links or hidden file inputs.
  - **Tests:** 421 passed.

## Industry leads

The agent that built Perch judged 14 leads for 3 researchers against the records each cites: 8 yes, 6 thin, 0 wrong (`bench/results/route_b/JUDGMENTS.md`). The first run, before papers with more than 30 authors were excluded, was 7 yes, 3 thin and 5 wrong of 15. The exclusion was chosen after seeing that run, on the same researchers, so the second row is not independent. A person has not checked it. There is no baseline for this task. Every lead is labelled inferred, not verified.

## Quality process (S29 to S31)

- **Reviews:** two independent fresh-context reviews, one of workflow and security and one of UI and UX, found 86 findings. 84 were fixed and 2 deferred (`docs/TRACKER.md`, S29 and S30 rows). The reviewers and fixers were Claude Opus agents.
- **QA rounds:** five rounds, each a fresh tester then a fixer, found 129 findings and fixed 125. Two were partly fixed, one was dropped and one was done at the deploy file (`docs/TRACKER.md`, S31 row).
- **Checks:** tests rose from 265 to 398. The full browser walk reached 217 states with 0 errors and 0 axe accessibility violations. The privacy canary was clean every round.
- **Live walk on the public URL after the rebuild (S32, 1 Nov 2026):** on the final build 219 states, 0 errors, 0 sideways scroll, 2 axe target-size hits from one card title scrolled under the sticky tab bar on the phone (`docs/sessions/S32.md`); an earlier live walk had one error, a two-part Scout question's NSF half withheld by the citation check, the designed fallback. Rehearsal on the demo 45 of 45; demo questions 5 to 6 s each.

## S38 rebuild: CPU, GPU, back-test, grounding (v1, `cloud-gpu` profile)

Every number is copied from the file named in its row. The back-test is NIH only, with the papers-before-award-start cut-off, and the keyword-only baseline is on every row. These rows measure speed and compare setups. A setup that scores the same as another is not a gain.

| What | Result | File |
|---|---|---|
| CPU timings, 16 cores, fp32, shared node | Query embed 270 to 316 ms; rerank of 14 candidates 9,386 ms; rerank of 50 32,472 to 41,027 ms; rerank of 100 58,192 to 65,379 ms; MiniCheck 619 to 635 ms per sentence. The `cloud-cpu` profile therefore reranks 14. | `bench/results/s38_cpu/README.md` |
| GPU timings, GPU 3, 0.6B reranker | Query embed 27.4 ms; rerank of 14 candidates 147 ms; of 50 468 ms; of 100 787 ms; MiniCheck 31.6 ms per sentence. The 4B reranker takes 3,710 ms for 100. | `bench/results/s38_gpu/README.md` |
| CPU brief with the fake model, cold vs pre-cached | 82.6 s cold; 2.2 s after the pre-cache job. Model text time is not in these numbers. | `bench/results/s38_cpu/README.md` |
| CPU back-test, targeted, hybrid | hit@10 0.062 at rerank 14 and 0.229 at rerank 100. Keyword-only (tsvector) 0.000. | `bench/results/s38_backtest/README.md` |
| GPU back-test, targeted, 48 awards, hit@10 / MRR | Keyword-only 0.000 / 0.002. Dense + 0.6B 0.250 / 0.142. Hybrid + 0.6B 0.229 / 0.125. Dense + 4B 0.250 / 0.132. Hybrid + 4B 0.229 / 0.125. | `bench/results/s38_backtest_gpu/README.md` |
| GPU back-test, parent, 78 awards, hit@10 / MRR | Keyword-only 0.000 / 0.000. Dense + 0.6B 0.051 / 0.032. Hybrid + 0.6B 0.013 / 0.004. Dense + 4B 0.051 / 0.025. Hybrid + 4B 0.000 / 0.001. | same |
| 4B against 0.6B reranker | No measurable difference: every paired 95 percent interval on the MRR difference spans zero. The 4B costs about 4.5 times the rerank time. The 0.6B is kept. | same, `paired_bootstrap.txt` |
| Dense against hybrid | Dense is at least as good on every metric, by one to four awards. Recall@200 is 0.500 dense and 0.417 hybrid. | same |
| Grounding proxy set, 40 pairs, MiniCheck on CPU | AUC 0.922, false-flag rate 0.0, miss rate 0.1, 0.362 s per claim. | `bench/results/s38_grounding/grounders_cpu.csv` |
| Grounding proxy set, 40 pairs, MiniCheck on GPU 3 (fp32) | AUC 0.922, false-flag rate 0.0, miss rate 0.1, 0.017 s per claim. Same AUC as CPU. | `bench/results/s38_grounding/grounders_cuda.csv` |
| Cost per researcher brief, real provider, `cloud-gpu` (2026-11-04) | 5 briefs for 5 distinct public researchers, 10 leads each, all succeeded. Per brief: 11 to 13 calls (Haiku 5.5 profile summary, Sonnet 5.5 fit explanations with regenerations), mean $0.0833 (min $0.0766, max $0.0957); mean tokens 12,500 input, 7,076 output, 31,492 cache read, 3,322 cache write; wall time median 37.7 s, max 50.3 s, after a warm-up brief. Hand-off and cover points are not in these numbers. At the start tier's 400K output tokens a minute, 7,076 output tokens per brief allows about 56 briefs a minute (arithmetic). Student briefs: NOT YET MEASURED; the v1 student path lands in Phases 5 and 6. | `bench/results/s38_cost/researcher_briefs.txt` |
| Scout bench on `cloud-gpu`, Sonnet 5.5 (2026-11-04) | 30/30 completed, 22/22 tasks, 8/8 restraint, 0/34 wrong calls, 0 flagged, 85,494 tokens, $0.4175, median 8.05 s. The task set has grown since the last recorded Sonnet row (20 cases: 20/20, 14/14 tasks, 6/6 restraint, 0/27 wrong calls, $0.4074, median 8.1 s), so the two rows are not the same set. | `bench/results/scout_s38_cloudgpu/scout_anthropic-claude-sonnet-5-5.csv`, `bench/results/scout_summary.csv` |

The grounding set is a proxy built from saved explanations, not human labels. It has 40 pairs, so one pair moves the miss rate by 0.025.

## S40 Temple awards dataset (v1 rebuild, Phase 4)

| Measure | Value | Source |
|---|---|---|
| Pages read | 142 of 461 inventoried pages (316 had no HTTP 200 in the inventory, 3 need sign-in) | `docs/SOURCES.md` Temple award pages table |
| Extraction | Two runs on Haiku 5.5, $0.220 and $0.214. Run 1: 309 records kept of 311 proposed. Run 2, with the widened Temple-funded rule: 289 of 291 | `data/temple/dataset/temple_awards_v2.manifest.json` |
| Quote check, run 2 | Amounts kept 60 of 89; dated deadlines 21 of 21; yearless deadlines kept as text only 33; eligibility lines 401 of 410; links 131 of 131; Temple-funded 17 of 189 | extraction log, summarised here |
| Dataset v2 | 310 records after dedupe of both runs (598 in, 238 merged groups, 7 pairs kept apart, 8 same-page reads with the disputed field set to not stated); 17 Temple-funded | `data/temple/dataset/temple_awards_v2.manifest.json` |
| Names | People's names outside award titles removed at build: 12 spots in v2. Independent read-only checks: 15 people found in v1 before the scrub, 0 after; v2 0, with no contacts | `perch/temple_names.py`, DECISIONS 2026-11-04 |
| Hand-check of v1, fresh-context reviewer | 29 records, 203 field rows: 188 correct, 4 wrong, 11 missing; error rate 7.4% (95% interval 4.5% to 11.8%, rows not independent). 10 of the 15 were Temple-funded left empty; without that field 5 of 174 rows (2.9%). The Temple-funded rule was widened for v2; v2's error rate is not yet measured (S46) | `bench/results/s40_handcheck/sheet.csv` |
| Hand-check of v2, fresh-context reviewer (S46) | 31 records, 217 field rows: 181 correct, 7 wrong, 29 missing; error rate 16.6% (95% interval 12.2% to 22.1%, rows not independent). Temple-funded left empty on 19 of 21 rows a Temple unit presents as its own; under a narrower reading (explicit funding wording only) 6 of 8, and the overall rate is 10.6% (7.2% to 15.4%). Eligibility 9 of 31 rows partial or wrong; 2 wrong amounts (a fund total kept as the per-project amount; a stipend and an allowance kept as a range); 2 missed deadlines, one a pipeline bug (deadline quote kept, deadline field empty). v2 is not better than v1. The Temple filter uses the listing source, not the Temple-funded field, so that field's misses do not change what users see. No name leaks outside the title exception | `bench/results/s46_handcheck_v2/` |

## S45 Scout open-question bench (v1 rebuild, Phase 8)

Real model (Sonnet 5.5 answers, Haiku 5.5 gate), 63 questions written by Perch-dev: 34 in scope, 24 out of scope, 5 distress. "Layer 1 pass" means the answer shown passed every rule on its first or second draft; "flagged" means both drafts failed and the failing sentences were removed. Usefulness is graded by a person in `grades.csv`, not yet done. The old Scout ran on researcher questions only, with no gate, no brief and no CV.

| Run | What changed | In scope: Layer 1 pass / flagged / empty | MiniCheck flags | Out of scope refused | Distress | Cost | Folder |
|---|---|---|---|---|---|---|---|
| Old Scout | S32 build | 17 of 18 / 0 / 0 | not run | 4 of 9 | 0 of 2 | $0.48 | `bench/results/scout_open_s45/` |
| s45 | first run of the new Scout | 4 of 33 / 29 / 7 | 22 | 24 of 24 | 5 of 5 | $1.08 | `bench/results/scout_open_s45/` |
| s45b | grounding rules fixed (citation placement, abbreviations, help and headings) | 23 of 33 / 10 / 0 | 96 | not run | not run | $0.91 | `bench/results/scout_open_s45b/` |
| s45c | security fixes, rounds 1 and 2 | 12 of 33 / 21 / 0 | 14 | 24 of 24 | 5 of 5 | $1.04 | `bench/results/scout_open_s45c/` |
| s45f | over-strict removals fixed; output cap raised | 16 of 33 / 17 / 0 | 37 | not rerun | not rerun | $0.93 | `bench/results/scout_open_s45f/` |
| s45g | shape rules; distress never budget-gated (before the claim-tail rule) | 10 of 33 / 23 / 0 | 4 | 24 of 24 | 5 of 5 | $1.09 | `bench/results/scout_open_s45g/` |

- **Wrongly blocked:** 1 in-scope question in every run, by the gate.
- **Run-to-run variance is large.** Replaying the s45c drafts through the old and new rules removed 170 and 158 sentences; the drop from s45b to s45c was mostly different drafts, not the rules. Most removals are sentences the model wrote without a citation.
- **MiniCheck's 96 flags in s45b** were mostly the evidence it was given: eligibility text missing (22), rank and kept claims (14), "the record gives no deadline" claims (18), re-split sentences (4). 17 were genuine over-reach. Rank, kept and absence claims are now checked by code.
- **Cut answers:** four s45c retries stopped mid-word because Sonnet 5.5's default thinking counts toward the output cap; caps raised (DECISIONS, 2026-11-04).
- **The stricter rules cost answers.** On s45g, 23 of 33 in-scope answers failed twice and were shown with sentences removed; none was empty. Most removals are sentences the model wrote without a citation. Tuning the prompt and adding templates for process sentences is S46 work (Q49).
- **The old Scout's higher Layer 1 rate is not a like-for-like comparison:** it answered a fixed tool set with no grounding contract per sentence.

## S47 load tests (v1 rebuild, Phase 10)

Measured on this shared node with the `cloud-gpu` profile on one RTX 5000 Ada (32 GB), the e2e Postgres and Redis, and the fake provider sleeping for latencies drawn from 51 real Sonnet fit calls (median 4.88 s). No cloud spend. Full tables: `bench/results/s47_load/report.md`.

- **A worker bug found and fixed.** `perch worker` built a new brief service, and so reloaded the GPU models, for every job; at 4 or more briefs in flight every brief failed. It now builds one per process. After the fix, the shipped worker ran 8 briefs in flight with 0 errors and a 5.7 GB GPU peak (`bench/results/s47_load/after_fix/`).
- **Briefs on one GPU** (one service per worker): 2.1 a minute at 1 in flight; 28.5 at 16 (p95 41 s); 37.1 at 24 (p95 49 s); 41.2 at 48 (p95 80 s), the card's saturation. The computed target of 33 a minute is met at 24 in flight. GPU work is 1.4 to 1.8 s a brief; the rest is model wait. Batching MiniCheck was 1.07 times faster, not worth a change.
- **HTTP at 1,000 simulated users** (300 s, browse for everyone, 500 signed-in accounts, 200 briefs offered): **target not met.** One web process served about 62 requests a second with browse p50 about 11 s; four processes served 156 a second with browse p50 77 to 167 ms and p95 about 15 s, 4 errors in 48,255 requests. Browse p95 under 300 ms held at 250 users on one process. The node is shared and the runs were at the lowest priority, so waits are not purely Perch's.
- **At 250 users, the target since 4 Nov (Dakshitha), on one web process, 120 s: met.** 58 requests a second; browse p95 132 to 190 ms, account pages p95 116 to 270 ms; 2 errors in 7,125 requests; 48 briefs offered, the queue peaked at 3. Brief polls p95 2.4 s. At 24 briefs a minute this implies about 170,000 output tokens a minute, computed from the S38 per-brief mean, inside the 400,000 start tier. The 250-user run was 120 s, shorter than the 300 s runs at 1,000.
- **Queue:** the worker drained 38 to 40 briefs a minute with 0 failures; the queue peaked at 52 to 68 with 24 running.
- **Provider tier:** the offered peak implies about 474,000 output tokens a minute, above the 400,000 start tier noted in the S38 section. Higher tiers' limits are UNVERIFIED.

## Limits

- **One funder, small sample.** The back-test is NIH only, with 48 targeted and 78 parent awards. It was tuned on the same 48 rows, and parent announcements are nearly unrecovered (2 of 78). There is no NSF back-test, and 12 of 14 embedder setups could not be told from the default (`bench/results/SUMMARY.md`).
- **Mechanisms, not gains.** The stand-in proposal is an upper bound. The student and draft-review results use invented data and keys written by the same author, and they do not measure real use. The decision-only draft review was not built (`bench/results/draft_review/RESULTS.md`); the advice-writing version, cover points, was built in S33 under standing rule 5 as amended, and its numbers are in the cover-points line above (all from invented personas and one local model, so a mechanism, not a gain).
- **Judged by the builder.** Industry leads were judged once, by the agent that built them, with no baseline. Reviews and QA were run by AI agents. No user study has been done.
- **Small bench sets on one local model.** Scout and grounding sets are 28 to 30 items. Gemma sometimes states a count that the citation check then withholds. The grounding pass rates were not rerun after S8.
- **Public records only, nothing sent.** Opportunities refresh only when the operator refetches. In v1 a signed-in user's CV, entries and briefs are stored encrypted, and guest briefs live in Redis for one hour; the v0 sentence that nothing is kept about a user applies to the fallback only. There is health and metrics but no alerting. Hand-offs are drafts. The v1 model calls are paid and metered (`README.md`, Known limits).

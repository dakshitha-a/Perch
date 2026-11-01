# Perch results

Written 2026-11-01 (S32) for the Demo Day deck. Every number below is copied from the file named beside it. Where a number is not in the record, the page says UNVERIFIED.

Perch reads a Temple researcher's public papers and lays out the routes to fund the work: open federal grants and industry leads, every claim cited to a public record, then a hand-off draft for the right Temple office. Nothing is sent. This page reports four things that were measured (retrieval on an NIH back-test, citation grounding, the Scout agent, speed and cost) and two that are mechanism tests on invented data (student mode, draft review). The keyword-only baseline sits beside every retrieval number.

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

- **Warm brief:** the demo researchers' briefs are held in memory and open in 17 ms. The full warm click path (5 screens, 14 clicks, a hand-off draft and a Scout answer) took 17.6 s wall (`docs/TRACKER.md` S24 row; `docs/design/WORKFLOW_REVIEW.md`, path tables).
- **Live brief:** 41.9 s after the S30 fixes, from 46.6 s (`docs/TRACKER.md`, S30 row). The QA rounds saw 36 s on a quiet server and 41 s beside another build (`docs/design/qa/CYCLE_5.md`). Under load a second brief waits in line. Live build time on the rebuilt demo: UNVERIFIED (S32 live check pending).
- **Two model slots:** the same brief took 42.7 s with one slot and 38.6 s with two, measured on a spare card (`docs/design/WORKFLOW_REVIEW.md`, P1 measurement). The demo unit now runs two slots (`docs/sessions/S32.md`).
- **S30 speed changes:** student polls fell from 8.06 MB to 0.41 MB, static files from 326 KB to 95 KB, and a cached rerank takes about 1 ms (`docs/TRACKER.md`, S30 row).
- **Cost per 10-lead brief:** $0.0915 on claude-sonnet-5-5 ($0.0792 explanations, $0.0123 summary), $0 on local models (`bench/results/cost.csv`). The demo runs local by default. Scout's 28-task bench cost $0.46 on Sonnet (`bench/results/scout_s28/`). Anthropic spend to date: $2.09 of $100 (`docs/TRACKER.md`, key numbers, as of 2026-10-29).

## Student mode (SYNTHETIC, mechanism test)

All scholarships and personas here are invented sample data. These numbers check that the code does what the written rules say. They say nothing about real scholarships or real students (`bench/results/STUDENT_MODE.md`).

- **Planted records retrieved:** 23 of 24 across 3 personas (`bench/results/STUDENT_MODE.md`). At the earlier retrieval depth of 40 it was 19 of 24 (`bench/results/RESULTS.md`).
- **Precision and recall of "may apply":** 1.00 and 1.00, counted on the retrieved records only. Verdicts matched the hand-written key on 23 of 23, and gap lists on 11 of 11.
- **End to end:** the student would see 11 of the 12 planted records they may apply for.
- **The key and the code follow the same rules,** so a perfect match is a check of the code, not evidence the rules suit real awards. Fellowships are real public listings with no key and are not scored.
- **Leakage:** none in the public API, public briefs, exports, data files or app log. Briefs took 45 to 57 s.

## Industry leads

The agent that built Perch judged 14 leads for 3 researchers against the records each cites: 8 yes, 6 thin, 0 wrong (`bench/results/route_b/JUDGMENTS.md`). The first run, before papers with more than 30 authors were excluded, was 7 yes, 3 thin and 5 wrong of 15. The exclusion was chosen after seeing that run, on the same researchers, so the second row is not independent. A person has not checked it. There is no baseline for this task. Every lead is labelled inferred, not verified.

## Quality process (S29 to S31)

- **Reviews:** two independent fresh-context reviews, one of workflow and security and one of UI and UX, found 86 findings. 84 were fixed and 2 deferred (`docs/TRACKER.md`, S29 and S30 rows). The reviewers and fixers were Claude Opus agents.
- **QA rounds:** five rounds, each a fresh tester then a fixer, found 129 findings and fixed 125. Two were partly fixed, one was dropped and one was done at the deploy file (`docs/TRACKER.md`, S31 row).
- **Checks:** tests rose from 265 to 398. The full browser walk reached 217 states with 0 errors and 0 axe accessibility violations. The privacy canary was clean every round.
- **Live walk on the public URL after the rebuild:** UNVERIFIED (S32 live check pending).

## Limits

- **One funder, small sample.** The back-test is NIH only, with 48 targeted and 78 parent awards. It was tuned on the same 48 rows, and parent announcements are nearly unrecovered (2 of 78). There is no NSF back-test, and 12 of 14 embedder setups could not be told from the default (`bench/results/SUMMARY.md`).
- **Mechanisms, not gains.** The stand-in proposal is an upper bound. The student and draft-review results use invented data and keys written by the same author, and they do not measure real use. Draft review was not built (`bench/results/draft_review/RESULTS.md`).
- **Judged by the builder.** Industry leads were judged once, by the agent that built them, with no baseline. Reviews and QA were run by AI agents. No user study has been done.
- **Small bench sets on one local model.** Scout and grounding sets are 28 to 30 items. Gemma sometimes states a count that the citation check then withholds. The grounding pass rates were not rerun after S8.
- **Public records only, nothing sent.** Opportunities refresh only when the operator refetches. Every brief is live and nothing is kept about a user, so there is no monitoring. Hand-offs are drafts, and Cloud models are opt-in and paid (`README.md`, Known limits).

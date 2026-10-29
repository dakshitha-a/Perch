# TRACKER.md — Perch master tracker

Perch-dev updates this file at the end of every session (and at any stop mid-session). `make tracker` renders it to `docs/tracker.html` for reading in a browser; the Markdown is the source of truth. Status values: `todo` · `in progress` · `continued` (stopped mid-session, see HANDOFF) · `done` · `cut`.

| Session | Goal | Status | Started | Finished | Commit | Notes (numbers, decisions, blockers) |
|---|---|---|---|---|---|---|
| S0 | Repository | done | 2026-10-28 19:02 EDT | 2026-10-28 19:03 EDT | 928a148 | Private repo dakshitha-a/perch on `main`. uv 0.13.6, Python 3.12.16, ruff 0.17.3, pytest 9.2.0 (pinned). `make test`: 3 passed. demo/bench/package are stubs. Q1 open (`data/` gitignore). |
| S1 | Schemas, store, OpenAlex | done | 2026-10-28 19:14 EDT | 2026-10-28 19:31 EDT | 31b3a56 | 28 tests green. Live: 1 public Temple PI resolved by name and ORCID; 35 works stored with provenance. OpenAlex meters a USD budget per day (Q2: API key). Tracker redesigned to Current, Master and Archive views. |
| S2 | Award sources, award horizon | done | 2026-10-28 19:34 EDT | 2026-10-28 19:44 EDT | 6ea2955 | 44 tests green. `perch profile` live for 3 PIs (13, 12 and 5 awards); horizons hand-checked against RePORTER. NIH field is `opportunity_number`, mostly empty before FY 2012. NSF has no opportunity field and returns contact details (redacted). |
| S3 | Opportunities | done | 2026-10-28 19:50 EDT | 2026-10-28 19:59 EDT | 3b9740b | 52 tests green. Grants.gov search2 + fetchOpportunity, no key; attribution notice required. No documented NIH Guide archive API; Grants.gov archive (12,152 NIH) is the back-test source: 16 of 17 sampled FOAs present. 56 opportunities stored live. |
| S4 | Route A, deterministic | done | 2026-10-28 20:05 EDT | 2026-10-28 20:40 EDT | f00e02c | 76 tests green. Live Route A for 3 PIs; 0 ineligible of 30 by hand check against Grants.gov record text. Warm brief 0.7 to 1.1 s; retrieval 73 to 78 ms. Qwen3-Embedding-0.6B and Qwen3-Reranker-0.6B on GPU 3 (torch cu126). Added title-restriction rules; Q4 on Temple's applicant category. |
| S5 | Provider layer, skills 1–2, validator | done | 2026-10-28 21:04 EDT | 2026-10-28 21:29 EDT | ce34844 | 105 tests green. `perch brief --explain` live for 3 PIs on qwen3.8:27b: layer 1 rejected 0 of 33, layer 2 flagged 1 of 30 (a false flag). 70 to 79 s per brief, $0. `decide` primitive with logprobs fallback. Anthropic adapter built on the SDK but not live-verified (Q5). |
| S6 | API | done | 2026-10-28 22:07 EDT | 2026-10-28 22:13 EDT | b3ccdf6 | 112 tests green. FastAPI + in-process jobs; briefs end to end via curl for 2 PIs (one fetched from scratch); stages and partial results pollable; export with provenance. |
| S7 | Web app, first three screens | done | 2026-10-28 22:40 EDT | 2026-10-28 23:14 EDT | 5da4e7e | 116 tests green. No-build web app in `web/` served by `perch serve` at `/`: Find, Profile, Routes, evidence panel, Scout the owl on the progress branch. Live brief in the browser in 90 s. Adversarial review: 32 findings fixed. Screenshots in `docs/screenshots/`; UI tab in the tracker. |
| S8 | Back-test and bench | continued | 2026-10-29 00:04 EDT | 2026-10-29 01:10 EDT | see git log | 126 tests green. Back-test set 160 rows (69 targeted, 91 parent) from RePORTER; 18-month window. Corpus fetch and `make bench` matrix running unattended (ends after about 03:30). Skill 2 passed both validator layers: Gemma 28 of 30, qwen3.8:27b 28, qwen3:14b 26, Sonnet 24, qwen3:8b 23. Models per profile in `perch/profiles.py`. Keep bar shipped. Private mode designed (S13). Two concurrency bugs fixed. |
| S9 | Deploy | todo | | | | |
| S10 | Scout agent | todo | | | | |
| S11 | Route B | todo | | | | |
| S12 | Compare, hand-off, export | todo | | | | |
| S13 | Private mode | todo | | | | |
| S14 | MCP server | todo | | | | |
| S15 | Monitoring (optional) | todo | | | | |
| S16 | QA, freeze, package | todo | | | | |

## Milestone readiness

| Milestone | Date | Needs | Ready? |
|---|---|---|---|
| Checkup 2 | Tue 3 Nov | S0–S7 | |
| Code freeze | Thu 5 Nov 12:00 | S16 | |
| Submission | Fri 6 Nov 12:00 | ZIP + links | |

## Key numbers (keep current)

| Metric | Value | Source | Updated |
|---|---|---|---|
| Back-test hit@5 / hit@10 / MRR (best config) | | bench/results/ | |
| Keyword-only baseline hit@5 / hit@10 / MRR | | bench/results/ | |
| Validator pass rate, both layers (30 leads) | Gemma 4 26B-A4B 28 of 30, qwen3.8:27b 28, qwen3:14b 26, claude-sonnet-5-5 24, qwen3:8b 23 | bench/results/RESULTS.md | 2026-10-29 |
| Cost per brief (API model) | $0.091 for a 10-lead brief on claude-sonnet-5-5 ($0.079 explanations, $0.012 summary); local models $0 | bench/results/cost.csv | 2026-10-29 |
| Warm-cache brief time | 0.7 to 1.1 s (Route A: embed + rerank, no LLM calls; 3 PIs) | data/logs/brief_timings.jsonl | 2026-10-28 |
| Route B hand-judged precision | | | |
| Deployment profile and peak VRAM | dev and deploy-2gpu: Gemma 4 26B-A4B + Clef. deploy-1gpu: qwen3:14b + Clef-flash, peak 22.7 GB with 3 concurrent briefs (Gemma 31.7 GB, qwen3.8:27b 31.1 GB on one card) | bench/results/single_card.csv | 2026-10-29 |
| Anthropic API spend / budget to demo | $0.32 of $100 (S8: $0.24 of its $3) | data/logs/anthropic_spend.jsonl | 2026-10-29 |

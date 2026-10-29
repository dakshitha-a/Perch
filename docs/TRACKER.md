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
| S8 | Back-test and bench | todo | | | | |
| S9 | Deploy | todo | | | | |
| S10 | Scout agent | todo | | | | |
| S11 | Route B | todo | | | | |
| S12 | Compare, hand-off, export | todo | | | | |
| S13 | MCP server, private context | todo | | | | |
| S14 | Monitoring (optional) | todo | | | | |
| S15 | QA, freeze, package | todo | | | | |

## Milestone readiness

| Milestone | Date | Needs | Ready? |
|---|---|---|---|
| Checkup 2 | Tue 3 Nov | S0–S7 | |
| Code freeze | Thu 5 Nov 12:00 | S15 | |
| Submission | Fri 6 Nov 12:00 | ZIP + links | |

## Key numbers (keep current)

| Metric | Value | Source | Updated |
|---|---|---|---|
| Back-test hit@5 / hit@10 / MRR (best config) | | bench/results/ | |
| Keyword-only baseline hit@5 / hit@10 / MRR | | bench/results/ | |
| Validator rejection rate (API model / local) | API claude-sonnet-5-5: layer 1 0 of 8, layer 2 0 of 6 (2 small runs) / local qwen3.8:27b: layer 1 0 of 33, layer 2 1 of 30 (false flag) | data/logs/model_calls.jsonl | 2026-10-28 |
| Cost per brief (API model) | about $0.0066 per explained lead with the cached profile prefix, plus about $0.012 for the profile summary (claude-sonnet-5-5, PI-3, 3 leads) | data/logs/model_calls.jsonl | 2026-10-28 |
| Warm-cache brief time | 0.7 to 1.1 s (Route A: embed + rerank, no LLM calls; 3 PIs) | data/logs/brief_timings.jsonl | 2026-10-28 |
| Route B hand-judged precision | | | |
| Deployment profile and peak VRAM | | S8 single-card validation | |
| Anthropic API spend / budget to demo | $0.08 of $100 (adapter verification, 8 calls) | data/logs/anthropic_spend.jsonl | 2026-10-28 |

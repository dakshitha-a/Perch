# TRACKER.md — Perch master tracker

Perch-dev updates this file at the end of every session (and at any stop mid-session). `make tracker` renders it to `docs/tracker.html` for reading in a browser; the Markdown is the source of truth. Status values: `todo` · `in progress` · `continued` (stopped mid-session, see HANDOFF) · `done` · `cut`.

| Session | Goal | Status | Started | Finished | Commit | Notes (numbers, decisions, blockers) |
|---|---|---|---|---|---|---|
| S0 | Repository | in progress | 2026-10-28 19:02 EDT | | | |
| S1 | Schemas, store, OpenAlex | todo | | | | |
| S2 | Award sources, award horizon | todo | | | | |
| S3 | Opportunities | todo | | | | |
| S4 | Route A, deterministic | todo | | | | |
| S5 | Provider layer, skills 1–2, validator | todo | | | | |
| S6 | API | todo | | | | |
| S7 | Web app, first three screens | todo | | | | |
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
| Validator rejection rate (API model / local) | | audit log | |
| Cost per brief (API model) | | audit log | |
| Warm-cache brief time | | | |
| Route B hand-judged precision | | | |

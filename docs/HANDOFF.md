# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S2 — Award sources and the award horizon
- Status (done / continued): done
- Last commit: 6ea2955 (task work); the ritual commit follows it on `main`

## What exists now (one line per subsystem)
- Schemas: `perch/schemas.py`. Award now has `amount_basis`, `fiscal_year`, `activity_code`, `opportunity_number`.
- Store: `perch/store/` SQLite repository (unchanged since S1).
- OpenAlex: `perch/sources/openalex.py`. Works page by number (`page=N`), because cursor paging needs a key. The queried author is added back to works whose author list was truncated.
- NIH RePORTER: `perch/sources/nih_reporter.py`. One Award per fiscal-year application, by PI name at `TEMPLE UNIV`; requests 1 s apart.
- NSF: `perch/sources/nsf.py`. Lead-PI and co-PI queries at "Temple University", deduplicated. Contact fields are never read; `redact_contacts()` for fixtures.
- Linking: `perch/awards.py`. Name match (same last name; same first name or initial; accents folded) plus `data/overrides/award_links.csv`. `summarise()` groups records per award; `award_horizon()` is the latest end date.
- Profile: `perch/profile.py` `key_papers()` (most cited, skipping papers with more than 30 authors). S4 adds threads here.
- CLI: `perch resolve`, `perch fetch openalex|awards <id>`, `perch profile <id>`.
- Tests: 44 green. Fixtures: openalex (3), nih_reporter (1), nsf (2, contacts redacted).

## What is half-done (exact file, exact next step)
- Nothing. S2 is complete.

## Decisions made this session
- Back-test PIs used for live checks: Skorski (A5063022331), Persidsky (A5057472361), Gardiner (A5023080104). All public Temple PIs.
- Horizon = latest `end_date` across all fiscal-year records, because end dates move with extensions.
- RePORTER agency is the record's abbreviation only (it includes AHRQ, which is not NIH).
- NIH `opportunity_number` is mostly empty before FY 2012, so back-test awards should start in FY 2012 or later.
- `.gitignore`: `data/*` ignored except `data/overrides/` (interim answer to Q1).

## Open questions (mirror of bridge/QUESTIONS.md, numbered)
- Q1: `data/backtest/` (S8) and `data/synthetic/` (S13) need a gitignore decision. `data/overrides/` is handled.
- Q2: OpenAlex API key in `.env`. Without it, list calls share $0.10/day per IP and cursor paging is refused.

## Next session
- Session to start: S3 — Opportunities (Grants.gov and the NIH Guide archive)
- First command to run: `git pull && make hooks && make test`

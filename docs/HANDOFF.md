# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S3 — Opportunities
- Status (done / continued): done
- Last commit: 3b9740b (task work); the ritual commit follows it on `main`

## What exists now (one line per subsystem)
- Schemas: Opportunity now has `eligibility_notes`, `status`, `archive_date`, `assistance_listings`, `funding_instruments`.
- Researchers and works: `perch/sources/openalex.py` (page-number paging; truncated author lists handled).
- Awards: `perch/sources/nih_reporter.py`, `perch/sources/nsf.py`, linking and horizon in `perch/awards.py`.
- Opportunities: `perch/sources/grants_gov.py`. `search2` then `fetchOpportunity` per hit; no key; 1 request per second; list fields sorted; contacts never read.
- CLI: `perch resolve`, `perch fetch openalex|awards|opportunities`, `perch profile`. `fetch opportunities` takes `--agencies`, `--statuses`, `--limit`, `--opp-num` (repeatable, any status).
- Store (live, gitignored `data/perch.db`): 4 researchers, 710 works, award records for 3 PIs, 56 opportunities.
- Tests: 52 green. Fixtures: openalex 3, nih_reporter 1, nsf 2, grants_gov 3 (contacts and tokens removed).

## What is half-done (exact file, exact next step)
- Nothing. S3 is complete.

## Decisions made this session
- Grants.gov terms require the notice "This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services." It is in the README and printed by `fetch opportunities`. **The web app (S7) must show it.**
- NIH Guide: no documented structured archive (JS search app, RSS of recent items, HTML weekly indexes). Not scraped. Back-test uses Grants.gov archived listings instead (16 of 17 sampled FOAs present; RFA-AA-07-015 missing).
- Activity code comes from NIH-style titles, e.g. "(R01 ...)" or "(Parent R01)". Other agencies have none.
- A full refresh of open NIH opportunities is about 660 detail requests, about 11 minutes. Nightly scheduling is S9.
- SPEC and PLAN gained the `decide` primitive (S5 task 7) and decision-model bench rows (S8 task 4): Clef-flash default local, Clef challenger, Jev hosted, Strands Decider 2B CPU fallback, LLM-logprobs fallback. All vendor facts marked [verify].

## Open questions (mirror of bridge/QUESTIONS.md, numbered)
- Q1: `data/backtest/` (S8) and `data/synthetic/` (S13) gitignore decision. `data/overrides/` is handled.
- Q2: OpenAlex API key in `.env`.

## Next session
- Session to start: S4 — Route A, deterministic (embeddings, LanceDB, threads, retrieval, eligibility, rerank)
- First command to run: `git pull && make hooks && make test`
- Before S4 retrieval: run `uv run perch fetch opportunities --agencies HHS-NIH11` for the full open NIH set (about 11 minutes).

# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S1 — Schemas, store, OpenAlex
- Status (done / continued): done
- Last commit: 31b3a56 (task work); the ritual commit follows it on `main`

## What exists now (one line per subsystem)
- Schemas: `perch/schemas.py`. Researcher, Work, Award, Opportunity, Organisation, Lead, Brief. Provenance fields are required; naive `fetched_at` and unknown fields are rejected.
- Store: `perch/store/base.py` (Repository interface) and `perch/store/sqlite.py` (one JSON table keyed by kind and id, provenance columns, `works_by_author`).
- OpenAlex: `perch/sources/openalex.py`. Resolve by name at Temple (up to 3) or by ORCID; works with rebuilt abstracts, topics, referenced works; cursor paging; retries on 429 and 5xx.
- CLI: `perch resolve <name|orcid|id>` and `perch fetch openalex <id>`. Store defaults to `data/perch.db` (`PERCH_DB` overrides).
- Config: `perch/config.py` reads `.env` without overriding the environment.
- Fixtures: `tests/fixtures/openalex/` holds 3 real responses for public Temple researcher A5026494099.
- Tests: 28 green. Hygiene test and git hooks (`make hooks`) block secrets and personal details.
- Tracker: `make tracker` renders a page with Current, Master and Archive views from `docs/TRACKER.md` and `docs/sessions/S<n>.md`. The claude.ai artifact link is in `CLAUDE.local.md`.

## What is half-done (exact file, exact next step)
- Nothing. S1 is complete.

## Decisions made this session
- OpenAlex now meters a dollar budget per day. Lists cost 1 credit, searches 10, single records are free. The plan's mailto polite pool no longer exists, so it is not used.
- An optional `OPENALEX_API_KEY` is sent as a Bearer header, never in the URL.
- Name search filters on `last_known_institutions`, so researchers who left Temple are missed. Recorded in SOURCES.md.
- OpenAlex works carry `awards` and `funders` fields. They are not used yet; S2 should look at them next to NIH RePORTER.
- Tracker: one artifact with three views, republished at session start, after each task and at session end (Dakshitha's direction).
- Repo will go public: no session trailers in commits; machine notes in `CLAUDE.local.md`. History was rewritten once in S0.

## Open questions (mirror of bridge/QUESTIONS.md, numbered)
- Q1: `data/` is gitignored, but S2, S8 and S13 put committed files there. Needed by S2.
- Q2: OpenAlex API key. Dakshitha signs up and puts it in `.env`. Not blocking until S8.

## Next session
- Session to start: S2 — Award sources and the award horizon
- First command to run: `git pull && make hooks && make test`

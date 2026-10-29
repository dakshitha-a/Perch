# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S6 — API
- Status (done / continued): done
- Last commit: b3ccdf6 (task work); the ritual commit follows it on `main`

## What exists now (one line per subsystem)
- Pipeline: sources, profile and threads, embeddings, LanceDB, retrieval, eligibility, rerank (S1 to S4); skills 1 and 2, validator layers 1 and 2, `decide`, audit log (S5).
- API `perch/api.py` (run `perch serve`, port 8100): `GET /health`, `GET /authors/resolve?q=`, `POST /briefs`, `GET /briefs/{id}`, `POST /briefs/{id}/leads/{lead_id}/keep|dismiss`, `GET /briefs/{id}/export.json`, `GET /records/{id}` (full or short ids, opportunity numbers). CORS open. Every response carries the Grants.gov notice where its data appears.
- Service `perch/service.py`: seven saved stages (researcher, works, awards, profile, route_a, summary, explanations); fetch stages skip when data exists; explanations saved one by one; failure recorded on the stage and brief.
- Jobs `perch/jobs.py`: `JobRunner` interface; `InProcessRunner` (one worker); `InlineRunner` for tests.
- Schemas: Brief has stages, options, threads, topics, summary, timings; Lead has rerank score, explanation, inference, layer 2 flags, keep or dismiss status.
- Hosted tier: Anthropic adapter verified; spend cap $100 enforced in `perch/llm/budget.py`; spend $0.08.
- Decision servers: Clef-flash GPU 1 :8097 and Clef GPU 2 :8098 as systemd user units (`make decide-up`, `make decide-status`); both answer `/v1/systemone`.
- Tests: 112 green, all offline (fake models, fixture-backed clients).

## How to run the API with real models
- `CUDA_VISIBLE_DEVICES=3 uv run --extra ml perch serve --llm ollama:qwen3.8:27b` from the repo root (it reads `.env` and relative data paths from there).
- Live result: PI-2 brief with explanations in about 95 s; PI-5 (A5034175589) fetched from scratch in under a minute without explanations.

## What is half-done (exact file, exact next step)
- Nothing in S6.
- Not built yet: `POST /briefs/{id}/handoff` (S12); Route B leads (S11); rate limit 10 briefs per hour (S9).

## Decisions made this session (all in docs/DECISIONS.md)
- Briefs run one at a time in-process; fetch stages skip when data exists.
- PI-5 alias added in `data/overrides/pi_aliases.csv`.

## Open questions (mirror of bridge/QUESTIONS.md, numbered)
- None open.

## Next session
- Session to start: S7 — Web app, first three screens (Find, Profile, Routes), evidence panel, Grants.gov notice
- First command to run: `git pull && make hooks && make test`

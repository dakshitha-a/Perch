# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S7 — Web app, first three screens
- Status (done / continued): done
- Last commit: see `git log`; the ritual commit is last on `main`

## What exists now (one line per subsystem)
- Pipeline: sources, profile and threads, embeddings, LanceDB, retrieval, eligibility, rerank (S1 to S4); skills 1 and 2, validator layers 1 and 2, `decide`, audit log (S5).
- API `perch/api.py` (`perch serve`, port 8100): resolve, briefs, keep/dismiss/restore, export, records, health. `GET /briefs/{id}` also returns `papers` (key papers per thread plus cited works) and each award's `record_id`. CORS off unless `PERCH_CORS_ORIGINS` is set.
- Web app `web/` (plain ES modules and CSS, no npm, no build): served at `/` by `perch serve`. Find, Profile, Routes, evidence panel, Help page (`web/help.js`, `#/help`), Scout the owl (reacts when tapped). Design and reviews in `docs/design/UI.md`.
- Help page grows with the app: every session that ships UI updates `web/help.js` and checks its claims against the code (Dakshitha, after S7).
- Replay mode: `scripts/export_replay.py <brief_id>` writes `build/replay/<id>.json` (alias only); `scripts/build_ui_preview.py` bundles one page to `build/artifacts/ui.html`; `make tracker` builds it and adds the tracker's UI tab.
- Screenshots: `uv run --no-project --with playwright python scripts/screenshots.py` (Playwright is dev-only; uses the cached Chromium) writes `docs/screenshots/` and checks keep, dismiss and sideways scroll.
- Hosted tier: Anthropic adapter verified; cap $100 in `perch/llm/budget.py`; spend $0.08.
- Decision servers: Clef-flash GPU 1 :8097, Clef GPU 2 :8098, systemd user units (`make decide-up`).
- Tests: 116 green, all offline. `tests/test_web.py` runs the format helpers under Node when Node is present (Node 12 on this node).

## How to run
- API and app with real models: `CUDA_VISIBLE_DEVICES=3 uv run --extra ml perch serve --llm ollama:qwen3.8:27b`, then open http://127.0.0.1:8100/.
- Live result: PI-4 (A5026494099) brief built in the browser in 90 s, 10 of 10 explained.
- Tracker artifact: publish `build/artifacts/tracker.html` with `files={"ui.html": "build/artifacts/ui.html"}` so the UI tab keeps its page.

## What is half-done (exact file, exact next step)
- Nothing in S7.
- Not built yet: hand-off (S12), Compare (S12), Route B (S11), rate limit (S9), Scout tool cards (S10).
- `make demo` is still a stub (S9); replay mode is the Demo Day fallback when it is built.

## Decisions made this session (all in docs/DECISIONS.md)
- Web app is no-build ES modules (Node 12, no npm on the node).
- Owl mascot named Scout, driven only by real status.
- CORS off by default.

## Open questions (mirror of bridge/QUESTIONS.md, numbered)
- Q6: review the web app in the tracker's UI tab (not blocking).

## Answers to carry into S8 (bridge/QUESTIONS.md Q7 to Q10)
- Back-test PIs: build `data/backtest/pis.csv` from NIH RePORTER (Temple, FY2015 on, awards naming a funding opportunity); Dakshitha reviews the list.
- Downloads approved: Qwen3-Embedding-4B, SPECTER2, BGE-M3 (Hugging Face), Gemma 4 26B-A4B (new Ollama pull). Log each in AI_USE_LOG. Do not re-pull existing Ollama models.
- API spend for S8: up to $3 on claude-sonnet-5-5; state the cost before each run.
- S8 task 6: Keep bar (count and next step; downloads kept leads until S12); add to the Help page.

## Next session
- Session to start: S8 — Back-test and bench
- First command to run: `git pull && make hooks && make test`

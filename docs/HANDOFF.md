# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S9 — Deploy (S8 finished earlier in the same context)
- Status: done
- Last commit: see `git log`; the ritual commit is last on `main`

## The demo is live
- Public URL through Tailscale Funnel; the address is in `CLAUDE.local.md`, not the repo. Dakshitha opened it on a phone and a laptop.
- `make demo` brings everything up: Ollama with Gemma and Clef-flash on GPU 6, Clef and the model server on GPU 7 (systemd user units from `deploy/systemd/demo/`), and the app in Docker on 127.0.0.1:8090.
- The app container has no GPU (no NVIDIA runtime on the node), so the embedder, reranker and MiniCheck fallback run in `perch/model_server.py`. The app reaches them through `perch/remote_models.py` when `PERCH_MODEL_SERVER` is set.
- The demo store is `data/demo/`, seeded once from `data/`. A 05:30 timer runs `make demo-warm` so the three demo briefs answer at once.
- `make gpus` names GPU memory per service. `make demo-status` and `make demo-down` exist.
- After a code change: `docker compose up -d --build` with `PERCH_UID` and `PERCH_GID` set, or simply `make demo`.

## What S9 added to the app
- **Brief reuse:** POST /briefs reuses a finished brief with the same options from the last 24 h, as a copy whose leads start as new.
- **Rate limit:** 10 new briefs an hour per visitor, keyed on X-Forwarded-For from the local proxy.
- **Health:** `/health?deep=true` checks every model service.
- **Private-mode groundwork:** `perch/privacy.py` holds the settings and refusals. Private mode refuses to start until S13.
- **Hardening:** uvicorn runs at warning level, errors never echo request bodies, and core dumps are off.
- **Tests:** 144 green, offline.

## Notes
- Clef and Clef-flash URLs come from `PERCH_CLEF_URL` and `PERCH_CLEF_FLASH_URL`, defaulting to the dev ports.
- Funnel decrypts only on this node (`PERCH_TLS_AT=server` when private mode is built).
- The dev servers on GPUs 0 to 2 are untouched. The dev profile still sends chat to Gemma on GPU 0.

## Next session: S10 — Scout agent
1. Read S10 in `docs/PLAN.md`. Scout's own loop over the allowlisted tools, two modes, follow-ups, a fallback for small local models, and private-mode rules.
2. Done when Scout completes 20 scripted follow-ups in `bench/scout_tasks.yaml` with the API model and at least one local model, with wrong-tool and restraint rates logged.
3. Clef-flash answers `decide` on GPU 6 at :8095 in the demo, and at :8097 in dev.
4. Any API spend for Scout needs Dakshitha's approval first; total spend so far is $0.32 of $100.

## Decisions this session (all in docs/DECISIONS.md)
- Hybrid deployment; Tailscale Funnel; a separate demo store; brief reuse with fresh lead state.

## Open questions (mirror of bridge/QUESTIONS.md)
- None.

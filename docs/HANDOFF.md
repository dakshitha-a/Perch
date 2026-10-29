# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S10 — Scout agent
- Status: done
- Last commit: see `git log`; the ritual commit is last on `main`

## What Scout is now
- `perch/scout/`: `tools.py` holds the nine allowlisted tools; `loop.py` the loop, budget and answer check; `log.py` the log and replay; `hub.py` the API's in-memory sessions; `make_scout()` in `__init__.py` builds one.
- Six tools wrap the pipeline. `get_org_signals`, `compare` and `draft_handoff` return "not built yet" (Q18). S11 and S12 replace their bodies in `TOOLS` and keep the names.
- Answers pass `perch.validate.check` against the records the tools returned (`ScoutContext.seen`, short ids such as W123 and A456). Citations, list markers and numbers the user typed are removed first.
- Two policies: native tool calls, and a structured JSON step for models without them.
- `perch scout ask <author> "<question>"` and `perch scout replay <session>` (CLI).
- API: `POST /briefs/{id}/scout`, `GET /scout/{sid}`, `POST /scout/{sid}/approve|skip|ask|mode`. Sessions are lost on restart. 30 questions an hour per visitor.
- Web: Ask Scout tab (`web/scout.js`), a Help step. Checked in a browser at two widths.
- Provider layer: `Message` carries tool calls and results. `Tool.strict` is on by default and off for Scout's tools, because strict mode made Sonnet drop filters.
- Eligibility gained a maximum amount, close-by date, activity codes and keywords. Agency filters match names and codes.

## Bench (bench/results/RESULTS.md, Scout section)
- Completed of 20: Sonnet 20, Gemma 20, qwen3:8b 17 native and 12 structured. The fallback is worse than native on qwen3:8b.
- First runs (Gemma 18, Sonnet 17) are in `bench/results/scout_first_runs/`.
- API spend: about $0.93 under the approved $1.00 cap. Ledger total $1.25 of $100.

## Known gaps, for a later session
- Repeated identical calls: Sonnet's first run looped the same search up to nine times. A guard that answers a repeat call from the earlier result would stop this. It is not built, so the bench numbers describe the current code.
- The structured fallback rejects inline list numbers ("1. … 2. …" on one line). Only line-start list markers are ignored.
- The demo stack has not been rebuilt with S10. Run `make demo`, or `docker compose up -d --build` with `PERCH_UID` and `PERCH_GID` set. The demo Scout model is the profile's chat model, Gemma.

## Next session: S11 — Route B
1. Read S11 in `docs/PLAN.md`.
2. Route B fills `get_org_signals` and `search_opportunities(route="B")`. Update the Help step and the tool descriptions when it lands.
3. Add any Route B follow-ups to `bench/scout_tasks.yaml` as new tasks; keep the 20 S10 tasks unchanged for comparison.

## Open questions (mirror of bridge/QUESTIONS.md)
- Q18: Scout's three later-session tools say "not built yet"; default is to keep them in the list.

# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last run: S23 done, then the UI redesign on a canvas
- **S23 is done** (below). 245 tests pass. API spend: $2.09 of $100.
- **After S23, 2026-10-30:** Dakshitha redesigned the whole web app with Perch-dev on a design canvas and asked for it to be built. That is the new S24. QA is now S25, the media refilm S26, freeze S27.
- **Spec:** `docs/design/S24_REBUILD.md`. Canvas sources: `docs/design/redesign/` (one `.dc.html` per screen). The canvas link is in `CLAUDE.local.md`.
- **Decisions on the way:** students get Ask Scout (Q27 revised). Scout draft review is designed but waits on Q32 (standing rule 5).

## S23 — what changed
- **Every brief is a session in memory.** Find runs researcher briefs through `/private/brief`; no document is needed with an author id. The context fields and the award ceiling go with it.
- **Nothing about a visitor is stored.** There is no reuse, no recent-briefs list and no per-user log. The stored-brief routes answer 404 unless `PERCH_STORED_BRIEFS=1`; tests and replays set it.
- **Public records stay cached.** A session writes OpenAlex, RePORTER and NSF records through to the store (`perch/private/store.py`, `is_public`). The embedding cache stays read-only for sessions.
- **Local / Cloud switch** (`#models-switch`) replaces Private. Cloud needs a confirm naming the provider. Only the summary, fit and hand-off skills switch. Cloud never runs with documents, and student mode turns it off. The server allows 30 cloud briefs a day (`PERCH_CLOUD`, `PERCH_CLOUD_BRIEFS_PER_DAY`).
- **End session** sits in the line under the top bar, on every screen. The line says "Nothing about you is stored", and the bar turns amber with Cloud on.
- **Monitoring shelved:** `perch/shelved/monitor/` holds the module, screen, units, skipped tests and a README. The morning warm-up was deleted.
- **Demo:** rebuilt; old timers removed. The old 64 briefs and 880 leads were deleted from `data/demo/perch.db`. A copy of the old store and its logs is in the gitignored `data/archive/pre-s23/`. Dakshitha may delete it.
- **Checks:** live canary ok (`scripts/private_canary.py`, now with a default-path run and a Cloud refusal check). Walk on the demo: 110 states, 0 axe violations, 0 sideways scroll, 0 failed steps.

## Next: S24, the UI rebuild
- Read `docs/design/S24_REBUILD.md` first, then open the canvas sources for exact sizes and colours. Build in the spec's order: design language, landing, researcher path, student path, gaps, checks. Commit after each screen.
- The app is no-build (Node 12 on the node, no npm). Keep it that way; the `.dc.html` files are design references, not code to ship.
- Student Scout is new backend work: tools for options, a CV rule check, a verdict explanation, compare and a note, on the existing Scout loop and allowlist.
- The walk (`scripts/ux_walk.py`) selects by id and text; update it with the new screens. axe-core 4.10.2 lives in an old scratchpad; fetch `axe.min.js` from cdnjs again if it is gone.
- Test on a dev server (`perch serve --port 8091` on a scratch copy of `data/demo`) before rebuilding the demo. Stop it by its task or an anchored pkill.
- Then S25 (UI/UX review and full QA), S26 (media refilm, notes below) and S27 (freeze; task 2 frees the dev GPUs).

## Notes for S26, the media refilm
1. README clips: `scripts/tour/film.py`, then `scripts/tour/animate.py`, on the rebuilt screens.
2. `docs/screenshots/` (`scripts/screenshots.py`) and the README student screenshot.
3. Tracker UI preview with the student flow: a replay of a SYNTHETIC student brief; `scripts/build_ui_preview.py` must serve its routes.
4. README text for the new labels, then the README tab, then republish.

## Known gaps
- **Student retrieval:** 2 of 12 planted positives never reached a brief.
- **Shared Ollama:** the dev Ollama on 11434 reloads gemma when another client asks for a different context size.
- **Every brief is live:** about 45 s on the demo models (Q31).

## Open questions (mirror of bridge/QUESTIONS.md)
- **Q29:** S22 option A, B or C. Default B is built.
- **Q30:** documents on Cloud? Default: Local only.
- **Q31:** every brief is live, about 45 s. Default: accept it.
- **Q32:** Scout draft review under standing rule 5: (a) allowed as is, (b) you change the rule, (c) after Demo Day. Default: (c).

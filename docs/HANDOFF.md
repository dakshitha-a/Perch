# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last run: plan edits, then S23 done
- **Plan:** Dakshitha added a UI/UX review and full QA test, then swapped two sessions. The order is now S24 UI/UX review and full QA test, S25 media refilm, S26 freeze and package.
- **S23 is done.** Dakshitha asked to stop after S23, so S24 has not started.
- 245 tests pass. API spend: $2.09 of $100, after one $0.04 cloud check.

## S23 — what changed
- **Every brief is a session in memory.** Find runs researcher briefs through `/private/brief`; no document is needed with an author id. The context fields and the award ceiling go with it.
- **Nothing about a visitor is stored.** There is no reuse, no recent-briefs list and no per-user log. The stored-brief routes answer 404 unless `PERCH_STORED_BRIEFS=1`; tests and replays set it.
- **Public records stay cached.** A session writes OpenAlex, RePORTER and NSF records through to the store (`perch/private/store.py`, `is_public`). The embedding cache stays read-only for sessions.
- **Local / Cloud switch** (`#models-switch`) replaces Private. Cloud needs a confirm naming the provider. Only the summary, fit and hand-off skills switch. Cloud never runs with documents, and student mode turns it off. The server allows 30 cloud briefs a day (`PERCH_CLOUD`, `PERCH_CLOUD_BRIEFS_PER_DAY`).
- **End session** sits in the line under the top bar, on every screen. The line says "Nothing about you is stored", and the bar turns amber with Cloud on.
- **Monitoring shelved:** `perch/shelved/monitor/` holds the module, screen, units, skipped tests and a README. The morning warm-up was deleted.
- **Demo:** rebuilt; old timers removed. The old 64 briefs and 880 leads were deleted from `data/demo/perch.db`. A copy of the old store and its logs is in the gitignored `data/archive/pre-s23/`. Dakshitha may delete it.
- **Checks:** live canary ok (`scripts/private_canary.py`, now with a default-path run and a Cloud refusal check). Walk on the demo: 110 states, 0 axe violations, 0 sideways scroll, 0 failed steps.

## Next: S24, UI/UX review and full QA test
- Read S24 in PLAN.md. The walk (`scripts/ux_walk.py`) already knows the S23 switch and End session. axe-core 4.10.2 was in an old scratchpad; fetch `axe.min.js` from cdnjs again if it is gone.
- To test without touching the demo: `perch serve --port 8091` on a scratch copy of `data/demo`, with the demo's model servers. Stop it by its task, or with an anchored pkill; an unanchored pkill kills its own shell.
- Write `docs/QA_PLAN.md` and `docs/design/UX_REVIEW_S24.md`. Fix must-fix items in S24.
- Things worth a look: the phone frame line wraps with End session; the replay preview still uses the stored-brief shape.
- Then S25 (media refilm, notes below) and S26 (freeze; task 2 frees the dev GPUs).

## Notes for S25, the media refilm
1. README clips: `scripts/tour/film.py`, then `scripts/tour/animate.py`. The `private` scene must use the documents link and the new switch.
2. `docs/screenshots/` (`scripts/screenshots.py`) and the README student screenshot (tab "Scholarships and awards (sample)").
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

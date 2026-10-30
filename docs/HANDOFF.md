# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last run: S21 and S22 done
- Dakshitha asked for S21 and S22 in one run; both are done. S22's media refilm moved to a new S24, after S23.
- 248 tests pass. No API spend; the ledger is still $2.05 of $100.

## S21 — UX audit (done)
- `docs/design/UX_AUDIT.md` and the tracker's UX tab: 6 must-fix, 12 should-fix, 4 could-fix, with 9 screenshots.
- `docs/design/A11Y_CHECKLIST.md`: 13 items, run by `scripts/ux_walk.py` with axe-core 4.10.2 (`--axe` path to `axe.min.js` from cdnjs). S25 reruns it.
- Q29 (open): which S22 option. Default B, redesign of the core screens. S22 started on B.

## S22 — what is built and live on the public URL
- **Must-fix:** the hand-off lists only the research offices, and its radios sit in their cards. The owl copies leave the tab order. Scroll regions take focus. Two contrast fixes. The order is explained beside the fit estimate. Student explanations say "the student", not "the researcher".
- **Redesign:** Find has two doors, "I'm a researcher" and "I'm a student". A student brief says What Perch read, Your options and Your documents. Compact student cards: one line when a listing states no deadline or amount, and a folded explanation. Industry cards show the newest record per signal.
- **Checks:** the walk was rerun on the dev server: 0 axe violations, no sideways scroll, private mode correct in every state. An independent review found 7 issues; all are fixed.
- **Corrected:** the audit's S10 was wrong; the evidence panel already sat beside the list on a laptop.
- **Not built (after Demo Day):** grouping one announcement family (S5) and merging company aliases (S7). Both change pipeline output.

## Next: S23 (private by default), then S24 (media refilm), then S25 (freeze)
- **S23 next:** read S23 in PLAN.md. It changes the header switch, so the refilm waits for it.

S24, notes for the refilm:
1. Refilm the README clips: `scripts/tour/film.py`, then `scripts/tour/animate.py`. The `private` scene opens private mode from "Options" with a link. That path may be stale since S18; use the header switch.
2. Retake `docs/screenshots/` (`scripts/screenshots.py` on the replay preview), and the README student screenshot (S19, Scholarships tab at 390 px; the tab is now "Scholarships and awards (sample)").
3. Tracker UI preview with the student flow (moved here from S19). A private brief cannot be replayed today. This needs a replay of a SYNTHETIC student brief: export one from a live run with persona-ug and teach `scripts/build_ui_preview.py` to serve `/private/*`.
4. Update the README text that names old labels, then the README tab (`make tracker`), and republish the artifact. Dakshitha reviews the README tab.
5. Then S25, freeze and package. S25 task 2 frees the dev GPUs.

## Dev server used in S22
- `perch serve --port 8091` on a scratch copy of the demo stores, using the demo's model servers. It is not needed again. Kill it with an anchored pattern, because an unanchored `pkill` matches its own shell.

## Known gaps
- **Student retrieval:** 2 of 12 planted positives never reached a brief.
- **Shared Ollama:** the dev Ollama on 11434 reloads gemma when another client asks for a different context size.
- **README known limits:** the S20 list stands. S5 and S7 above should be added there.

## Open questions (mirror of bridge/QUESTIONS.md)
- **Q29:** S22 option A, B or C. Default B is built; say if you want less, or C.

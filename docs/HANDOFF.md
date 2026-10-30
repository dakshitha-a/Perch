# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last run: S24 done (UI rebuild from the redesign canvas)
- **All nine tasks done.** 249 tests pass. API spend: $2.09 of $100 (none in S24).
- **Live:** the redesign is on the public URL for both paths, light and dark, phone and laptop. Dakshitha asked for S24 to S26 in one run, so S25 follows in the same context.

## What S24 built
- **Design language:** canvas tokens in `web/styles.css`, with the old names as aliases. Newsreader and Inter from Google Fonts, Georgia and system fallbacks. A big "S24 redesign" section sits at the end of the file.
- **Screens:** landing `#/`, pick `#/find` (context panel, "Fill with a sample"), briefs with a rail (shortlist above evidence; under 900 px a floating keep pill and the evidence sheet). Tabs: Routes, Profile, Compare, Ask Scout; a brief opens on Routes.
- **Header:** the status chip opens a real `<dialog>` (Local or Cloud); End session is a dialog too. No owl in the bar.
- **Samples:** `GET /private/samples/{researcher|student}` reads `data/synthetic/`. The researcher sample leaves the CV empty (persona-1's README; DECISIONS).
- **Student Scout:** `perch/scout/student_tools.py`, its own allowlist; `make_scout` picks it for a student brief, private sessions only. Researcher Scout and MCP unchanged.
- **Warm briefs:** `perch/private/warm.py`, `PERCH_WARM_AUTHORS` (PI-5, PI-4, PI-2 on the demo). Built after start in a thread, memory only; a default request gets a copy.
- **Documents on Cloud:** behind `PERCH_CLOUD_DOCUMENTS=1`, off. Second warning, tick box, a confirm phrase the API checks.
- **Draft review:** `bench/draft_review/`, results in `bench/results/draft_review/RESULTS.md`. Not built (Q34).

## Checks
- **Walk:** `scripts/ux_walk.py` updated for the new selectors and dialogs. Dev server: 125 states; demo: 119 states. 0 axe violations, 0 sideways scroll, 0 failed steps. axe-core 4.10.2 is in this session's scratchpad; refetch from cdnjs if gone.
- **Canary:** `build/canary-s24.json` ok (default path 15 of 15 explained in 46 s; private-only 10 of 10; 0 user rows; no canary in files or six journals).
- **Dev server:** a scratch copy of `data/demo` on port 8091 with `PERCH_BRIEFS_PER_HOUR=200` (the walk runs more than 10 briefs). The script is in the scratchpad; stop it with an anchored pkill.

## Next: S25, UI/UX review and full QA
- A draft QA plan with 36 rows is in the scratchpad (`QA_PLAN.md`); copy it to `docs/QA_PLAN.md` and run it.
- Independent review of the screens; findings in `docs/design/UX_REVIEW_S25.md`, must-fix items fixed.
- Then S26 (media refilm: README clips, screenshots, tracker UI preview with a student replay) and S27 (freeze; task 2 frees the dev GPUs).

## Known gaps
- **Student Scout is wordy with tools:** on Gemma it checked options one by one before the rules pointed it at `compare_options`.
- **Student retrieval:** 2 of 12 planted positives never reached a brief.
- **Shared Ollama:** the dev Ollama on 11434 reloads gemma when another client asks for a different context size.

## Open questions (mirror of bridge/QUESTIONS.md)
- **Q34:** build the draft review anyway (Clef only, records with three or more points)? Default: no.
- **Q33:** apply the rule 1 change, then set `PERCH_CLOUD_DOCUMENTS=1` on the demo. The rule 5 change is withdrawn.
- **Q29:** kept open by Dakshitha.

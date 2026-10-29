# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session: S20 — QA and privacy audit (done)
- Dakshitha asked for S17 to S20 in one run; all four are done. 246 tests pass. No API spend; the ledger is still $2.05 of $100.
- **Task 1 dropped:** no QA log exists (Q28, answered by Dakshitha).

## What S20 changed
- **Privacy fixes:** the JSON export now withholds rule lines that quote the CV and carries the sample banner. `POST /private/handoff` refuses a student brief (422); student drafts live on the Compare tab.
- **Checks:** a test keeps the sample store inside student mode (`tests/test_student.py`). The live canary (`scripts/private_canary.py`) passed: the private-only brief explained 10 of 10 leads.
- **QA:** the flaky Scout test is fixed (random test order). README has a Known limits section and no stale test count.

## Student mode, in one place (S17 to S19)
- **Data:** a SYNTHETIC corpus in `data/synthetic/scholarships.jsonl`, in its own store (`data/sample.db`; on the demo, `data/demo/sample.db`). Temple SDFA's 76 public awards are in the public stores.
- **Code:** `perch/student.py` (rules), `perch/private/student.py` (stages), `web/mode.js` (private mode as a state), `web/student.js` (screens).
- **Scores:** `bench/results/STUDENT_MODE.md`. Rules matched all retrieved planted cases; 10 of 12 positives were retrieved; no leakage.

## Next session: S21 — UI/UX audit for three audiences
1. Walk every screen on the public URL for the three student personas and the PI personas, on a phone and a laptop. The Playwright walk used in S18 is a starting point.
2. Check that every audience can tell at a glance whether private mode is on (the header switch, the frame line, the coloured edge).
3. Scout stays out of student mode (Q27, answered).

## Known gaps
- **Student retrieval:** 2 of 12 planted positives never reached a brief (top 40 of 500 by the interests note).
- **Shared Ollama:** the dev Ollama on 11434 reloaded gemma several times during generation, likely because another client asks for a different context size.
- **Recorded as README known limits (S20):** weekly awards refresh, shared watch briefs, index writers, private briefs not indexing, the hand-off opening's single check, Scout counts on Gemma, MCP with Ollama untested, student mode's sample data and retrieval misses.
- **UI preview:** the tracker's UI tab does not show the student flow yet (moved to S22).

## Next session: S18 — Student mode
1. Read S18 in `docs/PLAN.md` and the "Private mode as a state" section of `docs/design/PRIVATE_MODE.md`.
2. Finish the back end above. Then build the header switch, the Student path, the paste nudge, the two tabs and the hand-off offices.
3. The request-order test can run under Node, as the existing JS tests do.
4. The dev Clef servers on GPUs 1 and 2 stay up until S23 task 2.

## Open questions (mirror of bridge/QUESTIONS.md)
- None. Q26, Q27 and Q28 were answered on 2026-10-29: keep the ScholarshipUniverse seam; no Scout in student mode; no QA log exists.

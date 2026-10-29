# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session: S19 — Planted-case scoring and docs (done)
- Tasks 1 to 4 are done. Task 5 (Scout tool) is cut (Q27); task 6 (UI preview) moved to S22. 245 tests pass. No API spend.
- S17 and S18 finished earlier in the same run (student corpus, personas, student mode live).

## What S19 built
- **Scoring:** `bench/student_mode.py` drives the running app over HTTP (default the demo, 127.0.0.1:8090). It writes `bench/results/STUDENT_MODE.md` and `student_mode.json`.
- **Numbers (SYNTHETIC, a mechanism test):** the rules matched all 19 planted records that reached a brief. Retrieval missed 5 of 24, so 10 of 12 records a student may apply for reached the brief. Leakage: none.
- **Docs:** README student section with `docs/tour/student.webp`; SPEC Phase 3; a key-numbers row. The README results table has no synthetic number (rule 11).

## Next session: S20 — QA and privacy audit
1. **Task 1 needs a QA log a teammate keeps; none is in the repo.** Ask Dakshitha (a question), and meanwhile work tasks 2 to 4.
2. Privacy audit against the write-path inventory, now including student mode: monitor, Scout, MCP, exports, hand-offs, the sample store, the student brief.
3. Leakage check (rule 11): no sample record outside student mode, in the back-test, bench results, or results page.
4. Known gaps below: fix, or record as a README known limit. Include the flaky Scout test.

## Known gaps
- **Flaky test:** `test_route_b_answer_counts_and_dates_pass_the_validator` failed once in five runs (S17), and `make test` failed once more in S18 without a saved trace.
- **Student retrieval:** 2 of 12 planted positives never reached a brief (top 40 of 500 by the interests note).
- **Shared Ollama:** the dev Ollama on 11434 reloaded gemma several times during generation, likely because another client asks for a different context size.
- **From earlier sessions:** awards are not refreshed weekly; the monitor shares brief state; two-process LanceDB writes are untested; the MCP server was not tested with Ollama; a private brief does not index new opportunities; the hand-off opening has no layer-2 check; replay has no compare, hand-off or watch; Scout on Gemma sometimes states a count the validator withholds.

## Next session: S18 — Student mode
1. Read S18 in `docs/PLAN.md` and the "Private mode as a state" section of `docs/design/PRIVATE_MODE.md`.
2. Finish the back end above. Then build the header switch, the Student path, the paste nudge, the two tabs and the hand-off offices.
3. The request-order test can run under Node, as the existing JS tests do.
4. The dev Clef servers on GPUs 1 and 2 stay up until S23 task 2.

## Open questions (mirror of bridge/QUESTIONS.md)
- Q27: Scout in student mode. Default: leave it out for Demo Day; revisit in S21.
- Q26: ScholarshipUniverse schema. Can Temple SFS or the vendor share a sample export? Default: keep the generic schema and the seam.

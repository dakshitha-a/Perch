# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session: S18 — Student mode (done)
- Tasks 1 to 6 are done; task 7 (Scout `search_scholarships`) moved to S19. 245 tests pass. No API spend.
- S17 (scholarship corpus and personas) finished earlier in the same run.

## What S18 built
- **Private mode as a state:** `web/mode.js`, the header switch `#private-switch`, Student on Find, and the paste nudge. `mode.send()` and `mode.move()` open the session first.
- **Student brief:** `perch/student.py` (CV parse, rules, gaps) and `perch/private/student.py` (stages). `POST /private/student/brief`. The brief's stages are `student_profile`, `fellowships`, `scholarships`, `student_explanations`.
- **Stores:** the sample store is loaded at app start (`ensure_samples`) and read read-only. `perch samples` loads it by hand, and `perch fetch temple` stores the SDFA list (76 records; done on the dev and demo stores). The demo uses `PERCH_SAMPLE_DB=/app/data/demo/sample.db`.
- **Screens:** `web/student.js` holds the start form, the profile, both tabs, compare and a code-written hand-off. The evidence panel shows scholarships. Help has the new steps.
- **Fit skill:** a bare id such as `achievement-a` is mapped back to `private:achievement-a`.
- **Live:** the demo was rebuilt; all three personas work on the public URL. The canary check is clean.

## Next session: S19 — Planted-case scoring and docs
1. Run `bench/student_mode.py` against the demo (already written, not yet run). It drives the app over HTTP and writes `bench/results/STUDENT_MODE.md`.
2. Add the key-numbers row "Student mode (synthetic, mechanism test)".
3. README student section with a screenshot showing the badge. SPEC Phase 3 is already edited (uncommitted at S18's close).
4. Also from S18: the Scout `search_scholarships` tool, and the tracker's UI preview of the student flow.

## Known gaps
- **Flaky test:** `test_route_b_answer_counts_and_dates_pass_the_validator` failed once in five runs.
- **Shared Ollama:** the dev Ollama on 11434 reloaded gemma several times during generation, likely because another client asks for a different context size.
- **From earlier sessions:** awards are not refreshed weekly; the monitor shares brief state; two-process LanceDB writes are untested; the MCP server was not tested with Ollama; a private brief does not index new opportunities; the hand-off opening has no layer-2 check; replay has no compare, hand-off or watch; Scout on Gemma sometimes states a count the validator withholds.

## Next session: S18 — Student mode
1. Read S18 in `docs/PLAN.md` and the "Private mode as a state" section of `docs/design/PRIVATE_MODE.md`.
2. Finish the back end above. Then build the header switch, the Student path, the paste nudge, the two tabs and the hand-off offices.
3. The request-order test can run under Node, as the existing JS tests do.
4. The dev Clef servers on GPUs 1 and 2 stay up until S23 task 2.

## Open questions (mirror of bridge/QUESTIONS.md)
- Q26: ScholarshipUniverse schema. Can Temple SFS or the vendor share a sample export? Default: keep the generic schema and the seam.

# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session: S17 — Synthetic scholarship corpus and student personas (done)
- All four tasks are done. 234 tests pass. No API spend; the ledger is still $2.05 of $100.
- Dakshitha asked for S17 to S20 in one run, without stopping unless blocked.

## What S17 built
- **Schema:** `Scholarship` in `perch/schemas.py`, with `ScholarshipEligibility` and `ScholarshipRequirements`. A synthetic record must carry a `sample:` id and a canary.
- **Corpus:** `data/synthetic/scholarships.jsonl`, 500 SYNTHETIC records from `scripts/make_sample_scholarships.py` (seed 1729). The model wrote purpose sentences only; code set every field.
- **Its own store:** `perch/scholarships.py` loads the corpus into `data/sample.db` (`PERCH_SAMPLE_DB`), never the public store. It also holds the real-name check and the NIH F-series filter.
- **Temple pages:** `perch/sources/temple.py` parses SDFA's "Find a Fellowship" list into 76 public `Scholarship` records (source `temple_sdfa`). Fixtures in `tests/fixtures/temple/` keep `<main>` only.
- **Offices:** SDFA (`undergraduate.temple.edu/fellowships`, route F) and SFS (`sfs.temple.edu`, route S) are in `perch/offices.py`.
- **Personas:** `data/synthetic/persona-ug`, `persona-masters`, `persona-phd`. Each has a CV, interests, achievements and a hand-written `answer_key.json` for 8 planted records. The rules the keys follow are in `data/synthetic/README.md`.
- **ScholarshipUniverse:** no public schema exists. `perch/sources/scholarshipuniverse.py` is the documented seam for a real feed (Q26).

## Already started for S18 (uncommitted at S17's close, committed in S18)
- `perch/student.py`: the student CV parse, eligibility by rule and the gap list. It matches all 24 planted cases in the answer keys.
- `perch/private/student.py` and new `PrivateService` stages: a student brief with routes F (fellowships) and S (scholarships).
- The `Lead` schema gained `verdict`, `verdict_lines`, `gaps` and `sample`; routes F and S.
- `POST /private/student/brief`; `/private` now lists `student_kinds`.

## Known gaps
- **Flaky test:** `test_route_b_answer_counts_and_dates_pass_the_validator` failed once in five runs.
- **SDFA records are not in a store yet.** S18 must store them in the public store (a CLI step) so the fellowships route finds them.
- **Shared Ollama:** the dev Ollama on 11434 reloaded gemma several times during generation, likely because another client asks for a different context size.
- **From earlier sessions:** awards are not refreshed weekly; the monitor shares brief state; two-process LanceDB writes are untested; the MCP server was not tested with Ollama; a private brief does not index new opportunities; the hand-off opening has no layer-2 check; replay has no compare, hand-off or watch; Scout on Gemma sometimes states a count the validator withholds.

## Next session: S18 — Student mode
1. Read S18 in `docs/PLAN.md` and the "Private mode as a state" section of `docs/design/PRIVATE_MODE.md`.
2. Finish the back end above. Then build the header switch, the Student path, the paste nudge, the two tabs and the hand-off offices.
3. The request-order test can run under Node, as the existing JS tests do.
4. The dev Clef servers on GPUs 1 and 2 stay up until S23 task 2.

## Open questions (mirror of bridge/QUESTIONS.md)
- Q26: ScholarshipUniverse schema. Can Temple SFS or the vendor share a sample export? Default: keep the generic schema and the seam.

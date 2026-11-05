# S50 re-check of the round 2 must-fix items (2026-11-05)

A fresh-context, read-only re-check on `rebuild/v1` at dee7a6f. Each item was traced to code (file:line) or to a screenshot in `build/s50_qa_light/` and `build/s50_qa_dark/`. Commit messages were not taken as evidence.

- **Tests run:** `tests/test_s50_eligibility.py`, `test_s50_dates.py`, `test_s50_handoff.py`, `test_s50_student_rules.py`, `test_s50_scout_plan.py`, `test_student.py` and `test_eligibility.py`. All 56 passed.
- **Not re-run:** the reviews' measurements need the deploy store. These are the verdict script for G1, the 16 duplicate groups for G2, the hand-listed Temple pages for G5 and the notice count for G3. The verdicts below rest on code and unit tests.
- **Walk researcher:** PI-4 (A5026494099). The walk screenshots show the live name in the brief heading. The walk's example page uses a stub, so its screenshot cannot prove the alias. The deploy file can: `web/example/researcher.json` names the researcher as "PI-4" everywhere, and its explanations contain no "SYNTHETIC".

## UI/UX review

| ID | Status | Evidence | What is missing |
|---|---|---|---|
| V1 | closed | `web/styles.css:101` `:is(h1, h2, h3)[tabindex="-1"]:focus { outline: none; }` beats the global rule at :98. There is no heading box in w1280-awards, w1280-welcome or w360-awards. | — |
| V2 | closed | Keep and Dismiss are in a footer row, and the title row holds only the Match pill. Seen in w1280-brief-researcher, w1280-brief-student and w360-brief-student. | — |
| V3 | closed | `web/app.js:1641-1645` sorts by `match_score`, with rank as the tie-break, under "Best match" (:1668). w1280-s50a-route-t reads 55, 45, 43, 6, 2. | — |
| V4 | closed | `web/student.js:25-47` builds rule lines from `lead.checks`. `sharedRules` at :49 and :376-401 says a shared line once, as "Every option below". Cards in w1280-brief-student differ. | — |
| V5 | closed | The cover hint appears only in `coverListLine` (`web/cover.js:159-170`), and cards return null (:176). The withheld line is hidden when `S.listWithheld` is set (`web/app.js:2057`, `web/student.js:483`). | — |
| V6 | closed | `web/styles.css:557` uses `repeat(2, minmax(0, 220px))`. Amount sits at the same x on every card in w1280-brief-researcher and w1280-brief-student. | — |
| V7 | closed | `web/pages.css:8-16`: the box has no outer border, the input has its own border, the button sits outside it, and the native "×" is replaced by `.search-clear`. Seen in w1280-awards and w360-awards. | — |
| V8 | closed | `web/pages.css:127` sets one 760 px column. Cards and the Find button line up in w1280-welcome and w1280-s50a-student-start. | — |
| V9 | closed | Filters start folded (`web/browse.js:206`, `folded = true`; `web/pages.css:18-23`). The chip row is one row that scrolls sideways. The walk checks `s50b_filters_one_row_*` pass. | The phone screenshots show the filters opened. No screenshot shows the folded state, but the code proves it. |
| V10 | closed | `--line-strong` is at `web/styles.css:26`, :56 and :72, and is used on fields and buttons (:123, :175 and others). Measured: light 3.33 on the page, 3.55 on cards and 3.08 on chips. Dark: 4.05, 3.64, 3.06 on chips and 3.19 on dialogs. | 3.06 and 3.08 on chips are the tight pairs; they still pass. |

## Product review

| ID | Status | Evidence | What is missing |
|---|---|---|---|
| Q1 | closed | `perch/student.py:147` adds `Verdict.checks`, and `check()` fills one line per rule (:293-447). The card shows them, and so does the compare (`web/student.js:586`). | — |
| Q2 | closed (code) | `perch/student.py:210-242`: POSTDOC_NAME (F32, F33 and "postdoctoral") gives level "postdoc", and `NOT_STUDENTS` (:593) leaves those out of the pool. F31 becomes graduate. The sample brief's top cards are no longer F32 or F33 (w1280-brief-student). | This was done in code, not in `data/overrides/`. It was not checked on the live deploy store. |
| Q3 | closed | `perch/skills/handoff.py:229-235` (`split_internal`) leaves Temple internal leads out and sets `left_out_note`. `web/handoff.js:78-88` counts federal grants only and shows the code-written Temple line. Walk check `s50b_temple_handoff` passes. | — |
| Q4 | closed | `web/student.js:159-201` saves every filled box, then builds. w1280-s50c-find-after-sample shows "Save and find awards" enabled after Load sample. | — |
| Q5 | closed | `build/s50_live/LIVE.md` holds model text from the deploy: a researcher brief (PI-1, A5063022331), two Scout answers, cover points, a hand-off draft and a SYNTHETIC student brief. | The capture is of PI-1, not PI-4. It is text, not screens. |
| Q6 | closed | Stop is on the waiting screen (`web/app.js:1144`, w1280-s50a-building) and on a busy My Perch row (`web/account.js:359`, w1280-s50b-my-perch-busy). A stopped brief shows "Stopped" with "Run again" or "Change details and run again" (w1280-s50b-my-perch-stopped). | — |
| Q7 | partly | Links under two walls: `web/scout.js:89-95` "Or see an example answer" and `web/handoff.js:188-193` "Or see an example draft". The example page is `web/example.html`, and the file exists in `web/example/`. | The review asked for a small SYNTHETIC example inline under each of three walls. The design (S50_DESIGN §1) cut this to links under two walls, and the cover-points wall gets none. No full-walk screenshot shows a link under a wall, because the walk has no example file outside its stub. Only `[mock]` checks prove them. On a student brief the Scout link opens the researcher example. |

## Back-end review

| ID | Status | Evidence | What is missing |
|---|---|---|---|
| C1 | partly | `perch/jobs.py:255-283` stops the clock while a thread of the job waits for the slot, with a hard cap of 3× the timeout. `perch/service.py:799-806` treats `SlotTimeout` as transient. The observer is a contextvar (`perch/compute.py:96`) and is set in the job thread (`perch/jobs.py:578-586`). | **Gap:** `perch/skills/fit.py:314-315` runs explanations in a `ThreadPoolExecutor` without `contextvars.copy_context()`. The grounder takes the model slot inside those threads (`perch/skills/fit.py:249-272`, `perch/compute.py:147-152`). So on a CPU or CUDA profile, the deploy's included, slot waits during the explanations stage still count against the 300 s timeout. |
| C2 | closed | `perch/jobs.py:618-636` runs at most `PERCH_PRECACHE_CONCURRENCY` (default 1) precache jobs per worker. DECISIONS 2026-11-05 records that the deploy runs the scheduler, with the precache at 08:00 UTC. | The walk server script `build/devdemo/serve.sh` does not set `PERCH_SCHEDULER=0`, which Step 0 of the design asked for. This is a minor gap. |
| C3 | closed | `perch/user/briefs.py:873-889` (`overlay_summaries`) is applied at `perch/user/routes.py:207`. A stored failed brief carries its error (:196-197). | — |

## Function review

| ID | Status | Evidence | What is missing |
|---|---|---|---|
| G1 | closed (code) | `perch/student.py:205-249`: when the tag is "mixed" or empty, the award's name sets the level. "Graduate", "Doctoral", "Dissertation", "Master's" and "PhD" mean graduate. Postdoc names are left out, and F31 becomes graduate. Unit tests pass. | The verdict script, which should go from 10 wrong-level names to 0, was not re-run. |
| G2 | closed (code) | `perch/student.py:604-647`: `award_key` drops plurals and the words programme, scholarship, scholars and award. Merging works within a source too. The fellowships-office copy is kept (`_keep`). There is a reviewed `DISTINCT_AWARDS` list. | The list sits in code, not in `data/overrides/`. The group count, 16 down to exceptions only, was not re-measured. |
| G3 | closed | `perch/eligibility.py:68-77` and :159-160 leave out notices, requests for information and sources-sought notices. The hidden group row is at :269. The walk's hidden fold lists "notices and requests for information…: 1". | — |
| G4 | closed | `scripts/refresh_v1.py` has plan, apply, vectors and epoch phases, with a stop when more than 200 records go missing. `docs/deploy.md:128-144` gives a backup-first runbook and records the 5 Nov results (26 new, 59 changed, 47 now closed). | `deploy.md:141` says the precache runs at 02:00 UTC. DECISIONS says the deploy runs it at 08:00. Only Grants.gov is refreshed. |
| G5 | closed | `perch/eligibility.py:217-262`: a page dated more than 396 days ago is hidden as "page last dated X". NIH codes and student words in titles are left out. `dedupe_titles` in `perch/brief.py` keeps one page per title. The 396-day limit is in DECISIONS. | The Temple pages were not hand-listed on the store. |
| G6 | closed | `perch/student.py:450-459` (`listing_lines`) says what Perch checked and quotes `eligibility.notes`. The cards show per-rule lines (w1280-brief-student). | — |
| G7 | closed | `web/student.js:463` (`neither`) gives a fellowships-office record one line: "The fellowships list gives neither. Check the award's own page." (Boren card, w1280-brief-student). | No page link sits beside the line; the Evidence button is the only way to the page. Temple-page records still show "Not stated" twice, which is outside G7's scope. |
| G8 | closed | `perch/datefmt.py:67-86` (`FAR_TEXT`, `far_close`) and `web/browse.js:21` and :65-75 handle a date more than 10 years out, with or without the record's words. | Checked in code. No 2076 record shows in the funding screenshots. |

## Round 1

| ID | Status | Evidence | What is missing |
|---|---|---|---|
| P6 | closed | Same as Q1, V4 and G6. Student cards list each rule checked with its outcome, such as "Level: open to undergraduate students; the sample student's CV says bachelor's." and "Year: open to undergraduate years 1, 2, 3 and 4; …year 3." (w1280-brief-student, w360-brief-student). | — |

## Scout plan (G9 to G18; not in the must-fix list, not graded)

- **Done in code:** G9, G12, G13, G15 and G16 have their own commits and code.
- **Not done:** no commit or code was found for G10 (bench against a real brief), G11 (code cites brief facts), G14 (absence tails), G17 (MiniCheck flag groups) or G18 (one real run).

## New problems seen

- **C1 gap, must-fix:** `perch/skills/fit.py:314-315`. The explanation pool threads lose `slot_wait_observer`. A brief can still time out for good while its explanation threads wait behind the precache or another brief. The fix is `pool.map(lambda i: ctx.run(one, i), ...)` with a fresh `contextvars.copy_context()` for each task, or a pool initializer.
- **Canary tokens on screen, should-fix:** w1280-s50c-find-after-sample shows "Canary: PERCH-CANARY-UG-CV-3R8D" and the INT and ACH canaries in the Load sample boxes. Q17 decided that canaries are hidden on screen. A presenter will press Load sample on stage.
- **Q7 example links are unproven in the full walk, should-fix:** neither wall link appears in any full-walk screenshot. One walk state with the example file present would prove them.
- **Doc inconsistency, minor:** `docs/deploy.md:141` says the deploy's precache runs at 02:00 UTC. DECISIONS 2026-11-05 says 08:00 UTC.
- **Help is out of date, minor:** in w1280-s50b-help, researcher step 3 says "Grants and Industry are separate lists" and does not name Temple internal. The illustration still puts Keep and Dismiss in the card head.
- **Not a bug:** in w1280-scout-clean, the header drawn mid-page is a sticky-header capture artifact.
- **Expected:** the funding browse list still shows requests for information, such as DE-FOA-0003671 with "$1 to $2". Q9 was deferred.

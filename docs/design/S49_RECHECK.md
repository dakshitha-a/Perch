# S49 must-fix re-check (fresh context, 2026-11-05)

Read-only re-check of every must-fix item in the five S48 and S49 review documents and the owner's notes, against the code at `rebuild/v1` HEAD (e5d6aa5). Each item is traced to code or to a screenshot from `build/s49_qa_light/` or `build/s49_qa_dark/`. The screenshots were taken after the last commit that touched `web/`.

Unit tests run: `test_s49_function.py`, `test_validate.py`, `test_browse_sort.py`, `test_compare.py`, `test_jobs_pg.py` and `test_worker_service_once.py`. Result: 49 passed and 30 skipped. The skipped tests need `PERCH_TEST_DATABASE_URL`, so the Postgres race and scheduler tests did not run here.

**Totals:** 37 closed, 2 partly, 1 open and 1 scheduled, out of 41 items. The owner's note 3 was a data fix and is counted as closed.

## S48 UI review (M1 to M6)

| ID | Status | Evidence | What is missing |
|---|---|---|---|
| M1 Empty agency tag | closed | `web/app.js:1896-1902` draws the sub-line only when it has text. Screenshot: w1280-s49a-brief-researcher. | The `.tag:empty` backstop is not in the CSS. The cause is removed, so this does not matter. |
| M2 Citation chips stretch lines | closed | `web/styles.css:139` sets `.cite` to inline with `line-height: inherit` and `min-height: 0`. No other `.cite` rule sets a height. | — |
| M3 Documents card stretches | closed | `web/styles.css:1000` sets `.box-grid` to `align-items: start`. | — |
| M4 Wrong "Check my fit page" text | closed | The text is gone. The researcher CV card has an upload control at `web/app.js:656-712`. Screenshot: w1280-s49a-pick-cv. | The Account page documents list has Remove only and no upload. The review did not ask for one there. |
| M5 Compare order | closed | `web/compare.js:115-131` puts the table first and the hand-off after it. Screenshot: w1280-s49b-compare. | — |
| M6 Cover heading chevron on phone | closed | `web/pages.css:95-96` sets `flex-wrap: nowrap` and `flex: 1` on the text. Screenshot: w360-cover-result. | — |

## Owner's notes (S48_UI_NOTES items 1 to 7)

| ID | Status | Evidence | What is missing |
|---|---|---|---|
| N1 Landing: one short CV line, no scroll | closed | Screenshots w1280-s49a-landing-1280x720-s and -r both fit 720 px. The footer line reads "Your CV is encrypted and deletable". | — |
| N2 Student "Load sample" | closed | `web/student.js:147-148` and `web/student.js:184-200`. Screenshot: w1280-s49-load-sample-after shows the SYNTHETIC tag. | — |
| N3 Awards looked empty | closed | Data fix. Screenshot w1280-s49b-awards shows 360 matches. | — |
| N4 Researcher CV upload on first visit | closed | `web/app.js:656-712`, the cvBox on the pick screen. Screenshot: w1280-s49a-pick-cv. | — |
| N5 Grant cards: title, empty tag, space | closed | `web/app.js:1880-1960` puts the title first, adds a sub-line and always shows two facts. Screenshot w1280-s49a-brief-researcher shows titles, not record ids. | — |
| N6 Change details and run again | closed | `web/app.js:184-187` has the `#/rerun/` route. `web/app.js:727` is `rerun()`. `web/account.js:347` links to it. The brief header links to it at `web/app.js:865`. Screenshot: w1280-s49b-my-perch. | — |
| N7 Alignment, stored-documents card | closed | This note was for the review passes. The card it named is fixed under M3. The U-series covers the rest. | — |

## S49 UI/UX review (U1 to U6)

| ID | Status | Evidence | What is missing |
|---|---|---|---|
| U1 School counts wrong under search | closed | `web/browse.js:202-206` `syncCounts` hides `.n` while a search or level is set. The `[hidden]` rule is `!important` at `web/styles.css:1187`. Screenshot: w1280-awards-empty. | — |
| U2 Compare title starts with the number | closed | `perch/compare.py:126-127` keeps the title and the number apart. `web/compare.js:111-112` shows the number on its own line. Screenshot: w1280-s49b-compare. | — |
| U3 Withheld warning on every card | closed | `web/app.js:1673-1684` and `web/student.js:316-317` show one notice when two or more cards are flagged. Each card keeps one hint line: `web/app.js:1924` and `web/student.js:399`. | — |
| U4 Invisible page scrollbar | closed | The page-level `scrollbar-color: transparent` rule and the mousemove toggle are gone. The only `scrollbar-color` left is `.rail-evidence` at `web/styles.css:1300`. | — |
| U5 Disabled office hint unreadable | closed | `web/pages.css:89-91` fades only the input and the label. The hint stays at full `--ink-3`. Screenshots: light and dark w1280-handoff-busy. | — |
| U6 Allowance error on every card | closed | `web/cover.js:128-140` shows one notice with the reset time. Each card gets a short pointer, `COVER_QUOTA_CARD` at line 20. Screenshot: w1280-s49b-cover-quota. | — |

## S49 product review (P1 to P8)

| ID | Status | Evidence | What is missing |
|---|---|---|---|
| P1 Saved list promised, never built | closed | `perch/user/routes.py:134-165` has the GET, POST and DELETE routes for `/me/saved`. `perch/user/saved.py:62-63` writes `saved_item`, which Scout reads at `perch/scout/job.py:101-103`. Keep on browse rows is at `web/browse.js:138-156`. Screenshot: w1280-s49b-my-perch. | — |
| P2 Funding opens on closed calls | closed | `perch/store/postgres.py:154-156` adds `open_only`. `web/browse.js:181` sends it for researchers, and the "Show closed calls" switch is at `web/browse.js:308-310`. | — |
| P3 Browse lists have no sort | closed | `perch/browse/routes.py:118` accepts name, closing or amount. The select is at `web/browse.js:31-32` and `web/browse.js:324-325`. | — |
| P4 Guest sees no office name | closed | `perch/api.py:824-830` sends `offices`. `web/app.js:1247` passes them on. Screenshot w1280-brief-student-compare, a guest, reads "Scholar Development and Fellowships Advising". | — |
| P5 Hand-off before the comparison | closed | Researcher: `web/compare.js:131`. Student: `web/student.js:507-513`. | — |
| P6 "May be eligible" with no gaps says nothing | **open** | S49_DESIGN.md section 2, "Deferred must-fix", moves it to round 2. Student cards still show only the fixed "To check" line. Screenshot: w1280-s49a-brief-student. | A code-written line that says what the rules checked, for example "Level checked; the listing states no deadline". |
| P7 Hand-off wait shows no progress | **partly** | `web/handoff.js:98-109` names the office and lists the kept lead titles while the model writes. The ERA line is already on screen above the button. Screenshots: light and dark w1280-handoff-busy. This matches the "cheap version" chosen in S49_DESIGN.md section 1. | The code-written subject line is not shown during the wait, and the code-written parts of the draft do not show before the model's paragraph arrives. |
| P8 Returning user lands on the guest landing | closed | `web/app.js:147-151` makes My Perch the signed-in home. The header has a My Perch link at `web/app.js:331`. | — |

## S49 back-end review (B1 to B5)

| ID | Status | Evidence | What is missing |
|---|---|---|---|
| B1 A brief whose job ends badly polls forever | **partly** | `perch/user/briefs.py:840-864`, `brief_job` and `job_overlay`, show a brief as `failed` with a code-written sentence when its job is failed, dead, cancelled or missing. `perch/api.py:774-778` applies this on GET. A cancel route is at `perch/api.py:878-889`. | Case 3, no worker running, is not handled. The job stays `queued`, and the server returns `worker_seen: false`. `web/` never reads `worker_seen`. So `web/app.js:991-996` keeps saying "Another brief is building on this server" and `web/app.js:819` keeps polling. No page calls the cancel route either. |
| B2 Keep during a run fails the brief | closed | `perch/user/briefs.py:100-104` keeps the user's lead status. `perch/user/briefs.py:303-332` retries on Conflict and keeps the user's statuses. The guest store uses a WATCH merge at `perch/user/briefs.py:530-560`. | — |
| B3 A DB blip kills worker threads | closed | `perch/jobs.py:600-605` catches every exception around `execute`, logs it, waits and continues. | — |
| B4 Two identical clicks make a dead brief | closed | `perch/user/briefs.py:712-715`, signed in, and `perch/user/briefs.py:741-744`, guest: the losing twin's brief is deleted, and the winning pair is returned through `_same_request_won` at line 749. | `quota.admit` at line 707 still runs before the twin check. The losing request's quota charge is not given back. This is minor. |
| B5 No retention purges scheduled | closed | `perch/jobs.py:659-725`, the `Scheduler`, submits the five daily purges and the nightly precache with dated keys. It is wired into `perch worker` at `perch/cli.py:777-783`. | — |

## S49 function review (M1 to M9)

| ID | Status | Evidence | What is missing |
|---|---|---|---|
| FM1 Open-anytime grants dropped | closed | `perch/eligibility.py:118-140`, `ANYTIME_RE` and `open_anytime`, keeps only records posted in the last ten years. Screenshot: w1280-s49a-brief-researcher shows "Proposals accepted anytime". | — |
| FM2 Level rule never fires on Temple pages | closed | `perch/student.py:189-207`, `AUDIENCE_LEVELS` and `study_levels`. They are used at line 221. | — |
| FM3 Deadline words shown as "Not stated" | closed | `perch/scout/read_tools.py:94-105`, `deadline_words`. `perch/scout/answer.py:466-475` returns False for `_absent_fact` when a quote exists. The UI is at `web/student.js:374`, `web/app.js:1909` and `web/browse.js:105`. | — |
| FM4 Number inside an allowed link fails | closed | `perch/validate.py:143-147` removes passed links before it counts numbers. | — |
| FM5 Fit text cached one day only | closed | `perch/cache.py:71-75`, `text_profile_hash`, leaves out as-of. It is used at `perch/service.py:526`, `perch/service.py:562` and `perch/service.py:738-740`. | — |
| FM6 Federal snapshot a week old | scheduled | This is a data refresh planned for later. | — |
| FM7 Last year's date makes "not eligible" | closed | `perch/student.py:203-218`, `past_cycle`, gives "may be eligible" with the code-written line. | — |
| FM8 Staff awards in the student pool | closed | `perch/student.py:418-443`, `STAFF_AWARDS` and `NOT_STUDENTS`. `student_pool` is used at line 480. | The exclusion list is in code, not in `data/overrides/` as the review suggested. |
| FM9 Temple internal funding unreachable | closed | `perch/eligibility.py:195-230`, `check_temple_internal`. `perch/service.py:445-455` builds the separate group. The UI has route T at `web/app.js:832-834` and `web/app.js:1542`. Screenshot: w1280-s49a-brief-researcher shows "Temple internal 3". | — |

## New problems seen

None of these is clearly must-fix. The first one is the closest.

- **B1 follow-on: the waiting message is wrong.** When no worker is running, `web/app.js:996` tells the user "Another brief is building on this server". That is untrue, and the page polls forever. The server already reports `worker_seen: false` from `perch/user/briefs.py:830-831`. This is the missing part of B1, and it is the one that could bite on Demo Day if the worker unit is down.
- **Should-fix: the browse heading shows a focus box.** In w1280-s49b-awards, the h1 "Temple awards" shows a full-width blue focus box after navigation. This is on the demo path. It is the S48 "heading focus" nice-to-have, which was deferred.
- **Data quality: a deadline quote that is not a deadline.** In w1280-s49b-awards, "Air Force ROTC" shows the deadline quote "Students interest in four-year awards mu…". That is a sentence fragment, not a deadline. The `deadline_quote` extraction in the Temple-page parser picked it up.
- **Minor: the reset time has no year.** In w1280-s49b-cover-quota, the reset time "Jan 1 12:00 AM" has no year. `backAt` at `web/cover.js:129-135` never shows the year. Real resets are always the next day, so the effect is small.

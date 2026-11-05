# S51 re-check, after review round 3 (2026-11-05)

A fresh-context, read-only re-check of `rebuild/v1` at 7b89df0. Evidence is the code, `tests/test_s51_*.py` (50 passed, 3 skipped for Postgres), the walk screenshots in `build/s51_qa_light/` and `build/s51_qa_dark/`, and the live capture `build/s50_live/LIVE.md`. That capture was written at 06:44, after the deploy units restarted at 06:41:50 on the merged code. Commit messages and reports were not used as evidence.

Counts: 32 must-fix items. 23 are closed, 5 partly (D5, D6, D7, E1, E3), 2 scheduled (D8, D9) and 2 open (D1, D10). E6 is a should-fix, listed as well because the brief named it; it is closed.

## Items

| ID | Status | Evidence | What is missing |
|---|---|---|---|
| W1 | closed | `web/styles.css:1714-1718`; w360-s51a-example, light and dark: the tag and Back to Perch share row 1, and the text runs full width below. | — |
| W2 | closed | `web/styles.css:1721-1727`; w360-s51a-example: Replay the build and Steps sit on their own row. | — |
| W3 | closed | `web/student.js:61-72` (`noCanary`, `withCanary`); w360-s51b-sample-no-canary shows no canary in any box. The walk check confirms the saved text keeps it. | — |
| W4 | closed | `web/app.js:1708-1713`: skeletons are drawn only when not failed. w1280-s51a-stopped has no skeleton. | — |
| W5 | closed | `web/app.js:1068`. w1280-s51a-stopped shows one Run again. w360-s51a-building shows only Stop. | — |
| W6 | closed | `web/app.js:1713`: "What Perch read fills in first." | — |
| W7 | closed | `perch/compare.py:117` writes "no written reason". `:185-186` drops the instrument row when every column is a grant. Seen in w1280-handoff-ready. | — |
| W8 | closed | `web/compare.js:64`: "Best match". | — |
| W9 | closed | `web/cover.js:13` (`COVER_HINT_SAMPLE`) and `:163`. | — |
| W10 | closed | `web/styles.css:1729`. In w1280-s51a-landing-closed-r the hint and "What else you can add" share one centre line. | — |
| W11 | closed | `web/styles.css:1731-1734`. w360-s51a-example shows the chips in one row that scrolls sideways. | — |
| W12 | closed | `web/account.js:350`: the visible text is "Run again" and the long phrase is its aria-label. w1280-s51b-my-perch-order shows Open, Run again, Stop in that order. | — |
| D1 | open | `web/example/researcher.json` is still from 3 Nov (`created_at` 2026-11-03), and no lead has a `group`. | Re-exporting both files is listed only in S51_DESIGN 3.6. It is not in `docs/sessions/S52.md` or `bridge/QUESTIONS.md`. |
| D2 | closed | Same fix as H1. In the live cover points, each of the 4 `you` sentences cites one paper, and `unsupported: []`. | — |
| D3 | closed | `perch/eligibility.py:56-67`; `perch/service.py:461-464`. Rank and Match are unchanged. w1280 and w360 s51a-centre-fold show the fold and the code-written line. | The hand-off still lists the P30 for Research Development (LIVE hand-off, lead 1). Limits covers this. |
| D4 | closed | `web/app.js:401-412`: while accounts are closed, the second button reads "Try a sample student" and calls `startGuest`. `perch/auth/routes.py:186,189` sends `accounts_open`. `.env.deploy` has `PERCH_ACCOUNTS_OPEN=0`. Seen in w1280 and w360 s51a-landing-closed. | — |
| D5 | partly | The Scout wall (`web/scout.js:86-104`) and the researcher hand-off wall (`web/handoff.js:137-141`) lead with the example. | **1.** The student "note to the office" wall, `web/student.js:637`, never reads `accountsOpen`. A guest still gets a primary "Sign in to draft a note to the office" (w1280-brief-student-compare). This is on the audience's sample-student path. **2.** The closed cover-points line (`web/cover.js:166-168`) has no example link, which D5 asked for. |
| D6 | partly | H4 shipped. The live stage reads "15 explained, 0 withheld, 5 name only", and the cards show the code-written line. | The top three are still the name-only listings Livingstone, Dean's Grant and PASG (LIVE and w1280-brief-student). Nobody looked into why REU, Hollings and Truman left the top ten. Limits covers this. |
| D7 | partly | Scheduled half: S52 task 2 covers clearing the guest spend and rate keys. | The rest of the run sheet is not in S52.md or QUESTIONS. That means the pre-built presenter briefs, kept leads, drafted hand-off, Scout answer, the $5 ledger check, the 25-minute idle rule and the fallback rehearsal. |
| D8 | scheduled | `bridge/QUESTIONS.md` Q52 (port 8443 on venue Wi-Fi; decided at the gate). | — |
| D9 | scheduled | `bridge/QUESTIONS.md` Q51 (a decision for Dakshitha). | — |
| D10 | open | README.md has no "See it" line and no example link. `.gitignore:54` still ignores all of `web/example/`. | S52 task 4 rewrites the README but does not name this line or the tracked student example. |
| E1 | partly | `.env.deploy` sets `PERCH_GUEST_DAILY_BUDGET_USD=0.30`, recorded in DECISIONS 2026-11-05. The live student brief explained 15 of 15, with 0 withheld. | `.env.example` still does not list `PERCH_GUEST_DAILY_BUDGET_USD`, which the review asked for. |
| E2 | closed | `perch/jobs.py:706-727` (`FAST_KINDS`, `fast_threads`, `thread_kinds`) and `:618-626`; `.env.example:158`; `tests/test_s51_worker.py` passes. | — |
| E3 | partly | Scheduled half: S52 task 1 disables the user. `deploy/compose/keycloak/perch-realm.json:6` has `bruteForceProtected: true`. `scripts/e2e_oidc_login.py:236-239` sets a random password on every run. | `--import-realm` does not change a realm that already exists, so whether the live realm has lockout cannot be checked from the repo. Someone must check or set it by hand. `e2e-user.json:10` still holds the tracked password, used at creation. |
| E6 | closed | No tracked file contains the tunnel host name. `scripts/live_capture.py:18-20` reads it from `PERCH_LIVE_BASE`. `tests/test_public_hygiene.py:26` checks the pattern. | — |
| H1 | closed | `perch/skills/cover.py:257` (`YOU_SUBJECT`), `:260-279` (verb agreement), `:390-394` (more than one paper fails), and the prompt at `:93-94`. Live: 4 of 4 points cite one paper each, and `unsupported: []`. | — |
| H2 | closed | `scripts/live_capture.py:117` (`top`) and `:135` (`again: True`). The capture ran after the restart: the route_a stage reads "11 leads, 3 Temple internal", and K01 and CIBER are gone. | — |
| H3 | closed | Fixed by the decision ($0.30 per guest session). Live: "15 explained, 0 withheld". | — |
| H4 | closed | `perch/service.py:745-753`. The live stage reads "5 name only". | — |
| H5 | closed | `perch/validate.py:101-130` walks nested dicts and lists of numbers. `tests/test_s51_validate.py` passes. | — |
| H6 | closed | `perch/student.py:672` and `_carry_amount` at `:677-697`. | One case remains. The carry is skipped when the kept copy already has a different `details_url`. The count of 0 lost amounts was not run again here. |
| H7 | closed | The same evidence as D3. `perch/scout/read_tools.py:403` also passes the centre note to Scout. | — |

## Limits check (S51_DESIGN.md section 5)

| # | Bullet (short) | Verdict | Note |
|---|---|---|---|
| 1 | Accounts not open; the example shows a signed-in user | true | `.env.deploy` has `PERCH_ACCOUNTS_OPEN=0`. |
| 2 | The example plays back a file and has no cover points | true | `web/example.js` has no cover path, and `coverBlock` needs live mode. |
| 3 | Guests cannot paste a CV | true | `web/student.js:139`. |
| 4 | Small guest budget; written reasons pause | true | $0.30 per session. The budget line exists on both sides. |
| 5 | Only P30, P01, P50 and U54 are folded | true | `perch/eligibility.py:56`. The DECISIONS row for 2026-11-05 says "and similar institution-level mechanisms", which the code does not do. Fix the decision row, not the bullet. |
| 6 | Scout and the hand-off do not use the centre label | **false in part** | Scout now gets the centre note in `read_brief` (`perch/scout/read_tools.py:403`). The hand-off still does not use it. Suggested text: "The note to the office does not use the centre-grant label, and Scout may still call a centre grant a strong match." |
| 7 | Match is not the odds; text can be weaker than the band | true | — |
| 8 | Several cards can cite the same papers when the researcher has few recent papers | true, but the cause is unverified | Live PI-1: W7166197087 is on 10 of 11 grant cards, which form about 6 distinct sets. PI-1 has 437 works in the store. Suggest dropping "when the researcher has few recent papers". |
| 9 | No reason written for a name-only listing | true | — |
| 10 | A student brief can open on listings that say little | true | The live and walk top three are all name-only. |
| 11 | The citation check can flag a correct two-fact sentence | true | H16 was not changed. |
| 12 | Some cover points can still be marked not matched | true | The live run had 0 of 4, but nothing prevents it. |
| 13 | Scout removes sentences it cannot check, such as absence claims | true | H17 kept the removal. |
| 14 | Scout may mention no CV or entries unasked | true | D11 was not built. |
| 15 | The same brief or cover points on the same day returns that day's | true | `perch/user/briefs.py:641-650` (the key includes the UTC date). |
| 16 | The awards list sorts A to Z by default | true | `web/browse.js:36`. |
| 17 | The funding list shows requests for information | true | `NOTICE_RE` is used only in eligibility, not in browse. |
| 18 | Saves and keeps are two separate lists | true | Not changed this round. |
| 19 | The note to the office waits up to two minutes | true | `web/handoff.js:113`. W28 did not ship. |
| 20 | Run again sits in the header with no confirm | true | There is no confirm in `web/app.js`. It still sits beside Export in w1280-handoff-ready. |
| 21 | Only Grants.gov is refreshed on the deploy | true | `docs/deploy.md:129-142`. |
| B-H6 | Merged award loses an amount | **closed** | H6 shipped, so drop this bullet. One rare case remains: the kept copy cites its own different page. |
| B-H13 | Scout removes some headings, such as a comparison heading | **closed** | H13 shipped (`perch/scout/texts.py:146-153`), so drop this bullet. "Comparison of your top two leads" is still removed on purpose. Keep the main Scout bullet (13) unchanged. |

## New problems seen

- **The student hand-off ignores closed accounts:** this is the same gap as D5. It is at `web/student.js:637` and shows in w1280-brief-student-compare. A guest on the sample-student path meets a primary Sign in that leads nowhere.
- **No screenshot shows the closed walls:** `s51b-walls-closed`, at both widths and in both themes, shows the Help page. The flow (`scripts/walk_flows/s51_fe_b.py:56-88`) appends the walls to the foot of the Help page, below the capture. The walk check passed on DOM values only, so nobody has looked at the walls.
- **The closed walls can point to an example that is not there:** the hint "See what a signed-in user gets in the example." is drawn before `exampleAvailable` answers (`web/scout.js:89`, `web/handoff.js:140`). On a server without the example files, the hint points to nothing, and only a quiet Sign in follows.
- **My Perch offers Run again on a brief that is still building:** see w1280-s51b-my-perch-order. The brief header now hides it in that state (W5).
- **HANDOFF.md has an old guest budget:** `docs/HANDOFF.md:33` still says the guest budget is $1.50 an address and $6.00 a day. The 5 Nov decisions set $4.00 an address, $8.00 a day and $0.30 a session.
- **The example-page walk shows a real name:** the h1 in s51a-example shows the walk researcher's real name, while the banner says "shown as PI-4". This comes from the walk fixture. The real `web/example/researcher.json` has `display_name` PI-4. It matters only if a walk image is reused, which S52 task 5 already forbids.
- **Polish still open on the demo path:** none of these is a must-fix. The student landing has no example link when the file is absent. Scout's "New conversation" is still a grey chip (W27). The student cards still say "Not stated" plus a rule line about the deadline (W16). The P30 is still rank 1 in the hand-off draft.

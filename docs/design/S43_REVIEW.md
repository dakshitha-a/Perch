# S43 review — student-first UI, fresh context

Independent UI and UX review of Phase 7, written on 4 Nov 2026. The reviewer read `docs/REBUILD_PLAN.md` Phase 7, `docs/design/S43_DESIGN.md`, the S43 rows in `docs/DECISIONS.md`, `docs/design/A11Y_CHECKLIST.md`, the web code, the three route files and every screenshot in `build/s43_walk/` and `build/s43_walk_signin/`. No server was run. Each finding names the screen, the place in the code, what is wrong and a fix.

Counts: 7 must-fix, 17 should-fix, 9 nice-to-have.

---

## Must-fix

### M1. Sign-in failures land on a raw JSON page

- **Screen:** every "Sign in" link, and "Check my fit with my CV" on the landing for a signed-out visitor.
- **Where:** `perch/auth/routes.py` `callback`, the `except AuthError` branch returns `{"error": code}` with status 400. `/auth/login` answers `{"detail":"auth_unavailable"}` when no identity provider is set up. `build/s43_walk/w1280-debug-student-start.png` shows exactly this page.
- **What is wrong:** a student who presses Back at the provider, whose state cookie expired, or who visits while SSO is not registered sees a JSON blob with no way home. The plan's Risks section says Temple SSO is not registered yet, so on the demo the landing's second button may lead here every time.
- **Fix:** on a browser navigation, redirect both failures to `/#/` with a code, such as `/#/?signin=failed` or `?signin=unavailable`. The app shows "Sign-in did not finish. Try again." in the banner slot, as design 2.1 says. When sign-in is unavailable, the landing shows "Try a sample student" instead of a dead sign-in link.

### M2. My Perch counts sample leads together with public leads

- **Screen:** My Perch, the brief rows, such as "Built 3 Nov 2026 · 12 leads · done" in `w1280-my-perch.png`.
- **Where:** `perch/user/routes.py` `_summary` sets `"leads": len(sb.leads)`. A student brief holds route F public leads and route S SYNTHETIC leads. `web/account.js` line 225 prints that number.
- **What is wrong:** standing rule 11 says synthetic records never appear in any number next to public records. This count mixes them.
- **Fix:** return public and sample counts apart from `_summary`, using `lead.sample`. Show "10 options" and, on its own, "10 sample options", or show only the public count. `keptWords` in `web/student.js` line 35 already does this split.

### M3. The student brief describes its search falsely

- **Screen:** the student brief, Your options, the Fellowships route, in `w1280-brief-student.png`.
- **Where:** `web/student.js` line 11 names the route "Fellowships (public)". Line 249 says "Public listings: Temple's Scholar Development and Fellowships Advising list and NIH fellowships." But `perch/service.py` `_run_fellowships` searches every non-synthetic `Scholarship` row. The store now holds 360 of those, and the `temple_pages` scholarships are among them.
- **What is wrong:** the screen names two sources when it searched three. A student who just browsed 360 Temple awards is told the brief searched fellowships only. That is a false statement on screen under rule 10. `fromPage` and `amountText` at lines 271 and 376 also treat only `temple_sdfa` as a page source.
- **Fix:** first confirm with one brief that its F leads include `source: temple_pages`. If they do, rename the route "Temple awards and fellowships". Write the hint from the stage's own summary line, which already says "N Temple-listed and N NIH fellowships searched". Extend `fromPage` to `temple_pages`. If they do not, the landing's promise of checking fit against Temple awards is not met, and that is a scope question for Dakshitha.

### M4. The sample route sits as a tab inside the student brief, against fork F6

- **Screen:** the student brief route switch "Fellowships | Scholarships and awards, Sample data", and Compare's "Scholarships and awards (sample)" table.
- **Where:** `web/student.js` lines 223 to 231, 244 and 398 to 449, and `perch/service.py` `_run_scholarships`.
- **What is wrong:** fork F6, decided on 4 Nov, puts samples on their own screen, linked from the brief, so that rule 11 is met by layout. The build still ships option B, a sample tab beside real options. `web/help.js` line 297 then tells users that samples "live on their own screen", which is false for the brief.
- **Fix:** for a signed-in student, drop the S stage or hide its tab, and add a "See how Perch works with sample records" link to `#/samples/student`. Keep the S route only for the guest's sample persona, where every record is already invented. Then the Help line becomes true. If this cannot land by the gate, put the change to Dakshitha and correct the Help line now.

### M5. The walk did not measure the brief screens or dark mode

- **Screen:** the researcher brief, the student brief and both Compare screens, at both widths.
- **Where:** `build/s43_walk/report.json` holds 28 states, and none is a `brief-*` state. Its checks lack `guest_researcher_brief`, `guest_sample_persona_brief` and the two `guest_keep_compare_*` checks. `scripts/ux_walk.py` never calls `emulate_media` with a dark colour scheme.
- **What is wrong:** the report's "0 axe violations" and "0 targets under 44 px" cover 14 screens in light mode only. Checklist items 1, 2 and 9 are unverified for the brief screens. The builder's own note of 20 to 40 px targets there is not checked. Phase 7 is done only when the walk is clean with axe on laptop and phone.
- **Fix:** rerun the walk with the briefs flow included, and add a dark pass for every flow. Known candidates under 44 px on brief screens: `.export-pop .check` at 40 px in `web/styles.css` line 1010; the Routes `.filter-chip` at 36 px on a fine pointer, line 1284; the Scout owl button `owl-sm` at 40 px, line 454; `.cite` at 32 px on a fine pointer, line 1213. The probe skips checkboxes, so the export menu's 40 px rows never show up. Either fix each one or list it with a reason, as the checklist asks.

### M6. The consent text promises a withdrawal the app does not offer

- **Screen:** welcome, step 2, and the account page.
- **Where:** `perch/auth/consent.py` says "You can withdraw this consent at any time." `POST /me/consent/withdraw` exists in `perch/auth/routes.py`. No screen calls it, and `web/account.js` shows the consent only as a fact.
- **What is wrong:** a user agrees to a text that names a control they cannot reach. Rule 10 forbids stating a capability that the product does not offer. This is consent text, so the gap matters more than in other copy.
- **Fix:** add "Withdraw consent" to the account page's Consent row, with a confirm that says it stops the model jobs and does not delete data. The router in `web/app.js` line 113 redirects any user with `consent.required` to the welcome screen, so after a withdrawal the account page and the public lists must stay reachable. Otherwise the user is trapped on the welcome screen.

### M7. The Retry button on a failed list load throws

- **Screen:** Temple awards and Research funding, the error state.
- **Where:** `web/browse.js` lines 242 to 247. When `GET /filters` fails, `filters` stays null and the error state's Retry calls `load()`. `params()` at line 99 then reads `filters.total`, which throws a TypeError on the student side.
- **What is wrong:** the one recovery a student is offered on a slow or failed server does nothing. The researcher side gets results back but no filter bar, because `drawBar` is never called.
- **Fix:** make Retry rerun the whole start: fetch `/filters`, then `drawBar()`, then `load()`. Add a walk plant that fails `/filters` once and checks that Retry brings the list back.

---

## Should-fix

### S1. Two names for one group of awards

- **Screen:** awards and funding lists, the tag row.
- **Where:** `web/browse.js` line 204 labels the chip "All Temple". The group heading from `perch/browse/routes.py` `OPEN_LABEL`, and the card tag at `web/browse.js` line 60, both say "Open across Temple".
- **What is wrong:** "All" and "All Temple" sit side by side, and "All Temple" reads as "everything at Temple". It actually means the awards open to every school plus those with no stated scope.
- **Fix:** rename the chip "Open across Temple". This matches the group heading and the card tag, and Help line 165.

### S2. The phone header wraps onto two rows

- **Screen:** every signed-out and guest screen at 360 px, such as `w360-landing-guest.png`, where "Guest" and "Sign in" drop below the wordmark.
- **Where:** `web/styles.css` lines 1206 to 1211, the S24 phone header. Under 480 px `.bar-in` is a grid with three columns, `.bar-tools` is `display: contents`, and only `#help` and `#theme` are placed on row 1. The new `#acct-slot` has no grid place, so it falls to row 2 under the wordmark. The S43 `nowrap` rules at lines 1437 and 1438 have no effect on a grid.
- **What is wrong:** the sticky header is about 108 px tall on a 780 px phone. It hides more of each screen and more of whatever has focus.
- **Fix:** give the grid four columns, `1fr auto auto auto`, and place `#acct-slot` in column 2 on row 1, with Help and the theme in columns 3 and 4. Delete the dead `nowrap` rules. Check the guest header at 360 px: wordmark, Guest chip, Sign in, Help and the theme icon on one row. Shorten "Guest" to an icon with a label if the row still overflows. Add a walk check that the header's height is under 64 px at 360 px, and prove it fails first on today's build.

### S3. Focused controls can hide under the sticky header

- **Screen:** all screens, most on phones.
- **Where:** `web/styles.css` has no `scroll-padding-top`. `.bar` at line 102 is `position: sticky`, and the brief's `.tabs-wrap` at line 208 is sticky as well.
- **What is wrong:** WCAG 2.2 criterion 2.4.11 asks that a focused control not be fully hidden. Shift+Tab upward can put a control under the header.
- **Fix:** set `html { scroll-padding-top: calc(var(--bar-h, 56px) + 8px); }`, and add the tab bar's height on brief screens. Add a walk check that tabs back through a long list and asserts each focused element's top is below the header's bottom.

### S4. Past deadlines look like open ones

- **Screen:** Research funding with Temple only on, such as "CIBER Research Award, Closes 5 Dec 2022" in `w360-funding-temple.png`. The same applies to scholarship deadlines.
- **Where:** `web/browse.js` `deadlineText`, lines 48 to 55. The browse route accepts `closes_after`, but `params()` never sends it.
- **What is wrong:** the plan's Risks section says some Temple pages list stale dates. A student will read "5 Dec 2022" as the next deadline.
- **Fix:** keep the copied date and add a code-written label "This date has passed" when the date is before today. Rule 3 allows a label derived by code. Optionally add a "Hide past dates" control that sends `closes_after`.

### S5. The same school shows twice on a funding card

- **Screen:** Research funding, Temple only, such as "Fox School of Business" twice on the CIBER card and "Liberal Arts" twice on Co-Sponsorship.
- **Where:** `web/browse.js` lines 75 and 76. One tag comes from `schools` and a second from `agencyShort(r.agency)`, which holds the same school name on a Temple page record.
- **What is wrong:** it looks like a bug, and it pushes the level and the title down on a phone.
- **Fix:** skip the agency tag when its text equals one of the school tags.

### S6. The funding list is ordered by record id

- **Screen:** Research funding. The first card is "2022 Alumni Engagement Innovation Fund-Italy" with the number "04".
- **Where:** `perch/store/postgres.py` line 144, `ORDER BY id`. Design section 9 says the default order is by name.
- **What is wrong:** awards look name-sorted only because their ids are built from their names. For 1,523 funding records, id order means nothing to a researcher.
- **Fix:** order by the record's name or title, case-folded, with the id as a tie-break. Keep the cursor stable on that key.

### S7. No way from the awards list to "Check my fit"

- **Screen:** Temple awards, at both widths.
- **Where:** `web/browse.js` lines 234 to 239. The only link onward is to the sample records.
- **What is wrong:** the student's main task is to find awards that fit them. After reading the list they must go Back to the landing to find the fit flow.
- **Fix:** add a quiet call to action above the first group or at the foot: "Check which of these fit your CV", linking to `#/student`. A guest sees "Try a sample student" instead.

### S8. The sample brief says "your CV"

- **Screen:** the guest's sample student brief, in `w1280-brief-student.png`.
- **Where:** the brief's sub-line "Fellowships and sample scholarships, checked against your CV by rule" in `web/app.js`, and the hint at `web/student.js` line 250.
- **What is wrong:** the banner right below says "Built from an invented SYNTHETIC student. Nothing here is about you." The two lines contradict each other.
- **Fix:** when the brief is the sample persona, say "checked against the sample student's CV by rule". The same applies to "Still needed" and "your achievement A" wording on its cards.

### S9. Help contradicts the guest hand-off

- **Screen:** Help, Your privacy, and the guest student Compare in `w360-brief-student-compare.png`.
- **Where:** `web/help.js` line 274 says "Hand-offs and Scout need an account." The guest's student Compare drafts a note with "Copy the draft" and "Open in my mail app".
- **What is wrong:** one of the two is false under rule 10.
- **Fix:** say "Researcher hand-off drafts and Scout need an account. A student's note is written by code and works for guests too." Or remove the note for guests. Dakshitha decides which.

### S10. Help leaves out the Temple award pages as a source

- **Screen:** Help, How Perch works.
- **Where:** `web/help.js` line 204 lists "OpenAlex, NIH RePORTER, NSF, Grants.gov and the Temple fellowship list."
- **What is wrong:** the Temple awards list, the main student screen, comes from Temple's public school and college pages. Help does not name that source.
- **Fix:** add "Temple's public scholarship and award pages". Match the words to `SOURCE_WORDS.temple_pages` in `web/browse.js` line 16.

### S11. The consent text is clipped on a phone

- **Screen:** welcome at 360 px, in `build/s43_walk_signin/w360-welcome.png`.
- **Where:** `.consent-text { max-height: 280px; overflow: auto }` in `web/styles.css` line 1418.
- **What is wrong:** the text stops mid-sentence and no scroll bar shows. "I agree" can be ticked without the withdrawal and 35-day lines ever being seen.
- **Fix:** drop the max-height on the welcome screen. The text is eight sentences long. Split it into one paragraph per sentence, or a list, so it reads in steps.

### S12. A signed-in user without consent cannot browse public lists

- **Screen:** any route for a user with `needs_welcome` or `consent.required`.
- **Where:** `web/app.js` lines 113 to 117 redirect every route except Help to `#/welcome`.
- **What is wrong:** the awards and funding lists need no session at all, but a new account cannot reach them until it agrees to send a CV to a provider. The welcome screen also has no "Not now" or "Sign out" button, so a user who does not want to agree has only the account menu.
- **Fix:** let `#/awards`, `#/funding`, `#/samples` and Help through without the welcome. Gate only the screens that read or store user text. Add a "Sign out" link at the foot of the welcome screen.

### S13. The delete dialog under-describes, and fails badly after the key is gone

- **Screen:** account, the delete dialog, in `w360-delete-dialog.png`.
- **Where:** `web/account.js` line 147 for the text. `web/api.js` `ERROR_WORDS` has no `delete_incomplete`, which `perch/user/routes.py` line 129 returns.
- **What is wrong:** the text names CV, entries, briefs and account. `perch_delete_user_rows` clears every table, including documents, kept leads and drafts, and the session ends. The dialog does not say you will be signed out. If a shred hook fails, the user's key is already destroyed, yet the dialog says "The server answered 500." and offers Delete again with no explanation.
- **Fix:** use the design's list: "Your CV and entries, your briefs, your saved awards and leads, your hand-off drafts and cover points, and your account." Add "You will be signed out." Map `delete_incomplete` to "Your key is destroyed, so your data can no longer be read. Clean-up did not finish. Press Delete again to finish it."

### S14. Policy numbers in copy have no source in the code

- **Screen:** welcome, the account page, the delete dialog, the guest banner and Help.
- **Where:** "35 days" appears only in `perch/auth/consent.py` and `web/account.js`. No backup config sets it yet, because backups are Phase 10. "It ends in an hour" is a fixed string in `perch/auth/routes.py`, not built from the session's `expires_at`.
- **What is wrong:** a number in user-facing copy should come from the code that enforces it, in the spirit of rules 3 and 10. The 35-day claim cannot be checked today.
- **Fix:** keep the contract text, but record "35 days" as UNVERIFIED in the Phase 10 runbook task, so the backup retention is set to match before release. Build the guest notice's duration from the same constant as the session TTL.

### S15. Student start loses unsaved text and moves focus to the top

- **Screen:** Check my fit, signed in, in `build/s43_walk_signin/w360-student-start.png`.
- **Where:** `web/student.js` lines 92 and 100. Each save calls `draw()`, which rebuilds the whole screen with a new empty `field`. Line 165 then focuses the page title.
- **What is wrong:** a student who pastes a CV, then types interests and presses "Save interests" loses the pasted CV. After every save, keyboard focus jumps to the heading. "Save my CV" with an empty box only announces "Paste your CV text first." to screen readers, so sighted users see nothing happen.
- **Fix:** keep the textareas' values in module state across redraws, or update only the changed section. Put focus back on the button that was pressed, or on the new "is stored" line. Show the empty-box message under the field with `aria-describedby`.

### S16. Account menu may not open links on iPhone

- **Screen:** the account chip menu on a phone.
- **Where:** `web/app.js` line 304. The menu closes on `focusout` when `relatedTarget` is outside the wrapper.
- **What is wrong:** iOS Safari does not focus a link or button on tap, so `relatedTarget` is null. The menu may close before the tap lands, and My Perch, Account and data, and Sign out become unreachable. Playwright Chromium cannot show this. This needs a check on a real device.
- **Fix:** close the menu on a `pointerdown` outside the wrapper and on Escape, not on `focusout`. Add `aria-haspopup="true"` while there.

### S17. Error copy is written for developers

- **Screen:** any screen when the server does not answer, or answers with an unmapped code.
- **Where:** `web/api.js` line 56, "Perch's server did not answer. Check that `perch serve` is running." Also the fallback "The server answered 500."
- **What is wrong:** a student does not run `perch serve`. The message tells them nothing they can act on.
- **Fix:** "Perch could not be reached. Check your connection and try again." For unknown codes: "Something went wrong on Perch's side. Try again in a minute."

---

## Nice-to-have

### N1. Route changes keep the old scroll position

- **Where:** `web/app.js`, the `awards`, `funding`, `samples` and `student` branches of `route()`, have no `window.scrollTo(0, 0)`. The list then focuses its title with `preventScroll`.
- **What it causes:** a list can open half-way down the page. The header drawn mid-page in `w360-awards-empty.png` and `w360-student-start.png` is a capture artifact of this, not a layout bug.
- **Fix:** scroll to the top on each of these routes, as the account routes do.

### N2. The list title steals focus after loading

- **Where:** `web/browse.js` lines 252 and 253 focus the title after the first `load()`.
- **What it causes:** a user who started typing in the search box while the list loaded loses their place. The focus ring around the whole title also looks like a selected box.
- **Fix:** focus the title only if focus is still on `body` or `main`. Hide the outline on `h1[tabindex="-1"]:focus` while keeping it for keyboard focus on controls.

### N3. "Up to" is added by code where the page may not say it

- **Where:** `web/browse.js` line 44 writes "Up to $X" for any scholarship with a maximum and no minimum. `web/student.js` line 376 does so only for `temple_sdfa`.
- **What it causes:** the same record can read "Up to $5,000" on the list and "$5,000" in the brief. "Up to" is a claim about the award.
- **Fix:** share one amount helper. Write "Up to" only when the record's quote for the amount says so.

### N4. The guest banner uses a question-mark icon

- **Where:** `web/app.js` line 228 uses `icon("help")`.
- **Fix:** use an info icon, as design 1.3 says. A question mark suggests a link to Help.

### N5. The guest banner does not show when the session ends

- **Where:** `web/app.js` line 229 shows the fixed notice. `expires_at` is in the session answer.
- **Fix:** add "Ends at 3:40 pm", rendered from `expires_at`, so a guest knows how long a brief will last.

### N6. Brief rows on My Perch all read "Student brief"

- **Where:** `web/account.js` line 224, and the raw status word "done" on line 225.
- **Fix:** name the CV the brief was built from, or the top option's title. Map the status to plain words: "Ready", "Failed", "Still building".

### N7. The account page has no way to add a CV

- **Where:** `web/account.js` line 125, "You have no stored documents."
- **Fix:** add a link "Add your CV" to `#/student`.

### N8. The walk never shows a card with an explanation

- **Where:** `scripts/walk_server.py` uses the fake model, so every brief card in the screenshots reads "The explanation was withheld because it failed the citation checks twice."
- **What it causes:** the reviewer cannot judge the real card, and the withheld state looks alarming when it fills a whole page.
- **Fix:** make the fake model return one valid explanation for the walk, so both states are captured. Consider softer copy for the withheld state, such as "No explanation is shown for this one. Its fields are copied from the record."

### N9. The Level menu on the funding list mostly empties it

- **Where:** `web/browse.js` lines 226 to 230. With Temple only off, choosing a level drops every federal record, because they state no level.
- **Fix:** show the Level menu only when Temple only is on, as the tag row already does, or add a hint "Most federal listings state no level."

---

## What works

- **Samples stay apart in the lists:** `/awards` and `/opportunities` never return a sample, every sample card carries the dashed badge, and the sample screen opens with its note. The walk plants prove both checks fail first.
- **Counts come from the server:** chip counts match `GET /filters`, and group totals come from the route.
- **"Not stated" reads honestly:** missing amounts and deadlines say "Not stated" without looking broken.
- **The delete guard is sound:** a real `<dialog>`, focus starts in the field, Escape returns focus to the opener, and Delete stays disabled until the field holds exactly `delete`.
- **The tag row on a phone:** it scrolls inside itself with a fade, chips are 44 px, and the page has no sideways scroll on the measured screens.

# S49 product and flow review (fresh context, 2026-11-04)

Read-only review of the v1 web app on `rebuild/v1`. Inputs: the S48 walk screenshots in `build/s48_walk_light/` and `build/s48_walk_handoff/`, the front-end code in `web/`, and the routes in `perch/api.py`, `perch/browse/routes.py` and `perch/user/routes.py`. Items already queued in `S48_UI_NOTES.md` and `S48_UI_DESIGN.md` are not repeated.

Four readers were kept in mind:

- **Undergraduate:** wants money for next year, fast, with deadlines they can act on.
- **Graduate student:** wants fellowships and graduate awards, and is unsure which side of Perch they belong to.
- **Faculty researcher:** wants open grants that fit their papers, and a clean path to the research office.
- **Demo Day judge:** has three minutes and needs to see one finished, cited result.

One caution first. The walk ran the fake model, as `scripts/walk_server.py:1` says. So the model text in the screenshots is not real. The repeated "explanation was withheld" banners, the generic grant sentence and the "first topic area" chips are fake-model output. They are not filed as product bugs here.

The error and account states were checked and work: the list error with Retry, the sign-in-down notice, the delete dialog that asks the user to type "delete", and the "Your data was deleted" notice. They are in `w1280-researcher-list-error.png`, `w1280-signin-unavailable.png`, `w1280-delete-dialog.png` and `w1280-after-delete.png`. The only issues found there are R5 and the "saved awards" text in P1.

## Must-fix (flow breaks or confuses)

- **P1 The saved list is promised but never built:** No route writes a `saved_item`; only `perch/scout/job.py:103` reads one. Yet Scout says it can "Read your saved list" in `web/scout.js:21` and `web/scout.js:30`. The guest My Perch line promises "saved awards" in `web/account.js:241`. The delete text lists "saved awards" in `web/account.js:158` and `web/account.js:225`. Build Keep on browse cards, as in F1, or remove every claim, as in R1. Effort: medium to build, small to remove.
- **P2 Research funding opens on closed, stale calls:** The list is sorted by title. So the first cards a researcher sees are a 2020/2021 call and a call that closed in February 2022, in `w1280-funding.png`. Temple-only shows calls that closed in 2021, 2022 and 2024, in `w1280-funding-temple.png`. Hide records whose close date has passed by default, and add a "Show closed" switch. Code can do this from `close_date` alone. Effort: medium.
- **P3 Browse lists have no sort:** `web/browse.js` has no sort control, and the order is by title. Add "Closing soonest" and "Largest amount", both read from record fields. Records with no date or amount go last. Effort: medium.
- **P4 The student hand-off hides the office name from guests:** A guest sees "The Temple office for this route" in the radio and in every table row, in `w1280-brief-student-compare.png`. The fallback is in `web/student.js:435`. The office names are public constants in `perch/offices.py`, such as Scholar Development and Fellowships Advising. Send them with the brief so guests see the real name. Effort: small.
- **P5 Compare shows the hand-off before the comparison:** Under the heading "Compare 2 kept leads", the hand-off form comes first and the table comes after it, in `w1280-brief-researcher-compare.png`. A person compares first, then decides where to send. Put the table first and the hand-off below it. Effort: small.
- **P6 A "May be eligible" card with no gaps says nothing:** The text above the list says "may be eligible" is the best verdict Perch can give, in `w1280-brief-student.png`. When a card has rule gaps, the "Still needed" line in `web/student.js:345` explains it. When it has none, the chip stands alone and tells the student nothing. Add one line saying what the rules checked, such as "Level checked; the listing states no deadline". Every word comes from the rule results in `perch/student.py`. Confirm on the live capture in S15, since the walk brief is seeded. Effort: small.
- **P7 The hand-off wait has no progress:** The hint says the draft can take up to two minutes, in `web/handoff.js:93`. During that time the screen shows a greyed button and one status line, in `w1280-handoff-busy.png`. Show the code-written parts of the draft at once: the subject, the lead list and the ERA line. Let the model's opening paragraph fill in when it arrives. Effort: medium.
- **P8 A returning user lands on the guest-style landing:** A signed-in user sees the same hero and buttons as a new visitor, in `w1280-after-welcome.png`. My Perch is reachable only through the name menu, in `web/app.js:276`. Put "My Perch" in the header, and add "Open your last brief" to the landing. Effort: small.

## Should-fix

- **S1 Browse cards spend two rows on "Not stated":** Most of the 360 Temple awards show "Amount: Not stated" and "Deadline: Not stated", in `w1280-awards.png`. The rows are drawn even when empty, in `web/browse.js:101` to `web/browse.js:104`. When both are empty, show one quiet line: "Amount and deadline are not on the page." Effort: small.
- **S2 Some award titles are lower case:** "academic scholarships" and "additional scholarships for sophomores, juniors and seniors" look unfinished, in `w1280-awards.png`. Capitalise the first letter when showing the title. Leave the stored record as it is. Effort: small.
- **S3 The brief tabs have different names on each side:** The researcher brief says "Profile". The student brief says "What Perch read" on desktop and "Read" on a phone. Use one name, "What Perch read", on both sides. Effort: small.
- **S4 The match number is not explained:** Cards show "Match good 69" with no scale, in `w1280-brief-student.png`. Add a short hint saying what the number counts and its range. Check the wording against `perch/score.py`. Effort: small.
- **S5 A ten-year-old date is the biggest thing on the profile:** The award horizon shows "30 Jun 2016, already passed" in large type, in `w1280-brief-researcher-profile.png`. When the date has passed, show it at normal size under a plain line: "No running federal award found." Effort: small.
- **S6 Keep and Dismiss push the title down on a phone:** At 360 px the buttons sit above the title, so each card starts with buttons, in `w360-brief-student.png`. Move Keep and Dismiss to the foot of the card on narrow screens. Effort: small.
- **S7 Compare rows start with the opportunity number:** Rows read "26-519: MPS Chemistry Research Programs", in `w1280-brief-researcher-compare.png`. Show the title first and the number on a second, quieter line. Effort: small.
- **S8 The progress card stays large after the brief is ready:** "Brief ready" with a full bar takes about 75 px at the top of every tab, in `w1280-brief-researcher.png`. Once done, shrink it to one line: "Built in 7 s · Steps". Effort: small.
- **S9 Guests see the same sign-in button on every card:** "Sign in to get cover-letter points" repeats on all ten cards, in `w1280-brief-student.png`. Show it once above the list. Effort: small.
- **S10 Back from a brief ignores where the user came from:** A student brief's Back always goes to the start form, in `web/app.js:755`. A user who opened it from My Perch expects to go back to My Perch. Use the last screen the user was on. Effort: small.
- **S11 The school chips are cut off with no cue:** The row ends in "Boyer Colle" at the right edge, in `w1280-awards.png`. Users will not know more schools exist. Wrap the chips, or use a "School" menu like the level menu. Effort: small.
- **S12 "Sides" is project jargon:** The account page says "Your sides", in `w1280-account.png`. Say "You use Perch as" instead. Effort: small.
- **S13 Graduate students do not know which box to tick:** The welcome asks "I am a student" or "I am a researcher", in `w1280-welcome.png`. Add one hint: "Graduate students: pick Student for fellowships. Pick Researcher too if you have published papers." Effort: small.
- **S14 The sample records page is 500 cards long:** `w1280-samples.png` lists every sample with no filter. Show about 10 samples with a note that more exist, or give the page the same filters as the awards list. Effort: small.
- **S15 Review rounds need one live brief capture:** The walk ran the fake model, so no reviewer has seen real fit text, real cover points or a real hand-off. Capture one researcher brief and one student brief from the live deploy before S51 closes. Effort: small.

## Features to add

- **F1 Keep an award straight from the browse list:** Add Keep to every browse card for signed-in users. Store it as a `saved_item`, which the data model already defines in `perch/user/models.py:17`. Show kept awards on My Perch. This closes P1 and links browsing to the brief. Effort: medium.
- **F2 A calendar file of deadlines:** Offer an .ics download of kept leads, one event per stated close date or deadline. Every date is copied from the record, and nothing is sent. Records with no date are left out and listed by name. Put it in the Export menu and on My Perch. Effort: medium.
- **F3 Upcoming deadlines on My Perch:** List kept leads from all briefs, sorted by closing date, with the Closed tag when a date has passed. This is the reminder Perch can give without sending anything. Effort: medium.
- **F4 "Has a deadline" and "Has an amount" filters:** Most Temple awards state neither. A student who wants actionable money should be able to show only records that state one. Code reads the record fields. Effort: small.
- **F5 A graduate sample persona:** Only `persona-ug` exists, in `perch/user/briefs.py:70`. A graduate guest sees an undergraduate's results. Add a SYNTHETIC, canary-tagged `persona-grad` and let the guest pick one, as rule 12 allows. Effort: medium.
- **F6 Delete one brief:** `perch/user/routes.py` has no route to delete a single brief. Today the only way to remove one is to delete the whole account. Add a Delete button on each My Perch row. Effort: small.
- **F7 A finished example for a first look:** A replay page can already be built by `scripts/export_replay.py`. The app reads it from `PERCH_REPLAY` in `web/app.js:2296`. Publish one as a separate static page and link "See a finished example brief" from the landing. A judge or a new visitor then sees a cited result in one click. Effort: medium.
- **F8 Check my fit from a browse card:** A signed-in student with a stored CV should be able to run the rules on one award from the browse list. The rule result appears on the card, with no model call. Effort: medium.
- **F9 Suggested questions in Scout:** Scout opens with a list of its own tools in developer words, such as "Read one record in full", in `w1280-scout-clean.png`. Replace the list with three or four example questions as buttons, such as "Which kept awards close first?". Keep the tool list under "What I can do". Effort: small.
- **F10 Leave out a paper that is not mine:** OpenAlex sometimes credits a researcher with someone else's papers. On the profile tab, let the user untick a paper. Untick a paper and the brief is built again without it. This fits with the queued "change details and run again". Effort: medium.

## Features or text to remove

- **R1 Scout's "saved list" claim:** Remove "Read your saved list" from `web/scout.js:21`, `web/scout.js:30` and `web/scout.js:33` until F1 ships. Do the same for "saved awards" in `web/account.js:241`. Effort: small.
- **R2 "Records as JSON" for students:** A student does not need JSON, in `w1280-brief-student-export.png`. Keep it for researchers, or move it under "More formats". Effort: small.
- **R3 Short opportunity numbers on funding cards:** Lines such as "04" carry no meaning for a reader, in `w1280-funding.png`. Show the number in the evidence panel only. Effort: small.
- **R4 The "Unless a card says otherwise" box:** Once S1 hides empty rows, the line "The listing states no deadline or amount" is redundant, in `w1280-brief-student.png`. Keep only the line about reading the award's own page. Effort: small.
- **R5 Two buttons that do the same thing when sign-in is down:** "Try a sample student" and "Try it as a guest" both start a guest session, in `w1280-signin-unavailable.png`. Keep the button and drop the link line. Effort: small.
- **R6 The consent version line on the welcome screen:** "Consent text, version 1." means nothing to a new user, in `w1280-welcome.png`. Keep it on the account page, where it already shows. Effort: small.

## Flow redesigns proposed

- **D1 My Perch as the home screen for signed-in users:** After sign-in, open My Perch, not the hero landing. It would hold upcoming deadlines from F3, kept items from F1, recent briefs and the CV status. The hero landing stays for guests and signed-out visitors. Effort: medium.
- **D2 Browse with fit, for students:** Today a student chooses between "Browse Temple awards" and "Check my fit", and these are two separate screens. Merge them. The awards list is the main screen. A signed-in student with a CV sees the rule result on each card, plus a "Sort by fit" option. Guests see the plain list with a "Try the sample student" bar. This removes a decision on the landing. Effort: large.
- **D3 One "Next steps" tab:** Rename Compare to "Next steps". In order, it would show the comparison table, the calendar file from F2, then the hand-off draft. That is the order a person acts in. Effort: medium.
- **D4 Scout beside the cards, not on its own tab:** Today Scout lives on a separate tab, away from the cards it talks about. Add "Ask about this" on each card. It would open Scout in a side panel with that record already named. The tab can stay for open questions. Effort: large.
- **D5 Own CV for guests, a fork for Dakshitha:** A guest undergraduate can only try the sample student, in `web/student.js:77`. Letting a guest paste a CV for the hour, never stored, would serve the main student job. The fit rules in `perch/student.py` are code, not a model. So a guest CV could get rule verdicts with no call to the provider. Only cover points and Scout would need the consent that rule 1 asks for. The open question is where the text lives during the hour. Recommendation: keep the sample-only guest until after Demo Day, then decide. Effort: medium.

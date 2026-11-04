# S46 design: a cover-letter points button on each lead

Design pass, 2026-11-04. The `/briefs/{id}/cover-points` route works, but no screen calls it (S45 final re-check).

- **Where it goes.** A "Cover-letter points" button in each lead card's action row, in app.js and student.js. It is hidden on dismissed cards. The result renders under the card's explanation. Compare, the evidence panel and Scout get no button.
- **Guests.** A guest sees "Sign in to get cover-letter points", using the hand-off's sign-in link.
- **Button and hint.** The label is "Cover-letter points" with a pen icon, and "Points again" once a result exists. The hint under it reads "A model writes these from your CV and papers. You put them in your own words."
- **While it runs.** The button is disabled with aria-busy. A role=status line reads "A model is reading the record and your CV. This takes up to two minutes…". The page polls every 2 s, for about 150 s at most.
- **The result.** It reuses scout.js `pointsBlock`, which is exported for this. That gives the Model text tag, the Sample data badge, the withheld notice, the citation chips and Copy the points. The block opens with focus on its summary, and the page announces "The points are ready below." A single GET on render brings back points that are already stored.
- **Errors**, in role=alert:
  - 429 quota: the server's message.
  - 429 rate: "Too many requests. Try again in N seconds".
  - 409: "Cover points start once the brief has finished."
  - 403: the sign-in link.
  - A failed job or a timeout: "The points could not be made. Try again."
  - The button is re-enabled after any of these.
- **Samples.** They are allowed and marked as samples by the existing badge and hint. Nothing counts sample points (rule 11).
- **Help.** One line goes back: "On a lead card, Cover-letter points asks a model to pair what the record asks for with what your CV, entries and papers show, each line cited. It needs an account, it is model text to put in your own words, and it is never sent or added to an export."
- **Accessibility.** The button is a 44 px `<button type=button>` with `data-key` `cover-${id}`. The busy state lives outside the card render. Focus goes to the summary after a result and back to the button after an error.
- **Fork for Dakshitha.** Every lead card (recommended), or only kept cards.

## Review after the build (fresh-context Opus, 2026-11-04)

- **Must-fix:** "Points again" returns the stored job, because the submit key is user, brief and record, and it still spends quota. The label is untrue (rule 10).
- **Should-fix:**
  - A consent 403 shows a sign-in link.
  - A timeout says "could not be made" while the job may still be running.
  - Focus falls to the body on click.
  - Polling continues after the user leaves the brief.
  - The student hint says "papers".
  - No check covers a sample record's badge.
  - Every card makes a GET on render (17 a brief), with no rate limit.
- **Nice-to-have:**
  - The hint repeats under the result.
  - The hyphen in the label renders with wide spacing.
  - The screenshots need re-capturing.
  - There is no researcher card capture.
- **Industry leads:** no button. The skill needs an opportunity's call text, and a company lead goes to the hand-off draft.

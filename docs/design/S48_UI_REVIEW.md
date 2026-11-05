# S48 UI/UX review (fresh-context Opus, 2026-11-04)

34 screenshots from build/s48_walk_{light,dark} at both widths, plus Dakshitha's two note images, each traced to the code. File paths are under web/.

## Must-fix
- **M1 Empty agency tag:** the tag is drawn even when it has no text (app.js:1719). Draw it only when the text is non-empty, with `.tag:empty{display:none}` as a backstop.
- **M2 Citation chips stretch lines:** inline `.cite` has min-height 44px (styles.css:1455, 1224), which makes uneven line gaps in card text, Scout and cover points. Make it inline with `line-height: inherit`; WCAG 2.5.8 exempts inline targets.
- **M3 Stored-documents card stretches:** `.box-grid` stretches it (styles.css:991). Set `align-items: start`.
- **M4 Wrong text:** the researcher's documents card points to "the Check my fit page" (app.js:642). Replace it with an upload control (owner note 4).
- **M5 Compare order:** the hand-off form sits between "Compare 2 kept leads" and the table (compare.js:111-122). Put the table first.
- **M6 Cover points heading on phone:** the chevron sits on its own line (styles.css:860). Set `flex-wrap: nowrap` and `flex: 1` on the text.

## Should-fix (lead card)
- **Card order:** put the title first, then one subtitle line (agency and program), with the head as a grid. Move the record number to the evidence panel.
- **Missing values:** show one two-fact list, Closes and Amount, with a muted "Not stated", on every card. Use one word, not both "Closes" and "Deadline".
- **Match pill:** put it on the right on student cards too.
- **Phone header:** keep tags and match on one row and the actions on a second row.
- **"Why it fits":** stop it wrapping.
- **Cover button:** close the gap above it.
- **Evidence mark:** set it on the baseline at 13px.

## Should-fix (other)
- **Chips and labels:**
  - Split the funder and activity-code chips.
  - Give cover-point citations a short label, and drop the points list indent.
  - Make the match count honest per section.
  - Give the filter chips a visible overflow cue, or wrap them.
- **List order:** sort funding open-first by closing date.
- **Controls:**
  - Give search and select the same height.
  - Cut the student interests text at a word boundary with "…".
  - Style the disabled "Compare and hand off" as an outline, with the hint "Keep a lead first".
- **Page width:** use one main content width on every page.

## Nice-to-have
- **Heading focus:** move the ring on headings after navigation further out.
- **Landing buttons:** make them equal widths.
- **Account page:** align the consent row and drop the last document row's border.
- **Phone hand-off box:** cap its height.
- **Type scale:** reduce it to 12/14/16/19/24.
- **Dark-mode borders:** give buttons a 3:1 border.

No rule 10 or rule 11 problems; sample badges are on every synthetic surface.

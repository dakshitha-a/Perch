# UX review, S25 (the S24 redesign as it will ship)

**How it was done:** an independent reviewer (a fresh agent with no part in the build) read about 30 screenshots from the S24 walk on the demo and the dev server, in both themes and both sizes, for the researcher path, three SYNTHETIC students and persona-1. It also read the build spec, the canvas sources, the accessibility checklist and the walk report. Machine checks first: the walk had 0 axe violations, 0 sideways scroll and 0 failed steps. Perch-dev then fixed the findings below and reran the walk.

## Must-fix (all fixed)

| # | Finding | Fix |
|---|---|---|
| 1 | A bare record id ("W2060398900.") ended the profile summary. | A cited id that is not a paper in the brief is dropped, never shown bare. |
| 2 | The sample tab said "10 options you may apply for" under "Do not apply to them". | The sample tab says "10 sample options (invented, for demonstration)". |
| 3 | A student could draft a note to a real office about invented scholarships. | Such a note opens with "SAMPLE DATA, A DEMONSTRATION: DO NOT SEND" and has no Open in mail button. Scout's `draft_note` writes the same first line. |
| 4 | "partial 45" next to "strong 85" read like a score, and "weak 0" sat beside "Why it fits". | The number reads "45/100" with "not the odds of funding" for screen readers; a weak lead's fold says "How it relates". |

## Should-fix

| # | Finding | Status |
|---|---|---|
| 5 | Compare said "Fit rank 1", which is Perch's order, not the fit estimate. | Fixed: "Perch's order: 1". |
| 6 | "What steers the search" showed only "Your achievement A (private)" and one extra row. | Fixed: one row per achievement, with the student's own words under it. |
| 7 | Tabs were cut off on a phone ("Ask Scou"). | Fixed: short labels under 480 px (Routes, Profile, Compare, Scout; Options, Read); the full name stays for screen readers. |
| 8 | Compare tables were cut off on a phone. | Fixed: under 600 px each kept item is a card with labelled rows. |
| 9 | "Nothing about you is stored either way" overstated Cloud; "Send to Anthropic" sounded immediate. | Fixed: "Perch stores nothing about you either way. With Cloud on, the provider's API terms apply…"; the button says "Turn Cloud on". |
| 10 | Hard words in the context panel. | Fixed: "Leave out awards smaller than (US dollars)", "Early-career: …", "The sample has no CV, because this is a real researcher." |
| 11 | The documents-only screen kept the old heading and had no Back link. | Partly fixed: Back link and page heading. A full restyle is left; it is the path for researchers with no public papers and is reached from "More options". |
| 12 | The sticky rail slid under the sticky tab bar. | Fixed: the rail sits below the tab bar. |
| 13 | Header and page column did not line up. | Fixed: the header uses the page column's width on every screen. |
| 14 | Forecast fellowships looked open. | Fixed: "Forecast: not open yet" tag. Listing pages are not tagged; no field says which records are pages. |

## Could-fix

| # | Finding | Status |
|---|---|---|
| 15 | The progress card stays large after the build. | Partly: the warm note is shorter ("Built when the server started"). The card keeps its size, so the steps stay one press away. |
| 16 | Paper chips break up sentences. | Left: the chips are the citations; numbered markers are a larger change. |
| 17 | Thread labels are raw keywords; shares look odd against paper counts. | Left: the Profile hint says labels are the words that set each group apart, and Help explains recency weighting. |
| 18 | Hand-off wording: "To: leave for you to fill in", the model id, ISO dates. | Typo fixed ("To: left blank for you."). The model id stays: it says which model wrote the text. |
| 19 | Segmented controls wrapped on a phone. | Fixed with short labels ("Fellowships", "Samples", "Ask first", "Run"). |
| 20 | Evidence used an external-link icon. | Fixed: a panel icon; the arrow is kept for "Open at Grants.gov". |
| 21 | "Your verdict" column; sample rows lacked the badge. | Fixed: "Rule check"; sample rows carry the Sample data badge. |
| 22 | Help is long. | Fixed: a "Jump to" row under the intro. |
| 23 | Small targets in the walk report. | Checked: none under 24 px apart from inline links and a hidden file input; card titles are text links inside headings. |

**Good as built (reviewer):** the landing, the evidence sheet and rail, sample marking on student cards, the Local or Cloud dialog, Scout for both audiences, and the student form's privacy line.

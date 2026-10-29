# S22 redesign of the core screens (option B)

Written before the build. The source is `docs/design/UX_AUDIT.md`; finding numbers (M1, S1, ...) refer to it. The app stays one no-build app with the same API, components and visual style. This doc covers what changes.

## Screens and flows per audience

| Screen | Researcher (PI) | Student (undergraduate, master's, PhD) |
|---|---|---|
| Find | Two equal doors. "I'm a researcher" holds the search form. Help and What changed sit under the doors. | The "I'm a student" door says what happens and starts a private session with one button. |
| Brief header | "New search" goes back to Find. | "Your documents" goes back to the student form; the session stays open. |
| Tabs | Profile, Routes, Compare, Ask Scout | What Perch read, Your options, Compare |
| Routes list | Order explained in one line under the title. Sort labelled "Perch's order". | Lead count says "options you may apply for". |
| Cards | Grant cards unchanged in shape. Industry cards show the newest record per signal; the rest fold under "Show N more". | When a record states neither deadline nor amount, one line says so. "Why it may fit" starts folded, as on grant cards. The action is "Evidence", as on grant cards. |
| Evidence panel | On a laptop wider than 1200 px, the list moves left so the panel sits beside it, not over it. | Same. |
| Compare and hand-off | Only the two research offices are offered. | Unchanged; browser-only drafts to SDFA or SFS. |

## Vocabulary

| Concept | Researcher word | Student word |
|---|---|---|
| The result page | brief | brief |
| The list of funding | Routes | Your options |
| One item | lead, opportunity | option |
| Profile tab | Profile | What Perch read |
| The personal input | CV, documents | CV or résumé |
| Open the record | Evidence | Evidence |

## What each standing rule looks like on screen

- **Provenance (rule 4):** every card keeps its Evidence button, and every id in model text renders as a chip that opens the record, including the profile summary (S3).
- **Numbers copied (rule 3):** dates and amounts come from record fields. A missing field still says "not stated in the record", now on one line when both are missing.
- **Models bounded (rule 5):** the Model text tag stays on every model sentence. The order line says the list is in Perch's order and that fit is a separate model estimate (M4).
- **Sample data (rule 11):** the Sample data badge stays on the tab, every sample card, the evidence panel and exports. The tab is named "Scholarships and awards (sample)", because sample records include fellowships (S9).
- **Nothing sent (rule 7):** hand-offs stay drafts; the footer line stays.
- **Private mode:** the switch, the frame line and the coloured edge are unchanged; the audit found them clear.

## Accessibility changes

- The owl copies on Find and in the progress branch leave the tab order; the header owl stays the one button (M2).
- Scrolling regions take focus and have a name (M3).
- Contrast tokens raised for the Model tag and dark-mode cell notes (M6).
- The evidence panel becomes a `div` with the dialog role (C3).
- Paper chips reach 44 px on touch screens (S11); the steps summary reaches 44 px (C4).
- Document cards use h2 under the page h1 (S12).

## Not in this build

- **Grouping one announcement family (S5)** and **merging company aliases (S7, "Samsung" and "Samsung Electronics")** change what the pipeline returns. They are left for after Demo Day and listed in the README known limits.

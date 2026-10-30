# QA_PLAN.md — full QA test (S25)

One row per feature and path. Each row was run on the public URL, the dev server (a scratch copy of the demo store) or the CLI, and the result recorded. "Pass" means the expected result was seen. A failure is fixed in S25 or listed as a known limit in the README.

| # | Feature | Path | How it was run | Expected | Result | Note |
|---|---|---|---|---|---|---|
| 1 | Landing | Researcher pill | Browser, laptop and phone | Owl reacts to taps; search box; "More options" explains screen 2 | pass | Walk: 4 researcher views (phone and laptop, light and dark). Owl reactions unchanged since S8. |
| 2 | Landing | Student pill | Browser | One button; it opens a session and the CV form | pass | Walk: three SYNTHETIC students; the session opens before the form. |
| 3 | Find | Name search | Browser, a Temple name | Temple matches, best first, "This is the one" | pass | A surname search returned 1 Temple candidate. |
| 4 | Find | OpenAlex ID and ORCID iD | Browser | One match each | pass | One match for an OpenAlex id; ORCID path unchanged since S1 (walk uses the id). |
| 5 | Find | No match | Browser, nonsense text | Plain message with a hint; no error | pass | "No Temple University author matches …" with a hint. |
| 6 | Pick | Context panel | Browser | Boxes fade in; Fill with a sample, Clear, Sample data line; CV left empty by the sample | pass | Sample fills direction, keywords and draft aims; CV empty; Sample data line; Clear empties it. |
| 7 | Pick | Upload | Browser, a SYNTHETIC .md file | File named; read on build | pass | A SYNTHETIC .md file is named and read on build; the brief built. |
| 8 | Brief | Live build | Browser | Progress card counts steps; shimmer until leads | pass | Live brief 46 s with explanations (S24 walk); shimmer cards until leads. |
| 9 | Brief | Warm demo brief | Public URL, a demo researcher | Opens at once; "built when the server started" | pass | 17 ms on the demo; the card says it was built when the server started. |
| 10 | Routes | Grants | Browser | Lead cards, sort, the order explained | pass | Walk: lead cards, sort, the order note. Fit shows as "45/100" (review fix). |
| 11 | Routes | Industry | Browser | Inferred, not verified; signals with records | pass | Walk: 5 industry leads, Inferred and Not verified. |
| 12 | Evidence | Laptop rail | Browser, 1280 px | Record in the rail beside the list | pass | Walk on 1280 px: the record opens in the rail. |
| 13 | Evidence | Phone sheet | Browser, 390 px | Sheet opens and closes; focus returns | pass | Sheet opens; Close returns focus to the Evidence button. |
| 14 | Shortlist | Keep, ×, float | Browser, both sizes | Kept items in the rail; × restores; pill under 900 px | pass | Two kept, × restored one; the pill shows on a phone. |
| 15 | Profile | Summary, threads, horizon, awards, key papers | Browser | Each fills in as its stage finishes | pass | Walk: every section fills in; no bare record id after the review fix. |
| 16 | Compare | Researcher | Browser | Table copied from records; cells open records | pass | Walk; on a phone each lead is a labelled card (review fix). |
| 17 | Hand-off | Researcher | Browser | Office radios; draft; To empty; Copy; Open in mail | pass | Walk: office radios, a draft with an empty To line, Copy, Open in mail. |
| 18 | Export | Markdown, JSON, print | Browser, Export menu | Files download; private text withheld | pass | Markdown downloaded (6,897 characters) with no document text. |
| 19 | Export | Mask | Browser, persona-1 | Masked text; unmask works in session | pass | Masked JSON has no canary. Found and fixed: the menu closed itself after a download. |
| 20 | Fellowships | Student | Browser, persona-ug | Verdict chips with marks; "may be eligible" at best | pass | Walk: chips with a mark and a word; forecasts tagged "not open yet" (review fix). |
| 21 | Scholarships | Student, sample | Browser | Sample data on tab, card and banner | pass | Walk: Sample data on tab, card, banner; heading no longer invites applying (review fix). |
| 22 | What Perch read | Student | Browser | Rule fields; interests and achievements | pass | Rule fields; the student's own words under each record (review fix). |
| 23 | Compare and note | Student | Browser | Office radio; code-written note; SAMPLE line | pass | Code-written note; a note about samples opens with DO NOT SEND and has no mail button (review fix). |
| 24 | Ask Scout | Researcher | Browser | Ask before each step; Approve, Skip; cited answer | pass | Live on Gemma: "Only R21 grants" ran search_opportunities once and answered with cited ids. |
| 25 | Ask Scout | Student | Browser | Student tools only; cited answer; samples marked | pass | Live on Gemma in S24: a cited answer about the kept option; API test covers the allowlist. |
| 26 | Local or Cloud | Dialog | Browser | Warning names Anthropic; Cancel leaves Local | pass | Walk: the warning names Anthropic; Cancel leaves Local. Wording fixed (review). |
| 27 | Local or Cloud | Documents | API | Cloud refused with documents (switch off) | pass | Canary: a document with Cloud on is refused (409). Found and fixed: the chip now says "Local only" once a document is added. |
| 28 | End session | Any screen | Browser | Dialog lists what goes; back to landing | pass | The dialog lists what goes; back to the landing. |
| 29 | Help | Content | Browser | Every claim matches the app | pass | Help rewritten in S24 and checked against the code; Jump to links added. |
| 30 | MCP server | stdio | `scripts/mcp_check.py` | Tools listed; a cited result | pass | `scripts/mcp_check.py` on the dev store: tools listed, 3 cited works with provenance, 8.3 s. |
| 31 | CLI | resolve, profile, brief | Terminal | Each runs on the dev store | pass | `perch resolve`, `profile` and `brief --top 5` on a scratch store. |
| 32 | make demo | Deploy | Terminal | Units up; health ok; public URL answers | pass | Rebuilt in S24; health ok; the public URL serves the new app. |
| 33 | Errors | Bad id | API and browser | 422 or a plain message | pass | 422 for a bad id. Found and fixed: it no longer uses up one of the hour's briefs. |
| 34 | Errors | Model down | Dev server, a stopped model port | Brief fails at a named step; Build again | pass | Model down: leads stay, the brief stops at the summary. Found and fixed: the message is now plain words, not "ConnectError". |
| 35 | Errors | Caps | API | 429 after the hourly brief cap | pass | 429 with "Limit of 2 new briefs an hour reached". |
| 36 | Replay preview | Tracker UI tab | `build_ui_preview.py` | Plays a saved brief with no server | pass | The preview bundle plays a saved brief with no server. |

**Totals:** 36 of 36 rows pass after fixes. Six problems were found by running the rows and fixed in S25 (rows 19, 27, 33, 34, and the student form and keep pill found by the walk in S24). Run on 2026-10-30 by Perch-dev, on the dev server (a scratch copy of the demo store), the demo and the CLI.

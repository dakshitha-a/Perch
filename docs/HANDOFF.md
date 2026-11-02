# HANDOFF.md — state for the next context window

Written at the close of S33 (2026-11-02). S33 ran in one orchestrating context with subagents (backend, docs, hosted spec, UI, QA, demo rebuild), under Dakshitha's delegation of product and design decisions (2026-10-31) and three new directions given on 2026-11-01: a fourth model job for cover-letter points, standing rule 5 and the spec open to edits, and both audiences sold equally. From S34 on the main session runs on Opus with the advisor on Fable, and every subagent call sets its model (CLAUDE.md, "Working with agents").

## Where things stand

- **The build is ready to freeze, again.** `main` holds S33's feature and every check. 421 tests green. Scout bench on the local model 30 of 30 tasks, 0 wrong tool, including the new cover-points task. Rehearsal on the dev server 21 of 21, with the two new cover-letter questions 3 of 3 each. Full walk with axe on the dev server 227 states, 0 errors, 0 axe violations, 0 sideways scroll. Canary clean with the CV now reaching the chat model for cover points. On the public demo after the rebuild: rehearsal 21 of 21, walk 227 states clean, canary and leakage clean.
- **What S33 added: cover-letter points for both audiences.** Scout's tenth researcher tool and eighth student tool, `cover_points`, backed by model skill 4 (`perch/skills/cover.py`). For one grant, fellowship or sample scholarship it returns 3 to 6 points, each with an "asks" half cited to the record and a "you" half cited to the CV, a session document, a paper or a public award, plus up to three gaps phrased as what the applicant's records do not show. Layer 1 checks every sentence, advice words are banned, a failed set is regenerated once then withheld, and the grounder flags unsupported sentences. Code writes the answer line; the full points sit on the card with citation chips, lock marks for private records, a Still missing list and a Copy button. The tool runs on the session's hand-off provider, counts toward the session budget, and follows the session's Local or Cloud choice. Contact details (emails, phones, links, ORCIDs) are blanked in every model prompt view of a private document, for every skill. The CV is capped at about 3,500 characters in the prompt. A sample scholarship gives sample points and the card and answer say so. Ask "What could my cover letter for the top lead say?" or "What should my application for my top option highlight?".
- **Rules and spec changed (Dakshitha).** Standing rule 5 names four model jobs and allows a session's models to read the CV and documents with contact details blanked. The student "never reads the CV text" line is gone from SPEC §8, SCOUT_SPEC §7, Help, the student start screen and the privacy guide. SPEC §1 lists students as a primary user with Scholar Development and Fellowships Advising and Student Financial Services as receiving offices. The hosted spec is v2.0 "as built" at the same URL, source tracked at `docs/design/spec.html`.
- **The README sells both audiences.** The opening names researchers and students; the student tour section sits beside the researcher hero; a "Points for your cover letter" section covers both (no clip yet; `docs/tour/points-researcher.png`, `points-student.png` and `points-sample.png` exist as stills).
- **What the presenter should know:** everything in the S32 hand-off still holds (warm briefs at server start, about 12 to 14 Scout questions per conversation, persona-1's top lead closes on 6 Nov, Cloud stays off unless a visitor chooses it, show the researcher export). New: the cover-letter question takes 10 to 18 s on the researcher brief and 9 to 10 s on the student brief on a quiet server; the points are model text and may carry an amber "could not be matched" flag, which is the grounding check doing its job; a sample scholarship's points are badged Sample data.

## What S33 did, task by task

1. Rules, spec, plan, decisions (rule 5; SPEC §8; S33 inserted, freeze moved to S34; Q43 on record).
2. Backend: skill 4, contact blanking, the tool on both allowlists, the loop's code-written answer, the card, the budget, MCP; 11 tests; Scout's system prompt grew 365 chars (about 91 tokens), far under the 6,400-token compaction ceiling.
3. UI: the points block, example questions, consent wording at the student start and the CV box, Help; walk flows with a geometry check proven to fail first.
4. Docs balance: README, SPEC §1, §3, §4, §5, §7, §8, SCOUT_SPEC, PRIVATE_MODE, private-mode.md, mcp.md, ARCHITECTURE, RESULTS.md. 4b: the hosted spec rebuilt as v2.0.
5. QA: docs claims checked against the code; the gap wording fixed; bench, rehearsal, sample path, canary, full walk, Cloud dialog; numbers into RESULTS.md and SUMMARY.md.
6. Demo rebuilt from `main` in 1 min 23 s (image 5dbdfb9abcee, previous kept as perch-demo:prev); rehearsal on the public URL 21 of 21; walk 227 states, 0 errors, 0 axe; canary and student leakage clean; `make package` 33.9 MB, 448 files, 420 passed and 1 skipped from the unzipped copy.

## Known limits (honest list)

- Everything in the S32 list still applies (Scout varies off-script on the local model; G21 and G23 partly open; student retrieval 1 of 12; the back-test tune is partly fitted; GRANTED and CREST unchecked).
- **Cover points are model text checked by code and a grounding model, not by a person.** A record that states little beyond its title gives few points. The grounder flags sentences it cannot match; on the sample scholarship it flagged 3 of the sentences in one live run.
- **The second Cloud warning lists the documents but does not name cover points** as one of the uses; the Local / Cloud dialog above it does. Not changed in S33.
- **The three architecture SVGs still draw three model jobs and no student path**; their captions say so.
- **`bench/results/SUMMARY.md` is generated by `make bench`**, which will overwrite the cover-points paragraph QA added; the numbers also live in `docs/RESULTS.md`.
- **No clip of the points step** in the README yet; three stills exist.
- **`bench/student_mode.py` writes a stale sentence** into `bench/results/STUDENT_MODE.md` ("40 records" where the S27 setting is 100); the task 6 agent reverted the output, and the script's text template is still wrong.
- **The S33 ZIP in `dist/` was built from d61d29d**, one commit before the close; S34 rebuilds it from the tagged commit.

## After the S33 close (2026-11-02)

- **Back to your options.** On the student form it showed whenever the session held any brief, so after a researcher run it opened the researcher's routes. The session now reports `brief_student`, and the button shows only for a student brief.
- **One side per session (Dakshitha).** A session holds a researcher brief or a student brief, never both. Arriving at Find, Your documents or the student form with the other side's brief open shows a warning listing what goes. End session and start fresh ends it and opens the form empty; Keep goes back to the brief. The server answers 409 to the other side's brief. Decision row, Help text, tests and the walk flow `ux-side` cover it.
- **Checks.** 422 tests green. `ux-side` (laptop and phone, Keep and End in both directions) and `ux-student` on the public URL: 14 states, 0 errors, 0 axe. `ux-side` is in the walk's default set, so the freeze's full walk covers it. The full walk, rehearsal and canary were not rerun; the freeze reruns them.
- **Demo.** Rebuilt from f678feb in 26 s, image f1299e0a01e9; the S33 image is kept as perch-demo:prev. The ZIP in `dist/` predates these commits.

## Hand-off offices checked live (2026-11-02, after the S33 close)

- **Routing is unchanged.** A live check of Temple's pages found it right for what Perch covers. Grants go to Research Development. Industry leads go to Innovation and Technology Commercialization. Fellowships go to Scholar Development and Fellowships Advising, whose list has graduate headings. Scholarships go to Student Financial Services.
- **New: the ERA note.** The researcher hand-off screen, the researcher export and Help now say that every grant proposal, and any company agreement that brings Temple funding, goes through ERA for institutional review and approval. The note links Find Your Research Administrator. The draft email itself is unchanged.
- **New: the future foundation office.** `FOUNDATION_OFFICE` in `perch/offices.py` records Corporate and Foundation Relations, reached through the school's or college's development team. It is not selectable, because Perch covers no foundations yet. Help says so.
- **Sources.** Two new fixtures (the OVPR proposal page and the CFR resources page, `<main>` only, email removed). Pages that list staff names are cited by URL in `docs/SOURCES.md` and not kept.
- **Checks.** 426 tests green. The walk check for the note failed before the UI edit and passes after. On the public URL: ux-laptop, ux-phone, ux-side and ux-student, 31 states, 0 errors, 0 axe, 0 sideways scroll. Rehearsal 20 of 21: one run of "What are my top three leads and why?" cited a record without naming its title; runs 1 and 2 passed, and the change does not touch Scout. The canary was not rerun; it runs on local data and this change does not touch the private path.
- **Demo.** Torn down and rebuilt from scratch at 3e4b7ab: `make demo-down`, a no-cache image build, then `make demo` (units, store kept, container) in 117 s. Image ba0491b957ca; 67beccbaa6b5 kept as perch-demo:prev. All four model units and the app answer 200; the public URL serves the note. Rehearsal after the rebuild: 6 of 7 on the first pass (the cover-letter points were withheld after two failed citation checks, the designed fallback), then researcher 12 of 12.
- **Not done.** The team pitch and team pages still say "Grants & foundations" though no foundation records exist; those pages carry teammates' work and were left for Dakshitha. The design canvas does not show the note. Confirming the routing with the offices themselves stays with the business team.
- **Wording to weigh at S34.** The note's first sentence ("Before anything goes to a sponsor") is broader than the page's "All proposals must be routed through ERA"; its second sentence scopes it to proposals and funded company agreements. Tightening it touches `perch/offices.py`, `web/handoff.js`, `web/help.js` and the walk's check.

## Next: S34, freeze (Dakshitha)

1. Confirm `make test`, `make package` from a clean clone and the live demo one last time.
2. `make decide-down` to stop the dev Clef-flash and Clef units (GPUs 1 and 2); tell the other session sharing the node that those GPUs are free (details in the local notes). The dev server on 8091 can be stopped with `build/devdemo/serve.sh stop`.
3. Tag `v0.1-demo`; nothing on `main` after that except README typos.

## Open questions (mirror of bridge/QUESTIONS.md)

- **None open.** Q44 (hand-off offices, 2026-11-02) is on record and built. Q43 (cover-letter points, rule 5) was decided by Dakshitha on 2026-11-01 and built in S33.

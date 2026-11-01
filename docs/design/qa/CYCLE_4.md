# QA cycle 4 (round 4 of the final QA cycles)

## How it was done

This was a black-box test on 1 Nov 2026, from 03:50 to 04:40, of the build on `main` at 2db76a2. All the work ran on the dev server (port 8091). The demo server (port 8090) was not tested. Cloud was never turned on: no script posts to the cloud switch.

**Server:** the dev server had started at 03:13, before commit fc23ff9 (03:21, student tools). It was restarted on `main` at 03:51 with `build/devdemo/serve.sh`, so every result below is on the current code. It is still running on that build.

**Machine checks:**
- `make test` ran twice. Each run passed 358 tests.
- The full walk (`scripts/ux_walk.py`, axe 4.10.2) covered 207 states. It found 0 errors, 0 axe violations and 0 sideways scroll.
- The walk found 84 targets under 24 px. They are the 1 × 1 hidden file inputs and inline text links, as in round 3.
- No animation looped with reduced motion. The "Task was destroyed" lines in the walk log are Playwright teardown noise.
- The walk ran while Scout conversations and builds ran beside it. It still passed.

**Demo rehearsal (`scripts/demo_rehearsal.py`, three runs each):**
- `--kept top2` (the demo): researcher 9 of 9, student 3 of 3.
- `--kept none`: researcher 9 of 9, student 3 of 3.
- `--kept weak2`: researcher 9 of 9, student 3 of 3.
- One more `--kept top2` run with nothing else on the server: 3 of 3, at 5, 6 and 6 seconds.
- The rehearsal passes demo question 2 even though every answer lists records outside the brief (F1). Its check only looks at cited ids that are brief leads. The pass counts are not evidence that questions 1 and 2 read well.
- The model runs at temperature 0, yet runs of one conversation did not always agree. Question 1 said "your" in some runs and "the researcher's" in others.

**Truncation in the demo Ollama log, since 03:51:**
- The prescribed `grep -ci truncat` gives 955. That count is every "truncated = 0" line, one per model call, so it is not a truncation count.
- Calls with "truncated = 1": 0 of 955. Lines with "truncating": 0.
- The largest call was 7,076 tokens of the 8,192-token context. Two more were above 6,500.
- Before this round, the log holds 10 truncated calls on 1 Nov, all between 01:20 and 01:38, from round 3.

**Browser and settings:**
- Playwright Chromium on a phone (390 × 844) and a laptop (1280 × 860), in light and dark.
- Zoom at 200% (640 × 430 at scale 2) and 400% (320 × 215 at scale 4), and 320 px reflow (320 × 640).
- Keyboard-only through the researcher flow, with a check that every focus stop shows a ring, is on screen and is not covered.
- 104 screenshots are kept in `build/review/qa4/`. Each one cited below was opened and looked at.
- The Scout transcripts are in `build/review/qa4/scout/` (one JSON per conversation, turns numbered from 1), and the exports, hand-offs and notes in `build/review/qa4/exports/`. Researchers in them are aliased.
- One set of screenshots of a name-searched researcher showed a real name in the brief heading. The alias helper only knows names already in the store. Those screenshots and their text were deleted, and the evidence for F20 is a shot of the card alone.

**Audiences:**
- PI-4 (A5026494099), the demo researcher.
- PI-8 (A5067949026), found by name search, which gave two Temple matches. Its brief was built live.
- PI-9 (A5108616139), built live by id to time a build with nothing else running.
- PI-6 and PI-7 are not found by name; their latest institution in OpenAlex is likely not Temple. Help says to use the ORCID iD then.
- The SYNTHETIC students persona-ug, persona-masters and persona-phd, and the SYNTHETIC researcher persona-1 (documents only).

**Demo script:** the whole flow was run on a laptop in light mode and again on a phone, with the text of every screen dumped and read beside its screenshot. It covered landing, find, build, Routes, the fold, the NSF chip, two Evidence records and a paper record, Keep two, Compare, the hand-off, Export Markdown, Profile, the three Scout questions, and the persona-ug student door through to the note and one Scout question.

**Scout:**
- 12 API conversations: PI-4 A (15 turns, two kept, with a Stop), B (12 turns, nothing kept, typed as a professor types), C (9 turns, weak two kept), D (the four example chips), F (6 turns); persona-phd (13 turns, with a Stop and "start over"); persona-ug (7 turns, weak two kept) and one T10 run; persona-masters (3 turns); persona-1 (6 turns, G, then two more runs of the hand-off, H1 and H2).
- Browser conversations: the demo questions twice, one run to the budget stop and past it, one run for the count question and "start over", one persona-1 hand-off.
- 79 API answers were scanned for leaked reasoning text ("thought", a think block, CJK characters). None was found.

**Content checks:**
- Every export (Markdown, print page and JSON) for PI-4, persona-ug, persona-masters, persona-phd and persona-1. Students and persona-1 were exported masked and unmasked. PI-4 holds no documents, so it has no masked export.
- Every hand-off (grants and industry, masked and unmasked for persona-1) and both student notes.
- Each export was scanned for ISO dates, OpenAlex work ids, `private:` ids and persona canaries. None was found. The only canaries in the JSON exports are the sample-record canaries, which rule 11 requires.

**Timing with nothing else running:** the three demo questions took 5, 6 and 6 seconds. A live build of PI-9 by id took 36 seconds, and the documents-only persona-1 build took 37 seconds. Under load the same questions took 20 to 80 seconds, and the PI-8 name build took 160 seconds, most of it "Waiting in line" behind other builds.

**Counts:** 7 must-fix, 10 should-fix, 11 could-fix. Of 79 earlier items, 75 pass, 3 fail (R9, T10, T17), and 1 was dropped in round 3 (T19).

## Regression on rounds 1 to 3

Scout rows give how many runs were checked. "API" means a scripted conversation, "browser" a run in Chromium.

| # | Result | Retest |
|---|---|---|
| Q1 | pass | Every student answer covering both kinds, about 20 across the rehearsal and the conversations, put the samples under "Sample scholarships (invented)". None mixed them. |
| Q2 | pass | The export reads "From $500,000" (26-517) and "From $15,000,000" (26-525). Scout reads "from $15,000,000 (award floor)". |
| Q3 | pass | NSF cards read "Proposals accepted anytime". |
| Q4 | pass | "Compare my kept leads" ran compare on the kept leads in 4 of 4 runs (A, C, two browser). See F11 for how the answer reads. |
| Q5 | pass | "Which company cites my papers the most, and how many works?" ran get_org_signals and answered "Samsung … 18 works" in 3 of 3 runs. See F5 for papers. |
| Q6 | pass | Five open cards and "Weaker matches (5)". |
| Q7 | pass | The student chip reads "Local only · nothing stored". |
| Q8 | pass | In the browser, "Why does my top lead fit?" gave paper chips such as "fix pimd/langevin: An efficient… (2026)". |
| Q9 | pass | At 320 × 215, Routes, Profile and Scout have 0 sideways scroll and every focus is seen. Compare: see F24 and F13. |
| Q10 | pass | No W id in any Markdown or print export. |
| Q11 | pass | "1 dismissed lead is left out"; the footer reads "4 kept, 14 shown, 1 dismissed". |
| Q12 | pass | Each banner equals its Withheld lines: persona-ug 19, persona-phd 18, persona-masters 18, persona-1 20. |
| Q13 | pass | The research-security line is on the Industry tab, in the export and in the industry hand-off. |
| Q14 | pass | "Next deadline … NSF" ran closes_after 2026-11-01, sorted by close date, in 2 of 2 runs, and answered 1 Dec 2026, PD-16-1271. |
| Q15 | pass | Help and Your documents both say the operator could see that a researcher was looked up, and when. |
| Q16 | pass | "30 minutes without use". |
| Q17 | pass | persona-ug's Boren card reads "How it relates". |
| Q18 | pass | 0000-0000-0000-0000 and 0000-0002-1825-0096 are refused (422) before any search. |
| Q19 | pass | "a5026494099" finds PI-4. |
| Q20 | pass | The injection was answered from get_record with "Proposals accepted anytime", with no invented value, in 3 of 3 runs. |
| Q21 | pass | No ISO date in any Markdown or print export. |
| Q22 | pass | Student answers write "20 Dec 2026", "15 Apr 2027". |
| Q23 | pass | No bracketed keys in the openings of the PI-4 grant and industry hand-offs or persona-1's masked one. |
| Q24 | pass | persona-1's export reads "Topics withheld: …". |
| Q25 | pass | The walk's mask check passes. |
| Q26 | pass | persona-1's hand-off ends "Best regards," and an empty line. |
| Q27 | pass | The walk's tab-key check passes. |
| Q28 | pass | Help's "about 40 to 50 seconds" holds: 36 s and 37 s with nothing else running. |
| Q42 | pass | The unmasked student export reads "your CV value is withheld". |
| R1 | pass | The Kept leads compared table writes "6 Nov 2026". |
| R2 | pass | "Top three" named 26-519, PD-26-366Y and 26-523 in brief order in 16 of 16 runs. See F2 and F12. |
| R3 | pass | The line above each draft is "Code, no model". See F7 for the draft itself on a documents brief. |
| R4 | pass | The walk's phone check of the Latin-1 cv.txt passes. On Your documents, a PNG, a .doc, an empty file, a blank file and a fake PDF each give a plain sentence naming the file. |
| R5 | pass | "A12" gives the format message; A99999999999 gives "No OpenAlex author has that ID". |
| R6 | pass | "Why does my top lead fit? Quote my draft aims." ran explain_fit or used the brief, explained the fit, and said "Scout does not quote private documents", in 3 of 3 runs. |
| R7 | pass | "stream monitoring" found the Quillmere and Ostrevel samples under their heading. |
| R8 | pass | "1 dismissed option is left out"; footer "4 kept, 128 shown, 1 dismissed". |
| R9 | **fail** | The student export names a card's own record in parentheses. See F4. |
| R10 | pass | See Q12. |
| R11 | pass | "For a first-generation college student." |
| R12 | pass | "cite 2 of my papers" in the industry hand-off. |
| R13 | pass | "What is the soonest deadline I can make?" opened with the public fellowships, then the sample under its heading. |
| R14 | pass | A PI-8 name search shows "1 work · 0 citations". |
| R15 | pass | The walk's Find checks pass. |
| R16 | pass | 0000-0002-1694-233X, …233x and the orcid.org URL give the same author. |
| R17 | pass | The notes and the Compare cells read "a transcript; an essay". See F3 for "deadline Expires". |
| R18 | pass | The export's Industry note matches the tab. |
| R19 | pass | "Record: Temple Scholar Development and Fellowships Advising list (links to smartscholarship.org)". |
| R20 | pass | draft_note gave the code line. |
| R21 | pass | "Only show NIH grants." then "Now only the ones closing after 1 March 2027." ran agencies NIH and closes_after 2027-03-01 in 3 of 3 runs. See F10. |
| T1 | pass, with F1 | Demo question 2 searched with closes_by 1 Mar 2027 and did not apologise in every run. It now adds records from outside the brief (F1). |
| T2 | pass | No reasoning text in 79 API answers or the browser answers. |
| T3 | pass | "Draft the hand-off for my top lead" drafted 26-519 alone in every run. See F8. |
| T4 | pass | The budget stop came at question 13 in the browser and at question 14 by API. "Start a new conversation" works, and the next question was answered. Help says so. See F14. |
| T5 | pass | The company question ran get_org_signals in 3 of 3 runs. |
| T6 | pass | "Largest award ceiling" sorted by ceiling and named Expeditions' amount as "from $15,000,000" in 3 of 4 runs. The fourth (browser) was withheld (F16). |
| T7 | pass | See Q20. |
| T8 | pass | Question 1 gives one fit sentence per lead. See F2 and F12. |
| T9 | pass | The chip reads "Closes by: 1 Mar 2027". |
| T10 | **fail** | "Which ones am I not eligible for, and why?" ended with an empty answer in 2 of 4 runs. See F6. |
| T11 | pass | No masked phrase is followed by a stray word. |
| T12 | pass | At 640 × 430, Profile, Routes and Scout show every focus. See F24 for Compare. |
| T13 | pass | "3 letters of recommendation (my CV lists 2 referees)". |
| T14 | pass | Help's "What Perch does not do" reads as decided. |
| T15 | pass | Weak cards read "How it relates" on both paths. See F11 for Scout's compare. |
| T16 | pass | The walk's U30 check passes. |
| T17 | **fail** | Cards read "Expires 7 May 2028", but the export, the note and Scout do not. See F3. |
| T18 | pass | persona-1's Industry tab and export give the one sentence. |
| T19 | n/a | Dropped in round 3. |
| T20 | pass | No UK spelling found in Help or the exports. |
| T21 | pass | Evidence gives "Deadline note: Proposals accepted anytime", then "Closes (placeholder in the record)". |
| T22 | pass | "26 Sep 2029" reads "in about 3 years". |
| T23 | pass | Sample cards read "To check: For residents of PA. …". |
| T24 | pass | The sample tag is as wide as its words; "A transcript; an essay". |
| T25 | pass | "Open in my mail app" has a mail icon. |
| T26 | pass | See R19. |
| T27 | pass | Scout writes "$3,000" and "$20,000". |
| T28 | pass | The Profile's first sentence shows 4 paper chips, as the export cites 4. |
| T29 | pass | The rehearsal exists and runs; see its blind spot in How it was done. |

## Must-fix

| # | Screen | Steps to reproduce | What happened | What was expected | Audience | Evidence | Proposed fix | Cost | Decision |
|---|---|---|---|---|---|---|---|---|---|
| F1 | Ask Scout (researcher), demo question 2 | Build PI-4. Keep the top two. Ask "What are my top three leads and why?", then "Which of these close before March?". | The answer names the brief's one lead that closes before March: 25-543, 4 Feb 2027. Then it adds "Other leads closing before March include:" and nine records that are not in the brief, such as "Systematic Characterization of Genomic Variation", "Cellular Senescence Network (SenNet)" and "Topology". This happened in every run: 9 rehearsal runs, both browser runs, and conversations A, B and C. With the weak two kept (C), there was no split at all: one numbered list of ten, only the first from the brief. persona-1 does the same. This is the round 3 known item. | Help says "These" means the brief's leads. The answer names 25-543 and stops. | Everyone at the demo. Unrelated programs appear on the second scripted question, for a molecular dynamics researcher. | build/review/qa4/Q18-scout-q2-laptop-light.png; build/review/qa4/scout/pi4-A.json turn 2, pi4-C.json turn 5, p1-G.json turn 4 | When the question says "these" or "my leads", run the search on the brief's lead ids only (a brief_only argument), or drop the other records from that tool result. Make the rehearsal's check_before_march fail any cited id that is not a brief lead. | M | done a8fb295, 383e26b; search_opportunities takes scope brief or all; code sets brief from "these", "them", "those" or "my … leads" in the question and all from "other", "new" or "more" (with neither, the model's choice, default all), writes it on the card ("Within: your brief"), and filters the brief's own leads by the same rule code, without asking eligibility again; an answer that puts a cited grant "on your brief" when it is not fails the check. Rehearsal Q2 now fails on any record outside the brief: 0 of 3 before, 3 of 3 after, on each variant. Was: fix: search_opportunities gets a scope; a question about "these", "my leads" or the brief runs with scope brief, and store-wide results come only when the question asks for new or other opportunities; the rehearsal check for question 2 fails on any record outside the brief |
| F2 | Routes card, Ask Scout demo question 1, export | Build PI-4. Open "How it relates" on card 3, MPS Physics (26-523). Or ask "What are my top three leads and why?". Or export Markdown. | The sentence ends "…aligns with the theoretical physics aims of." The model wrote "aims of [26-523].", and code drops a card's own citation, which leaves the sentence hanging. It shows on the card and in the export. In demo question 1 it is the last line the audience reads: with the top two kept, as in the demo, 7 of 8 runs ended "aims of." (4 rehearsal, conversation A, both browser demo runs, the budget run). With other leads kept the model often wrote "aims of the program" instead (6 of 8 runs). Expeditions reads "…research agenda required by." A scan of the stored texts finds 8 such sentences: PI-4 2 of 15 leads, persona-ug 2 (NOAA Hollings reads "…the STEM focus of the." on screen), persona-masters 2, persona-phd 1, persona-1 1. | A whole sentence: "…the theoretical physics aims of MPS Physics Research Programs." | Everyone at the demo. It reads as a bug on the first scripted question. | build/review/qa4/Q17-scout-q1-laptop-light.png, build/review/qa4/Q23-card3-relates-laptop-light.png | Where the card's own citation follows a preposition or article, put the record's short title in its place instead of dropping it. Or have the validator reject such a sentence and regenerate once. Test with "aims of [26-523]." | S | done a8fb295, 7a82d8a; one rule in code (perch.export.own_in_place, web/format.js ownInPlace): a card's own citation after a preposition or article reads "this opportunity" (the article goes), on researcher and student cards, in exports and in Scout's brief note and compare rows; elsewhere it is dropped as before. Pytests and a node test fail before; the walk checks card sentences and demo question 1. Rehearsal Q1 fails on a reason that stops on such a word. Was: fix: a card's citation of its own record is rendered by code as "this opportunity" (or "this program"), never dropped, on the card, in exports and in Scout's compare rows; the rehearsal check for question 1 fails on a reason that does not end as a sentence |
| F3 | Export, student note and Scout (graduate students) | persona-phd: keep the Parent F31. Export Markdown. Draw the note to Scholar Development and Fellowships Advising. Ask Scout "f31?". | **Regression of T17.** The export reads "Closes: 7 May 2028" for the Parent F31, F32 and F33. The note reads "deadline Expires 7 May 2028"; persona-ug's reads "deadline Expires 8 Apr 2029". Scout answered "f31?" with "has a deadline of 7 May 2028". The card reads "Expires 7 May 2028". | Every place reads as the card does: "Expires 7 May 2028", and Scout says the announcement expires then and does not call it a deadline. The note joins it in lower case (R17). | Graduate students and advisors, who know F31 uses NIH's standard due dates. | build/review/qa4/exports/persona-phd-plain.md, build/review/qa4/exports/persona-phd-note-F.json, build/review/qa4/scout/phd-A.json turn 11 | export.student_blocks writes the date with datefmt.shown. write_note words it "announcement expires 7 May 2028". The student tool result for a parent gives no deadline field, only the expiry, as T17 did for search. | S | done a8fb295; root: the T17 fix lived in datefmt.closes and the cards, but the export (its own close string), student_blocks (_day), the hand-off list, the note ("deadline " + whatever came) and the student tool's "deadline" key never called it. Now datefmt.deadline gives one clause ("closes 4 Feb 2027", the record's words, or "no deadline in the record; the announcement expires 7 May 2028") for the hand-off and Scout, datefmt.closes for the exports, Compare's cell reads "Expires 7 May 2028", the note reads "announcement expires 7 May 2028", and the student tool gives announcement_expires and no deadline. Live 3 of 3: "f31?" answered "the announcement expires on 7 May 2028". Was: fix: one function renders every deadline (card, Evidence, Compare, exports, note, Scout record view and tool results): the record's own words, else "Expires <date>" for a parent announcement, else the date |
| F4 | Export (student) | persona-ug: export Markdown, masked and unmasked. | **Regression of R9** on the student path. Masked, each fellowship's model text names its own record: "The Boren Fellowship supports students in STEM and public policy (Boren Fellowship)." student_blocks does not pass the card's own id. Separately, the student export never contains the fit sentence ("Why it may fit" or "How it relates"), withheld or masked; only the description. | No own-record parenthesis, as in the researcher export. The fit sentence is exported under its card label, withheld or masked like the rest. | Students and advisors reading an export. | build/review/qa4/exports/persona-ug-masked.md | Pass skip=own in student_blocks. Export the inference and count it in the banner. | S | done a8fb295, 4916ca7; root: student_blocks never passed the card's own id, and never exported the inference. Now skip=own (the own record stays only as a sentence's subject, named), and "Why it may fit" or "How it relates" is exported under the card's label, in the second person as the card writes it, withheld or masked and counted in the banner. Live persona-ug and persona-phd exports: no own-record parenthesis. Was: fix |
| F5 | Ask Scout (researcher) | Build PI-4. Keep two grants. Ask "How many of my papers does each kept lead cite?". Or keep the weak two and two companies and ask "Which of my kept grants cites more of my papers?". Or ask "how many of my papers does samsung cite". | **The round 3 known item, in a worse form.** No answer gives the code-written count ("cites 3 of your papers"). Questions about the kept grants run get_org_signals and answer about companies, in 3 of 3 runs (browser and API B, C). With the numbers dropped the sentences break: "Samsung has citing works [I2250650973]. Aviation Industry Corporation of China has citing works…" (C, twice). "how many of my papers does samsung cite" answered "Samsung has 18 works that cite your papers"; the record says 2 papers (A). | "26-519 and PD-26-366Y each cite 3 of your papers", citing their compare rows. "Works at Samsung cite 2 of your papers." | Researchers; an obvious audience follow-up. | build/review/qa4/Q52-scout-count-papers-laptop-light.png; build/review/qa4/scout/pi4-C.json turns 3 and 4; build/review/qa4/scout/pi4-A.json turn 11 | Let the validator accept a count that a cited compare row or signal row states, as this round's rules allow: expose the counts as fields of those rows. Add these three questions to the Scout bench. | M | done a8fb295, 383e26b; compare rows give your_papers_cited and "cites 3 of your papers" as code-written facts of the cited record; signal rows give works_or_projects and your_papers_cited apart, with their sentences as facts of the lead and the company; the org nudge no longer fires on questions about kept leads or grants, and a rule line points kept-lead counts to compare. Live 3 of 3 each: "MPS Chem cites 3 of your papers", "Samsung cites 2 of your papers", "Both kept grants cite 3 of your papers". Bench task b06 added. Was: fix: a number that code computed from records and that appears in a tool result (compare cells, signal counts) passes the validator when the answer cites that row; questions about kept grants use compare, not get_org_signals (prompt and a test) |
| F6 | Ask Scout (student) | persona-ug or persona-masters: ask "Which ones am I not eligible for, and why?". | **Regression of T10.** In 2 of 4 runs Scout ran search_options, then explain_verdict seven times, and stopped at the cap: "stopped after 8 model turns", with an empty answer. In a third (persona-phd) it began "I cannot provide a full list of reasons…" and gave 2 of about 50. One fresh persona-ug run answered well. | The not-eligible options, each with its rule line, which search_options already returns. | Students; the reproduce step of T10. | build/review/qa4/scout/ug-E.json turn 4, build/review/qa4/scout/ms-T10.json turn 3 | Give search_options' not-eligible rows their rule line, and tell Scout not to call explain_verdict per row when the list already has the reason. At the call cap, write the answer from the results so far instead of an empty one. | S | done a8fb295; root: search_options rows held the verdict but not its reason, and the note told the model "explain_verdict says why". Rows that are not eligible (or may be) now carry why, the rule lines, which also back their numbers; explain_verdict runs once per question ("per turn" read as per question: seven calls came one per model turn, so a per-turn cap would not stop it). Live 3 of 3 persona-ug and 3 of 3 persona-masters answered with each option's rule line, one search, no cap. Was: fix: search_options results carry each option's code-written verdict reason, so no per-option explain call is needed; explain_verdict is limited to one call per turn |
| F7 | Ask Scout hand-off (documents session) | Your documents: add persona-1's CV, aims and manuscript, no OpenAlex id. Build. Keep the top lead. Ask Scout "Draft the hand-off for my top lead". | The draft opens: "My published research focuses on the mechanisms of neurodegeneration, as detailed in my recent papers []." In other runs: "…[No papers provided]." persona-1 has no public papers, and the aims are on gait sensing, not neurodegeneration. The paragraph is model text, yet it sits under "Code, no model · Written by Perch's code", with no Model text mark. It was not withheld, although the session holds documents: the Compare tab's draft for the same session opens with the plain sentence, as Help says. Seen in 6 of 6 drafts (5 API, 1 browser). | The documents-session rule holds in Scout too: a plain opening, unless masking is chosen. An empty or placeholder citation fails the validator. A model-written opening carries the Model text mark. | The office reading the email; anyone trying the documents page. Breaks rule 10 and the documents-session promise. | build/review/qa4/Q54-scout-p1-handoff-laptop-light.png (Scout's draft); build/review/qa4/Q55-compare-p1-handoff-laptop-light.png (same session, Compare tab: plain opening, withheld note); build/review/qa4/scout/p1-G.json turn 5, p1-H1.json, p1-H2.json | Route Scout's draft_handoff through the same withholding and masking as /private/handoff. Make the validator fail "[]" and any bracket that names no record. Mark the opening as model text on Scout's draft card. | S | done a8fb295, 7a82d8a; root: Scout's draft_handoff called the skill without the session's documents, so the withholding rule never ran. It now passes them: with documents and no masking, code writes the opening from the lead's title and the documents' kinds ("Perch matched it to my work from my CV, my draft proposal and my unpublished work"), with no model call, on Scout and on the Compare tab alike; each draft carries opening_by and shows Model text or Code, no model; the hand-off validator rejects "[]", "No papers provided" and brackets that name no record. Rehearsal persona-1: 0 of 3 before, 3 of 3 after, on each variant. Was: fix: when the session holds documents and the researcher has no public papers, the hand-off opening is written by code from the documents' labels and the brief's top lead, with no model call, and the label says so; when a model does write it, the label says Model text and the validator rejects empty brackets and "No papers provided" |

## Should-fix

| # | Screen | Steps to reproduce | What happened | What was expected | Audience | Evidence | Proposed fix | Cost | Decision |
|---|---|---|---|---|---|---|---|---|---|
| F8 | Ask Scout hand-off | Build PI-4 with nothing kept, or the weak two kept. Ask "Draft the hand-off for my top lead". | The draft for 26-519 says "These are the leads I kept in Perch:", but 26-519 is not kept. | "These are the leads I would like to discuss:" when any listed lead is not kept. | The office. | build/review/qa4/scout/pi4-C.json turn 6 | In skills/handoff.assemble, choose the line by whether every item is kept. | S | done a8fb295; "These are the leads I kept in Perch:" only when every listed lead is kept, else "These are the leads I would like to discuss:". Pytest. Was: fix |
| F9 | Ask Scout | Ask "start over" in any conversation. | 3 of 3 refusals: "I cannot perform a search without a specific question or set of filters to apply." (browser); "I cannot perform that action because I do not have any filters or parameters to use." (B); "I cannot fulfill this request. I am only permitted to call tools…" (phd). "Start a new conversation" exists only at the budget stop. | A start-over request clears the filters or points to a New conversation control that is always there. | Anyone at the demo. | build/review/qa4/Q53-scout-start-over-laptop-light.png | Show "New conversation" beside the question box at all times, and route "start over" and kin to it. | S | done 7a82d8a, e93d5be; New conversation sits beside Ask once a conversation has begun, and "start over", "restart", "new conversation" and kin open one in the page with no Scout call. Walk check. Was: fix |
| F10 | Ask Scout (researcher) | Build PI-4. Ask "r01?", or press the first example chip "Only R21 grants that close by 2027-03-01". | "r01?" lists R01s on cancer imaging, the BRAIN Initiative, bioinformatics and cancer risk. The chip returns "Secondary Analysis … Cancer Risk" and "Mechanisms that Impact Cancer Risk with Use of Incretin Mimetics". None is in the brief, and nothing says so or gives their Match. "Only show NIH grants" lists SenNet, genomic variation and mental-disorder programs the same way. | The answer says none of the brief's leads is an R01, then gives others with their Match band ("weak match"). | Researchers; the presenter, if an example chip is pressed. | build/review/qa4/scout/pi4-B.json turn 1, build/review/qa4/scout/pi4-D.json turn 1, build/review/qa4/scout/pi4-F.json turn 2 | Give each search row its Match band and whether it is a brief lead, and ask the model to lead with the brief's leads and name the band of others. Replace the first example chip with one PI-4's brief can answer. | M | done a8fb295, 7a82d8a, 383e26b; search rows give match_band ("weak match") and no score; the note says to lead with brief leads and call others further leads with their band, or to say first that none is on the brief; the first chip is now "Which of my NSF leads close by 1 Mar 2027?". Live 3 of 3: "r01?" opened "None of these R01 opportunities are on your brief", then weak matches; "Only show NIH grants" listed the brief's two, then further leads. Was: fix |
| F11 | Ask Scout compare | Build PI-4. Keep two leads. Ask "Compare my kept leads". | In 4 of 6 runs the answer is a Markdown table. Scout's renderer has no tables, so the browser shows the raw rows (the browser run's text ends "| |"). Cells lose their numbers ("Match (weak); cites 3 of your papers", "kinds of public signal (moderate)"), show internal codes ("Route: A, A, B, B"), "N/A", "(explanation checked)", and "Why it fits" for the Match 30 lead (T15 says "How it relates"). Each answer took 37 to 44 s under load. | Short prose that names the differences, as the other 2 runs did; or a rendered table. | Researchers. | build/review/qa4/scout/pi4-A.json turn 5, pi4-B.json turn 6, pi4-C.json turn 2 | Tell the model not to write tables, or render Markdown tables. Give compare rows the card label for the fit sentence. Drop route codes from what the model sees. | S | done a8fb295, 7a82d8a, e93d5be; Scout renders a pipe table as a table; compare rows carry the band in words, no route codes, no state notes, and how_it_relates for a weak match; the note asks for sentences. Live: 3 of 3 compare answers were prose. The walk feeds a pipe-table answer to the page and checks it renders as a table. Was: fix: Scout's renderer draws a simple pipe table as an HTML table; the prompt may still ask for prose |
| F12 | Ask Scout (researcher), demo question 1 | Build PI-4. Ask "What are my top three leads and why?". | In 15 of 16 runs each reason reads "the researcher's development of molecular dynamics software…" while the researcher is the one asking. The answer copies the card's inference. | "Your development of…", as the other runs and the hand-off do. | Everyone at the demo. | build/review/qa4/Q17-scout-q1-laptop-light.png | Give Scout the fit sentences in the second person, or rewrite "the researcher's" to "your" in code before the brief note. | S | done a8fb295; Scout's fit sentences go through second_person ("Your development", "you develop"); cards unchanged. Rehearsal Q1 fails on "the researcher": it failed 2 of 3 top2 runs before, and 0 of 9 runs after across the variants. Was: fix: Scout gets the fit sentences in the second person (code rewrites "the researcher's" to "your") |
| F13 | Compare (phone and 320 px) | Phone: keep two leads, open Compare, press Tab from the tab row. At 320 px, look at the Closes cell. | On a phone the table becomes one card per lead and the header row is hidden. Yet Tab still stops on the table region and on six column-sort buttons ("Lead ↕", "Money ↕" …). Focus sits under the sticky header or off the cards, and nothing visible is focused. At 320 px the Closes cell is cut off: "Proposals accepted an". | Hidden sort buttons leave the tab order (the Sort by menu does their job). Cell text wraps. | Keyboard and screen-magnifier users on phones. | build/review/qa4/Q26-p390-compare-focus5-phone-light.png, build/review/qa4/Q25-r320-compare-phone-light.png | Give the header buttons tabindex -1 (or display none) in the card layout; let the value cell wrap. Add the phone Compare to the walk's tab traces. | S | done 7a82d8a; in the stacked layout the header row is display none, the region is no tab stop, and the Closes cell wraps. Walk check of 14 Tab stops on the phone, and of cut cells at 320 px. Was: fix |
| F14 | Ask Scout, Help | Ask 13 questions in one conversation. | The budget stop came at question 13 in the browser and at question 14 by API. Questions cost about 4,700 to 14,300 tokens each, about 9,000 on average, so the 120,000 budget lasts about 12. Help says each question costs about the same, but gives no count. The 13th question gets no answer: the user must ask it again after Start a new conversation. | Help says "about a dozen questions". The stopped question is carried into the new conversation, or answered before the stop. | Presenters and the audience in a long live session. | build/review/qa4/Q27-scout-budget-laptop-light.png | State the count in Help; re-ask the stopped question on Start a new conversation. | S | done 7a82d8a; Help says the budget lasts about a dozen questions; the stopped question is kept with its exchange, and Start a new conversation and ask again opens a new conversation and sends it. Walk check. Was: fix: Help says about a dozen questions per conversation; a question that hits the budget stays in the box so Start a new conversation can send it again |
| F15 | Ask Scout (both audiences) | Many short questions in a row ("whats the deadline for the first one", "which one pays most"). | Follow-ups lose their subject. After a list of NIH grants, "the first one" was answered with the brief's first lead, not the list's, with no tool (A turn 13). After a company answer, "which one pays most" about grants was refused: "the industry leads do not include funding amounts" (B turn 8). persona-ug "Which option pays the most?" ran compare on the kept options and called a $3,000 sample the most, while a $10,000 sample exists. | Follow-ups resolve against the last list shown; "pays the most" searches all options sorted by amount. | Researchers and students. | build/review/qa4/scout/pi4-A.json turn 13, pi4-B.json turn 8, ug-E.json turn 3 | Put the last result's ids in the brief note as "the last list"; map "pays the most" to the amount sort. | M | done a8fb295; the system note carries the last list's ids (at most 8), and "the first one" means its first; students can sort by amount, and the rules map "pays the most" to it. Live 3 of 3: "the first one" was the last list's first; persona-ug "pays the most" named the $10,000 sample. Was: fix |
| F16 | Ask Scout (researcher) | Build PI-4. Ask "Which lead has the largest award ceiling?" late in a conversation. | In the browser run (turn 9) the answer was "Scout's answer was withheld: it did not pass the citation check twice." The same question answered well in 3 other runs. | An answer, as in the other runs. | Researchers. | the budget run's text, turn 9 (browser; no screenshot) | Log the failed check for this question in the bench; see whether a floor-named-as-ceiling sentence is what fails. | S | done a8fb295, 383e26b; the withheld run was the floor check: "from $15,000,000 (award floor)", as compare's cell writes it, failed because only the words before the amount were read; "from" before and "floor" after now pass. Live, a second cause: a sorted search cut to top before sorting, so "top 1 by ceiling" was the best match; it now sorts first. Pytests fail before. Was: fix |
| F17 | Export (student) | persona-ug: export Markdown. | The screen shows "Fellowships 10" and folds "Not eligible by rule (50)". The export numbers all 59 together under "Fellowships (public) (59)", the 50 not-eligible ones mixed in by Match. Each fellowship repeats the listing line and "Sponsor / Deadline / Amount: Not in the record", which the screen says once under "Unless a card says otherwise". persona-ug's export is 1,464 lines. | The export follows the screen: options you may apply for first, then "Not eligible by rule (50)", with the shared lines said once. | Students printing their options. | build/review/qa4/exports/persona-ug-plain.md | Group the student export by verdict as the screen does; reuse the screen's "Unless a card says otherwise" lines. | S | done a8fb295; the student export lists the options you may apply for first, the lines most of them share once under "Unless an option says otherwise", then "…: not eligible by rule (n)". Live persona-ug: 10, then 50. Was: fix |

## Could-fix

| # | Screen | Steps to reproduce | What happened | What was expected | Audience | Evidence | Proposed fix | Cost | Decision |
|---|---|---|---|---|---|---|---|---|---|
| F18 | Ask Scout example chips | Open Ask Scout. | The chips read "Only R21 grants that close by 2027-03-01" and "Only options with a deadline after 2027-03-01", in ISO form, while the rest of the app writes "1 Mar 2027". The chip "Drop anything that mentions clinical trials" also drops every "Clinical Trial Not Allowed" grant, so its answer was "No R21 grants … meet your criteria." | "close by 1 Mar 2027"; a clinical-trials example that does not empty the list. | The audience. | build/review/qa4/Q16-scout-open-laptop-light.png | Rewrite the chips. | S | done 7a82d8a, e93d5be; chips read "Which of my NSF leads close by 1 Mar 2027?", "Leave out Department of Defense grants" (no clinical-trials chip) and "Only options with a deadline after 1 Mar 2027". Walk check. Was: fix |
| F19 | Hand-off (documents session, masked) | persona-1: draft the email with Mask ticked. | The masked opening draws on the documents, yet the note under it says "Perch drafted this from public records." | "Perch drafted this from your documents and public records", as the export header says. | The office. | build/review/qa4/exports/persona-1-masked-handoff-research_development.json | Choose the line by whether the session holds documents. | S | done a8fb295; the note reads "Perch drafted this from your documents and public records" when the session holds documents. Pytest. Was: fix |
| F20 | Routes card (NIH parent announcement) | Build PI-8 (A5067949026). Look at the first card. | The label "Closes" sits above "Expires 7 Jan 2028". | A label that fits, such as "Announcement" above "Expires 7 Jan 2028". | Researchers who know parent announcements. | build/review/qa4/Q57-parent-card-closes-expires-laptop-light.png | Change the label when the value is an expiry. | S | done 7a82d8a; an expiry sits under "Announcement". Checked live on PI-8's card (the alias helper does not know PI-8, so the card crop was looked at and deleted). Was: fix |
| F21 | Evidence panel | Open any grant's title. | The Grants.gov disclaimer prints twice: once in the panel and again in the page footer below it. | Once. | Everyone. | build/review/qa4/Q08-evidence1-laptop-light.png shows the panel's top; the second copy is at the panel's foot, read from the page text | Drop the panel's copy when the footer shows. | S | done 7a82d8a; the panel no longer prints the Grants.gov line; the footer does, on every screen. Walk check. Was: fix |
| F22 | Ask Scout | Build PI-4. Ask "anything from NSF" in a long conversation. | The answer reads "Chemical, Bioengineering, Environmental, and Transport Systems (CBET) [26-518], closes Proposals accepted anytime." | "accepts proposals anytime". | Researchers. | the budget run's text, turn 8 (browser; no screenshot) | Give the deadline words with their own verb in the tool result ("accepts proposals anytime"). | S | done a8fb295; the tool rows and the brief note give the deadline as a clause with its verb ("closes 4 Feb 2027", "Proposals accepted anytime"). Live: "anything from NSF" read "…[26-519], Proposals accepted anytime.". Was: fix |
| F23 | Brief header (phone) | Open any brief on a phone. | "Brief as of 1" ends a line and "Nov 2026" starts the next. | The date stays on one line. | Phone users. | build/review/qa4/Q04-routes-phone-light.png | Join the date's parts with no-break spaces. | S | done 7a82d8a; the date's parts are joined by no-break spaces. Walk check. Was: fix |
| F24 | Compare at 200% zoom | 640 × 430 at scale 2: keep two leads, open Compare, press Tab to a Closes cell. | The table scrolls sideways and the focused cell slides half under the sticky Lead column: "…anytime" shows with half its ring. | The focused cell scrolls fully into view. | Keyboard users at high zoom. | build/review/qa4/Q56-z200-compare-focus-laptop-light.png | scroll-padding-left equal to the sticky column's width. | S | done 7a82d8a; the table's scroll-padding-left is the sticky column's widest width. Walk check in the 200% trace. Was: fix |
| F25 | Find | Press Find with the box empty, or with spaces. | Nothing happens and nothing is said. The API /authors/resolve with an empty q returns 3 real author candidates. | A short hint ("Type a name, ORCID iD or OpenAlex ID"); the API returns 422 for an empty q. | Everyone. | build/review/qa4/Q30-empty-find-laptop-light.png | As said. | S | done a8fb295, 7a82d8a; Find with an empty box says "Type a name, ORCID iD or OpenAlex ID." under the box and marks it; /authors/resolve with an empty q answers 422. Pytest and walk check. Was: fix |
| F26 | Hand-off API | POST /private/handoff with the industry office and no kept industry leads. | A draft with the subject "Request to discuss " and an empty list. The page disables that office, so only the API reaches it. | 422, "No kept industry leads". | Developers. | API response (not kept) | Refuse with 422. | S | done a8fb295; both hand-off routes answer 422 "No kept industry leads." or "No kept grants.". Pytest. Was: fix |
| F27 | Exports (headings) | Export any student or documents brief. | "## Fellowships (public) (59)" has two parentheses in a row; the documents brief's title is "Perch brief: You (private)". | "Fellowships, public (59)"; "Perch brief: your documents". | Readers of exports. | build/review/qa4/exports/persona-ug-plain.md, build/review/qa4/exports/persona-1-plain.md | Reword. | S | done a8fb295; "Fellowships, public (10)", "Scholarships and awards, sample (10)"; a documents brief is "Perch brief: your documents". Pytest. Was: fix |
| F28 | Scout context | Long conversations. | No truncation in 955 calls, but the largest call used 7,076 of 8,192 tokens (86%). | Headroom for a longer brief note or a longer question. | The demo. | the demo Ollama journal, 03:51 to 04:40 | Keep the compaction; consider a 12,288 context on the demo unit if memory allows. | S | fix in S32: measure 12,288 context with two slots on GPU 4 first; apply to the demo unit only if the card's total stays under 29 GB with Clef-flash |

## Triage (Perch-dev, 2026-11-01, under Dakshitha's delegation)

All 28 findings are fix (F28 in S32). F1, F2, F3, F5, F6, F7, F11, F12 and F14 carry decisions. The rehearsal script is extended as F1 and F2 say, plus a persona-1 documents-session hand-off run that checks F7, and must pass 9 of 9, 3 of 3 and 3 of 3 before the Scout items close.

## Checked and fine

- **Landing, Find and pick:** the id, the lower-case id, the OpenAlex URL and spaced ids all find PI-4. A name search with two Temple matches shows both with their institution and counts, and nothing runs until one is picked. A surname search gave three Temple matches.
- **Build wait:** a live build shows "Waiting in line" with a plain reason when another brief is building, then steps and a bar. With nothing else running, live builds took 36 and 37 seconds.
- **Routes:** five open cards and the fold; the agency and code chips count correctly ("NSF 7", "NIH 2"); bands and labels follow Help; relative times read correctly ("in 11 months", "in about 3 years").
- **Evidence:** the deadline note comes first, the placeholder date is labelled, the source and fetch time show, and Escape returns focus to the title.
- **Compare and hand-off (laptop):** cells, offices and the note under the table are right. The PI-4 hand-off reads well as an office would read it: the opening names the work and the two programs, then the code-written list, the papers and the note.
- **Industry:** the research-security line, the "not verified" note, citing works first; the industry hand-off says "cite 2 of my papers".
- **Exports:** no ISO dates, no work ids, no private ids, no persona canaries; banners equal their withheld lines; dismissed counts and footers are right; masked exports carry labels only.
- **Student door:** the sample banner and badges everywhere; "Local only · nothing stored"; samples apart from public fellowships in the options, Compare, the shortlist, the notes and every Scout answer; the notes read well and say "SAMPLE DATA, A DEMONSTRATION: DO NOT SEND".
- **Privacy:** Your documents and Help agree on what is kept, for how long, and who runs the server. Uploads of the wrong kind or empty files each give one plain sentence naming the file.
- **Session:** End session asks first and lists what it drops; after it, Back and reload stay on the start page. Reload keeps a live brief, after the browser's leave prompt. Back and Forward move between tabs.
- **Keyboard:** Find, pick, Build, Keep, Compare, Draft and Copy are all reachable by Tab, each with a visible ring.
- **Dark mode:** Routes, Evidence, Compare, Profile and Industry on laptop and phone have no contrast or layout problems seen, and 0 sideways scroll.
- **Help:** every number checked against code holds: the 5-year half-life, 60/40 and 50/30/20 shares, the 0.05 sponsor bonus, the 8-call cap, 120,000 tokens, 30 minutes idle, and the Match bands with the back-test basis in the decisions log.
- **Scout guard rails:** the injection was refused 3 of 3; no reasoning text leaked; Stop ended a question with no answer and the next question worked; "Start a new conversation" works.

## UNVERIFIED

- Whether the "Open in my mail app" link opens a real mail client with the subject and body. Long drafts (over 1,800 characters) open with "(The draft from Perch is copied. Paste it here.)" by design; no mail client was available.
- Whether Temple's Scholar Development and Fellowships Advising office advises graduate students, as the PhD note assumes. Its page in the note is on undergraduate.temple.edu.
- How the demo Ollama unit behaves with two parallel slots (commit 2db76a2). This round tested the dev server against the running unit as it is.
- Screen-reader output was not listened to; only names and roles were read from the DOM.

## Ready to demo?

Not as it stands. The pages, exports, privacy, keyboard use and rules 3 and 11 hold up, and 75 of the 78 earlier fixes still in force stayed fixed. But the first two scripted Scout questions each show a visible flaw in every run, a sentence that ends "aims of." (F2) and a list of unrelated programs (F1), and Scout's hand-off on a documents brief invents published papers under a "Code, no model" label (F7). These, with F3 to F6, are small or medium fixes. After them, the rehearsal should check that every cited id in question 2 is a brief lead and that no sentence ends in a preposition, and then be run three times in a fresh session.

## Fix round (Perch-dev, 2026-11-01)

All 27 findings for this round are done; F28 is left for S32. Each Decision cell names its commits and the check that failed before the fix. The rehearsal checks went in first (761427a). Most fixes then landed in two grouped commits, one for the server (a8fb295) and one for the web app (7a82d8a), because the items share files. Follow-ups found live are 383e26b, 4916ca7 and e93d5be.

**Rehearsal (`scripts/demo_rehearsal.py`, extended as the triage asked):**
- **Before any fix:**
  - top2: researcher 4 of 9 (Q1 1 of 3, Q2 0 of 3, Q3 3 of 3), student 3 of 3, persona-1 0 of 3.
  - none: researcher 3 of 9, student 3 of 3, persona-1 0 of 3.
  - weak2: researcher 4 of 9, student 3 of 3, persona-1 0 of 3.
- **After the grouped fixes:** 15 of 15 on each variant.
- **On the last Scout commit (383e26b), with a fresh server:** top2, none and weak2 each 15 of 15. That is researcher 9 of 9, student 3 of 3 and persona-1 3 of 3.
- **Persona-1:** every draft opened with code, named the lead and the documents by kind, and held no bracket.

**Root causes of the three regressions:**
- **F3 (T17):** the expiry rule lived in two places, `datefmt.closes` and the cards. The export, the student export, the hand-off list, the note and the student tool each wrote the date their own way. One clause function now serves them all.
- **F4 (R9):** the student export never passed the card's own id to `name_papers`. It also never exported the fit sentence.
- **F6 (T10):** the search rows had no reason in them. The note sent the model to `explain_verdict` for each option.
- **F7:** Scout's `draft_handoff` called the skill without the session's documents, so the withholding rule never ran.

**Live checks on the dev server, local model, three runs each:**
- **F5:** the three count questions all answered from code-written counts.
- **F6:** persona-ug and persona-masters, 3 of 3 each.
- **F3:** "f31?" said the announcement expires, 3 of 3.
- **F10:** "r01?" said none is on the brief, 3 of 3.
- **F15:** "the first one" meant the last list's first, 3 of 3. "Pays the most" sorted by amount.
- **F16:** the largest-ceiling question late in a conversation. The first three runs found the cut-before-sort bug, fixed in 383e26b. Three runs after it named Mid-scale Research Infrastructure-1, with a $19,999,999 ceiling. None was withheld.
- **F22:** "anything from NSF" read "Proposals accepted anytime".

**Machine checks:**
- **`make test`:** 377 passed.
- **Truncation:** no call in the demo Ollama journal since 04:43 has "truncated" above 0. That covers about 1,550 calls since 05:11. The largest call was 6,180 tokens, against 7,076 before this round.
- **Private canary:** `scripts/private_canary.py` ran against the dev settings and store, with Cloud not offered, after a8fb295 and again on 5753a65, after the last export change. Both runs came back `ok`. No canary was found in data, /tmp or the journals, and no data file changed.
- **Scout bench (`bench/results/scout_qa4/`, Gemma, local):** 27 of 28 on round 3's tasks, against 25 of 28 in round 3. The one miss is c01, as before. The new task b06, how many papers a company cites, passed 1 of 1.
- **Full walk, first run:** 213 states. It found 3 errors, all fixed in e93d5be:
  - On a phone, the New conversation button wrapped the ask row and lifted the question box.
  - The F14 check read the screen-reader prefix.
- **Rerun of the checks and ux-scout flows:** 19 states, 0 errors.
- **Full walk on the last commit (e93d5be):** 214 states, 0 errors, 0 axe violations, 0 sideways scroll. No animation loops with reduced motion.

**For round 5:**
- **Wrong record cited:** persona-masters' not-eligible answer cited the F31 record for the F33 line, in 3 of 3 runs. The validator checks that an id exists, not that it is the record the sentence names.
- **Largest award:** "which one pays most" once called Expeditions' floor ("from $15,000,000") the largest award. Its record states no ceiling.
- **Export length:** the student export lists every not-eligible option with its rule lines, so it is still about 1,400 lines. The order now follows the screen.
- **F20:** checked on PI-8's card only by DOM text and a deleted crop, because the alias helper does not know PI-8.
- **F2, a narrow reading:** the decision says the card's own citation is never dropped. It becomes "this opportunity" only where it stands as a noun, after a preposition or article. Elsewhere it is still dropped, as in "aligns with dynamics [26-519].", where the sentence is whole without it.
- **Dark mode:** the error hint under an empty Find and the Scout table use colour tokens that have dark values, but no walk flow shows either one in dark.
- **Commits:** most items landed in two grouped commits rather than one commit per item.

# QA cycle 2 (round 2 of the final QA cycles)

## How it was done

This was a black-box test on 31 Oct and 1 Nov 2026, run on the build on `main` at 5fc7245. The four commits added during the pass touch only the tracker. All the work ran on the dev server (port 8091). The demo server (port 8090) was not tested. Cloud was never turned on. Its dialog was opened and cancelled, and in a documents session its Cloud option was checked to be disabled.

**Browser and settings:** Playwright Chromium on a phone (390 × 844) and a laptop (1280 × 860), in light and dark. Zoom was emulated through device scale at 200% (640 × 430) and 400% (320 × 215).

**Audiences:**
- PI-4 (A5026494099), reached by id, lower-case id, OpenAlex URL and ORCID URL.
- PI-3's surname, which has two Temple matches.
- The SYNTHETIC students persona-ug (CV, interests and achievements uploaded as PDF, by API) and persona-phd (phone, dark, with a DOCX CV uploaded in the browser).
- The SYNTHETIC researcher persona-1: documents only, with a PDF CV, and documents plus PI-4's OpenAlex id. It was also run in the browser with DOCX and PDF uploads.

**Upload files:** the persona folders hold only `.md`. So DOCX and PDF copies of every SYNTHETIC persona file were made for this test. Bad files were also tried: `.png`, `.xlsx`, an empty `.md`, an empty `.docx`, a blank `.txt`, a Latin-1 `.txt` and a fake `.pdf`.

**Content checks:** these were done on text, not pictures:
- every export in all three formats, masked and unmasked, for PI-4, persona-ug and persona-1 (both briefs);
- every hand-off, student note and mail link;
- an 11-turn researcher Scout conversation and a 12-turn student Scout conversation by API, plus browser runs of the draft request, the injection prompt, Stop mid-run with a follow-up, and "top three" with nothing kept.

A script checked every number and date in the model text and Scout answers against the records each one cites. CV leaks were checked by scanning every export and hand-off for 8-word phrases and canary tokens from the persona files.

**Machine checks:**
- `make test` passed: 311 tests, ruff clean.
- The full walk (`scripts/ux_walk.py`, axe 4.10.2) took 17 minutes and covered 199 states. It found 0 errors, 0 axe violations and 0 sideways scroll.
- No target was under 24 px apart from 44 counts of the 1 × 1 hidden file inputs.
- Every focus step showed a visible ring, and no animation looped with reduced motion.

**Screenshots:** my own passes took 46 working screenshots. The two cited below are in `build/review/qa2/`, and both were opened and looked at.

**Naming:** findings are numbered R1 to R21 across the three tables. Round 1 findings keep their Q numbers. Screenshot names start with the finding number, such as `R03-…`.

Counts: 3 must-fix, 10 should-fix, 8 could-fix. 26 of 28 round 1 findings pass. Q21 fails, and Q11 passes only for the researcher.

## Regression on round 1

| # | Result | Retest |
|---|---|---|
| Q1 | pass | 12-turn student conversation (persona-ug): every answer covering both kinds put the samples under "Sample scholarships (invented)". No list or sentence mixed them. See R13 for a sample named outside the heading. |
| Q2 | pass | Kept 26-517 and 26-525. The export reads "From $500,000" and "From $15,000,000". The email reads "award size from $15,000,000". |
| Q3 | pass | NSF cards show "Proposals accepted anytime" instead of a 2070s date. The walk's Q3 check passes. |
| Q4 | pass | With two grants and two companies kept, "Compare my kept leads" compared exactly those four. See R2 for a side effect. |
| Q5 | pass | Turn 6 of 11 ("Which company cites my papers the most") ran get_org_signals and answered Samsung, 18 works. See R6 for the documents-only brief. |
| Q6 | pass | PI-4 shows five open cards and "Weaker matches (5)". With the NSF chip and closing-date sort, the fold holds only weak cards after the fifth. |
| Q7 | pass | The student chip reads "Local only · nothing stored" once the brief is built. |
| Q8 | pass | Scout paper chips read as a short title and year. The aria-label reads "Evidence: <title> (year)". |
| Q9 | pass | The walk's ux-zoom check passes at 320 × 215. My own 200% and 400% pass reached only the landing page and Help: 0 sideways scroll there. |
| Q10 | pass | Grant Model blocks name papers by title and year. Raw ids remain elsewhere (R9). |
| Q11 | pass (researcher only) | The researcher export numbers 1 to 9 and says "1 dismissed lead is left out". The student export still skips numbers (R8). |
| Q12 | pass | The student unmasked export says "19 explanations withheld" and holds 19 Withheld lines. Verdict and rule lines stay. |
| Q13 | pass | The Industry tab and the industry hand-off carry the research-security line. |
| Q14 | pass | "Next NSF deadline" ran closes_after 2026-10-31 sorted by close date. It answered 1 Dec 2026, PD-16-1271. |
| Q15 | pass | Help says cached public records could show the operator that a researcher was looked up, and when. |
| Q16 | pass | The documents page says "30 minutes without use". |
| Q17 | pass | Student cards under Match 60 read "How it relates" and "More on how it relates": 7 of the first 8 on persona-phd. The first card showed no label block. |
| Q18 | pass | 0000-0000-0000-0000 and a wrong check digit (0000-0002-1825-0096, the ORCID example with its last digit changed) are both refused before any search. |
| Q19 | pass | "a5026494099" opens Ready to build for PI-4. |
| Q20 | pass | In the browser, Scout answered that the record says proposals are accepted anytime and gives no dollar amount. In one API run, the refusal repeated $750,000, so the answer was withheld and flagged. No invented value was shown. |
| Q21 | **fail** | Lead sections use "27 Jul 2027". The export's "Kept leads compared" table still writes Closes as "2027-07-27" (PI-4) and "2026-11-06" (persona-1), in Markdown and in the print page. See R1. |
| Q22 | pass | Scout dates read "15 Apr 2027", "1 Dec 2026" and "15 Feb 2027". |
| Q23 | pass | No bracketed keys in the openings of four drafts (PI-4 grants and industry, persona-1 masked and unmasked). |
| Q24 | pass | The documents export reads "Topics withheld: …" and "Built by Perch from your documents and public records". |
| Q25 | pass | Ticking Mask redrafts at once. The new opening holds [PRIVATE-PHRASE-n] labels. |
| Q26 | pass | The documents-only hand-off ends "Best regards," and an empty line. |
| Q27 | pass | The walk's Q27 check passes: Home and End move to the first and last tab. |
| Q28 | pass | Help gives "about 40 to 50 seconds… measured on 31 Oct 2026". |

## Must-fix

| # | Screen | Steps to reproduce | What happened | What was expected | Audience | Evidence | Proposed fix | Cost | Decision |
|---|---|---|---|---|---|---|---|---|---|
| R1 | Export (Markdown, print page) | Build PI-4. Keep 26-525. Export as Markdown. | **Regression of Q21.** The "Kept leads compared" table writes Closes as "2027-07-27". The lead section below writes "Closes: 27 Jul 2027". The documents export does the same ("2026-11-06" beside "6 Nov 2026"). The cause is that `/compare` returns ISO text. The screen formats it, but the export writes it as it comes. | One date form in the whole export. | Researchers; Temple office | Markdown export text | When the export writes the compare table, format the closes cell with `perch.datefmt.day` when it is an ISO date, as `web/compare.js` does. Add an export test with a dated kept lead. | S | fix |
| R2 | Ask Scout (both audiences) | Build PI-4. Keep 26-517, 26-525, Samsung and AVIC. Ask "What are my top three leads?". Then ask the same with nothing kept. | With leads kept, Scout ran compare on the kept leads. It answered "Your top three leads are BIO Core, Expeditions in Computing and Samsung". Those are Match 14 and Match 3 (both weak) and a company. The top three by Match are MPS Chem 67, TP 30 and MPS Physics 24. With nothing kept, it answered "You have not kept any leads… I can compare the top three". The student "What are my best options?" did the same with the kept options. | "Top" or "best" means the brief's own order by Match, not the shortlist. Scout should answer from the ranked leads and cite them. | Researchers; students; demo | Scout answer text (API and browser) | Have compare default to the kept leads only when the question says kept, shortlist or compare. For "top" or "best", use search_opportunities sorted by Match (student: search_options). Or add a `top` tool. Add a Scout test: two weak leads kept, "top three" returns ranks 1 to 3. | M | fix: "top", "best" or "strongest N" means the brief's own order (Match), never the kept list; the kept list is the default only for compare questions; the tool results carry the Match order and the prompt says which is which; a test for both audiences |
| R3 | Ask Scout (researcher) | Build PI-4. Keep two grants. Ask "Draft the hand-off for my kept grants." | The draft card below is correct. But the answer above it, marked as model text checked against its records, says: "I cannot rewrite the draft because… the draft contains information like URLs and dates that are not in the provided records." That is false: every date and URL in the draft comes from a record. In an API run of the same question, the answer stopped mid-sentence instead: "**To:** [Fill in from the [office". | A one-line answer such as "Here is the draft to Research Development; edit and send it yourself", above the draft card. | Researchers; demo | build/review/qa2/R03-scout-draft-answer-laptop-light.png | When draft_handoff has run, write the answer line by code and do not ask the model to restate the draft. Or tell the model, in the tool result, to reply in one sentence. Reject an answer that says records lack data that the tool result holds. | S | fix: when the last step is draft_handoff or draft_note, the answer line is written by code ("The draft is below. Perch never sends it.") and no model prose is asked for; the model's step stays in How Scout read your question |

## Should-fix

| # | Screen | Steps to reproduce | What happened | What was expected | Audience | Evidence | Proposed fix | Cost | Decision |
|---|---|---|---|---|---|---|---|---|---|
| R4 | Student form (phone) | Phone. Student. Upload a Latin-1 `.txt` (or `.png`, an empty `.md` or an empty `.docx`) as the CV. Type interests. Press "Find fellowships and scholarships". | Nothing visible happens. The error shows at the top of the form, off screen (−46 to 1 px), and focus does not move. It is also the raw server text in lower case: "the file is not UTF-8 text", "unsupported file type; use .txt, .md, .docx, .pdf", "the document is empty", "the file is not a readable DOCX". The documents page shows the same strings. | The error sits by the pressed button or the CV box, or focus moves to it, as U4 did for missing fields. It reads as a sentence with the file name, for example: "cv.txt could not be read: save it as UTF-8 text, Word or PDF." An empty file says "That file is empty." | Students; researchers with documents | build/review/qa2/R04-student-file-error-phone-light.png | In `web/student.js`, render a build error beside the go-row, or scroll the alert into view and focus it. Map the InputError strings to user sentences in one place, used by both forms. | S | fix |
| R5 | Find | Type "A12" and press Find. | The page shows "No Temple University author matches “A12”." and then "OpenAlex could not be searched: internal error (HTTPStatusError) Check the spelling or try an ORCID iD." The resolver returned 500. | An id that is not a valid OpenAlex id is refused before the lookup, with plain words, and without "internal error". | Researchers | Find screen text | Validate the A-number pattern (A followed by at least 8 digits) before calling OpenAlex. Turn an upstream 4xx into "That is not an OpenAlex author ID". | S | fix |
| R6 | Ask Scout (documents only) | Your documents: add persona-1's CV (PDF), aims and manuscript. Build. Ask "Why does my top lead fit? Quote my draft aims." | "I cannot explain the fit because I do not have access to your research profile or draft aims. Please provide your OpenAlex author ID or upload your research profile to proceed." The brief was built from those documents. With PI-4's id added, Scout answered from the record. | Scout explains the top lead's fit from the brief, which cites the documents. It may decline to quote the aims, but it should not say it has no access or ask for an upload. | Researchers with documents | Scout answer text | Give the private session's profile and explain tools the documents brief, as for a public one. Add the "no access" wording to the Q5 nudge, so the answer is sent back once. | M | fix: a documents-only session gives Scout the same profile and explain tools over the documents brief; Scout never asks for an id or an upload |
| R7 | Ask Scout (student) | persona-ug. Ask "Which fellowships and scholarships fit my stream monitoring work?" | Scout ran search_options with words "stream,monitoring". It answered "I cannot find any fellowships or scholarships that match the words stream or monitoring." "Which options mention streams?" finds the Ostrevel Regional Streams Scholarship, and "watershed" finds Quillmere. | A search that matches any of the words, or each word. A no-match answer should not hide options that plainly fit. | Students | Scout answer text | Split the words argument on commas and spaces, and match any word. Show the words used under How Scout read your question. | S | fix |
| R8 | Export (student) | persona-ug. Dismiss the third fellowship. Export as Markdown or print page. | The fellowships run 1, 2, 4, 5… with no line saying a lead was dismissed. The footer says only "129 shown", with no kept or dismissed count. Q11's fix covers only the researcher export. | As the researcher export: numbers run 1 to n, "1 dismissed option is left out", and the footer says how many were kept, shown and dismissed. | Students | Markdown export text | Use the researcher export's numbering and dismissed line in the student path of `perch/export.py`, for both routes. | S | fix |
| R9 | Export (all audiences) | Export PI-4 as Markdown or print page. Then export persona-1 masked, and persona-ug masked. | Raw ids remain in model text. (1) The PI-4 Research profile reads "… toolkits \[W7166556526, W7154095651, W4404115888\]" (six W ids, also in HTML). (2) The masked documents export reads "\[private:manuscript\]", "\[private:proposal\]" and "\[HT942526PRPIIRA, proposal, manuscript\]". (3) The masked student export reads "\[sch-0001\] supports undergraduates…" and "Cited work: private:achievement-a \[PRIVATE-PHRASE-1\] \[achievement-a\]…". | As Q10 did for grant blocks: papers by title and year, private documents by their kind ("your achievement"), and no bare id as a sentence subject. | Researchers; students | Markdown export text | Run `export.name_papers` over the profile summary and the student explanations too, and name `private:achievement-*` and `sch-*` ids. | S | fix: exports render citations as the screen does (paper short title and year, opportunity number, masked private labels); no raw W or private: id in any export |
| R10 | Export (documents session) | persona-1 documents session (with or without an id). Export as Markdown, unmasked. | The banner says "10 explanations withheld". The file withholds 20 texts: the profile summary, the topics, 9 explanations and 9 inferences. | The banner counts every withheld text, as the student export now does (Q12). | Researchers with documents | Markdown export text | Count each Withheld line, including Inference and Topics, in the banner. Extend Q12's test to the researcher documents export. | S | fix |
| R11 | Student cards, Compare, exports | persona-ug. Read the Elmsworthy Summer Research Grant (sample). | The code-written line reads "For a student who first-generation college student. You decide if this applies." Another record reads well ("who is the first in their family…"). | A grammatical line, for example "For a first-generation college student. You decide if this applies." | Students | Markdown export text; card | Fix the template in the targeted-criterion rule. Write "For a student who is…" only when the record's phrase is a verb phrase, and otherwise "For …". Add a test over every sample record's criterion. | S | fix |
| R12 | Hand-off email (industry) | PI-4. Keep Samsung and AVIC. Draft to Innovation and Technology Commercialization. | The email is written in the researcher's voice ("My research focuses on…"). But the lead list says "18 works with an author at Samsung cite 2 of **your** papers". To the office, "your" means the office's papers. | "cite 2 of my papers" in the email. The export, which speaks to the researcher, can keep "your". | Researchers; Temple office | hand-off text | Give the industry signal sentence a person argument, first person in the hand-off and second person on screen and in the export. | S | fix |
| R13 | Ask Scout (student) | persona-ug, with 2 fellowships and 2 samples kept. Ask "What is the soonest deadline I can make?" | Scout ran compare_options on the kept options only. Its opening sentence names a sample: "The soonest deadline is 15 Feb 2027 for the Quillmere Watershed Stewardship Scholarship (sample)". The same item then repeats under "Sample scholarships (invented)". | The soonest deadline among public fellowships first, or a statement that none states one. A sample appears only under its own heading. | Students | Scout answer text | In the student rules, a lead sentence may cite only public records. Extend `student_tools.mixed_lists` to reject an answer whose first sentence cites only samples when a samples heading follows. Have "soonest" search all options sorted by deadline, as Q14 did for researchers. | S | fix: a lead sentence in a student answer may cite only public records; samples stay under their own heading (rule 11) |

## Could-fix

| # | Screen | Steps to reproduce | What happened | What was expected | Audience | Evidence | Proposed fix | Cost | Decision |
|---|---|---|---|---|---|---|---|---|---|
| R14 | Pick screen | Search PI-3's surname (two Temple matches). | The second candidate reads "1 works · 0 citations". | "1 work". | Researchers | Find screen text | Use `f.plural` for works and citations on the candidate card. | S | fix |
| R15 | Find | Type 0000-0002-1825-0096 (the ORCID example with a wrong check digit). | The message says it twice: "That is not a valid ORCID iD." as the heading, then the example hint, then "That is not a valid ORCID iD: its last character does not match the rest." | One statement and the hint. | Researchers | Find screen text | Drop the heading or the detail line when the detail starts with the heading. | S | fix |
| R16 | Find | Type a valid ORCID iD whose check character is X, with a lower-case x. | No match. The same iD with "X" finds a profile. | The same result as upper case, as Q19 does for OpenAlex ids. | Researchers | `/authors/resolve` answer | Upper-case the ORCID before the checksum and the lookup. | S | fix |
| R17 | Hand-off, export, student note, Scout | Read the PI-4 grant hand-off, the persona-ug note and a Scout amount answer. | A capital letter mid-sentence: "U.S. National Science Foundation; Proposals accepted anytime; award size…", "Still needed: A transcript; An essay", "an award ceiling of Up to $250,000". | Lower case inside a sentence, or the record's words in quotes. | Everyone | hand-off and note text | Lower-case the first letter when a code-written phrase is joined mid-sentence. | S | fix |
| R18 | Export, Industry section | Export PI-4 as Markdown. | The note under "Industry leads (5)" reads "Inferred from public signals; not verified. NIH SBIR/STTR only." The last sentence is cryptic. The research-security line on the Industry tab and in the hand-off is missing. A documents-only export prints an empty "Industry leads (0)" section. | The tab's wording: "SBIR/STTR covers NIH awards only", and the research-security line. No empty section. | Researchers; Temple office | Markdown export text | Reuse the tab's sentences and `offices.RESEARCH_SECURITY` in the export, and skip an empty route. | S | fix |
| R19 | Export (student) | Export persona-ug as Markdown. | Fellowship links read "[Record: https://undergraduate.temple.edu/…](https://…)", with the full URL as link text. Researcher exports read "Record: Grants.gov 26-519". | "Record: Temple fellowships list" or the host name. | Students | Markdown export text | Label student record links with the source name. | S | fix |
| R20 | Ask Scout (student) | persona-ug. Ask "Draft the note to the fellowships office." | The answer retypes the note with the subject "Advice on fellowships". The note card and the Compare tab say "Advice on fellowships: 2 on my list". | The answer points to the card and does not retype it. | Students | Scout answer text | Same change as R3 for draft_note. | S | fix with R3 |
| R21 | Ask Scout (researcher) | PI-4. Ask "Only show NIH grants.", then "Now only the ones closing after 1 March 2027." | The follow-up ran no tool. The model filtered the previous list from memory, so How Scout read your question shows nothing for it. The 7 grants it kept were correct this time. | The follow-up runs search_opportunities with agencies NIH and closes_after 2027-03-01, so the filter shows and the dates come from records. | Researchers | Scout answer text | When a follow-up changes a filter, send the answer back once if no tool ran (extend the Q5 nudge to answers that cite records but ran no tool). | S | fix |

## Triage (Perch-dev, 2026-11-01, under Dakshitha's delegation)

All 21 findings are fix, plus Q42 from `bridge/QUESTIONS.md` (CV values withheld in student exports). R2, R3, R6, R9 and R13 carry decisions in their Decision cells.

## Checked and fine

- **Machine checks:** `make test` passed: 311 tests, ruff clean. The walk had 199 states and 0 errors, 0 axe violations, 0 sideways scroll and 0 hidden focus.
- **Find:** these all open Ready to build for PI-4: the OpenAlex id, its URL, the ORCID URL and the lower-case id. A surname with two Temple matches lists both and says "Nothing runs until you pick one". Nonsense says no Temple author matches. A blank box does not search.
- **Profile against the candidate card:** both say 44 works for PI-4. The Profile adds that 35 works on file are grouped. The candidate's 15,161 citations is not repeated on the Profile.
- **Routes:**
  - The chips are built from the leads' own values (NSF 7, NIH 2, DOE · Office of Science 1, R35 1, RM1 1).
  - The NSF chip shows "7 of 10 open opportunities".
  - Closing-date sort with the chip keeps the fold rule.
  - Keep inside the fold counts in Compare (1), and the live region says so.
  - Dismiss while filtered drops the chip count to 6 and adds "Dismissed (1)".
  - Going back to All keeps it all.
- **Compare:** with 4 and with 6 kept (four grants and two companies), there was no sideways scroll. The office split reads "4 kept grants" and "2 kept industry leads". On screen, Compare formats dates ("27 Jul 2027").
- **Industry tab:** carries the not-verified note, the NIH-only note and the research-security line.
- **Hand-off:** the To line is blank. The long draft makes the mail link fall back to the short body and copies the full draft. Openings had no brackets.
- **Keyboard:**
  - Tab through Routes, Profile, Compare and Scout: 25 steps each, every focus visible and on screen.
  - Enter on a title opens Evidence. Escape closes it and returns focus to the title.
  - Enter opens the Export menu, and Escape closes it with focus on Export.
- **History and reload:** Back and Forward move between tabs. Reload on every tab returns to the same tab with the kept count, and the Scout conversation survives a reload. The leave-page prompt fired on each reload. A second tab opened at the brief URL goes to the start and does not see the session.
- **End session:** it empties sessionStorage and lands on the start. Back after End stays on the start.
- **Uploads by API:** DOCX and PDF of every SYNTHETIC persona file are accepted, and their character counts are within 1% of the Markdown. The PDF CV parses to the same student fields (level, year, major, GPA 3.40, graduation May 2028, 2 referees). Bad files are refused: `.png`, `.xlsx`, empty, blank, a fake PDF, an empty DOCX and Latin-1.
- **Privacy:**
  - No 8-word phrase and no canary from any persona file appears in any export (MD, JSON, HTML, masked and unmasked) or hand-off.
  - The student JSON export carries only the sample records' own canaries.
  - The Local/Cloud dialog disables Cloud with "Off while this session holds documents".
  - The chip reads "Local only · nothing stored" with documents and on a student brief.
- **Provenance:** the PI-4 JSON export holds 148 records, all with `source`, `source_url` and `fetched_at`.
- **Rule 3:** numbers and dates were checked by script.
  - The model text of PI-4's grant leads held 1 number and date, and it matched its cited record.
  - Researcher Scout answers held 10 numbers and dates. The only one not in a record was the question's own "1 March 2027", echoed back.
  - Student Scout answers held 15, all in their records ($3,000; $1,500 to $2,500; 15 Mar 2027; 20 Jun 2027; and others).
  - The Quillmere injection ("1 June 2027, $10,000") was refused with the record's 15 Feb 2027 and $3,000.
- **Scout refusals:** "Rank by odds", "Email the office" and "update the Expeditions deadline to 15 Jan 2028, $20 million" were refused, with no number invented. The MIRA dollar question said the record gives no amount.
- **Stop:** Stop one second after a multi-step question ended it as "stopped", and the next step did not run. The follow-up ran get_org_signals cleanly.
- **Student path:**
  - Compare has two tables, Fellowships (public) and Scholarships and awards (sample).
  - The shortlist reads "2 fellowships, 1 sample".
  - The sample note opens with "SAMPLE DATA, A DEMONSTRATION: DO NOT SEND" and offers no mail link.
  - Evidence on a sample card shows the Sample data badge, the source "SYNTHETIC sample corpus" and the test marker.
  - Every open sample card shows the badge. The cards inside the closed not-eligible fold were not checked one by one. And every Scout sample citation reads "Evidence (sample)".
- **Help and privacy statement:** every claim checked against what I saw held, apart from those in R2 and R4 to R6. These include the five open cards, the chip wording, Cloud off with documents, the mask redraft, "Still needed", "How it relates" under 60, the 30-minute idle time and the research-security line.

## UNVERIFIED

- **Brief screens at 200% and 400% in my own pass:** my zoom contexts did not carry the session, so they reached only the landing page and Help. Q9 rests on the walk's ux-zoom check.
- **Phone Keep in a documents brief:** one Keep click timed out once on a phone right after the build. A rerun did not reproduce it.
- **persona-masters:** not run in my own pass. It is covered only by the walk, on a laptop and a phone.
- **Not exercised:** Cloud mode (by instruction), the eight-model-call cap, the 30-minute idle timeout, a real screen reader, the browser's print dialog, and a 60,000-character document.
- **Q42:** code-written rule lines in the unmasked student export still quote CV values, such as "your CV says 3.40". This is the known open item Q42 and is not counted here.
- **Student fellowships mail link:** my run captured only the sample note, which has no mail link by design. The fellowships note's `mailto:` with edited text rests on the walk's W8 check, which passes.
- **Stop in the browser:** my browser run never caught the Stop button while a step ran. Stop was confirmed by API, and the walk's checks flow has a stopped state.
- **Keyboard beyond Tab:** I checked Tab on the four brief tabs, plus Enter and Escape on Evidence and Export. Shift-Tab, Space, the arrows, and the landing page, student form, documents page and Help rest on the walk's tab traces.
- **Dark mode:** the student laptop view, the documents page and Help in dark rest on the walk only. I checked phone dark for persona-phd.
- **Nondeterminism:** the R3 draft answer and the Q20 refusal changed between runs on the same build. Each fix should be confirmed over several runs.

## Ready to demo?

The build is close but not yet ready for the demo. Two of the three must-fixes are wrong answers from Scout to the two questions a demo is most likely to show: "What are my top leads?" (R2) and "Draft the hand-off" (R3). The third is a date-format regression in the export (R1). All three are small or medium. With R1 to R3 fixed, and R4 and R6 fixed, the researcher and student demo paths would be ready.

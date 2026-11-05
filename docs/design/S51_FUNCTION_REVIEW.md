# S51: back-end function review, round 3 (2026-11-05)

A fresh-context review of the model text and the code behind it. It reads the live captures in build/s50_live and build/s50_live_before, the round-3 notes in docs/design/S50_ORCHESTRATOR_NOTES.md, the skills, the validator, the grounder and the Scout bench. It made no paid calls and edited nothing but this file. MiniCheck and the Scout replay ran on CPU through scripts/run_limited.sh. All SQL against the deploy store was read-only.

## First: the second capture is mostly stale

- **Same brief:** both captures show brief 3c19f096, created at 06:08Z (01:08 EST). The same-day idempotency key (perch/user/briefs.py:641) returned the existing brief, and its timings show it was served from precache in 20 ms.
- **Same cover set:** both captures show cover job c326e5e0, created at 06:09Z. `cover_submit` (perch/scout/web.py:290) returns the existing job when `again` is not set.
- **What that means:** the researcher cards, the Temple internal group and the cover points come from code older than commit dd86194 (3c role check) and f4fa993 (G5 Temple pages), both at 01:54 EST. Only Scout, the hand-off and the student brief were made fresh.
- **Effect on the notes:** the K01 page and the CIBER page dated 2022 should now be left out by G5 (perch/eligibility.py:241 and the 396-day rule). The same papers on most cards should now vary because of 3b. Neither change has been seen live yet.

## Must-fix

- **H1. Cover points are unsupported because each one makes a compound claim, not because ids do not match.**
  - **The id idea is wrong:** the grounder gets the paper text. The model cites short ids (`W7166685335`), and `build_prompt` keys the records the same way. The full `https://openalex.org/W…` form appears only in storage, where perch/scout/job.py:255 maps the ids back after grounding. All three papers have abstracts in the store (1,123 to 14,167 characters).
  - **The real cause, part 1:** four of the five `you` sentences join facts from two or three papers. `ground` (perch/skills/cover.py:383) joins the papers into one document. MiniCheck then scores the claim against its best single 400-token chunk, so no chunk can support both halves.
  - **The real cause, part 2:** the sentences end with a judgment, such as "which are mechanistic findings about how these cancers behave" or "which links target biology to drug development". MiniCheck scores those as unsupported by design. The fit skill solved this by splitting off a link sentence.
  - **The real cause, part 3:** `as_record_claim` (cover.py:255–262) makes broken subjects: "The paper have work spanning …" and "The paper contribute …". Its regex also misses "Your paper", which becomes "its paper reports …".
  - **Measured:** scored with today's code (`as_record_claim` and `ground`), the five stored points got 0.042, 0.049, 0.010, 0.330 and 0.450. Split into one paper and one fact each, the same content scored 0.972, 0.985 and 0.949.
  - **Fix (layer 1, by code):** a `you` sentence that cites papers cites exactly one; check this in `validate` next to cover.py:361. The prompt asks for "Your paper reports …" with no "which …" tail. Optionally, add a `link` field that is shown as an inference and not grounded, as fit does. Make `YOU_SUBJECT` also match `your papers?` and turn it into "The paper".
  - **Measure:** run the stored five again in split form, which is already done above. Then do one paid re-run of cover points with `again=true` on PAR-25-444, at about $0.015 by the ledger. Target: at least 4 of 5 `you` sentences supported.
  - **Effort:** 1 to 2 hours, including tests.

- **H2. Capture again, so S50's fixes are actually exercised.**
  - **Brief:** change the idempotency key, for example with an option such as `top: 11`. The Temple internal group is computed live even when the brief comes from precache (perch/service.py:456), so G5 shows up straight away.
  - **Federal leads:** the federal eligibility split is stored in the precache. Its key has no rules version (H8), so a same-day re-capture still shows the 01:08 federal split. Land H8 first, or capture after the next nightly precache.
  - **Cover:** post with `again=true`.
  - **Check:** the K01 page and the 2022 CIBER page are gone, the top 10 cards cite more than one set of papers, and the cover role check (3c) fires.
  - **Fix:** scripts/live_capture.py:91 and :109.
  - **Effort:** 15 minutes, and about $0.10.

- **H3. The guest's sample student brief runs out of budget before every card is explained.**
  - **Seen twice:** the first capture explained 7 of 20 eligible leads. The second explained 13 of 20. Both show the stage `student_explanations: skipped, withheld: the daily model budget is used`.
  - **Cause:** each fit call reserves $0.015 (perch/user/spend.py:38), and up to 4 calls run at once. In the ledger, a fit call costs $0.0072 on average. The p95 is $0.0129 and the maximum is $0.0171. The student calls in that minute averaged $0.0041. The guest day is $0.10 (perch/redisx.py:218). By reservation arithmetic, the cap is reached at about $0.06 of real spend.
  - **Fix:** lower the fit estimate to $0.013, the ledger's p95. H4 and H10 also cut calls and tokens.
  - **Alternative fix:** raise `PERCH_GUEST_DAILY_BUDGET_USD` in .env.deploy to $0.20. The $3.00 global guest cap still holds.
  - **Measure:** one guest sample brief shows "20 explained, 0 withheld".
  - **Effort:** 15 minutes.

- **H4. Name-only student listings: skip the model and write a code line.**
  - **Data:** 43 of 284 `temple_pages` scholarships have no purpose, no notes and no field of study, so `record_text` is just the name. In the capture, 4 of the 9 explained Temple listings say "The record names … and gives no further detail", and MiniCheck flags every one of those sentences.
  - **Fix:** in `_run_student_explanations` (perch/service.py:706), leave out of `explain_leads` any lead whose scholarship has an empty purpose, empty `eligibility.notes` and an empty `field_of_study`.
  - **Code line for those leads:** "This listing gives only the award's name. Read its page for what it funds." Set the inference to None. The card already links the page.
  - **Measure:** the student capture has no "gives no further detail" and makes fewer fit calls.
  - **Effort:** 1 hour.

- **H5. The validator ignores nested record fields.**
  - **The problem:** `evidence()` (perch/validate.py:101–118) handles strings, numbers, dates and lists of strings. It does not handle a nested model, which `model_dump` turns into a dict, or a list of ints.
  - **What gets lost:** `Scholarship.eligibility.gpa_min`, `class_year`, `graduation_by`, `notes`, `citizenship` and `residency_state` never become allowed numbers, dates or text.
  - **Reproduced:** "It asks for a GPA of 3.50" against a record with `gpa_min=3.5` fails with "number '3.5' is not in any cited record". The cover skill works around this only by pasting the verdict lines into the description (cover.py `with_context`).
  - **Seen in the replay:** among Scout's 23 `layer1_number` removals, i14 lost "The record lists class years 1, 2 and 3" three times. It is a true fact.
  - **Fix:** walk dict values recursively, and add the ints and floats in lists to the allowed numbers. It is rule-3 safe because every value comes from a record field.
  - **Measure:** a unit test with a GPA and a class year. Then the s49b replay's `layer1_number` should drop below 23.
  - **Effort:** 30 minutes.

- **H6. Merged duplicate student awards lose an amount.**
  - **The problem:** `student_pool` (perch/student.py:631) keeps one copy through `_keep` (:622) and drops the others' fields. `temple_dedupe.merge` already carries an amount over at build time, but the runtime merge does not.
  - **Measured on the deploy store:** 4 of 17 merged groups show no amount, but a dropped copy has one: Creative Arts, Research and Scholarship (3000), Diamond Peer Teachers (2250), Diamond Research Scholars (4000) and NSF GRFP (37000). No group loses a deadline.
  - **Fix:** after `_keep`, if the kept copy has no amount and the other copies agree on one, copy `amount_min`, `amount_max` and `amount_quote`. Set `details_url` to that copy's `source_url` if it is empty. This was decided in S50.
  - **Measure:** run the same count script again; the target is 0 lost.
  - **Effort:** 45 minutes.

- **H7. Centre, programme and partnership grants fill the researcher's top 10. This is a design fork for Dakshitha.**
  - **What the capture shows:** P30 is rank 1, P01 is rank 3, P50 is rank 7 and U54 is rank 8. That is 4 of the top 10. No code looks at these activity codes: `EXCLUDED_ACTIVITY` (perch/eligibility.py:41) covers only F, K99/R00, R36 and SBIR/STTR.
  - **The fit text knows:** the P30 card itself says "the grant funds the center's infrastructure rather than individual projects". Scout then calls it "Rank 1, strong match", and the hand-off asks Research Development about it.
  - **Back-test check:** the 126 back-test rows hold 60 distinct announcements. Only 10 of them are in the deploy store: R01 7, R21 1, R37 1 and U01 1. None of those is P30, P50, P01 or U54. The other 50 were not checked. Check them in `perch_backtest` before claiming no effect, as rule 9 requires.
  - **Option A (recommended):** move P30, P50, U54 and similar codes into a new hidden-fold group, "centre and programme grants", the same way `career_stage` works. It is code-only, and the user can still open it.
  - **Option B:** keep the rank and add a code-written card line.
  - **Rule note:** `score.py` promises that Match order is rank order, so demoting a lead in place would break that promise. For any line text, copy the activity-code names from NIH's public activity-codes page with its URL (rules 2 and 10). Do not write them from memory.
  - **Measure:** count institutional codes in the top 10 of the PI-1 brief, and run the back-test again (95 s on GPU 3).
  - **Effort:** 2 hours.

## Should-fix

- **H8. The precache key has no rules version.** `precache_key` (perch/precache.py:64) hashes the profile and the ingest epoch only. The precache stores the federal eligibility split (precache.py:120), so a deploy that changes federal rules, such as G3 notices, serves the old split until the next nightly run. This is H2's prerequisite for checking federal leads.
  - **Fix:** add a `RULES_VERSION` constant in eligibility.py and include it in the key.
  - **Measure:** after a version bump, a test brief recomputes instead of hitting the cache.
  - **Effort:** 20 minutes.

- **H9. Student labels read badly.** The capture has "Your achievement A presented a poster …", and "Your interests described your interest in …" appears in 9 of 9 cards.
  - **Where they come from:** the titles are set at perch/student.py:551 and perch/user/inputs.py:31, and `Fit.part` puts them in front of the clause.
  - **Fix:** use "Your entry" when there is only one entry. Otherwise use "Your entry on ‘<first five words>…’", taken from the user's own text after `blank_contacts`. Use "Your interests note" for the interests note.
  - **Measure:** grep the next capture for "achievement A" and "interests described your interest".
  - **Effort:** 30 minutes.

- **H10. Every student card repeats the same two cited sentences.** The persona has 3 achievements, but every card cites `achievement-a` and `interests`.
  - **Cause:** `CHOSEN_PAPERS["student"] = 2` (perch/skills/fit.py:96), and the tf-idf choice picks the same pair each time.
  - **Fix:** set it to 1, so each card names its single closest record. This also cuts output tokens, which helps H3.
  - **Measure:** count distinct cited-work lines across the student cards.
  - **Effort:** 10 minutes, plus updating the tests.

- **H11. "Nothing there rules them out" has no one for "them" to refer to.** It appears on the guest's sample cards.
  - **Fix:** change the substitution at perch/student.py:707 to "rules the sample student out".
  - **Effort:** 10 minutes.

- **H12. The cover wording assumes a CV.** `COVER_NOTE` (perch/scout/web.py:327) says "one thing from your CV or entries", but PI-1's points come from papers. The missing items also say "nothing you added shows it", which is odd when the user added nothing.
  - **Fix:** use "your CV, entries or papers" and "nothing in your records shows it". `ABOUT_YOU` accepts "your", so the check still works.
  - **Effort:** 20 minutes.

- **H13. Scout removes harmless headings.** Replaying s49b with today's rules removed 20 headings as `heading_not_structural`. Examples: "Which closes soonest:", "NIH records with no stated ceiling:", "Comparison of your top two leads:", "Top two leads, side by side:" and "Main themes of your work:".
  - **Why it matters:** each removal flags the whole answer. Q1 in the capture is flagged for one heading.
  - **Fix:** add the comparison, side-by-side and soonest forms to `STRUCTURAL_HEADINGS` (perch/scout/answer.py:117). Or have the system prompt name the allowed headings.
  - **Measure:** the replay's `heading_not_structural` count.
  - **Effort:** 30 minutes.

- **H14. Same papers on most researcher cards: not yet measured.** The 3b paper choice is in the code (fit.py:99, `choose_papers`), but the capture predates it.
  - **Measure after H2:** count distinct cited-paper sets across the top 10. In the stale capture, 7 of 10 cards cite exactly {W7166685335, W7138257158, W4415441733}.
  - **Effort:** included in H2.

- **H15. Scout bench: one free step before release.**
  - **Today's replay:** I ran `bench.scout_replay` on bench/results/scout_open_s49b with no model and no grounder. Results: 55 drafts, of which 11 now grade differently from what was stored. In scope, 19 of 33 answers are clean by the second draft. Removals: `no_citation` 31, `layer1_number` 23, `heading_not_structural` 20, `absent_not_template` 8, `placeholder_only` 3, `question_not_offer` 2 and `uncited_fit_word` 1.
  - **The free step:** run the replay again with `--grounder minicheck` through run_limited, after H5 and H13. That gives a real layer-2 number; the replay above shows 0 only because it had no grounder.
  - **Not worth it before release:** a new paid bench run, which costs about $0.90 (s49b spent $0.88). The `usefulness` column in grades.csv is empty for all 126 rows, so no human grade exists yet.
  - **Effort:** 20 minutes of CPU.

## Leave for later

- **H16. MiniCheck flags some correct student opportunity sentences.** Examples are Boren, Ostrevel and Global Green. The cause is that `record_text` joins lists with ". ", so a claim that combines a field and a level matches no single sentence. It is cosmetic, because the sentence is shown with a flag.
- **H17. Scout's `absent_not_template` removes honest absence lines.** There were 8 in the replay, such as "Neither record gives a deadline …". Loosening this is risky, because a claim that something is absent can be false. Keep the removal.
- **H18. Industry lead titles were checked, and the problem did not reproduce.** The capture prints `record_id`, but each lead carries `organisation.name`. The export (perch/export.py:347) and the hand-off (perch/skills/handoff.py:120) fall back to the URL only when the organisation record is missing.
- **H19. Same-day brief and cover reuse after a deploy.** A user who asks again on the same day gets output from the old code. This is acceptable product behaviour. Only the capture needs a way around it (H2).
- **H20. The P01 deadline wording.** Scout says the P01 "has no deadline in its record, and its announcement expires 25 May 2029", while the capture's close field shows 2029-05-25. Check that the card uses the same words, an expiry rather than a deadline, after H2.

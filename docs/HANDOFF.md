# HANDOFF.md — state for the next context window

Written at the close of S27 (2026-10-31). Dakshitha asked for S28 to start in the same context, so read S28's task file `docs/sessions/S28.md` for how far it got.

## Last run: S27, funding coverage and ranking tune, run live

- **Coverage:** the dev and demo stores hold 1,497 open or forecast Grants.gov listings from every agency, not only NIH and AHRQ (was 679). The parser reads the agency from `agencyDetails`, and an "Others" applicant type counts when the eligibility text names institutions of higher education.
- **Ranking:** thread queries carry topic names and 100 leads are reranked. NIH back-test, 48 awards with the date cut-off: hit@5 0.104 to 0.188, hit@10 0.146 to 0.208, MRR 0.067 to 0.149. Keyword-only: 0.021, 0.021, 0.027. Rounds are in `bench/results/RESULTS.md`; harness `bench/tune.py`.
- **One score:** cards show Match, the ranking score on a 0-100 scale (`bench/calibrate.py`). Sort is Score or Closing date on both researcher and student briefs.
- **Test PIs:** PI-1, PI-130 and PI-132, with second checks PI-7, PI-131 and PI-133. None of them shaped the tuning; only the NIH back-test did.
- **UI fixes from Dakshitha's review (tasks 8 to 20):**
  - **Evidence:** the card floats over the page as a drawer and crossfades between records. It closes on a click outside it.
  - **Scout:** Scout fills the window as a single-column chat with the question box on the bottom edge, from the first view on. Its welcome message lists its tools, example questions and its limits. No approval card shows. The chat has no scroll bar.
  - **Page scroll bar:** it shows only near the pointer.
  - **Student cards:** they say why an option may fit. "What this is based on" starts open.
  - **Researcher cards:** "Why it fits" starts open when a CV or current research is given.
  - **Timeouts:** an expired session goes back to the start and says why.
- **Plan:** new S29 to S32, a workflow review and a fresh UI/UX review, each diagnosed then fixed. Freeze and package is now S33.

## Checks at close

- `make test`: 262 passed.
- **Walk:** the last full run had 141 states, 0 errors, 0 axe violations and 0 sideways scroll. The later checks, student and private groups, gave 65 states with 0 errors on the public URL.
- **Walk checks added in S27:** panel shift, Evidence blanking, approval UI, box position on first open and after questions, side box, outside click, scroll bars, reasons open. Each failed on the build before its fix.
- **Demo:** rebuilt and live on the public URL.

## Next: S28, Scout redesign phase 1

Already done in S27, on the web side: no mode switch, no Approve or Skip buttons, no waiting card. The rest is in PLAN.md S28: the server's ask mode and APIs, Stop, Scout fixed to the brief, Cloud steps counted and labelled, the "how Scout read it" block, the words, and the retest with the Scout bench.

## Known gaps

- **Flaky test:** `tests/test_scout.py::test_route_b_answer_counts_and_dates_pass_the_validator` failed once in a full run and passed five times after. Not investigated.
- **Scout search quality:** an R21 question for PI-4, who works on molecular dynamics, returned cancer R21 grants.
- **Canvas:** the Scout tab on the redesign canvas still shows the old chat layout with a side box.
- **Media:** the README clips and screenshots predate the S27 UI changes (Q41).
- **Student Scout is wordy with tools:** on Gemma it checked options one by one before using `compare_options`.
- **Student retrieval:** 2 of 12 planted positives never reached a brief.

## Open questions (mirror of bridge/QUESTIONS.md)

- **Q41:** refilm the media at the start of S33? Default: yes, once, before the freeze.
- **Q36:** Google Fonts reach a third party; keep them? Default: keep.
- **Q35:** per-visitor caps by IP on Demo Day wifi. Default: keep.
- **Q34:** build the draft review anyway? Default: no.
- **Q33:** apply the rule 1 change, then set `PERCH_CLOUD_DOCUMENTS=1` on the demo.
- **Q29:** kept open by Dakshitha.

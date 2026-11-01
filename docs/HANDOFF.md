# HANDOFF.md — state for the next context window

Written at the close of S32 (2026-11-01). S29 to S32 ran in one orchestrating context with subagents, under Dakshitha's delegation of every product and design decision (2026-10-31, DECISIONS.md).

## Where things stand

- **The build is ready to freeze.** `main` holds every review fix and five QA rounds. 408 tests green. Full walk with axe 217 states, 0 errors, 0 axe violations, 0 sideways scroll on the dev server. On the public demo after the last rebuild (the Q33 build): pi, checks and workflow groups 98 states, 0 errors, 0 axe, 0 sideways scroll; private, student and ux groups 125 states, 0 errors, 0 axe, the consent dialog included. An earlier full live walk on the pre-Q33 build had 219 states and 2 axe target-size hits from one card title scrolled under the sticky bar on the phone. An earlier live walk on 52e75b0 had one error: a two-part Scout question's NSF half withheld by the citation check, the designed fallback. Canary clean. `make package` builds the submission ZIP from the closing commit (about 34 MB, tracked files only plus SUBMISSION.md) into `dist/`; the tests passed inside an unzipped copy at 2d1ed4b and the app served from a clean unzip at 9698b07. S33 rebuilds it once more.
- **The demo is live on the rebuilt build** (container rebuilt from the final `main`, eeb7d3b, on 2026-11-01; the model units were restarted once earlier that day with the new settings). The chat model runs with a 12,288-token context and two slots; GPU 6 sits flat at about 27,490 MiB. Demo Day caps are set in the compose file (100 briefs, 200 sessions, 300 hand-offs and Scout questions an hour per address). The three warm briefs take about 4 min 39 s to build after a restart, so restart the demo well before the slot.
- **The demo script passes every run.** `scripts/demo_rehearsal.py` runs the three researcher questions, the student question and the documents hand-off in fresh sessions, three times each, on three kept-leads variants: 45 of 45 on the demo, and 15 of 15 on the final build after the Q33 rebuild. Questions take 5 to 6 s on a quiet server.
- **What the presenter should know** (from the round 5 report, `docs/design/qa/CYCLE_5.md`, "Fix round"): the demo researchers' briefs open at once because they were built at server start, and the card says so; a live brief takes about 40 s, longer behind another build; Scout's session budget allows about 12 to 14 questions, then "Start a new conversation"; persona-1's top lead closes on 6 Nov, so check that brief on the morning; Cloud stays off unless a visitor chooses it (documents then need the second confirmation); show the researcher export rather than the student one; avoid asking Scout "how many of my options are samples".

## What S29 to S32 did

- **S29, reviews (two Opus reviewers in parallel, fresh context):** workflow, code and security (43 findings: 18 redundancy, 18 security with 3 high, 7 speed) and UI/UX (43 findings: 2 must, 26 should, 15 could). 84 marked fix, 2 deferred (keyboard shortcuts; a second brief worker). Baseline paths measured by `scripts/path_measure.py`.
- **S30, fixes (four fixers in sequence):** security and speed, then workflow, then UX must and should, then UX could. Highlights: DOCX inflation capped, pypdf 6.21.4 and pip-audit clean, private-derived text filtered from exports, CSP, self-hosted fonts, Scout and document rate limits, IPv6 /64 keys, gzip and 304 polls, stage reorder (live brief 46.6 to 41.9 s), rerank cache for public threads, phone Export fixed, one rule for every close date, Scout answers tagged as model text, weak matches folded, filter chips, company parents merged by OpenAlex lineage, the session id in sessionStorage so a reload resumes the brief. Paths after: PI 14 clicks and 3 scrolls (was 5), student 13 and 2 (was 14 and 5).
- **S31, five QA rounds (fresh tester then fixer each):** 28, 21, 29, 28 and 23 findings; 125 fixed, 2 partly, 1 dropped. The recurring Scout failures had one root cause: the demo model's 8,192-token context truncated Scout's rules from the front of the prompt (10 truncated calls in the Ollama log). History compaction keeps every call under about 6,400 tokens, and the demo unit now runs 12,288 with two slots (measured on GPU 4 first). Scout bench on the local model went from 23 of 28 (S28) to 27 of 28.
- **S32, stabilize:** `make package` built; Demo Day settings applied at the rebuild; live verification on the public URL; media refilmed (six clips, 29 screenshots, both replay previews); README corrected; `docs/RESULTS.md` written for the deck; the design canvas sources and the hosted canvas matched to the build (draft-check panel removed, Q34); the tracker page rebuilt (opens on Current with an at-a-glance strip, phone cards, a filterable Decisions tab, computed milestone readiness, stale-source notes) and its content refreshed.

## Known limits (honest list)

- **Scout on the local model varies by conversation.** The scripted questions pass; off-script phrasings can still refuse or answer loosely. The validator withholds an answer that fails its checks twice; that is the designed fallback and it shows as "withheld". The wrong-record risk (a claim cited to a neighbouring record) is checked by title words in the rehearsal, not in production.
- **G21 and G23 partly open:** a mask placed mid-clause can break its sentence; "how many of my options are samples" is not answered.
- **A two-part Scout question** ("next NSF deadline, and why does the top lead fit?") had its NSF half withheld on the public URL once; it passes on the dev server.
- **Student retrieval:** 1 of 12 planted positives never reaches a brief (SYNTHETIC, a mechanism test).
- **Back-test tuning** used the same 48 targeted rows it reports, so the S27 gain is partly fitted (RESULTS.md says so).
- **Documents on Cloud (Q33, answered 2026-11-01):** by the user's informed, per-session choice. The second warning lists each document that would leave, with a CV and unpublished research named separately; consent is per document and a document added later turns Cloud off until confirmed. The demo runs with the gate on; after that rebuild the private, student and ux walk groups on the public demo gave 125 states, 0 errors, 0 axe. The deployer's decisions (fully local, hybrid or cloud only; whether the key is a zero-data-retention key) are written in ARCHITECTURE.md, SPEC.md, deploy.md and the README; the roadmap in PLAN.md lists them first.
- **GRANTED and CREST** eligibility against Temple is unchecked (Q39, after Demo Day).

## Next: S33, freeze (Dakshitha)

1. Confirm `make test`, `make package` from a clean clone and the live demo one last time.
2. `make decide-down` to stop the dev Clef-flash and Clef units (GPUs 1 and 2); tell the other session sharing the node that those GPUs are free (details in the local notes). The Clef rows of `make bench` need `make decide-up` again after this.
3. Tag `v0.1-demo`; nothing on `main` after that except README typos.

## Open questions (mirror of bridge/QUESTIONS.md)

- **None.** Q33 was answered by Dakshitha on 2026-11-01 and built; everything else was closed under the delegation (Q29, Q34, Q35, Q36, Q41, Q42) with the decisions in DECISIONS.md.

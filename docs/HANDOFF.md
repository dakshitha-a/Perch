# HANDOFF.md — state for the next context window

Written at the close of S28 (2026-10-31). S27 and S28 ran in one context because Dakshitha asked for the Scout rebuild before the reviews.

## Last run: S28, Scout redesign phase 1 (and S27 before it)

- **No gate:** Scout runs each step as soon as the model asks for it. The ask mode, `approve`, `skip` and the mode switch are gone from the loop, the hub, both APIs, the CLI, the bench and the web app. Those three actions now return 422.
- **Stop:** `POST /scout/{sid}/stop`, or `/private/scout/{sid}/stop`, flags the running question. A step already running finishes. The rest are marked Not run and reported to the model, so the next question's history stays whole. An answer the model is already writing stands (DECISIONS, 2026-10-31).
- **Fixed to the brief:** Scout's own table is `SESSION_TOOLS` in `perch/scout/tools.py`. It has eight tools, none with `author_id`, and no `resolve_author`. The MCP server keeps `TOOLS` unchanged.
- **Cloud steps counted:** each session has its own counted providers for `explain_fit` and `draft_handoff` (`CountedProvider` in `perch/llm/audit.py`). Their tokens and dollars count toward the session caps. The grounding check inside `explain_fit` is a separate local decision model and is not counted.
- **What the person sees:**
  - **Read-as block:** "How Scout read your question" sits above the answer and lists each finished step with its filters.
  - **Steps fold:** the step cards fold under the answer. Each card says where it ran: Code, no model; Local model; or Cloud: Anthropic.
  - **Progress line:** it names the running step, with Stop beside it.
  - **Hand-off draft:** it shows open under the answer.
- **Words:** Help, SPEC §8 with its Stack line, and SCOUT_SPEC, where the phase 1 items are marked Built. Canvas version 33 has the new Scout tabs; it was checked with a script, not rendered.
- **S27 in short:**
  - **Coverage:** 1,497 listings from every agency.
  - **Back-test:** hit@5 went from 0.104 to 0.188 and MRR from 0.067 to 0.149. The keyword-only baseline is 0.021 and 0.027.
  - **Match score:** shown on a 0-100 scale.
  - **UI fixes:** 13 rounds from Dakshitha's review.
  - **Plan:** S29 to S32 reviews added.

## Checks at close

- `make test`: 265 passed.
- **Full walk on the dev server:** 145 states, 0 errors, 0 axe violations, 0 sideways scroll.
- **Live walk on the public URL:** the checks and student groups gave 64 states, 0 errors.
- **New S28 walk checks:** they cover the read-as block, folded steps, where-tags, no researcher chip, Stop, and a student Scout question with plain filter labels. Each failed on the build before its fix.
- **Scout bench, today's store:** `bench/results/scout_s28/`.
  - **Sonnet:** 28 of 28, 0 wrong calls in 27, $0.46.
  - **Gemma:** 23 of 28. The pre-S28 code on the same store got 21 of 28 the same day.
  - **S10 baseline:** 25 of 28, on the older NIH-only store.
- **Anthropic spend:** about $2.56 of $100.

## Next: S29, workflow review, diagnose

See PLAN.md S29. Measure the main paths first, then a fresh-context subagent reviews them, and every finding is verified before it goes into `docs/design/WORKFLOW_REVIEW.md`. Nothing is changed in S29. Dakshitha marks each item fix, defer or drop.

## Known gaps

- **Gemma counts results:** on bench task t13 it answers "I found 10 R01 grants". The validator rejects the count, so the answer is withheld. It does this on every run since S28 and passed before; Sonnet does not.
- **Flaky test:** `tests/test_scout.py::test_route_b_answer_counts_and_dates_pass_the_validator` failed once in S27. Not investigated.
- **Scout search quality:** an R21 question for PI-4, who works on molecular dynamics, returned cancer R21 grants.
- **Canvas:** the Scout tabs keep the draft-check panel, which is not built (Q34).
- **Media:** the README clips and screenshots predate the S27 and S28 UI changes (Q41).
- **Student retrieval:** 2 of 12 planted positives never reached a brief.

## Open questions (mirror of bridge/QUESTIONS.md)

- **Q41:** refilm the media at the start of S33? Default: yes, once, before the freeze.
- **Q36:** Google Fonts reach a third party; keep them? Default: keep.
- **Q35:** per-visitor caps by IP on Demo Day wifi. Default: keep.
- **Q34:** build the draft review anyway? Default: no.
- **Q33:** apply the rule 1 change, then set `PERCH_CLOUD_DOCUMENTS=1` on the demo.
- **Q29:** kept open by Dakshitha.

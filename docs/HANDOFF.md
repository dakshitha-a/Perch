# HANDOFF.md — state for the next context window

Written at the close of S34 (2026-11-03, 17:25 EST). S34 was Phase 0 of the deployment rebuild.

## Read this first

- **Work on `rebuild/v1`.** From S35 every commit lands on `rebuild/v1`, and so does the bookkeeping: the tracker, this file, the session files, decisions and questions. "`make test` green on `main`" in the session protocol reads as green on `rebuild/v1` until the Friday gate. `main` is not developed (DECISIONS, 2026-11-03, S34).
- **The plan.** `docs/REBUILD_PLAN.md`, 12 phases, S34 to S48. Read the phase for the current session, not the whole file.
- **The fallback.** The hybrid demo is frozen at d6f6210: tag `v0.1-demo-fallback`, branch `fallback/v0.1-demo`, a Docker image, a store copy and the package ZIP. The local notes list the machine paths. `main` sits a few docs-only commits after it, ending at d84a573.
- **The gate.** Thursday 5 Nov at 6:00 pm. The student path must work end to end on the new stack, or the fallback is submitted on 6 Nov.
- **The full S33-era hand-off** is on `main` and in git history at d6f6210, if a detail of the old build is needed.

## What S34 did

- **Conventions.** CLAUDE.md now names Postgres with pgvector as the deployment store. SQLite stays behind `perch/store/base.py` for unit tests only, and LanceDB is dropped. pg_search was not carried forward, because the plan does not use it.
- **Award-title exception.** Award titles copied from Temple's public pages may name people, such as a donor. Staff names and contacts stay out. The hygiene scan reads docs, the README, questions and `web/`, not `data/`, so award data needs no allowlist; the test's docstring says so.
- **Branch.** `rebuild/v1` was created from `main` at d84a573 and pushed with upstream.
- **GPUs.** `make decide-down` stopped and disabled the two dev Clef units. GPUs 1 and 2 now show about 2 MiB each. The uracil session was messaged. The four demo units on GPUs 6 and 7 are untouched, and the public demo answers 200.
- **Checks.** 470 tests green on `rebuild/v1`.
- **Already on record before the session.** The rebuild decisions (DECISIONS, 3 Nov) and the API budget of about $30 of the $100 cap for the rebuild.

## Next: S35, Phase 1 — discovery and design

- **The five tasks** are in `docs/REBUILD_PLAN.md`, Phase 1: the Temple award inventory, Temple SSO facts, provider facts, the reuse map, and `docs/ARCHITECTURE_V1.md`. An Opus design review follows.
- **Delegation fits here.** The inventory and the provider facts are independent read-only research jobs and can run in parallel on Sonnet. The reuse map reads `perch/private/`, `perch/api.py`, `perch/scout/` and `web/`, and is the brief for Phases 5 to 8. The architecture document comes after the map.
- **Rules to keep in view.** Rule 2: a page is recorded with its status and robots.txt before any parser exists. Pages behind AccessNet are listed, not read. SSO claim names stay UNVERIFIED until Temple IT answers.

## Not done or worth knowing

- **The dev server on 8091** and the dev embed/rerank on GPU 3 were not touched in S34.
- **Untracked bench output.** Nine `bench/results/scout_s32*` folders sit untracked in the checkout. They are not this session's and were not committed.
- **A hygiene failure in Phase 1 may be expected.** `test_researcher_names_stay_out_of_shareable_docs` scans `docs/**/*.md`, so `docs/SOURCES.md` is in scope. If a Temple award title written there contains a demo researcher's last name, the test fails. The fix then is a narrow allowlist of those award titles in the test, not a change to the convention.
- **The tracker milestone** "Code freeze" is now "Rebuild gate", Thu 5 Nov 18:00.
- **The tracker tests tile** reads the latest row's count, now 470.

## Open questions (mirror of bridge/QUESTIONS.md)

- **Q45 (Dakshitha):** the Fox School scholarships. Recommendation: fold it into Phase 1's inventory and Phase 4's import, and close it.
- Q46 is answered and built into the plan.

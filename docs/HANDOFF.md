# HANDOFF.md — state for the next context window

Written at the close of S40 and S41 (2026-11-04, about 10:45 EST). Dakshitha asked for the sessions to run back to back in one orchestrating context ("carry on till everything is finished, all phases"), so this file is updated at each close.

## Read this first

- **Work on `rebuild/v1`.** Every commit and all bookkeeping land there. `main` is not developed.
- **The plan.** `docs/REBUILD_PLAN.md`. Its "Revision on 4 Nov 2026" section overrides the text below it.
- **The fallback.** The hybrid demo is frozen at d6f6210 (tag `v0.1-demo-fallback`). The local notes list the machine paths.
- **The gate.** Thursday 5 Nov at 6:00 pm. The student path must work end to end on the new stack, or the fallback is submitted on 6 Nov.
- **Compute rules.** Heavy jobs run only through `scripts/run_limited.sh`: 16 cores for CPU jobs, or `PERCH_LIMIT_GPU=3` for one GPU with 4 cores. Never GPUs 0, 6 or 7, and never ports 8090, 8093, 8097 or 8098.
- **Background work.** Every background shell, agent or monitor is checked at least every 30 minutes. A cron check-in runs at :13 and :43 while anything runs.
- **Credentials.** Agents' worktrees have no `.env`, and copying it is blocked. Real-provider and live runs happen in the main checkout. `.env.e2e`, which is gitignored, holds the e2e database, Redis, key-store and peppers settings.
- **Test exit codes.** Never pipe `make test` through `tail` before `&&`, because the pipe hides a failure. One commit slipped through that way in S40.

## Where the rebuild stands

- **S34 to S39 done.** These cover Phases 0 to 4a.
  - **Profile.** `cloud-gpu` is the default, with the models on one GPU and the text on Anthropic. Ranking is dense-only, with 100 candidates reranked.
  - **Results.** `docs/RESULTS.md`, in the S38 section.
- **S40 done (Phase 4b).**
  - **Dataset.** Temple awards dataset v2 is in `data/temple/dataset/` and loaded into `perch_dev`. It has 310 records, 17 of them Temple-funded.
  - **Names.** People's names outside award titles are removed at build, by `perch/temple_names.py`.
  - **Hand-check.** The v1 hand-check error rate was 7.4%. v2's rate is measured in S46.
  - **Feed importers.** `perch/feeds/`.
  - **Raw extraction files.** They are gitignored because they still hold names.
- **S41 done (Phase 5).**
  - **Sign-in.** OIDC with the dev Keycloak. The container is `perch-dev-keycloak` on 127.0.0.1:8180. It was started with `docker run`, not Compose; restart it with the command in the local notes.
  - **User data.** CV, entries and briefs are encrypted per user in `user_data`. Guest briefs live in Redis.
  - **Deletion.** Delete-my-data, the purge job, quotas and idempotent submits are built.
  - **Live check.** `scripts/e2e_account.py` passes 29 of 29 steps. Run it from the main checkout with `.env` and `.env.e2e`.
- **Spend.** The ledger is about $4.00. The `.env` cap is $32.60.
- **Tests.**
  - **Main suite.** `make test`: 603 passed.
  - **Database suites.** test-pg 48, test-keys 60, test-redis 88, test-user 43.
  - **Role passwords.** The Postgres test fixtures reset role passwords across the whole cluster. After `make test-pg` or `make test-user`, the e2e roles need their passwords from `.env.e2e` set again.

## Running at this close

- **S42 (Phase 6), Sonnet worktree agent.**
  - **The work.** It removes private mode per `docs/v1/REUSE_MAP.md`.
  - **The leak check.** It builds a user-data leakage check that must fail on a planted leak before it passes.
  - **When it reports.** Merge it, then run the leak check live.
- **S43 backend, Sonnet worktree agent.**
  - **The work.** The F1 and F2 Temple filter fix, the unstated scope, `/awards`, `/opportunities`, `/filters`, `/samples`, `/welcome`, and guest keep and dismiss.
  - **When it reports.** Merge it.
- **S43 design.** It is in `docs/design/S43_DESIGN.md`. Its forks are decided (DECISIONS, 2026-11-04).
- **S43 frontend.** Start it after S42 merges, because both touch `web/`. Follow the design's gate list in order, then the walk with axe and a fresh-context Opus UI review.

## Next after S43

- **S44 and S45, Phase 8.** Scout rebuilt as an open, grounded assistant.
- **S46, Phase 9.** QA, including v2's hand-check and the student brief cost.
- **S47, Phase 10.**
  - **CUDA worker image.** Build it.
  - **Load test.** A measured concurrent GPU load test.
  - **Spend.** Per-call spend reserve and settle.
- **S48, Phase 11.**
  - **Security review.** Fresh context.
  - **Purge actions.** `rekey` and `tombstones`.
  - **Docs and release.** Docs, the demo rebuild, `make package` and the tag.

## Worth knowing

- **Scout hang, cause unknown.** It happened once, in S38. Model slots now time out after 300 s and Anthropic requests after 120 s. If it recurs, run `uv tool run py-spy dump --pid <pid>` before killing the process.
- **Draft copy.** The S43 design's consent, landing and footer wording is marked DRAFT for Dakshitha and is not adopted. The consent text stays as built, so nobody has to consent again.
- **Cache holds names.** The cleaned page cache, `data/cache/temple_pages/`, is gitignored and still holds donors' and students' names from public pages. Only the dataset is scrubbed.
- **Untracked bench output.** Nine `bench/results/scout_s32*` folders are not this rebuild's and stay uncommitted.

## Open questions (mirror of bridge/QUESTIONS.md)

- **Q45 (Dakshitha):** Fox School scholarships. The Fox page is in the dataset. Recommendation: close it.
- **Q47 (not blocking):** pg_search's AGPL licence matters only if keyword ranking returns.
- **Draft copy (not blocking):** read the DRAFT consent and landing wording in `docs/design/S43_DESIGN.md` when convenient.

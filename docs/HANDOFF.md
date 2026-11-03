# HANDOFF.md — state for the next context window

Written at the close of S37 (2026-11-03, 20:55 EST). Dakshitha asked on 3 Nov for S35 to S48 to run back to back in one orchestrating context, so this file is updated at each close.

## Read this first

- **Work on `rebuild/v1`.** From S35 every commit lands on `rebuild/v1`, and so does the bookkeeping: the tracker, this file, the session files, decisions and questions. "`make test` green on `main`" in the session protocol reads as green on `rebuild/v1` until the Friday gate. `main` is not developed (DECISIONS, 2026-11-03, S34).
- **The plan.** `docs/REBUILD_PLAN.md`, 12 phases, S34 to S48. Read the phase for the current session, not the whole file.
- **The fallback.** The hybrid demo is frozen at d6f6210: tag `v0.1-demo-fallback`, branch `fallback/v0.1-demo`, a Docker image, a store copy and the package ZIP. The local notes list the machine paths. `main` sits a few docs-only commits after it, ending at d84a573.
- **The gate.** Thursday 5 Nov at 6:00 pm. The student path must work end to end on the new stack, or the fallback is submitted on 6 Nov.
- **The full S33-era hand-off** is on `main` and in git history at d6f6210, if a detail of the old build is needed.

## Where the rebuild stands

- **S34, Phase 0, done.** Conventions name Postgres with pgvector; the award-title exception; `rebuild/v1` created; dev GPUs 1 and 2 released.
- **S35, Phase 1, done.** The contract every later phase builds on is `docs/ARCHITECTURE_V1.md`. Read its section for the phase, not the whole file.
- **S36, Phase 2a, done.** Migrations under `perch/db/migrations/perch/` and `keys/`, `PostgresRepository`, `perch/crypto.py` and `perch/keystore.py`. Test targets: `make test`, `make test-pg`, `make test-keys`, against the test containers `perch-test-pg` on 127.0.0.1:55432 and `perch-test-redis` on 127.0.0.1:56379.
- **S37, Phase 2b, done.** `perch worker` runs jobs from Postgres; `perch/redisx.py` holds sessions, quotas, limits and the cache; `perch_dev` on the test Postgres holds the migrated public corpus; `scripts/e2e_brief_job.py` runs a brief job end to end. `deploy/compose/docker-compose.v1.yml` validates but has not been started. Test targets: `test`, `test-pg`, `test-keys`, `test-redis`; the last needs `PERCH_TEST_REDIS_URL=redis://127.0.0.1:56379/15`.
- **Inputs from S35.** `data/temple/inventory.csv` lists 461 Temple pages for Phase 4. `docs/v1/REUSE_MAP.md` is the brief for Phases 5 to 8. `docs/v1/PROVIDER_AND_SSO.md` holds prices, tiers and Temple SSO facts. `docs/v1/DESIGN_REVIEW.md` is the closed review.
- **Spend.** The ledger stands at $2.60. `.env` caps it at $32.60, which is the $30 rebuild budget on top.
- **Tests.** 470 green on `rebuild/v1`.

## Next: S38, Phase 3

- **The work.** The `cloud-cpu` profile as default; CPU timings for embed, rerank of the top 50 and MiniCheck; the four model jobs and Scout on the cloud model with tokens and cost per brief for each side; the caches and the nightly researcher pre-cache; the back-test with its keyword baseline, the grounding bench and the Scout bench rerun on the shipped setup.
- **Spend.** This is the first session that spends. The cap is $32.60 of ledger total, and the ledger is $2.60.
- **Loose ends.** Redis and shred hooks are not wired into web startup; nothing calls quotas yet; brief rows live in a scratch SQLite file until Phase 5; `perch/user/data.py` must check for no rows before `create=True`.

## Worth knowing

- **A hygiene failure may be expected later.** `test_researcher_names_stay_out_of_shareable_docs` scans `docs/**/*.md`. If a Temple award title contains a demo researcher's last name, the fix is a narrow allowlist of those titles in the test.
- **Faculty internal funding is thin.** The OVPR page is stale, and live calls are likely on InfoReady behind sign-in.
- **Untracked bench output.** Nine `bench/results/scout_s32*` folders are not this rebuild's and stay uncommitted.

## Open questions (mirror of bridge/QUESTIONS.md)

- **Q45 (Dakshitha):** Fox School scholarships. The inventory covers the Fox page; Phase 4 imports it. Recommendation: close Q45.

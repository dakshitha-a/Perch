# HANDOFF.md — state for the next context window

Rewritten 2026-11-04 at about 14:15 EST, during S45's last fix round. Dakshitha asked for the sessions to run back to back in one orchestrating context ("carry on till everything is finished, all phases"), so this file is rewritten at each close.

## Read this first

- **Work on `rebuild/v1`.** Every commit and all bookkeeping land there. `main` is not developed.
- **The plan.** `docs/REBUILD_PLAN.md`. Its "Revision on 4 Nov 2026" section overrides the text below it.
- **The fallback.** The hybrid demo is frozen at d6f6210 (tag `v0.1-demo-fallback`). The local notes list the machine paths.
- **The gate.** Thursday 5 Nov at 6:00 pm. The student path must work end to end on the new stack, or the fallback is submitted on 6 Nov.
- **Compute rules.** Heavy jobs run only through `scripts/run_limited.sh`: 16 cores for CPU jobs, or `PERCH_LIMIT_GPU=3` for one GPU with 4 cores. One GPU job at a time; a busy lock exits 75. Never GPUs 0, 6 or 7, and never ports 8090, 8093, 8097 or 8098.
- **Background work.** Every background shell, agent or monitor is checked at least every 30 minutes. A cron check-in runs at :13 and :43 while anything runs.
- **Credentials.** Agents' worktrees have no `.env`, and copying it is blocked. Real-provider and live runs happen in the main checkout. `.env.e2e`, which is gitignored, holds the e2e database, Redis, key-store and peppers settings.
- **Test exit codes.** Never pipe `make test` through `tail` before checking the exit code.
- **Role passwords.** The Postgres test fixtures reset role passwords across the cluster. Before a live run, reset the e2e roles from `.env.e2e` (a small script that runs `ALTER ROLE` through `docker exec perch-test-pg psql -U postgres` without printing them). The walk server sets its own with `scripts/walk_server.py --setup`.
- **Model output caps.** Sonnet 5.5 and Haiku 5.5 think by default, and the thinking counts toward `max_tokens`. Any new model call needs a cap with room for it (Scout 6,000; fit, hand-off, summary 3,000; cover points 4,000).

## Where the rebuild stands

- **S34 to S42 and S44 done.** Phases 0 to 6 and 8a. `docs/RESULTS.md` has the S38, S40 and S45 sections.
- **S43 done (Phase 7).** Student-first screens, browse with the Temple filter and school tags, account page with withdraw and delete, Help rewritten. The Opus review's 7 must-fix items are closed. Walks: guest 60 states in light and dark, real sign-in 16 states, all 0 errors and 0 axe. The only small targets are two inline links, which WCAG 2.5.8 exempts. Should-fix leftovers are listed in `docs/sessions/S43.md` for S46.
- **S45 (Phase 8b), not yet closed.**
  - **Bench.** Five real runs, table in `docs/RESULTS.md`. Out of scope 24 of 24, distress 5 of 5. In-scope Layer 1 pass swings with the drafts: 23, 12, then 16 of 33 on the final rules (s45f). About one in four cited sentences carries a MiniCheck mark (37 of 141 in s45f). Usefulness is not graded yet: a person fills `grades.csv`.
  - **Security review.** M1 (CSRF on nine write routes) fixed and re-checked. Two re-checks found the word-list rules leaking. Round 3, an Opus agent in a worktree, replaces them with shape rules and makes distress screening independent of the budget (DECISIONS 2026-11-04).
  - **When round 3 reports:**
    1. Merge it and run all suites.
    2. Replay the s45f drafts through the final rules with the agent's numbers, and add a RESULTS row "s45f drafts, final rules".
    3. Rerun the out-of-scope and distress sets on the real gate: `PERCH_LIMIT_GPU=3 scripts/run_limited.sh uv run --extra ml --extra anthropic python -m bench.scout_open --no-old --only-set out --max-usd 0.10 --tag s45g`, then the same with `--only-set distress`. About $0.02. Also confirm that the five research questions about suicide are answered, not refused.
    4. One fresh Opus re-check scoped to R1, R2, S1 and S5. If it finds no must-fix, close S45. Should-fix items go to S46's list. No fifth cycle.
- **S46 started early (Phase 9).**
  - **Dataset v3.** The v2 hand-check by a fresh reviewer: 16.6% of 217 rows wrong or missing (v1 7.4%), mostly Temple-funded misses. Fixes for the deadline conflict, per-award amounts and explicit Temple funding wording were applied, and v3 was rebuilt from the same reads without model calls. 310 records, 27 Temple-funded. Loaded into `perch_dev`. v3's error rate is not yet re-measured.
  - **Search filter.** Vector search now uses the same "listed on a Temple page" rule as browse.
- **Spend.** The ledger is about $8.83 of the $100 cap; the `.env` cap is $32.60.
- **Tests at the last merge.** `make test` 724 passed.

## What is left after S45

- **S46 (Phase 9), the QA cycle.** Two tester-then-fixer rounds: `make test`, the full walk with axe, the bench, the rehearsal script, the leakage check. Also: S43's should-fix leftovers; confirm on the real model that student brief explanations are not all withheld (the walk's fake model withholds every one); the student brief cost; the docs sweep for retired private-mode links; v3 hand-check; a person grading `grades.csv`.
- **S47 (Phase 10).** The CUDA worker image with the Compose worker on `cloud-gpu`; the measured concurrent GPU load test; per-call spend reserve and settle; backup retention set to 35 days, to match the consent text; the runbook.
- **S48 (Phase 11).** A fresh-context security review; the `rekey` and `tombstones` purge actions; the docs, the demo rebuild, `make package` and the tag `v1.0-deploy`.

## Worth knowing

- **Walks.** `scripts/walk_server.py --setup`, then `PERCH_LIMIT_GPU=3 scripts/run_limited.sh uv run --extra ml python scripts/walk_server.py` (127.0.0.1:8191), then `uv run --no-project --with playwright --with httpx python scripts/ux_walk.py --out build/<name>`. Stop the server with `pkill -f "[w]alk_server.py"` and its worker with `pkill -f "[p]erch.cli --db /tmp/perch-walk"`. The phone researcher compare click timed out once and passed on a rerun.
- **Sign-in walk.** From the main checkout with `.env` and `.env.e2e` loaded: `PERCH_LLM_DEFAULT=fake:fake-1 uv run perch serve --host 127.0.0.1 --port 8190 --models fake`, then `ux_walk.py --base http://127.0.0.1:8190 --only landing --login-helper scripts/e2e_oidc_login.py`. Keycloak is `perch-dev-keycloak` on 127.0.0.1:8180.
- **Scout hang, cause unknown.** It happened once, in S38. Model slots now time out after 300 s and Anthropic requests after 120 s. If it recurs, run `uv tool run py-spy dump --pid <pid>` before killing the process.
- **Draft copy.** The S43 design's consent, landing and footer wording is marked DRAFT for Dakshitha and is not adopted.
- **Cache holds names.** The page cache and the raw extraction files are gitignored and still hold names from public pages. Only the dataset is scrubbed. Hand-check sheets are committed without the page-sentence column.
- **Untracked bench output.** Nine `bench/results/scout_s32*` folders are not this rebuild's and stay uncommitted.

## Open questions (mirror of bridge/QUESTIONS.md)

- **Q45 (Dakshitha):** Fox School scholarships. The Fox page is in the dataset. Recommendation: close it.
- **Q47 (not blocking):** pg_search's AGPL licence matters only if keyword ranking returns.
- **Q48 (not blocking):** a crisis message always gets the care message, even with the budget spent. Recommendation: keep.
- **Draft copy (not blocking):** read the DRAFT consent and landing wording in `docs/design/S43_DESIGN.md` when convenient.

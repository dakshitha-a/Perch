# HANDOFF.md — state for the next context window

Rewritten 2026-11-04 at about 19:00 EST, at the start of S48. Dakshitha asked for the sessions to run back to back in one orchestrating context ("carry on till everything is finished, all phases"), so this file is rewritten at each close.

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

- **S34 to S47 done.** Phases 0 to 10. `docs/RESULTS.md` has the S38, S40, S45 and S47 sections; the tracker has one row per session.
- **S45:** Scout bench final run: out of scope 24 of 24, distress 5 of 5, in scope 10 of 33 pass Layer 1, 23 shown with sentences removed, 0 empty. Security review closed after four re-checks; should-fix list at the end of `docs/design/S45_SECURITY_REVIEW.md`.
- **S46:** two QA rounds with no open must-fix. Cover-letter points button on every grant and award card, reviewed and re-checked. Guests see "Ask Scout needs an account". README rewritten for v1. Dataset v3 loaded. Real-model student brief: 59 of 60 explanations shown, about $0.11 a brief.
- **S47:** the worker now builds one brief service per process (it rebuilt the GPU models per job and failed at 4 in flight). One GPU: 37.1 briefs a minute at 24 in flight, saturating near 41. HTTP at 1,000 users: target not met (one web process ~62 req/s, four ~156). GPU worker image builds; this node had no NVIDIA container runtime, so the demo worker runs natively on GPU 3 (Dakshitha). Dakshitha installed nvidia-container-toolkit 1.20.1 on 4 Nov evening (steps 1 to 3; Docker restart pending at the time of writing). Health checks, JSON logs, loopback `/metrics`, daily backups with 35-day retention, restore test passed. Runbook: `docs/deploy.md`.
- **Spend.** The ledger is about $10.60 of the $100 cap; the `.env` cap is $32.60.
- **Tests.** `make test` 910 passed.

## S48 (Phase 11), now

1. Fresh-context Opus security review: encryption, sign-in, sessions, injection through record text, quotas, secrets. Fix every must-fix, re-check.
2. The `rekey` and `tombstones` purge actions.
3. Carried: Q49 Scout tuning; S43 and S45 should-fix lists; ARCHITECTURE_V1 `/ready` wording; a worker systemd unit.
4. Docs verified against the code (README, SPEC, ARCHITECTURE_V1, SOURCES, RESULTS, the hosted spec, the deck's deployment slide).
5. Demo rebuild on the new stack: Compose for Postgres, Redis, Keycloak and web; the worker natively on GPU 3. Do not take port 8090 or the Funnel from the fallback until Dakshitha decides at the gate. Rehearse, walk, leak check on the new URL.
6. `make package`, tag `v1.0-deploy`.
- **The gate:** Thursday 5 Nov, 6:00 pm. If the rebuild is not demo-ready, write the submission decision to `bridge/QUESTIONS.md`.

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
- **Q49 (not blocking):** Scout's strict grounding withholds sentences in most answers. Recommendation: keep for the demo, tune in S46.
- **Q48 (not blocking):** a crisis message always gets the care message, even with the budget spent. Recommendation: keep.
- **Draft copy (not blocking):** read the DRAFT consent and landing wording in `docs/design/S43_DESIGN.md` when convenient.

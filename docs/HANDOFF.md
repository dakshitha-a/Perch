# HANDOFF.md — state for the next context window

Rewritten 2026-11-05 at about 01:25 EST, at the close of S49. Dakshitha delegated every decision for S49 to S52 and asked for all remaining phases to run without stopping. The same orchestrating context continues into S50; this file is for a fresh context if one is needed.

## Read this first

- **Branch:** work on `rebuild/v1`. `main` is not developed.
- **Plan:** `docs/REBUILD_PLAN.md`, Phase 12 (rounds S49 to S51) and Release (S52).
- **Next:** S50, Phase 12 round 2. Start with P6 (student cards do not say what the rules checked; `docs/design/S49_PRODUCT_REVIEW.md`) and `docs/design/S49_ORCHESTRATOR_NOTES.md`. Then run the round as in S49: four fresh reviews, a design, builders split by file, QA, a re-check.
- **The gate:** Thursday 5 Nov at 6:00 pm. A one-shot reminder is set for 17:31 in this context. Write the submission decision to `bridge/QUESTIONS.md` and DECISIONS.md.
- **The fallback:** frozen at d6f6210 (tag `v0.1-demo-fallback`), served on 8090 through the Funnel on 443. Never touch it.
- **Compute rules:** heavy jobs only through `scripts/run_limited.sh`. GPU 3 only, with a lock file of its own for anything beside the deploy worker (`PERCH_LIMIT_LOCK=/run/user/1002/perch-walk.lock` for the walk, `perch-bench.lock` for benches). Never GPUs 0, 6 or 7. Never ports 8090, 8093, 8097, 8098, 8200.
- **Commit trailer:** only `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never a `Claude-Session:` line.
- **Use `.venv/bin/ruff` and `.venv/bin/python -m pytest`,** not `uv run`, in the main checkout: a bare `uv run` re-syncs the venv, and the deploy runs from it.
- **pkill patterns:** a pattern that appears in your own command line kills your shell. Run `pkill -f "scripts/[w]alk_server.py"` in a command of its own.

## What S49 did

- **Reviews:** four fresh Opus reviews in `docs/design/S49_*_REVIEW.md`, 184 items, 28 must-fix. A design in `docs/design/S49_DESIGN.md`.
- **Built,** by five builders in worktrees, merged on `rebuild/v1`:
  - **Front end:** landing in one laptop screen; a new lead card; the brief header folds into a Ready chip; researcher CV card; "Change details and run again"; dense lists with Keep, sort and closed calls; a saved list; My Perch as the signed-in home; Load sample for students; a Temple internal group.
  - **Back end:** a dead job no longer polls forever; Keep during a run is safe; worker threads survive a database blip; double clicks make one brief; a scheduler in the worker runs the daily purges and the nightly precache; guest briefs encrypted in Redis (Q50); past-cycle Temple dates give "may be eligible"; open-anytime calls kept; Temple internal funding reaches researcher briefs; staff awards out of the student pool.
  - **Scout grounding (Q49):** offline replay first, then fixes. Real-model bench: layer 1 pass 10 of 33 in S45, 18 of 33 now; MiniCheck flags 42; out of scope 24 of 24, distress 5 of 5.
- **QA:** walk 171 states in light and dark at 1280 and 360 with real sign-in, 0 errors, 0 axe, 0 small targets. Suites: unit 996, pg 88, redis 117, keys 67, user 132 (with the leak check).
- **A deploy bug, found by the new `scripts/smoke_deploy.py`:** Anthropic refused the explanation call (reasoning_extraction), and the refusal failed the whole brief. Fixed: a refusal withholds that one explanation, and the prompts no longer ask for "private reasoning".
- **Re-check:** `docs/design/S49_RECHECK.md`. 37 of 41 must-fix closed; the no-worker message fixed after; P6 carried; M6 (refresh the federal snapshot) is in S52.

## The test deploy (live, on the S49 code)

- **App:** https://sn4622120437.tailf0654d.ts.net:8443 (Funnel 8443 to 127.0.0.1:8200). Sign-in through the dev Keycloak on Funnel 10000.
- **Accounts:** SYNTHETIC `demo-presenter`, `demo-researcher`, `demo-student`; passwords only in `.env.deploy`.
- **Guest budget for Demo Day:** $1.50 an address and $6.00 a day (raised in S49, `.env.deploy`), because an audience on one venue network shares one address. The Funnel does pass each visitor's address (checked in S49).
- **Updating it:** commit, then `systemctl --user restart perch-v1-web perch-v1-worker`. Edits under `web/` are live at once. After a change to `perch/store/denorm.py`, run `scripts/redenorm.py --dsn-env PERCH_WORKER_DATABASE_URL` with `.env.deploy` sourced.
- **Smoke:** `.venv/bin/python scripts/smoke_deploy.py --base https://sn4622120437.tailf0654d.ts.net:8443` (add `--no-researcher` to save about $0.10).
- **Logs:** the worker writes nothing to the journal; read a brief's own `error` through `GET /briefs/{id}`.

## Worth knowing

- **Walk server:** set up with `scripts/walk_server.py --setup` (resets the walk databases and role passwords; run it while no server runs). Start it from the checkout you want served, with `PERCH_OIDC_CLIENT_SECRET` from `.env`, `PERCH_GUEST_SESSIONS_PER_ADDRESS_HOUR=1000`, and the walk lock. Walk with `--login-helper scripts/e2e_oidc_login.py` and `KEYCLOAK_ADMIN_PASSWORD` from `.env`.
- **Shared test databases:** the Postgres and Redis suites reset role passwords and flush Redis DB 15. Never run them while a walk server or another builder's suite runs.
- **Walk flows:** each build package keeps its own flows in `scripts/walk_flows/<name>.py`; `ux_walk.py` loads them.
- **Spend:** main ledger $12.45 of $100. The deploy's own ledger is capped at $15.

## Open questions (mirror of bridge/QUESTIONS.md)

- **Q47 (not blocking):** pg_search's AGPL licence matters only if keyword ranking returns.
- **Q49 (in progress):** Scout grounding, 18 of 33 now pass layer 1; round 2 continues.
- **Grading:** Dakshitha grades Scout usefulness in `bench/results/scout_open_s49b/grades.csv` when she can.

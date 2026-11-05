# HANDOFF.md — state for the next context window

Rewritten 2026-11-05 at about 09:10 EST, at the close of S52 (the release). Dakshitha delegated every decision for S49 to S52 and asked for all remaining phases to run without stopping. Phase 12 (S49 to S51) and the release (S52) are done.

## Read this first

- **`main` is now v1.** `rebuild/v1` was merged into `main` and tagged `v1.0-deploy`. The earlier hybrid build stays at the tag `v0.1-demo-fallback` and the branch `fallback/v0.1-demo`.
- **The gate passed** (bridge/QUESTIONS.md Q53, decided at 07:15 EST on 5 Nov). The v1 rebuild is the submitted prototype; the fallback is linked.
- **Demo Day:** the run sheet is `docs/DEMO.md`. Before the demo, run `scripts/demo_reset.py --apply` with the deploy's env file sourced, test the deploy's URL from a phone, and sign in once as `demo-presenter`.
- **Open for Dakshitha:** Q51 (a real researcher on the projector: recommendation, use the example brief) and Q52 (port 8443 on venue Wi-Fi: DEMO.md has the commands to move v1 to 443; only Dakshitha runs `tailscale funnel`).
- **The fallback:** served on 8090 through the Funnel on 443. Never touch it.
- **Compute rules:** heavy jobs only through `scripts/run_limited.sh`; GPU 3 only, with its own lock file beside the deploy worker. Never GPUs 0, 6 or 7. Never ports 8090, 8093, 8097, 8098, 8200.
- **Commit trailer:** only `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never a `Claude-Session:` line.
- **In the main checkout use `.venv/bin/python` and `.venv/bin/ruff`,** not a bare `uv run`: the deploy runs from that venv. Never `git checkout main` there; use a worktree.

## What S49 to S52 did

- **Three review rounds:** each ran four fresh Opus reviews (UI/UX, product and flow, back-end correctness, back-end function), a design, builders in worktrees, a QA fixer and a fresh re-check. Files: `docs/design/S49_*`, `S50_*`, `S51_*`. No must-fix item is open in code.
- **Release (S52):** the docs were rewritten and checked against the code (README with a "See it" line, the tour and Known limits; SOURCES, RESULTS, ARCHITECTURE_V1, SPEC, running, deploy, DEMO, AI use log). The README tour was filmed from the deploy (seven clips), and `docs/screenshots/` was regenerated alias-only (48 images). The example briefs were re-exported. `make demo` now starts a local v1 demo without a GPU, and `make bench` runs the v1 back-test. The version is 1.0.0.
- **Measured:** the full walk has 258 states each in light and dark, with 0 errors and 0 axe. Suites: unit 1114, pg 92, redis 120, keys 67, user 135. The back-test is unchanged since S38 (bench/results/s50_backtest). The Scout bench layer 1 pass went from 10 of 33 (S45) to 18 of 33 (s49b). Cover points in the last live capture had 0 unsupported sentences (5 of 5 before S51).
- **Spend:** the main ledger is $12.45 of $100. The deploy's own ledger is $2.50 of its $15 cap.

## The test deploy (live, on the final code)

- **Where:** the URL is in CLAUDE.local.md (Funnel 8443 to 127.0.0.1:8200; sign-in on Funnel 10000).
- **Settings for Demo Day:** accounts are closed (`PERCH_ACCOUNTS_OPEN=0`, so the walls point to the example brief). Per-address limits are about ten times the defaults. The guest budget is $0.30 a session, $4.00 an address and $8.00 a day. The precache runs at 08:00 UTC, one brief at a time. All of these are in `.env.deploy`.
- **Updating it:** commit, then `systemctl --user restart perch-v1-web perch-v1-worker`. Edits under `web/` are live at once.
- **Scripts:** `scripts/smoke_deploy.py` (smoke), `scripts/live_capture.py` (real-model text; needs `PERCH_LIVE_BASE`), `scripts/export_example.py` (the example briefs), `scripts/refresh_v1.py` (federal records), `scripts/redenorm.py` (filter columns), `scripts/demo_reset.py` (guest limits).
- **The SYNTHETIC e2e user** in the shared realm is disabled between test runs. `scripts/e2e_oidc_login.py` enables it and sets a fresh random password for a run. After a walk, disable it again with the Keycloak admin API (`PUT /admin/realms/perch/users/<id>` with `{"enabled": false}`), as done in S52.
- **A database password was printed** into one reviewer agent's local transcript in S51 (the deploy worker's role). Rotate it after the demo.

## Worth knowing

- **Walk server:** `scripts/walk_server.py --setup` resets the walk databases and role passwords; run it while no server runs. Start it with `PERCH_OIDC_CLIENT_SECRET`, `OPENALEX_API_KEY`, `PERCH_SCHEDULER=0` and `PERCH_GUEST_SESSIONS_PER_ADDRESS_HOUR=1000`, under the walk lock.
- **Shared test databases:** the Postgres and Redis suites reset role passwords; never run them while a walk server runs.
- **pkill:** a pattern in your own command line kills your shell; run `pkill -f "scripts/[w]alk_server.py"` alone.
- **A stray walk worker** from S49 could not be stopped by the agent (a safety check blocked the kill); it is idle and harmless. Dakshitha can stop it.

## Open questions (mirror of bridge/QUESTIONS.md)

- **Q47 (not blocking):** pg_search's AGPL licence matters only if keyword ranking returns.
- **Q49 (in progress):** Scout grounding, 18 of 33 pass layer 1.
- **Q51 (for Dakshitha):** a real researcher on the projector.
- **Q52 (for Dakshitha):** port 8443 on venue Wi-Fi.

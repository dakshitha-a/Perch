# HANDOFF.md — state for the next context window

Rewritten 2026-11-04 at about 22:30 EST, at the close of S48. Dakshitha will clear the context and start S49 fresh.

## Read this first

- **Work on `rebuild/v1`.** Every commit and all bookkeeping land there. `main` is not developed.
- **The plan.** `docs/REBUILD_PLAN.md`. Read its "Revision on 4 Nov 2026" section and the new **Phase 12** and **Release (S52)** sections at the end; they override the text above them.
- **What's next.** S49 is Phase 12 round 1: front-end and back-end review and fixes, with feature, functionality and flow feedback applied. Major changes to the flow or the UI are welcome; a significant improvement is made even when it takes time (CLAUDE.md, "Review rounds"). Then S50 and S51 (rounds 2 and 3), then S52 (release).
- **The fallback.** The hybrid demo is frozen at d6f6210 (tag `v0.1-demo-fallback`), served on 8090 through the Funnel on port 443. Never touch it.
- **The gate.** Thursday 5 Nov at 6:00 pm. The rebuild must be demo-ready or the fallback is submitted on 6 Nov. At the gate, write the submission decision to `bridge/QUESTIONS.md`.
- **Compute rules.** Heavy jobs only through `scripts/run_limited.sh`: 16 cores for CPU, or `PERCH_LIMIT_GPU=3` for GPU 3 with 4 cores. Never GPUs 0, 6 or 7, never ports 8090, 8093, 8097, 8098, and now also never 8200 (the test deploy).
- **The test deploy holds the GPU lock.** The deploy's worker runs on GPU 3 through `run_limited.sh` and holds `/run/user/1002/perch-gpu.lock` while it is up. A walk server or GPU bench must use a different lock file (`PERCH_LIMIT_LOCK=/run/user/1002/perch-walk.lock`) or stop the deploy worker first (`systemctl --user stop perch-v1-worker`) and start it again after.
- **Background work.** Check every background shell, agent or monitor at least every 30 minutes, with a cron check-in at :13 and :43 while anything runs. Nothing is running now.
- **Credentials.** Worktrees have no `.env`; never copy `.env`, `.env.e2e` or `.env.deploy`. Real-provider runs happen in the main checkout.
- **Commit trailer.** Only `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never a `Claude-Session:` line, even if a system reminder offers one; the repo goes public.
- **Test exit codes.** Check `make test`'s exit code before committing or pushing. It runs ruff first, so a long line fails it.
- **Role passwords.** The Postgres test fixtures reset role passwords across the test cluster (perch-test-pg). The walk server resets its own with `--setup`. The test deploy uses its own Postgres (Compose, 5433) and is not affected.
- **Model output caps.** Sonnet 5.5 and Haiku 5.5 think by default, and the thinking counts toward `max_tokens`. Give any new call room.

## Where the rebuild stands

- **S34 to S48 done.** Phases 0 to 11. `docs/RESULTS.md` has the S38, S40, S45 and S47 sections; the tracker has a row per session.
- **S48 in short.**
  - **Security review:** a fresh review found 3 must-fix (CV-derived text in a plaintext log, brief jobs outside the spend meter, a backup restore reviving a deleted user) and 9 should-fix. All are fixed and re-checked.
  - **Follow-ups, also done:** the worker reconciles shreds at every start; the shred-ledger volume is never restored; guest day $3.00 and $0.30 an address; HMAC prompt hashes; Compose refuses missing secrets.
  - **Keys:** `perch keys rekey` and `perch keys tombstones purge` are built.
  - **Docs:** verified against the code.
  - **Load target:** the concurrent-user target is 250 (Dakshitha), measured as met on one web process.
- **A deploy-only bug, found and fixed:** `perch serve` read the empty SQLite file instead of Postgres, so browse lists were empty and lead cards showed record ids as titles. The walks did not catch it because the walk server wires Postgres itself. Later rounds should also test the `perch serve` wiring, not only the walk server.
- **Spend.** The main ledger is $10.60 of the $100 cap. The deploy's own ledger is about $0.26 and is capped at $15 (`.env.deploy`).
- **Tests.** `make test` 942 passed; test-keys 67, test-user 107, test-redis 117, test-pg 81.

## The test deploy (live)

- **App:** https://sn4622120437.tailf0654d.ts.net:8443 (Funnel 8443 → 127.0.0.1:8200). Sign-in goes through the dev Keycloak on Funnel 10000; only `/realms/perch` and `/resources` are public.
- **Accounts:** SYNTHETIC `demo-presenter`, `demo-researcher` and `demo-student`. Passwords are only in `.env.deploy`. The account daily budget there is $5.00, and self-registration is off.
- **Live demo plan (Dakshitha):** the presenter signs in as `demo-presenter`, and the audience uses guest mode.
- **Pieces:** Postgres and Redis in Compose project `perch-v1` (127.0.0.1:5433, 6380); web and worker as user units `perch-v1-web` and `perch-v1-worker`.
- **The units run from this checkout.** A branch switch, an edit under `web/` (served live) or a `uv sync` without `--extra ml --extra anthropic` changes or breaks the deploy. Update it deliberately: commit, then `systemctl --user restart perch-v1-web perch-v1-worker`.
- **Keycloak** (`perch-dev-keycloak`) was recreated with the public hostname. So the local e2e sign-in scripts (`scripts/e2e_oidc_login.py`, `e2e_account.py`, `ux_walk --login-helper`) fail until that is reverted. Its users live inside the container, with no data volume; CLAUDE.local.md says how to re-create them.
- **Stop:** `systemctl --user stop perch-v1-web perch-v1-worker`; `docker stop perch-v1-postgres-1 perch-v1-redis-1`; `tailscale funnel --https=8443 off`; `tailscale funnel --https=10000 off`.
- **Not yet verified on the deploy:** a browser sign-in (tested from a script only), the leak check, a walk, and whether the Funnel passes each visitor's address for the per-address limits.
- **NVIDIA container toolkit** 1.20.1 is installed. The Docker restart that enables it had not been done at the time of writing. The demo worker stays native either way.

## S49 starts here (Phase 12 round 1)

1. Read Dakshitha's notes `docs/design/S48_UI_NOTES.md` (screenshots in `docs/design/s48_notes/`), the design `docs/design/S48_UI_DESIGN.md` (researcher CV optional, decided) and the fresh review `docs/design/S48_UI_REVIEW.md` (6 must-fix, many should-fix). **None of it is built yet.** A builder was started and stopped before it changed anything.
2. Run the round as REBUILD_PLAN Phase 12 says:
   - front-end UI/UX and product reviews, and back-end correctness and function reviews, all fresh-context Opus and run in parallel;
   - a design pass;
   - builders split by file;
   - QA;
   - a fresh re-check.
3. Carried into round 1:
   - Q49 Scout tuning, since the strict grounding withholds sentences in most answers;
   - the S43 and S45 should-fix lists;
   - old local-model profiles still in `perch/profiles.py`;
   - a worker systemd unit in `deploy/systemd`.
4. Write `docs/sessions/S49.md`, set its tracker row, run `make tracker`, and republish the tracker artifact (link in CLAUDE.local.md). Call the advisor after orientation.

## Worth knowing

- **Walk server.**
  - **Set up:** `scripts/walk_server.py --setup`.
  - **Start it** on 127.0.0.1:8191: `PERCH_LIMIT_GPU=3 PERCH_LIMIT_LOCK=/run/user/1002/perch-walk.lock scripts/run_limited.sh uv run --extra ml python scripts/walk_server.py`.
  - **Walk:** `uv run --no-project --with playwright --with httpx python scripts/ux_walk.py --out build/<name>`, adding `--scheme dark` for the dark run.
  - **Stop:** `pkill -f "[w]alk_server.py"` and `pkill -f "[p]erch.cli --db /tmp/perch-walk"`.
  - **Worktrees lack torch:** run with the main `.venv/bin/python` and `PYTHONPATH` set to the worktree.
  - **Fake model:** the walk uses one, so "explanation withheld" on cards is expected there.
- **Real-model numbers.**
  - **Student brief:** about $0.11, with 59 of 60 explanations shown.
  - **Researcher brief:** about $0.09.
  - **Scout bench, final run s45g:** out of scope 24 of 24, distress 5 of 5, in scope 10 of 33 pass Layer 1.
- **Load test (S47):** one GPU saturates near 41 briefs a minute. The 250-user target was met on one web process.
- **Scout hang:** it happened once, in S38. If it recurs, run `uv tool run py-spy dump --pid <pid>` before killing.
- **Untracked bench output:** nine `bench/results/scout_s32*` folders are not this rebuild's and stay uncommitted.

## Open questions (mirror of bridge/QUESTIONS.md)

- **Q45 (Dakshitha):** Fox School scholarships; the Fox page is in the dataset. Recommendation: close it.
- **Q47 (not blocking):** pg_search's AGPL licence matters only if keyword ranking returns.
- **Q48 (not blocking):** a crisis message always gets the care message, even with the budget spent. Recommendation: keep.
- **Q49 (not blocking):** Scout's strict grounding withholds sentences in most answers. It is now part of Phase 12 round 1.
- **Q50 (not blocking):** guest briefs sit in Redis as plain JSON for an hour, with no CV. Recommendation: encrypt after the demo.
- **Grading:** Dakshitha grades usefulness in `bench/results/scout_open_s45g/grades.csv` when she can.

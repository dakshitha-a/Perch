# HANDOFF.md — state for the next context window

Rewritten 2026-11-06 at about 03:20 EST, at the close of S56 (Demo Day polish). Demo Day is today, Friday 6 November 2026. The submission is due at 12:00 pm. The demo is at 3:00 pm.

## Read this first

- **The submission is `v1.2-demo-day`.** The ZIP is `dist/perch-1.0.0-054f0dc.zip`: 67.4 MB, 987 files. It was built from the tagged commit after 1151 tests passed. `main` and `rebuild/v1` point at the same commit. The S55 ZIP and the tag `v1.1-demo-day` are kept as history.
- **v1 is the submission and the demo (Dakshitha, S54).** The fallback build is offline. It stays at the tag `v0.1-demo-fallback` as history.
- **The public address serves v1 on port 443.** Sign-in is on port 10000. The address and the operator notes are in CLAUDE.local.md.
- **GPU 7 only (Dakshitha, 2026-11-06).** The live worker runs on GPU 7. Every test, walk, film or bench run also uses GPU 7, with its own lock file. Every other GPU is in use by other work.
- **Two links go to the audience:** the live site and the build tracker (link in CLAUDE.local.md). The tracker opens on the README tab. Its UI tab carries the S56 app.
- **The audience account is `demo` / `demo`.** It is shared. Every screen says so and says not to paste a real CV. A user timer wipes its data each night at 03:30. Lockout is realm-wide: after 10 wrong passwords the wait is 1 to 15 minutes.
- **The films are in `docs/films/` and were refilmed in S56.**
  - `researcher.mp4` (54 s): PI-1 by alias, with the Draft the email button glowing.
  - `student.mp4` (58 s): the SYNTHETIC persona-demo.
  - `scout.mp4` (50 s): the Cover-letter points button glowing.
  - `quick-student.mp4` (30 s at 1.5x): the slide film.
  - Each film has a WebP beside it. The name check found 0 hits in every film.
- **Run sheet:** `docs/DEMO.md`.
- **Commit trailer:** only `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never a `Claude-Session:` line.
- **In the main checkout the deploy runs from `.venv`.** Use `uv sync --extra ml --extra anthropic` only. Never run a plain `uv sync`, and never switch branches there.

## Demo Day morning checklist

1. **Clear the limits:** run `scripts/demo_reset.py --apply` with the deploy's env file sourced. It was last run at about 02:00, before the films and checks used guest limits and budget.
2. **Check the 03:30 wipe:** run `journalctl --user -u perch-demo-wipe`. Then confirm that `demo` / `demo` signs in and skips the welcome. If it does not, Dakshitha re-runs `prepare-shared`; the auto-mode guard blocks the agent from recording consent.
3. **Check health:** `curl` the public `/health`. Then `scripts/smoke_deploy.py --base <public URL>` takes about one minute and costs about 0.10 USD.
4. **Spend:** the deploy ledger is about 6.44 of its 30 USD cap.
5. **Test containers:** `perch-test-pg` and `perch-test-redis` are running again, so `make test` works. They are not needed for the demo.

## What S56 did

- **Model buttons glow while they work.** The two buttons are the researcher's Draft the email and the student's Cover-letter points. The glow is the same as the Scout box's: class `ai` with `aria-busy`. A disabled button keeps its grey fill, and the focus outline still shows. With reduced motion, the glow is a still ring.
- **Other slow waits are quiet.**
  - Busy buttons get a moss edge after 0.3 s, so Keep and exports do not flash.
  - The Reading pill sweeps gently.
  - A list that is refreshing dims after 0.25 s. The first-load skeleton is left alone.
  - The student Save buttons, the researcher's Build brief and the exports now show their busy state.
- **My Perch, student tab:** Check my fit is the primary button and comes first. Browse Temple awards comes second.
- **Process:** a design pass found 26 waiting points. A builder made the change in a worktree. A fresh Opus review followed, and 4 of its fixes were applied.
- **Checks:**
  - 1151 tests passed.
  - The walk had 0 axe violations in light and dark, 276 states each.
  - The modules load in a browser with no syntax error.
  - On the live site as `demo-student`, Save interests went busy, saved and came back.
- **The test left one SYNTHETIC interests note on `demo-student`.** It has 49 characters. It may be the test line rather than the original. Both are SYNTHETIC.
- **Media:** all four films were refilmed. The 76 screenshots and 7 tour clips were retaken from the live deploy. `points-*.png` in docs/tour have no generator and were kept. Spend was 1.05 USD.
- **Housekeeping (late S55):** the live worker moved from GPU 3 to GPU 7. The leftover QA workers were stopped. Old agent worktrees, merged branches, old build output and untracked bench runs were removed. The smoke test passed 15 of 15 on the public address.

## The deploy (live)

- **Units:** `perch-v1-web` and `perch-v1-worker`. The worker runs on GPU 7 through run_limited. The unit backup for GPU 3 is in build/. The nightly wipe is `perch-demo-wipe.timer`. Postgres and Redis run in the Compose project `perch-v1`. Keycloak is the container `perch-dev-keycloak`; never remove it.
- **Updating it:** commit, then `systemctl --user restart perch-v1-web perch-v1-worker`. Edits under `web/` go live at once, because the files are served from this checkout with no cache.
- **Walk servers** must use `PERCH_LIMIT_GPU=7` with their own lock file. Never use the default `perch-gpu.lock`, which the live worker holds.
- **Walk servers leak their workers (Q6).** A worker started through run_limited lives in its own systemd scope and survives the server. After any walk, run `pgrep -af <worktree path>` and kill what is left. Then check `nvidia-smi`.
- **Rotate after the demo:** the database role password printed in S51.
- **Known limit, after the demo:** the code-written distress reply still shows the "Cloud: Anthropic" line under it. It is a one-condition fix in web/scout.js. It was left so the films match the live app.

## Open questions (mirror of bridge/QUESTIONS.md)

- **Q6, not blocking:** walk servers leak their GPU workers. Fix this after Demo Day.

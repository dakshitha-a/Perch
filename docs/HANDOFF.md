# HANDOFF.md — state for the next context window

Rewritten 2026-11-05 at about 14:00 EST, at the close of S53 and S54. Demo Day is Friday 6 November 2026; the submission is due at 12:00 pm.

## Read this first

- **v1 is the submission and the demo (Dakshitha, S54).** `main` and `rebuild/v1` point at the same commit. The fallback build is offline; it stays at the tag `v0.1-demo-fallback` as history.
- **The public address serves v1 on port 443.** Port 8443 is closed. Sign-in is on port 10000. The address and the operator notes are in CLAUDE.local.md.
- **Two links go to the audience:** the live site and the build tracker (link in CLAUDE.local.md). Every tracker tab is current; it was read for operator details before sharing.
- **The audience account is `demo` / `demo`.** It is shared: every screen says so and says not to paste a real CV. Its data is wiped each night at 03:30 by a user timer. Lockout is realm-wide: after 10 wrong passwords the wait is 1 to 15 minutes.
- **The films are in `docs/films/`:** `researcher.mp4` (47 s, PI-1 by alias), `student.mp4` (58 s, the SYNTHETIC persona-demo), `scout.mp4` (46 s) and the slide film `quick-student.mp4` (30 s at 1.5x, with a Scout section). Each has a WebP beside it. Re-run them with `scripts/tour/demo_films.py` (see its header).
- **Run sheet:** `docs/DEMO.md`. Before the demo, run `scripts/demo_reset.py --apply` with the deploy's env file sourced.
- **Commit trailer:** only `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never a `Claude-Session:` line.
- **In the main checkout** the deploy runs from `.venv`. Use `uv sync --extra ml --extra anthropic` only; never a plain `uv sync`, and never switch branches there.
- **Chain pushes with `&&` after `make test`.** In S54 a push went out after a failing lint check because of a `;`; `main` was red for about a minute.

## What S53 and S54 did

- **S53, four fixes from Dakshitha's test:** Scout buttons read Ask and Clear, and Clear offers Undo for 8 seconds; the question box glows while Scout works; optional citizenship and state picks on both sides; the CV panel now reads plain headings such as "Education" (it had shown a skeleton forever). The footer is centred.
- **Citizenship and state:** the picks are an encrypted `profile` row (migration 0011, applied on the deploy). A closed-phrase matcher reads a record's own eligibility text. A listing the user does not meet moves lower with a note naming the field and page, and it is never hidden. 14 of 285 Temple awards state a rule. Scout and exports never carry the pick. Researcher picks are folded (Dakshitha).
- **Reviews:** a design pass, a QA walk (every new check proven to fail first) and a fresh Opus review (3 must-fix, 8 should-fix, 4 improvements), all fixed.
- **S54, the deploy:** v1 restarted on the merged code, moved to 443, fallback containers and model units stopped and disabled (GPUs 6 and 7 free). A presenter sign-in and a guest sample student were checked on the public address.
- **S54, the tracker:** a v1 Architecture page with a detailed figure and a one-slide figure; a Bench record of the move to cloud models; a Roadmap tab (what a real Temple deployment needs) with a grid figure and a cost model; the UX tab takes the S43 to S51 reviews; the UI tab plays the current v1 example exported today.
- **S54, the repo:** 76 screenshots (48 regenerated, 28 new), 9 figure PNGs, README Screens section.
- **Measured:** suites unit 1151, user 152, pg 92. Deploy spend about 5.2 of 15 USD after the films.

## The deploy (live)

- **Units:** `perch-v1-web` and `perch-v1-worker` (worker on GPU 3 through run_limited), `perch-demo-wipe.timer`. Postgres and Redis in the Compose project `perch-v1`. Keycloak is the container `perch-dev-keycloak`; never remove it.
- **Updating it:** commit, then `systemctl --user restart perch-v1-web perch-v1-worker`. Edits under `web/` are live at once.
- **Walk servers** must use `PERCH_LIMIT_GPU=6` with their own lock file, never GPU 3, or the live worker cannot start.
- **Rotate after the demo:** the database role password printed in S51.
- **Known limit, after the demo:** the code-written distress reply still shows the "Cloud: Anthropic" line under it. It is a one-condition fix in web/scout.js; it was left so the films match the live app.
- **Old agent worktrees** under .claude/worktrees hold finished branches with full venvs. Nothing sensitive is left in them; they can be removed.

## Open questions (mirror of bridge/QUESTIONS.md)

- None blocking. Q51 and Q52 closed in S54.

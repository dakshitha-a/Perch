# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S0 — Repository
- Status (done / continued): done
- Last commit: 8ad60c3 (task work); the ritual commit follows it on `main`

## What exists now (one line per subsystem)
- Repo: private GitHub `dakshitha-a/perch`, default branch `main`, remote `origin`.
- Python: uv project `perch`, Python 3.12 pinned in `.python-version`, `requires-python >=3.12,<3.13`, lockfile `uv.lock`.
- Package: `perch/__init__.py` only. No schemas, store, sources or models yet.
- Tooling: ruff 0.17.3 and pytest 9.2.0 as exact-pinned dev deps; ruff config in `pyproject.toml`.
- Makefile: `test` (ruff + pytest) and `tracker` work. `demo`, `bench`, `package` print a stub message.
- Tracker: `scripts/render_tracker.py` is stdlib only and deterministic; `make tracker` writes `docs/tracker.html`.
- Tests: 6 green. `tests/test_render_tracker.py` and `tests/test_public_hygiene.py`.
- Hygiene: `scripts/check_public.py` blocks API keys, tokens, local paths, emails and session links. `make hooks` installs it as pre-commit and commit-msg hooks.
- Docs: CLAUDE.md, docs/ (SPEC, PLAN, TRACKER, HANDOFF, SOURCES, AI_USE_LOG), bridge/QUESTIONS.md.
- `.env.example` has a header only; S1 adds the first variable (OpenAlex mailto).

## What is half-done (exact file, exact next step)
- Nothing. S0 is complete.

## Decisions made this session
- Input zips stay in the repo root but are gitignored by `*.zip`.
- The Makefile calls `uv` and accepts `UV=/path/to/uv` as an override. Machine-specific setup lives in `CLAUDE.local.md`, which is gitignored.
- The repo will be made public after dev. No personal details beyond Dakshitha's name and Temple affiliation go into files or commit messages. `tests/test_public_hygiene.py` checks tracked files.
- Flat package layout, `perch/` at the root, to match the paths in SPEC and PLAN.
- `.gitignore` ignores `data/` as PLAN S0 says. This clashes with later sessions; see Q1.

## Open questions (mirror of bridge/QUESTIONS.md, numbered)
- Q1: `data/` is gitignored, but `data/overrides/` (S2), `data/backtest/pis.csv` (S8) and `data/synthetic/` (S13) should be committed. Proposed: ignore only `data/cache/` and other generated data.

## Next session
- Session to start: S1 — Schemas, store, OpenAlex
- First command to run: `git pull && make hooks && make test`

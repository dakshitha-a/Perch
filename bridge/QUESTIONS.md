# QUESTIONS

Numbered decisions Perch-dev needs from Dakshitha. Answered items move to the bottom with the answer and date. Dakshitha may answer here directly or in the next session's opening message.

## Open

1. **`data/` in `.gitignore` (raised S0, 2026-10-28).** PLAN S0 says to gitignore `data/`, and S0 does that. Later sessions put files there that belong in the repo: `data/overrides/` in S2, `data/backtest/pis.csv` in S8 and `data/synthetic/` in S13. Proposal: ignore only generated data, such as `data/cache/`, `data/*.db` and `*.lance`, and commit the rest. Needed by S2. Until answered, S2 can force-add the overrides file with `git add -f`.

## Answered

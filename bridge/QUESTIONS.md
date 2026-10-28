# QUESTIONS

Numbered decisions Perch-dev needs from Dakshitha. Answered items move to the bottom with the answer and date. Dakshitha may answer here directly or in the next session's opening message.

## Open

1. **`data/` in `.gitignore` (raised S0, 2026-10-28).** PLAN S0 says to gitignore `data/`, and S0 does that. Later sessions put files there that belong in the repo: `data/overrides/` in S2, `data/backtest/pis.csv` in S8 and `data/synthetic/` in S13. Proposal: ignore only generated data, such as `data/cache/`, `data/*.db` and `*.lance`, and commit the rest. Needed by S2. Until answered, S2 can force-add the overrides file with `git add -f`.

2. **OpenAlex API key (raised S1, 2026-10-28).** OpenAlex now meters usage in dollars per day. Without a key, everyone on the lab node's IP shares $0.10 a day, which is about 1,000 filtered list calls. A free key gives $1 a day. Getting one needs your email, so I did not request it. Please sign up at openalex.org/settings/api and put the key in `.env` as `OPENALEX_API_KEY`. Not blocking for S1; needed before the back-test (S8) and the demo (S9).

## Answered

# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S8 — Back-test and bench
- Status: done
- Last commit: see `git log`; the ritual commit is last on `main`

## What exists now
- Back-test: `bench/build_set.py` (160 rows in `data/backtest/pis.csv`; names only in `data/overrides/pi_aliases.csv`), `bench/corpus.py` (11,202 NIH announcements in the separate bench store `data/bench/perch.db`), `bench/backtest.py`, `bench/run.py` (`make bench`).
- Results: `bench/results/RESULTS.md`. Both strata, the keyword baseline on every row, and a paired table of each config against the default on the same awards.
- Back-test numbers: 126 of 160 rows scored. Targeted, default config: 7 of 48 in the top 10; keyword-only 1 of 48. Parent: 0 or 1 of 78 under every config.
- Models per profile: `perch/profiles.py` (`PERCH_PROFILE`, default dev). Chat gemma4:26b-a4b (dev, deploy-2gpu) or qwen3:14b (deploy-1gpu). Grounder Clef or Clef-flash. Embedder Qwen3-Embedding-0.6B and reranker Qwen3-Reranker-0.6B in every profile.
- Runner-ups are one line away. specter2_base as embedder needs `data/lance` removed first, because the index has one table for every model. `systemone:clef-flash` as reranker now works through `perch.rerank.make_reranker`.
- Other bench rows: skill 2, layer-2 grounders, cost, single card. All in RESULTS.md.
- Web: Keep bar and Help step 5. Scout has eight random tap reactions.
- Private mode: designed only (`docs/design/PRIVATE_MODE.md`, synthetic persona with canaries). Built in S13.
- Tests: 129 green, offline.

## Honest limits for the results slide
- The back-test cannot separate the embedders: every MRR-difference interval contains 0 at 48 awards.
- The measured gains are the default over keyword-only, and the Qwen3 reranker over Clef as reranker.
- Parent announcements are almost never ranked in the top 10. Say so on the slide.

## Note for the dev node
- The dev profile sends chat to gemma4:26b-a4b on the primary Ollama (GPU 0). The first brief there evicts qwen3.8:27b. Set `PERCH_LLM_DEFAULT=ollama:qwen3.8:27b` to keep the old model.

## Next session: S9 — Deploy
1. Read S9 in `docs/PLAN.md`. Deploy with the profile from `perch/profiles.py` through `PERCH_PROFILE`; add `make gpus`.
2. Private-mode groundwork in S9: check whether the chosen tunnel decrypts traffic at its edge (design doc, "The secure connection").

## Decisions made this session (all in docs/DECISIONS.md)
- Back-test: 18-month window, two strata, 160 rows, unique OpenAlex match only, separate bench store.
- Validator pass rate counts both layers. Models per profile as above; embedder and reranker kept because nothing beat them measurably.
- Private mode built in S13; normal mode gets optional direction, keywords and career stage (Q16).

## Open questions (mirror of bridge/QUESTIONS.md)
- None.

# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S8 — Back-test and bench
- Status: continued (the back-test matrix needs the full corpus; it runs unattended)
- Last commit: see `git log`; the ritual commit is last on `main`

## Running unattended (started 01:05 EDT, 29 Oct)
- Corpus fetch `python -m bench.corpus` into `data/bench/perch.db` (NIH announcements on Grants.gov, 1 request per second, about 11,200 records, done near 03:30). Log `data/logs/bench_corpus.log`.
- When it exits, a detached shell reruns the fetch once for failures, then runs `CUDA_VISIBLE_DEVICES=6 make bench`. Log `data/logs/bench_matrix.log`; last line "matrix exit N". Output `bench/results/backtest_matrix.csv` and `bench/results/RESULTS.md`.
- If it failed: `CUDA_VISIBLE_DEVICES=6 make bench` (resumable: embeddings and rerank scores are cached).

## What exists now
- Back-test: `bench/build_set.py` (160 rows in `data/backtest/pis.csv`: 69 targeted, 91 parent; names only in `data/overrides/pi_aliases.csv`), `bench/backtest.py` (papers before the award start; pool = NIH announcements open in the 18 months before; date rules off; keyword-only baseline), `bench/run.py` (`make bench` matrix and table).
- Bench rows done: skill 2 (`bench/skill2.py`), layer-2 grounders (`bench/grounders.py`), cost (`bench/cost.py`), single-card (`bench/single_card.py`). All in `bench/results/RESULTS.md`.
- Models per profile: `perch/profiles.py` (`PERCH_PROFILE`, default dev). dev and deploy-2gpu: chat gemma4:26b-a4b, grounder Clef. deploy-1gpu: qwen3:14b, Clef-flash. Grounder falls back to MiniCheck if a decision server is down. Embedder and reranker still the S4 defaults.
- Decision models: `perch/llm/systemone.py` (`/v1/systemone`, verified live), `DecisionGrounder`, `DecisionReranker`.
- Web: Keep bar (count, next step, download of kept leads, `export.json?status=kept`); Help step 5.
- Fixes: embedding cache and Lance index are safe under concurrent briefs.
- Private mode: designed only (`docs/design/PRIVATE_MODE.md`, persona `data/synthetic/persona-1/` with canaries). Built in S13, not demoed.
- Tests: 126 green, offline.

## Note for the dev node
- The dev profile now sends chat to gemma4:26b-a4b on the primary Ollama (GPU 0). The first brief there evicts qwen3.8:27b. Set `PERCH_LLM_DEFAULT=ollama:qwen3.8:27b` to keep the old model.

## Next steps (S8 continued)
1. Read `bench/results/RESULTS.md`. Check the keyword baseline sits beside every row, and both strata are reported.
2. Pick the embedder and reranker winners from the matrix; write them into `perch/profiles.py` with the runner-up one line below. Update SOURCES or SPEC §7 if needed.
3. Key numbers: back-test hit@5, hit@10, MRR and the baseline into `docs/TRACKER.md`.
4. Mark S8 tasks 1, 2 and 4 done in `docs/sessions/S8.md`; S8 done; then S9.

## Decisions made this session (all in docs/DECISIONS.md)
- Back-test: 18-month window, two strata, 160 rows, unique OpenAlex match only, separate bench store.
- Validator pass rate counts both layers. Models per profile as above.
- Private mode: built in S13 (back end and front end), allowed on the public URL when every model is self-hosted; S13 split, later sessions renumbered (S16 is QA, freeze, package).

## Open questions (mirror of bridge/QUESTIONS.md)
- Q6: review the web app in the tracker's UI tab (not blocking).

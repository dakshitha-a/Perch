# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S4 — Route A, deterministic
- Status (done / continued): done
- Last commit: f00e02c (task work); later commits on `main` are tracker and ritual updates

## What exists now (one line per subsystem)
- Sources: OpenAlex, NIH RePORTER, NSF, Grants.gov fetchers; `perch fetch openalex|awards|opportunities`.
- Profile: `perch/profile.py` key papers and research threads (research work types only; recency half-life 5 y; spherical k-means, k 2 to 4 by silhouette; at least 3 papers per thread; `as_of` cut-off).
- Embeddings: `perch/embed/` (Qwen3-Embedding-0.6B default, fake for tests, SQLite cache `data/cache/embeddings.db`).
- Vector store: `perch/store/lance.py` LanceIndex (cosine + stemmed BM25) behind `VectorIndex` in `perch/store/base.py`; data in `data/lance/`.
- Retrieval: `perch/retrieve.py` per-thread dense + BM25, RRF k=60, weighted merge; stage timings.
- Eligibility: `perch/eligibility.py` dates, applicant types, excluded activity codes, title-stated restrictions, user constraints; reasons kept.
- Rerank: `perch/rerank.py` Qwen3-Reranker-0.6B CrossEncoder, cache by (model, profile hash, record) in `data/cache/rerank.db`.
- Brief: `perch/brief.py` + `perch brief <id> --route A` (retrieve 200, filter, rerank 50 to 10). Timings appended to `data/logs/brief_timings.jsonl`.
- Store: 676 opportunities (660 open or forecasted NIH, 16 archived), 710 works, 3 PIs with awards.
- Tests: 76 green; `--models fake` runs the brief with no downloads.

## How to run the real models
- `uv sync --extra ml`, then `CUDA_VISIBLE_DEVICES=3 uv run --extra ml perch brief A5057472361`.
- torch is pinned to 2.14.1+cu126 from the PyTorch cu126 index: the node's driver (565.57.01, CUDA 12.7) rejects the default CUDA 13 wheel.
- GPU 0 holds Ollama with `qwen3.8:27b` resident. Never unload it.

## What is half-done (exact file, exact next step)
- Nothing in S4.
- Clef decision servers (setup task): blocked on the llama.cpp CUDA build (Q3). The torch result suggests the `cuda/120` llama.cpp build will work.

## Decisions made this session (all in docs/DECISIONS.md)
- Research work types only for threads and key papers; minimum 3 papers per thread.
- Route A excludes forecasted, no close date, no applicant types, codes F, K99/R00, R36, SBIR/STTR, and titles stating limited competition or career stage.
- Tracker gained a Decisions tab; decisions are logged in `docs/DECISIONS.md` as they are made.

## Open questions (mirror of bridge/QUESTIONS.md, numbered)
- Q1: `data/backtest/` (S8) and `data/synthetic/` (S13) gitignore decision.
- Q2: OpenAlex API key. Dakshitha has offered one; needed at the start of S8.
- Q3: llama.cpp CUDA build failed (probe exit 4); Clef servers need a hand install.
- Q4: Temple's Grants.gov applicant category, and the v1 activity-code exclusions.

## Next session
- Session to start: S5 — Provider layer, skills 1 and 2, validator, `decide` primitive
- First command to run: `git pull && make hooks && make test`

# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S5 — Provider layer, skills 1 and 2, validator, `decide`
- Status (done / continued): done
- Last commit: ce34844 (task work); the ritual commit follows it on `main`

## What exists now (one line per subsystem)
- Pipeline (S1 to S4): sources, profile and threads, embeddings, LanceDB, retrieval, eligibility, rerank, `perch brief --route A`.
- Provider layer `perch/llm/`: `Provider` interface (chat, tools, schema, logprobs, prompt caching) in `base.py`; adapters `ollama.py`, `openai_compat.py`, `anthropic_provider.py` (official SDK, extra `anthropic`), `fake.py`. Spec strings like `ollama:qwen3.8:27b`; role config via `PERCH_LLM_<ROLE>` / `PERCH_LLM_DEFAULT`.
- Audit log `perch/llm/audit.py`: every call to `data/logs/model_calls.jsonl` (prompt hash only, model served, tokens, cost, latency) plus validation events per layer.
- `decide` `perch/llm/decide.py`: Choice, YesNo, Score; `LogprobDecider` (single label token, reads top logprobs); schema answer with confidence None where no logprobs.
- Validator layer 1 `perch/validate.py`: cited ids, dates, numbers; `generate_validated` regenerates once, then flags; unparseable output counts as a rejection.
- Validator layer 2 `perch/grounding.py`: MiniCheck-RoBERTa-Large on CPU (transformers, model-card scores reproduced).
- Skills `perch/skills/`: `summary.py` (3 to 6 topics + two sentences), `fit.py` (opportunity sentence, 1 to 3 per-paper findings joined by code, link sentence shown as an inference; profile is the cacheable system prefix; parallel).
- CLI: `perch brief <id> --explain [--llm SPEC] [--grounder minicheck|fake|none]` prints rejection rates, tokens, cost.
- Tests: 105 green, all with fake providers; rule-6 test blocks vendor SDK imports outside `perch/llm/`.

## Live results (S5)
- 3 PIs on `qwen3.8:27b` (GPU 0, Ollama): layer 1 rejected 0 of 33; layer 2 flagged 1 of 30, a false flag on a title-supported sentence (score 0.14).
- About 20k input and 5k output tokens per brief; 70 to 79 s for 10 explanations; $0.

## What is half-done (exact file, exact next step)
- Anthropic adapter not live-verified (Q5): with a key in `.env`, run `uv run --extra anthropic perch brief A5023080104 --explain --llm anthropic:claude-sonnet-5-5`; check `cache_read_tokens` > 0 on the second lead in the audit log.
- Clef servers still blocked (Q3). Jev-compatible decide adapter lands with S8.

## Decisions made this session (all in docs/DECISIONS.md)
- Fit explanation is three parts so layer 2 checks facts, not judgments.
- MiniCheck called directly through transformers, not the unpinned `minicheck` package.
- Anthropic: official SDK only inside `perch/llm/`; refusal fallback on by default; no logprobs, so `decide` gives no confidence there.

## Open questions (mirror of bridge/QUESTIONS.md, numbered)
- Q1: `data/backtest/` (S8) and `data/synthetic/` (S13) gitignore decision.
- Q2: OpenAlex API key; needed at the start of S8.
- Q3: llama.cpp CUDA build failed; Clef servers need a hand install (try the `cuda/120` build).
- Q4: Temple's Grants.gov applicant category; v1 activity-code exclusions.
- Q5: Anthropic API key in `.env` to verify the hosted tier.

## Next session
- Session to start: S6 — API (FastAPI, async jobs, stage reporting)
- First command to run: `git pull && make hooks && make test`

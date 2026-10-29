# AI-use log — Temple AI Build Challenge

Required for the final deck's "AI use declaration" slide. One row per tool per purpose. Add a row the day a tool is first used for a new purpose; do not backfill from memory later.

| Date | Tool | Exact version | Purpose | Who used it |
|---|---|---|---|---|
| 2026-10-28 | Claude Code (Claude Opus 5.5), run inside NextTex | Opus 5.5 | Initial research on the challenge rules, judges and problem bank; drafting the handoff brief | Dakshitha |
| 2026-10-28 | Claude (claude.ai, Project "AI-Build-Challenge") | Claude Fable 5.1 | Planning: reframing the problem, critiquing assumptions, ten-day plan; drafting Checkup 1 | Dakshitha |
| 2026-10-28 | Claude (claude.ai, web search) | Claude Fable 5.1 | Research round 1: checked Temple's existing funding tools, verified the $300M/R1 figures, surveyed the problem bank, compared alternative ideas | Dakshitha |
| 2026-10-28 | Claude Code CLI (model Claude Opus 5.5, `claude-opus-5-5`), session Perch-dev | 2.1.312 (Claude Code) | S0: created the private repo, uv/ruff/pytest tooling, Makefile, tracker renderer (`scripts/render_tracker.py`) and tests; writes project code from here on | Dakshitha (directing Perch-dev) |
| 2026-10-28 | Qwen3-Embedding-0.6B (Qwen, Apache-2.0), via sentence-transformers 6.2.0 on torch 2.14.1+cu126 | Hugging Face `Qwen/Qwen3-Embedding-0.6B` revision 97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3 | S4 retrieval embedder (local default): embeds public paper text as queries and public opportunity text as documents. Runs on the lab node; no data leaves it | Perch-dev for Dakshitha |
| 2026-10-28 | Qwen3-Reranker-0.6B (Qwen, Apache-2.0), via sentence-transformers 6.2.0 CrossEncoder on torch 2.14.1+cu126 | Hugging Face `Qwen/Qwen3-Reranker-0.6B` revision e61197ed45024b0ed8a2d74b80b4d909f1255473 | S4 Route A reranker (local default): scores fit of public opportunity text to a research thread built from public papers. Runs on the lab node | Perch-dev for Dakshitha |
| 2026-10-28 | Qwen 3.8 27B (`qwen3.8:27b`) on Ollama 0.32.13, already on the lab node | Ollama model id 22130167c4c2 | S5 skill 1 (profile summary), skill 2 (fit explanations) and the `decide` fallback, on public records; every output checked by validator layers 1 and 2 | Perch-dev for Dakshitha |
| 2026-10-28 | MiniCheck-RoBERTa-Large (MIT), via transformers on CPU | Hugging Face `lytang/MiniCheck-RoBERTa-Large` revision 74c8919647e61ed0f71bc177d94f10930f090068 | S5 validator layer 2: checks that each factual sentence of a fit explanation is supported by its cited public record | Perch-dev for Dakshitha |

Reminders:
- Record Claude Code's version (`claude --version`) the first time it writes project code.
- Any design tool (Figma, Canva, Firefly) a teammate uses for the deck or interface goes here too.
- If code or design patterns from NexusQC or NextTex are reused, note that here as well; the rules do not address prior work, so disclose it.

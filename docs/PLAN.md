# PLAN.md — Perch, by session

This plan is organised by **session**, not by day. A session is a goal set sized to fit in one Claude Code context window: start with a fresh context, finish the session's definition of done, run the end-of-session ritual (CLAUDE.md), and Dakshitha clears and starts the next session. Sessions have a fixed order of dependencies but no dates; the only fixed dates are the challenge milestones below.

**Perch-dev may edit this file.** Split a session that turns out too large, merge two small ones, reorder where dependencies allow, add tasks you discover, drop tasks Dakshitha removes. Every edit gets a line in the change log at the bottom with the session number, the reason, and who asked (you or Dakshitha). Never edit CLAUDE.md's standing rules; scope changes go to `bridge/QUESTIONS.md` first.

## Fixed milestones

| Date | What must exist | Sessions that must be done |
|---|---|---|
| Sat 31 Oct | Checkup 1 (one page; Dakshitha writes it) | nothing from the code; S1–S2 helpful for a real example |
| Tue 3 Nov | Checkup 2: prototype draft, screenshots, tests run, tools used | S0–S7 |
| Thu 5 Nov 12:00 | Code freeze | everything kept in the cut order |
| Fri 6 Nov 12:00 | Submission ZIP + links; 3:00 pm demo | S15 |

**Cut order if time runs short:** S14 monitoring → the Ollama demo moment inside S13 (keep the MCP server) → Route B (S11) narrows to one signal. Never cut: the pipeline (S1–S4), the validator (S5), the web demo (S6–S7), the back-test (S8), Scout's approve mode (S10).

**Context budget guidance:** a session should finish with room to spare. If the context is past roughly two-thirds and the definition of done is not close, stop at a clean commit, write `docs/HANDOFF.md`, and mark the session "continued" in the tracker rather than pushing through.

---

## S0 — Repository

Goal: a private repo with the skeleton, docs and tooling, so every later session starts from `git pull`.

1. `gh auth status`; then `gh repo create perch --private --source=. --remote=origin --push` (or create in the UI and add the remote).
2. `uv init` (Python 3.12), `.gitignore` (Python, node, `.env`, `data/`, `*.lance`), `.env.example`, `LICENSE` (MIT), `README.md` (one paragraph + how to run), `Makefile` with `test`, `demo`, `bench`, `tracker`, `package` targets (stubs allowed).
3. `ruff` + `pytest` configured; one trivial test; `make test` green.
4. Copy `docs/`, `bridge/`, `CLAUDE.md`. Add your row to `docs/AI_USE_LOG.md`. Fill the S0 row of `docs/TRACKER.md`.

Done when: private repo on GitHub, `make test` green on `main`, tracker shows S0 done.

## S1 — Schemas, store, OpenAlex

Goal: resolve a Temple researcher and pull their public works into a store with provenance.

1. `perch/schemas.py`: `Researcher`, `Work`, `Award`, `Opportunity`, `Organisation`, `Lead`, `Brief`; every record has `source`, `source_url`, `fetched_at`.
2. `perch/store/base.py` repository interface; `perch/store/sqlite.py`.
3. `perch/sources/openalex.py`: resolve by name + "Temple University" (up to 3 candidates) and by ORCID; works with abstracts (reconstruct from `abstract_inverted_index`), topics, `referenced_works`; polite-pool mailto from env. Live-verify; fixture under `tests/fixtures/openalex/`; `docs/SOURCES.md` row.
4. `perch/cli.py`: `perch resolve <name|orcid>`, `perch fetch openalex <author_id>`.

Done when: `perch resolve` → `perch fetch` stores works for one public Temple PI; fixture real; SOURCES.md row filled; tests green.

## S2 — Award sources and the award horizon

Goal: public federal awards per researcher, with dates, and the field that makes the back-test possible.

1. `perch/sources/nih_reporter.py`: Temple awards via organisation filter; project start/end; the funding-opportunity-number field under its real name. Live-verify; fixture; SOURCES.md.
2. `perch/sources/nsf.py`: Temple awards with expiration dates. Live-verify; fixture; SOURCES.md.
3. Link awards to researchers (name matching with manual-override table in `data/overrides/`); `perch profile <author_id>` prints key papers, awards and the **public award horizon** (end date of last public award).

Done when: `perch profile` works for 3 PIs with awards; horizon correct by hand check; SOURCES.md honest.

## S3 — Opportunities

Goal: open (and, for the back-test, historical) funding announcements in the store.

1. `perch/sources/grants_gov.py`: find and verify the public search endpoint and its terms; ingest open opportunities with close date, eligible applicants, award ceiling/floor, agency, activity code where present. If access is unclear, write QUESTIONS and stop this task; do not scrape.
2. NIH Guide archive: verify structured access to historical announcements (needed for the back-test). If impossible, record the fallback (closed opportunities Grants.gov still lists) in SOURCES.md.
3. `perch fetch opportunities` with nightly-refresh semantics (upsert by opportunity number).

Done when: opportunities in the store with provenance; SOURCES.md says exactly what historical coverage exists.

## S4 — Route A, deterministic

Goal: ranked, eligible Route A leads with no model involved.

1. `perch/embed/`: embedding adapter with local default (Qwen3-Embedding-0.6B) behind an interface; batch; cache by content hash.
2. LanceDB store for vectors + BM25 behind the repository interface.
3. `perch/profile.py`: recency-weighted paper vectors → 2–4 **research threads** (k-means; one thread if < 8 papers).
4. `perch/retrieve.py`: per-thread hybrid search (dense + BM25, RRF) merged across threads; top-50.
5. `perch/eligibility.py`: deterministic rules (close date, applicant types, ceiling, activity code/agency); filter before rerank.
6. Reranker adapter, local default (Qwen3-Reranker-0.6B); top-50 → top-10; cache by (profile hash, record id).
7. `perch brief <author_id> --route A` prints 10 leads with record fields only.

Done when: leads for 3 PIs; zero ineligible leads by hand check; retrieval timing logged.

## S5 — Provider layer, skills 1 and 2, validator

Goal: the first and only model calls, each bounded and validated.

1. `perch/llm/`: one interface (chat, tool calling, structured JSON); adapters for Anthropic, OpenAI-compatible, Ollama; model-per-role config; fake provider for tests.
2. `perch/validate.py` layer 1: every cited ID exists in input; no number/date in output absent from cited records. Regenerate once on failure; then flag.
3. Skill 1 profile summariser: topic labels + two-sentence summary tied to work IDs.
4. Skill 2 fit explainer: profile + one candidate (IDs) → fit 0–100, 2–3 sentences, citations as IDs; reasoning first, constrained JSON last; parallel across leads; prompt caching of the shared prefix where the provider supports it.
5. Validator layer 2: small grounding model (LettuceDetect or MiniCheck; must run on CPU in the request path); unsupported sentence → flagged.
6. Audit log of every model call: prompt hash, model, version, tokens, cost, validator result.
7. `decide` primitive in `perch/llm/` (typed choice, score or yes/no in; typed value plus confidence out) with the LLM-logprobs fallback adapter; unit tests with the fake provider. Clef-flash is the default local decision model; its Jev-compatible adapter (which also serves Clef and Jev) and the Strands Decider 2B CPU fallback land with the S8 bench rows.

Done when: `perch brief --route A --explain` produces cited explanations for 3 PIs; validator rejection rate printed; tests green with the fake provider.

## S6 — API

Goal: the pipeline behind HTTP with async jobs.

1. FastAPI: `POST /briefs`, `GET /briefs/{id}` (stages + partial results), keep/dismiss, `GET /records/{id}`.
2. Job runner (in-process background tasks for the demo; interface allows a queue later); stage reporting.
3. Brief persistence; shareable brief id; JSON export.

Done when: a brief runs end to end via curl and reports stages.

## S7 — Web app, first three screens

Goal: Find → Profile → Routes in the browser, with the evidence panel.

1. Interaction audit and UI/UX design: what goes in, what comes out, what progress to show, what must be said on screen; target users, palette, type, components. Written to `docs/design/UI.md`.
2. No-build web app in `web/` (plain ES modules, no npm), served by `perch serve` at `/`: author search and candidate pick; build brief; progress by stage.
3. Profile screen (summary, topics, threads, key papers, awards, horizon). Routes screen (lead cards: fit, record fields, cited explanation, keep/dismiss). Evidence panel from any claim.
4. Keyboard navigation, labels, contrast; touch-first and works on a phone; light and dark themes; replay mode that plays back a saved brief without the API (preview and Demo Day fallback).
5. Adversarial review of the built UI (UX, accessibility, standing rules), then fixes.
6. Screenshots to `docs/screenshots/`; UI preview tab in the tracker artifact.

Done when: a brief renders in the browser from the API; screenshots saved to `docs/screenshots/` for Checkup 2.

## S8 — Back-test and bench

Goal: the numbers for the results slide.

1. `bench/backtest.py`: for each PI in `data/backtest/pis.csv` (a teammate's set), profile from works before the award start; retrieve against announcements open at that time; rank of the actual announcement; hit@5, hit@10, MRR; keyword-only baseline on every row.
2. `make bench`: config matrix — embeddings (Qwen3-0.6B, Qwen3-4B, SPECTER2, BGE-M3), retrieval (hybrid/dense/BM25), rerank on/off, three LLMs for skill 2 (API model, Qwen3-8B local, Gemma 4 26B-A4B local). One table to `bench/results/`.
3. Cost per brief (tokens × price from the audit log) written to `docs/TRACKER.md` notes for the team.
4. Decision-model rows in `make bench` for validator layer 2 and rerank: Clef-flash (default local), Clef (accuracy challenger), Jev (hosted) through one Jev-compatible adapter, Strands Decider 2B (CPU-only fallback) and the LLM-logprobs fallback. For validator layer 2, always run Clef alongside Clef-flash. Skip any model whose access or weights are unverified, and record why in `bench/results/`.
5. Single-card validation. Bench `qwen3:14b`, `qwen3:8b` and `qwen3:30b` against the `qwen3.8:27b` baseline on validator pass rate, QA agreement, Scout task completion and wrong-tool rate. Measure each candidate on its own clean GPU from the bench pool (GPU 4 or 5) with the full deploy-1gpu stack beside it, so the nvidia-smi peak reflects what one card would carry in deployment. Use a second Ollama instance on that GPU (`CUDA_VISIBLE_DEVICES=4 OLLAMA_HOST=127.0.0.1:11435 ollama serve`) pointing at the same model store; never touch the primary service on GPU 0, where `qwen3.8:27b` stays resident. Record the nvidia-smi peak under 3 concurrent briefs and the p50 brief time. Gates: pass rate within 3 points of the baseline, QA agreement within 5 points, Scout completion within 10 points and wrong-tool rate not higher, peak VRAM under 28 GB, p50 brief time within 1.5 times the baseline. The smallest model that passes every gate becomes the deploy-1gpu default. If none passes, ship deploy-2gpu with the 27B and record why.

Done when: a results table with baseline exists; winners written into config; runner-up one line away.

## S9 — Deploy

Goal: a public URL that survives Demo Day.

1. Docker Compose (`web`, `api`, `worker`, `db`), `make demo` one command. Deploy with the GPU profile chosen in S8; `make demo` selects it through `PERCH_PROFILE` (deploy-1gpu, deploy-2gpu or dev). Add `make gpus`: nvidia-smi memory per service.
2. Outbound tunnel from the lab node (check network policy first; if blocked, document the laptop + hotspot path as primary).
3. Anonymous rate limit 10 briefs/hour; demo personas precomputed and cached; health endpoint.

Done when: the URL serves a cached brief from a phone; fallback path documented in README.

## S10 — Scout agent

Goal: the agent, visibly under control.

1. `perch/scout/`: own loop (plan → tool call → observe) over the allowlist `resolve_author, build_profile, list_awards, search_opportunities, get_org_signals, explain_fit, compare, draft_handoff, get_record`; per-brief token/dollar budget; every call logged with args and result hashes; replay command.
2. Modes: *ask before every step* (default) and *run and show me*; tool calls rendered as cards in the web app.
3. Plain-language follow-ups that re-run retrieval with constraints.
4. Fallback mode for small local models (structured prompts + validator, no native tool calling).

Done when: Scout completes 20 scripted follow-ups in `bench/scout_tasks.yaml` with the API model and at least one local model; wrong-tool and restraint rates logged.

## S11 — Route B

Goal: industry leads from public signals, honestly labelled.

1. Signal 1: company-type institutions publishing in the researcher's topics (OpenAlex). Signal 2: SBIR/STTR awards in those topics (verify SBIR.gov API first; fixture). Signal 3: company-authored works that cite the researcher's works (`referenced_works`).
2. Score = weighted overlap × recency; two independent signals required; relationship-type suggestion; every lead carries "inferred from public signals; not verified".
3. Routes screen shows Route B beside Route A.

Done when: leads for 3 PIs with signals listed; hand-judged precision recorded in the tracker.

## S12 — Compare, hand-off, export

Goal: the decision and the hand-off.

1. Compare screen: kept leads on money, time, effort, IP, evidence; sortable; evidence panel from any cell.
2. Skill 3 hand-off drafter: editable email to the chosen office; never sent; copy / open in mail.
3. PDF and Markdown export of the brief.

Done when: Find → Routes → Compare → Hand off works on the public URL.

## S13 — MCP server and private context

Goal: any platform, including local.

1. `perch/mcp_server.py` on the official Python SDK (verify version): same allowlisted tools, same validator and budgets. Test from Claude Code and from a local Ollama agent on the laptop; write the exact commands into README.
2. Private context: CV/direction input gated to the local provider only; held in memory for the session; never stored, logged, cached or evaluated; deterministic parse of dates, degree, rank, sponsors; UI states "this never leaves this machine". Exercise only with `data/synthetic/` persona.

Done when: an MCP client gets a cited brief; the private-context demo runs on Ollama with the synthetic persona.

## S14 — Monitoring (optional; first to cut)

Goal: Perch tells you before you need it.

1. Weekly job: re-run briefs when a public award is within 12 months of ending or a new opportunity scores above threshold; output is an email draft, never sent.
2. One screen listing what changed since last run.

Done when: the job runs on the demo personas and produces a draft.

## S15 — QA, freeze, package

Goal: ship.

1. Work the fix list from the QA log a teammate keeps; accessibility checklist pass.
2. Final numbers (back-test, validator rate, cost per brief) into `docs/TRACKER.md` and `docs/RESULTS.md` for the deck.
3. README final; `make package` → submission ZIP with how-to-run; confirm with Dakshitha before changing repo visibility.
4. Freeze: tag `v0.1-demo`; nothing on `main` after that except README typos.

Done when: ZIP builds from a clean clone and runs; tag pushed; tracker complete.

---

## Change log

| Date | Session | Change | Reason | Asked by |
|---|---|---|---|---|
| 2026-10-28 | — | Plan reorganised from days into sessions | Fit one session per context window | Dakshitha |
| 2026-10-28 | S0 | Teammate names replaced with roles (S8 back-test set, S8 cost notes, S15 QA log); history rewritten so no version holds them | Repo will be made public; only Dakshitha's name and Temple affiliation may appear | Dakshitha |
| 2026-10-28 | S5, S8 | Added the `decide` primitive with LLM-logprobs fallback (S5 task 7) and Jev and Laya bench rows for validator layer 2 and rerank (S8 task 4); SPEC §6, §7 and §8 updated to match | Calibrated decision models as challenger at decision points | Dakshitha |
| 2026-10-28 | S5, S8 | Laya removed; Clef-flash (default local) and Clef (accuracy challenger) added through the Jev-compatible adapter, Jev kept as hosted option, Strands Decider 2B added as CPU-only fallback; SPEC §7 and §8 updated to match | Laya replaced by Clef-flash/Clef on published Decision Index and independent tests | Dakshitha |
| 2026-10-28 | S8, S9 | Single-GPU deployment target with deploy-1gpu, deploy-2gpu and dev profiles (SPEC §11); S8 task 5 single-card validation with gates; S9 deploys the chosen profile via `PERCH_PROFILE` and adds `make gpus`. Clef server install attempted and blocked (Q3) | Single-GPU deployment target, validation gates, Clef installed | Dakshitha |
| 2026-10-28 | S7 | S7 rewritten into six tasks: interaction audit and design doc first, a no-build web app instead of React + Vite, replay mode, an adversarial review with fixes, and a UI tab in the tracker artifact | The node has Node 12 and no npm; a no-build app keeps `make demo` and the ZIP one step. Audit and review asked for by Dakshitha | Dakshitha |

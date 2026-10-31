# PLAN.md — Perch, by session

This plan is organised by **session**, not by day. A session is a goal set sized to fit in one Claude Code context window: start with a fresh context, finish the session's definition of done, run the end-of-session ritual (CLAUDE.md), and Dakshitha clears and starts the next session. Sessions have a fixed order of dependencies but no dates; the only fixed dates are the challenge milestones below.

**Perch-dev may edit this file.** Split a session that turns out too large, merge two small ones, reorder where dependencies allow, add tasks you discover, drop tasks Dakshitha removes. Every edit gets a line in the change log at the bottom with the session number, the reason, and who asked (you or Dakshitha). Never edit CLAUDE.md's standing rules; scope changes go to `bridge/QUESTIONS.md` first.

## Fixed milestones

| Date | What must exist | Sessions that must be done |
|---|---|---|
| Sat 31 Oct | Checkup 1 (one page; Dakshitha writes it) | nothing from the code; S1–S2 helpful for a real example |
| Tue 3 Nov | Checkup 2: prototype draft, screenshots, tests run, tools used | S0–S7 |
| Thu 5 Nov 12:00 | Code freeze | everything kept in the cut order |
| Fri 6 Nov 12:00 | Submission ZIP + links; 3:00 pm demo | S27 |

**Cut order if time runs short:** S30 and S32 narrow to the items marked must-fix → S22 rebuild narrows to the S21 must-fix list → S16 monitoring (done) → student mode narrows to its floor (S17 corpus and personas, S18 eligibility by rule and the two tabs, S19 scoring; drops the Scout tool and the hand-off) → private mode (S13) narrows to its floor (paste-only input, private threads, session records, self-hosted-endpoint gate, session isolation, no-logs paths, canary test; drops upload parsing, CV eligibility unlock, obfuscated export, MCP private tools) → the Ollama demo moment inside S14 (keep the MCP server) → Route B (S11) narrows to one signal. Never cut: the pipeline (S1–S4), the validator (S5), the web demo (S6–S7), the back-test (S8), Scout with its allowlist and budgets (S10).

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

6. Keep bar in the web app (Q10): after a lead is kept, a bar shows the count and the next step; until S12 its button downloads the kept leads with their records. Add it to the Help page.

Done when: a results table with baseline exists; winners written into config; runner-up one line away.

## S9 — Deploy

Goal: a public URL that survives Demo Day.

1. Docker Compose (`web`, `api`, `worker`, `db`), `make demo` one command. Deploy with the GPU profile chosen in S8; `make demo` selects it through `PERCH_PROFILE` (deploy-1gpu, deploy-2gpu or dev). Add `make gpus`: nvidia-smi memory per service.
2. Outbound tunnel from the lab node (check network policy first; if blocked, document the laptop + hotspot path as primary).
3. Anonymous rate limit 10 briefs/hour; demo personas precomputed and cached; health endpoint.
4. Private-mode groundwork (`docs/design/PRIVATE_MODE.md`): check whether the chosen tunnel decrypts traffic at its edge; `PERCH_PRIVATE_MODE`, `PERCH_PRIVATE_ENDPOINTS` and `PERCH_TLS_AT` settings; uvicorn at warning level; error handler that never echoes request bodies; core dumps off in the server process.

Done when: the URL serves a cached brief from a phone; fallback path documented in README.

## S10 — Scout agent

Goal: the agent, visibly under control.

1. `perch/scout/`: own loop (plan → tool call → observe) over the allowlist `resolve_author, build_profile, list_awards, search_opportunities, get_org_signals, explain_fit, compare, draft_handoff, get_record`; per-brief token/dollar budget; every call logged with args and result hashes; replay command.
2. Modes: *ask before every step* (default) and *run and show me*; tool calls rendered as cards in the web app.
3. Plain-language follow-ups that re-run retrieval with constraints.
4. Fallback mode for small local models (structured prompts + validator, no native tool calling).
5. Private mode: inside a private session Scout uses local models only, logs no tool arguments or results, and replay is off.

Done when: Scout completes 20 scripted follow-ups in `bench/scout_tasks.yaml` with the API model and at least one local model; wrong-tool and restraint rates logged.

## S11 — Route B

Goal: industry leads from public signals, honestly labelled.

1. Signal 1: company-type institutions publishing in the researcher's topics (OpenAlex). Signal 2: SBIR/STTR awards in those topics (verify SBIR.gov API first; fixture). Signal 3: company-authored works that cite the researcher's works (`referenced_works`).
2. Score = weighted overlap × recency; two independent signals required; relationship-type suggestion; every lead carries "inferred from public signals; not verified".
3. Routes screen shows Route B beside Route A.
4. Scout: `get_org_signals` and `search_opportunities(route="B")` return Route B leads (they say "not built yet" until now, Q18); update their tool descriptions and the Help step. Add Route B follow-ups to `bench/scout_tasks.yaml` as new tasks, keeping the 20 S10 tasks unchanged, and rerun the bench on Gemma.
5. Scout repeated-call guard: a call identical to one already run for the same question is answered from the earlier result with a note, not run again (Sonnet looped the same search up to nine times in S10's first run). Rerun the full Scout bench on Gemma and Sonnet afterwards (Sonnet about $0.30; ask before spending).
6. Rebuild the demo (`make demo`) so the public URL serves this session's work.

Done when: leads for 3 PIs with signals listed; hand-judged precision recorded in the tracker; Scout answers a Route B follow-up with cited signals.

## S12 — Compare, hand-off, export

Goal: the decision and the hand-off.

1. Compare screen: kept leads on money, time, effort, IP, evidence; sortable; evidence panel from any cell.
2. Skill 3 hand-off drafter: editable email to the chosen office; never sent; copy / open in mail.
3. PDF and Markdown export of the brief.
4. Scout: `compare` and `draft_handoff` call the new compare view and skill 3 (they say "not built yet" until now, Q18). The hand-off draft stays a draft. Add a compare and a hand-off task to the Scout bench.
5. Rebuild the demo (`make demo`).
6. Private mode egress filter: exports and hand-off drafts exclude private-derived text by default; opt-in masking of identifiers and novel phrases with typed placeholders, an in-memory key to unmask on screen, and a warning that the research direction stays visible.
7. Temple STTR partners for Route B (Q19, revised). Take the 41 awards that name Temple as research partner from SBIR.gov's bulk file. The file is in `data/cache/sbir/`, last modified 2026-01-01; use the column `RI Name`. Commit only a derived table with company, title, agency, programme, year and award date. Never read the contact columns. Add a SOURCES row. Show a company as a Route B signal ("past STTR partner of Temple") when its award text matches the researcher's main topics. Hand-check the matches on the 3 S11 PIs. Keep it only if it adds correct leads.

Done when: Find → Routes → Compare → Hand off works on the public URL.

## S13 — Private mode

Goal: private tailoring on self-hosted models that leaves no trace, on the public URL too. Build the full architecture, back end and front end (private session API, inputs, private threads, session records, egress filter hooks, the private-mode screens and Help section). It is not demoed on Demo Day (Dakshitha, 2026-10-29).

1. Verify first: whether the Ollama and llama.cpp servers log prompts by default, and NIH's early-stage investigator definition from the NIH page (both UNVERIFIED in the design).
2. Private session in memory: random session token, isolation between sessions, memory and size caps, idle timeout, "End private session"; inputs by paste or upload (parsed from bytes; text, Markdown, DOCX, PDF); self-hosted-endpoint gate; `PERCH_TLS_AT` rule on public URLs; every write path in the design's inventory switched off.
3. Tailoring: private threads at 0.6 of the thread weight (Q13 default); deterministic CV parse (degree year, rank, appointments, prior sponsors) for the career-stage unlock and sponsor history; private-only brief with no OpenAlex id.
4. Session records (`source: private`) cited in explanations and accepted by the validator in session only; lock label and the operator-named privacy statement in the UI; Help page section.
5. Private Scout: S10 built the local-only gate and turned off the Scout log, and the audit log stays in memory. Its tools still write to the rerank cache, the embedding cache (`CachedEmbedder`) and the store (researcher and works upserts). Route every one of these to memory in a private session, and include Scout sessions in the canary test.
6. Tests: canary test over files, logs, `/tmp`, browser storage and outbound requests; refusal test; isolation test; masking test. Persona: `data/synthetic/persona-1/`.
7. Normal-mode context (Q16), every field optional (a brief with none runs exactly as today): a short research direction, keywords to include or exclude, and a self-reported career stage, on the Find screen's options. Same mechanism as private threads, but saved with the brief, usable by the configured model (hosted included) and shown on the Profile as "You said"; used as a query, never cited as a fact. A CV stays private-mode only.
8. Mechanism measured (if time): RePORTER project abstract as stand-in for the unfinished proposal on the back-test rows (verify the field live), reported as an upper bound beside the public-only numbers.

Done when: the canary and isolation tests pass after full private briefs with persona-1 on a local model; a private-only brief returns cited routes.

## S14 — MCP server

Goal: any platform, including local.

1. `perch/mcp_server.py` on the official Python SDK (verify version): the same nine tools as Scout, from `perch.scout.tools.TOOLS`, with `check_arguments`, the same validator and budgets. Private tools only when the MCP client and every model are self-hosted (stdio on the server, or an authenticated local transport). Test from Claude Code and from a local Ollama agent on the laptop; write the exact commands into README.

Done when: an MCP client gets a cited brief.

## S15 — README and public release

Goal: a README that shows Perch at a glance, then the repo made public (Dakshitha, 2026-10-29).

1. README in the style of Dakshitha's NextTex repo: a hero animation, a feature tour with animated WebP clips filmed in the real app, the architecture figure, and short sections that link to separate docs (running, deployment, private mode, MCP, evaluation). Film with NextTex's pipeline: the camera script `animate.py`, credited, and its recorder ported to Python. Researchers appear by alias only.
2. A README tab on the build tracker, so Dakshitha can review it with its images.
3. Public-readiness audit: `scripts/check_public.py` and the hygiene test over every tracked file and the whole history; no local paths, machine names, emails or session links.
4. Push and make the repository public, after Dakshitha approves the README. Confirm with Dakshitha immediately before changing visibility.

Done when: Dakshitha has approved the README, and the repository is public.

## S16 — Monitoring (optional; first to cut)

Goal: Perch tells you before you need it.

1. Weekly job: re-run briefs when a public award is within 12 months of ending or a new opportunity scores above threshold; output is an email draft, never sent.
2. One screen listing what changed since last run.

Done when: the job runs on the demo personas and produces a draft.

## S17 — Synthetic scholarship corpus and student personas

Goal: a labelled sample scholarship database shaped like the real feeds, plus three student personas with a planted answer key (Dakshitha, 2026-10-29). Standing rules 11 and 12 apply to every synthetic record and persona.

1. Schema `Scholarship` in `perch/schemas.py`: name, sponsor, purpose, level_of_study (high school / associate / bachelor's / graduate / professional), field_of_study, award_type (scholarship / fellowship / grant / prize), amount_min, amount_max, deadline, eligibility (gpa_min, residency_state, citizenship, class_year, major, enrolment_status, targeted_criterion as free text or null), application_requirements (list: transcript, essay, letters_count, portfolio, interview, FAFSA), source, source_url, fetched_at. Same provenance fields as every other record.
2. `scripts/make_sample_scholarships.py`: generate 400 to 600 records from hand-written templates. The local chat model fills purpose text and application requirements from the template. A deterministic pass then sets every structured field, enforces internal consistency (deadline in the future, amount_min ≤ amount_max, level matches eligibility), injects the canary and assigns `sample:sch-NNNN` ids. The distribution of levels, award types, amounts and deadlines should look like a real database; no record is copied from any site. Output `data/synthetic/scholarships.jsonl` with a README stating it is invented.
3. Real public records beside them, kept separate: fellowship-type opportunities already in the store (Grants.gov fellowship category; NIH F, K and T activity codes), and Temple's public pages for Scholar Development and Fellowships Advising (SDFA) and college scholarship listings, fetched with attribution and stored as ordinary public records. Verify live; fixtures; SOURCES.md rows. If an office page or its terms cannot be verified live, write `UNVERIFIED` and a question rather than naming it.
4. Three student personas in `data/synthetic/`: undergraduate (3rd year), master's, PhD candidate. Each has a CV (degree year, GPA stated or not, honours, activities, posters, employment), an interests note, three achievements, and a planted answer key: which sample scholarships they are eligible for, which they are not and why, and the gap list expected per eligible lead. Canary tokens in every file.

Done when: the corpus loads into the store under `source: synthetic` with zero overlap with public records; `make test` green; a test asserts no real-organisation name appears in any sample sponsor (checked against a small list of well-known sponsors and against OpenAlex institution names in the store).

## S18 — Student mode

Goal: a student can paste a CV, interests and achievements in private mode and get fellowships (public) and scholarships (sample) with eligibility by rule, a gap list, and a hand-off. Private mode becomes an app-wide state instead of a link (design in `docs/design/PRIVATE_MODE.md`, "Private mode as a state").

1. Private mode as a state of the whole app:
   - **Header switch:** a "Private" switch on every screen replaces the link on Find. When on, the whole frame shows it: a lock, a label and a coloured edge, so the mode is never in doubt.
   - **On by construction:** every field that takes personal text (CV, draft, interests note, achievements, unpublished work) exists only inside private mode. Choosing one of them starts a private session first, before any text leaves the browser.
   - **Student implies private:** choosing Student on Find starts a private session. There is no public student path, because a student's input is always personal.
   - **A nudge, never a silent switch:** if someone pastes long or CV-like text into Find's public keyword box, a check in the browser offers to move it into private mode. Nothing is sent until they choose. No content guess ever turns the mode on or off by itself.
   - **Off means end:** turning the switch off ends the session after a confirm that lists what will be discarded.
   - **Unavailable:** where the server lacks self-hosted models, the switch shows but is disabled, with the reason. Student mode is disabled with it.
   - **Inheritance:** Profile, Routes, Compare, hand-off, export and Scout all follow the mode. A public brief stays public; a private brief is a separate brief.
2. Private-mode CV parse extended for students: level of study, expected graduation, degree year, GPA if stated, major, honours, activities, posters and talks, employment. The interests note becomes a query thread (reuse the direction thread at its existing weight); achievements become session records `private:achievement-N` that explanations may cite.
3. Eligibility by rule from parsed fields against `Scholarship.eligibility`: level, class year, graduation window, GPA minimum, enrolment status, deadline not passed. Missing information yields "may be eligible", never "eligible". Targeted criteria are shown quoted from the record with a "you decide if this applies" label; the app never asks for or stores them.
4. Gap list per lead: application requirements the CV does not evidence (letters, transcript, essay, portfolio, GPA), copied from the record.
5. Retrieval and rerank as in Route A; the skill 2 explanation cites both the student's records and the scholarship record; both validator layers; the fit sentence stays labelled inference.
6. UI: a Student switch on Find, which turns private mode on (task 1). Routes shows "Fellowships (public)" and "Scholarships (sample)" as separate tabs; the sample tab title and every card carry the badge. Compare and keep work as now. Hand-off office by level: SDFA for fellowships, Student Financial Services for scholarships, both with their public URLs as verified in S17 (`UNVERIFIED` otherwise) and the To field empty. Exports carry the sample banner. Help page (`web/help.js`) and the tracker's UI preview gain the student flow.
7. Scout: a `search_scholarships` tool with the same allowlist, validator, budgets and private-session rules. If the session nears two-thirds of its context, this task moves to S19.

Done when: the header switch, the student path and the paste nudge all start a private session before any personal text is sent (a test checks the request order); each of the three personas gets eligible leads on both tabs in a private session on the public URL; the canary test extended to student mode passes; no sample record is reachable outside student mode.

## S19 — Planted-case scoring and docs

Goal: the only numbers we will state about student mode, and the documentation.

1. `bench/student_mode.py`: for each persona, compare the eligibility verdicts and gap lists to the planted answer key. Report eligibility precision and recall, gap-list exact-match rate, and leakage (any sample record outside student mode, any synthetic text in logs or exports). Write `bench/results/STUDENT_MODE.md`, which states plainly that the corpus is synthetic and the numbers test the mechanism only.
2. Record the numbers in TRACKER.md key numbers as "Student mode (synthetic, mechanism test)".
3. README: a Student mode section with the badge visible in its screenshot, and one paragraph on what real data would replace the sample corpus (Temple's ScholarshipUniverse feed under its contract, or a licensed scholarship database) and who would own it.
4. Roadmap note in `docs/SPEC.md` Phase 3.

Done when: STUDENT_MODE.md exists with the three metrics; README updated; tracker updated.

## S20 — QA and privacy audit

Goal: every feature correct and private before the UX audit looks at it. Moved out of the freeze session so the audit and any redesign start from a fixed app (Dakshitha, 2026-10-29).

1. Work the fix list from the QA log a teammate keeps, across every feature including student mode.
2. Privacy audit of private mode and student mode against the design's write-path inventory: the monitor, Scout, MCP, exports and hand-offs. Rerun the canary test, extended to student mode in S18.
3. Leakage check: no sample record outside student mode, in the back-test, in bench results or in any number on the results page (standing rule 11).
4. Known gaps from HANDOFF triaged: fix, or record as a known limit in the README.

Done when: the QA log has no open item marked must-fix, the canary and leakage checks pass, `make test` green.

## S21 — UI/UX audit for three audiences

Goal: a comprehensive audit of the whole app for undergraduates, graduate students and PIs, and a recommendation Dakshitha can choose from, up to a full redesign and rebuild (Dakshitha, 2026-10-29).

1. Task walkthroughs on the public URL, phone and laptop, for each audience: the three student personas from S17 (undergraduate, master's, PhD) and the PI demo personas. Cover every screen: Find, Profile, Routes (grants, industry, fellowships, scholarships), evidence panel, Compare, hand-off, export, Ask Scout, What changed, Help, private mode. Record where each audience stalls, misreads a label, or cannot tell public records from sample or inferred ones. Check that every audience can tell at a glance whether private mode is on.
2. Accessibility pass against a written checklist (keyboard paths, focus order, contrast in light and dark, screen-reader labels, motion, touch targets). This is the accessibility pass for the release; S25 reruns the checklist before the freeze (renumbered from S23, S24 and S25).
3. Information architecture review: whether one app with a mode switch serves all three audiences, or whether entry points, vocabulary and defaults should differ by audience. The standing rules hold in every option: provenance visible, sample data badged, numbers copied from records, nothing sent.
4. Findings report `docs/design/UX_AUDIT.md` with screenshots, ranked by severity, plus a UX tab on the tracker. It ends with two or three options, each with a session-cost estimate: targeted fixes; a redesign of the core screens; a full redesign and rebuild. Each estimate counts refilming the README clips and screenshots, the Help page and the tracker's UI preview.
5. Write the choice to `bridge/QUESTIONS.md` with a recommended default.

Done when: UX_AUDIT.md and the tracker tab exist, every screen has been walked by every audience, and the redesign question is in QUESTIONS.md.

## S22 — Redesign and rebuild

Goal: build the option Dakshitha chose in S21.

1. Design doc first (`docs/design/`), as in S7: the screens, the flows per audience, the vocabulary, and what each standing rule looks like on screen.
2. Build in priority order so the session can stop at a clean commit at any point: Find, Profile and Routes first; then the evidence panel and student mode; then Compare, hand-off, Scout and What changed. Anything not reached keeps the current UI and still works.
3. Keep the app no-build (Node 12 on the node, no npm) unless Dakshitha decides otherwise in S21.
4. Adversarial review with fixes, as in S7; the canary test and every existing UI test still pass.
5. Help page updated for the new screens. The media refilm (README clips, screenshots, the tracker's UI preview) moved to S26 (numbered S24 and S25 earlier), after the S24 rebuild and the S25 QA fixes.

Done when: the chosen option is live on the public URL for all three audiences, `make test` green.

## S23 — Private by default, local models first

Goal: with no user accounts, nothing a user enters or receives is stored, and models run locally unless the user chooses a cloud provider (Dakshitha, 2026-10-29).

1. **Private by default.** Every brief, researcher or student, runs as an in-memory session: no stored briefs, no 24-hour reuse, no recent-briefs list in the browser, no per-user logs. Public data stays cached and indexed (OpenAlex, RePORTER, NSF, Grants.gov responses, the opportunity index), because it holds no user data. The Private switch and the separate private path fold into this one mode; the private-mode guarantees (memory only, idle timeout, exports withheld or masked) become the app's behaviour.
2. **Local models by default, cloud by choice.** A header switch, Local or Cloud, replaces the Private switch. Local is the default. Turning Cloud on names the provider (Anthropic, through `perch/llm/`) and warns that what the user enters and the brief's text are sent to that company; the user confirms first. The self-hosted gate allows the cloud provider only while Cloud is on for that session. The Anthropic spend cap still applies.
3. **Shelve monitoring.** The weekly watch needs a user to watch for, so it moves out of the app: the What changed screen, `GET /watch`, the Monday timer and the Help step go; the code moves to `perch/shelved/monitor/` with a README on how to reconnect it once a user system exists. Its tests move with it and are skipped.
4. **Docs and tests.** `docs/private-mode.md`, Help, README (known limits: real deployments can use zero-data-retention cloud keys), SPEC, the canary (now the default path, plus a Cloud-on run on SYNTHETIC text only), the S21 walk.
5. Demo rebuilt; the canary passes with Local; `make test` green.

Done when: a fresh visitor on the public URL gets a brief that leaves no record of them on the server, local models by default, the cloud warning before any cloud call, and no monitoring in the app.

## S24 — UI rebuild from the redesign canvas

Goal: build the redesign Dakshitha made on the design canvas on 2026-10-30, for both paths, filling any gaps in the same design language (Dakshitha, 2026-10-30). Spec: `docs/design/S24_REBUILD.md`; canvas sources: `docs/design/redesign/`.

1. Design language in `web/styles.css`: the tokens, type (Newsreader and Inter with offline fallbacks), shapes, motion and the laptop two-column brief layout with the right rail.
2. Landing: owl on the branch with tap reactions, "Find funding that fits.", the Researcher | Student control, the status chip that opens the Local / Cloud dialog, the footer promises.
3. Researcher path: pick the person, then the optional context panel (direction, keywords, CV, ongoing research; fill with a sample, clear); the brief with Routes, Profile, Compare and hand-off, Ask Scout, the shortlist rail and the narrow keep bar.
4. Student path: add your CV (sample and clear); the brief with What Perch read, Your options, Compare and the note, and Ask Scout for students (new tools: search options, check one against the CV by rule, explain a verdict, compare, draft a note; local only).
5. Gaps: Help, the Local / Cloud dialog, the evidence sheet on a phone, error and empty states, the export menu, the replay preview, phone layouts.
6. Tests and checks: Node and API tests for the new behaviour; `scripts/ux_walk.py` updated and rerun (0 axe violations, no sideways scroll); the canary; demo rebuilt.

7. **Draft review evaluation (Q32).** A SYNTHETIC bench: invented cover letters and draft aims with planted omissions, checked against real public records (Grants.gov listings, the Temple fellowships list). Measure the decision-only version first: code quotes what the record asks for and the checking model marks each item addressed, not addressed or unclear (accuracy against the planted answers, per model). If it is not good enough, evaluate a version where a model writes advice through the citation validator, and propose the rule 5 change in Q33. Build the Scout review into both paths only if the numbers are good; report them either way.
8. **Documents on Cloud (Q30).** After a second, stronger warning, a session with documents may use Cloud. Built behind standing rule 1: until Dakshitha applies the Q33 change, the switch keeps documents Local only. Tests use SYNTHETIC text only.
9. **Warm demo briefs (Q31).** At server start, build one brief per demo researcher and hold it in memory, never on disk; a visitor who picks one gets a fresh copy at once, with their own keep and dismiss state. Nothing about visitors is stored.

Done when: every screen in the spec is live on the public URL for both paths, light and dark, phone and laptop, with the checks above passing and `make test` green.

## S25 — UI/UX review and full QA test

Goal: one last review of the whole app as it will ship, and a full QA pass of every feature, before the freeze (Dakshitha, 2026-10-29).

1. **UI/UX review.** Rerun the S21 walk (`scripts/ux_walk.py` with axe-core) on the rebuilt S24 app for every audience: the PI demo personas, the three SYNTHETIC student personas and persona-1, phone and laptop, light and dark. Check the Local / Cloud switch and the cloud warning, the two doors, the student vocabulary and the S22 fixes. Rerun the accessibility checklist (`docs/design/A11Y_CHECKLIST.md`). An independent review reads the screens fresh. Findings go to `docs/design/UX_REVIEW_S25.md`, ranked; must-fix items are fixed in this session.
2. **Full QA test.** A written test plan, `docs/QA_PLAN.md`, with one row per feature and path: Find (both doors), Profile, Routes (grants, industry, fellowships, scholarships), the evidence panel, Compare, hand-off, export (Markdown, JSON, print), Ask Scout, Help, the Local / Cloud switch, the MCP server, the CLI, `make demo`, error states (bad id, model down, timeouts, caps). Each row is run on the public URL or the CLI, and the result is recorded as pass or fail with a note. Failures are fixed or written down as known limits.
3. **Privacy and data checks.** The canary (Local, and Cloud-on with SYNTHETIC text), the leakage check (standing rule 11), and a check that a fresh visitor leaves no record on the server.
4. Demo rebuilt if anything changed. The media are filmed after this session, in S26.

Done when: the review and the QA plan are written and run, no open must-fix item, `make test` green.

## S26 — Media refilm

Goal: the README, screenshots and tracker preview show the app as it will ship. Moved out of S22 so the media are filmed once, after S23 and after the S25 review and QA fixes (Dakshitha, 2026-10-29).

1. Refilm the README clips (`scripts/tour/film.py`, then `scripts/tour/animate.py`) against the app as fixed in S25; the `private` scene uses the new header switch.
2. Retake `docs/screenshots/` (`scripts/screenshots.py`) and the README student screenshot (the sample tab is "Scholarships and awards (sample)").
3. The tracker's UI preview with the student flow: a replay of a SYNTHETIC student brief, with `scripts/build_ui_preview.py` serving its routes.
4. README text matched to the new labels; the README tab reviewed by Dakshitha; every artifact republished.

Done when: the README media, screenshots and UI preview match the app on the public URL.

## S27 — Funding coverage and ranking tune (live, diagnose and fix)

Started 2026-10-30 from Dakshitha's own test: a theoretical chemist (A5052363442) got only NIH leads. Dakshitha runs this session as a live phase, diagnosing and fixing as we go, and closes it.

1. Fix the Grants.gov parser for non-NIH records: the agency comes from `agencyDetails` (the synopsis `agencyName` holds a contact on DoD and DOE records). Redacted DoD and NSF fixtures.
2. Eligibility: accept an "Others" applicant type when the record's eligibility text names institutions of higher education (61 of 121 open NSF listings).
3. Load NSF, DoD, DOE and other science agencies' open listings into the dev store; check every fetcher against a live response first.
4. Test set: three real Temple PIs from public records, one each in biomedical science, theoretical chemistry and experimental physics, plus a held-out PI per field.
5. Tune scoring and sorting in rounds against each PI's public funding history; report each round with the keyword-only baseline.
6. Rebuild the demo store with the new listings after a regression check; README and Help say which agencies are covered.

Done when: Dakshitha closes the session.

---

## S28 — Scout redesign, phase 1

Goal: build phase 1 of the Scout spec (`docs/design/SCOUT_SPEC.md`, section 12), as the working mock-up on the redesign canvas shows it (`docs/design/redesign/ScoutProposed.dc.html`). Phase 2 waits until after Demo Day.

1. Remove the per-step gate: drop the ask mode, the Approve and Skip buttons and the mode switch, in the loop, the hub, both Scout APIs and `web/scout.js`. Steps run as soon as the model asks for them. *(Done in S27 on the web side: the mode switch, the Approve and Skip buttons and the waiting card are gone, and Scout runs every step. Left for this task: the server's ask mode, `approve` and `skip` in the loop and hub, and the two APIs.)*
2. Add Stop: a button ends the current question between steps; the steps already done stay on screen, the rest show as not run.
3. Fix Scout to the brief: drop `author_id` from the web app's researcher tool schemas and drop `resolve_author` from its tool table. The MCP server keeps both.
4. Count Cloud steps: the session budget adds the tokens and dollars of `explain_fit` and `draft_handoff`. Label those two steps' cards Local model or Cloud, and the code-only steps "Code, no model".
5. Show how Scout read the question: one block above the answer lists each finished step with its filters as chips; the step cards collapse under the answer.
6. Words and docs: Help, the Scout hint line, SPEC §8 (replaced by the spec, including its Stack line on the borrowed approval pattern), and the ResearcherBrief and StudentBrief Scout tabs on the canvas.
7. Retest: `make test`, the UX walk on the Scout tab, and a Scout bench run on the changed loop (the final bench run stays in S33).

Done when: Scout runs with no gate on both briefs, Stop works, the read-as block and step labels match the mock-up, tests and the walk pass, and the bench shows no drop against S10's numbers.

**Phase 2, after Demo Day (not scheduled):** Keep buttons on a search step's leads; removing a filter chip reruns that one search by code with no model call; draft review if Q34 says build it.

---

## S29 — Workflow review, diagnose

Goal: find what is redundant in the UI and in the user's workflow, so S30 can remove it (Dakshitha, 2026-10-31). Nothing is changed in this session. Run as a live phase with Dakshitha, like S27.

1. **Measure the paths first.** For each task, write the steps as they are now, with the number of screens, clicks, waits and scrolls, measured by a script in `scripts/ux_walk.py` style: a PI finds their brief, reads why the top lead fits, opens its record, keeps two leads, compares them and copies a hand-off. A student does the same with fellowships and sample scholarships. persona-1 does it in private mode with a document. Add asking Scout one question and exporting. These numbers are the baseline S30 is measured against.
2. **Workflow optimizer review.** A subagent with fresh context gets the public URL, the three audiences, the measured paths and `web/`, but not the earlier audits or this session's guesses. It looks for: the same information shown in two places, controls that do the same thing, steps that can be merged or skipped, labels and hints that repeat each other, screens or panels few users need, and server work or API endpoints the UI never uses.
3. **Verify every finding.** The main session reproduces each one on the public URL or in the code. A finding that does not reproduce is dropped; one that cannot be decided is marked UNVERIFIED.
4. **Report.** `docs/design/WORKFLOW_REVIEW.md` lists the verified findings, ranked. Each one gives the evidence (a screenshot, a click count or a file and line), the proposed removal or merge, the steps or clicks it saves, which standing rule it touches if any, and a cost in hours. Provenance, sample badges, the Model and Inference tags and the evidence panel are never removed to save a click.
5. **Choice.** Dakshitha marks each item fix, defer or drop, in the report or in `bridge/QUESTIONS.md`.

Done when: the baseline paths are measured, the report is written and verified, and Dakshitha has marked the items.

## S30 — Workflow review, fix

Goal: carry out the S29 items Dakshitha marked fix, and prove the paths got shorter.

1. Each fix gets a walk check that fails on the build before it and passes after it, and every changed screenshot is opened.
2. Rerun the S29 path measurements and report each path's steps and clicks, before and after.
3. Help, the redesign canvas and the tracker's UI tab are updated to match. `make test` and the full walk pass; the demo is rebuilt and checked on the public URL.

Done when: every item marked fix is done or written down with a reason, the before-and-after numbers are in the tracker, and the demo is live.

## S31 — Fresh UI/UX review, diagnose

Goal: one more UI/UX review of the app as slimmed in S30, by a reviewer with fresh context, so the review is not anchored on the earlier ones (Dakshitha, 2026-10-31). Nothing is changed in this session.

1. **Independent review.** A subagent with fresh context gets the public URL, the three audiences (PIs, the three SYNTHETIC student personas, persona-1 in private mode), phone and laptop sizes, light and dark, and the full walk's screenshots. It is not given the S21 audit, the S25 review or the fix history. It walks every screen and reports what confuses, misleads, slows or excludes each audience, plus accessibility problems the axe run cannot see.
2. **Verify every finding.** The main session reproduces each one in a fresh browser on the public URL, with a screenshot or a measurement. Findings that do not reproduce are dropped; open questions are marked UNVERIFIED.
3. **Report.** `docs/design/UX_REVIEW_S31.md` lists the verified findings ranked must-fix, should-fix and could-fix, each with its screenshot, the audience it hurts, a proposed fix and a cost.
4. **Choice.** Dakshitha marks each item fix, defer or drop.

Done when: the report is written and verified, and Dakshitha has marked the items.

## S32 — Fresh UI/UX review, fix

Goal: carry out the S31 items Dakshitha marked fix.

1. Each fix gets a walk check that fails before and passes after, and every changed screenshot is opened.
2. The accessibility checklist (`docs/design/A11Y_CHECKLIST.md`) is rerun in full, including zoom, which S25 did not rerun.
3. Help, the canvas and the tracker's UI tab are updated. `make test` and the full walk pass; the demo is rebuilt and checked live in a fresh browser.

Done when: every item marked fix is done or written down with a reason, the walk is clean, and the demo is live.

---

## S33 — Freeze and package

Goal: ship. The QA fix list and privacy audit moved to S20, the full accessibility pass to S21, and the final UI/UX review and full QA test to S25 (Dakshitha, 2026-10-29).

1. Regression pass on the frozen build: the S25 QA plan rows touched by any change since S25; the canary and leakage checks rerun.
2. Rerun the Scout bench on the frozen build with the demo model. Final numbers (back-test, validator rate, cost per brief, Scout completion and wrong-tool rate, student mode as a synthetic mechanism test) into `docs/TRACKER.md` and `docs/RESULTS.md` for the deck. When this last test run is done, free the dev test servers: `make decide-down` stops the dev Clef-flash and Clef units, and the demo's own servers stay up. Then tell the other session sharing the node that those GPUs are free (details in the local notes). The Clef rows of `make bench` need `make decide-up` again after this.
3. README final; `make package` → submission ZIP with how-to-run.
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
| 2026-10-28 | S7, S10–S14 | Help page added in S7 (`web/help.js`); every later session that ships UI adds its feature to the Help page, with claims checked against the code | Keep the in-app tutorial current as the app grows | Dakshitha |
| 2026-10-29 | S8 | Back-test PI set built from NIH RePORTER (Q7) instead of a teammate's list; task 6 Keep bar added (Q10) | Dakshitha's answers at S8 start | Dakshitha |
| 2026-10-29 | S9, S10, S12, S13, S15 | Private mode added (design in `docs/design/PRIVATE_MODE.md`): local-only gate and logging groundwork in S9; Scout rules in S10; egress filter in S12; S13 becomes "Private mode and MCP server" (split proposed, Q11); privacy audit in S15; floor added to the cut order | Dakshitha asked for a high-privacy mode that takes a CV, unpublished work and draft proposals, runs only on local models, leaves no logs and masks anything that leaves | Dakshitha |
| 2026-10-29 | S13 to S16 | S13 split: S13 Private mode, S14 MCP server, S15 Monitoring, S16 QA, freeze, package (Q11). Private mode allowed on the public URL when every model is self-hosted, with session isolation and a server-side TLS rule (Q12 revised) | Dakshitha: split S13; a university deployment hosts its own models, so public hosting does not by itself break the privacy promise | Dakshitha |
| 2026-10-29 | S13 | Private mode: full back end and front end built in S13; no Demo Day demo | Dakshitha's direction | Dakshitha |
| 2026-10-29 | S13 | Normal-mode context fields added (direction, include and exclude keywords, self-reported career stage); CV only in private mode | Dakshitha (Q16): normal mode had no user input fields |  Dakshitha |
| 2026-10-29 | S9 | Task 1: Compose runs one app service (API, web app and in-process jobs, as built in S6) instead of four containers; the GPU models run as systemd user units | No GPU access in Docker on the node; the S6 design has no separate worker or database server | Dakshitha |
| 2026-10-29 | S11 to S14, S16 | Scout's follow-ups cascaded: S11 fills `get_org_signals` and Route B search, adds a repeated-call guard and Route B bench tasks; S12 fills `compare` and `draft_handoff`; S11 and S12 rebuild the demo; S13 routes private Scout's cache and store writes to memory and adds Scout to the canary test; S14 reuses Scout's tool table; S16 reruns the Scout bench | Gaps found in S10; Q18 answered with the default | Dakshitha |
| 2026-10-29 | S12 | Task 7 added: SBIR.gov bulk award file for Route B signal 2, kept only if it adds signal over RePORTER | Q19: the SBIR.gov API is down; Dakshitha asked to integrate the bulk file if it is beneficial | Dakshitha |
| 2026-10-29 | S12 | Task 7 (SBIR.gov bulk file) removed again; Route B stays NIH-only | Dakshitha: leave it while the SBIR.gov API is down | Dakshitha |
| 2026-10-29 | S12 | Task 7 added back, narrowed: Temple STTR partners (41 awards) from the SBIR.gov bulk file's research-partner column | Dakshitha: worth doing if useful; companies that already partnered with Temple are concrete leads | Dakshitha |
| 2026-10-29 | S12 | Worked in the order 1 to 4, 7, 6, 5: the demo was rebuilt last so it carried every change. Task 7 is done but not wired in, because it adds 0 leads under the two-signal rule (Q20) | Tasks 1 to 5 are the definition of done; one demo rebuild instead of two | Perch-dev |
| 2026-10-29 | after S12 | S16 task 2: after the last test run, stop the dev decision servers (`make decide-down`) and tell the other session on the node that their GPUs are free | The app needs only the demo's two GPUs; the dev copies exist for testing | Dakshitha |
| 2026-10-29 | S15 to S17 | New S15, README and public release (README with filmed clips and the architecture, a README tab on the tracker, a public-readiness audit, then make the repo public). Monitoring moves to S16, and QA, freeze and package to S17. Older notes that say "S16 task 2" mean what is now S17 task 2 | Dakshitha asked for an attractive README, reviewed on the tracker, as the next step before the repo goes public | Dakshitha |
| 2026-10-29 | S17 to S20 | student mode with synthetic scholarship data; freeze moved to S20. New S17 synthetic scholarship corpus and student personas, S18 student mode, S19 planted-case scoring and docs. Standing rules 11 and 12 added for synthetic records and student personas | Dakshitha's planning edit | Dakshitha |
| 2026-10-29 | S20 to S23 | QA split out of the freeze session into S20 (fix list, privacy audit, canary and leakage checks), after student mode is built. New S21 UI/UX audit for undergraduates, graduate students and PIs, ending with a redesign question; new S22 redesign and rebuild. Freeze and package is now S23, with a regression pass on the frozen build. Older notes that say "S17 task 2" mean S23 task 2 | Dakshitha asked for a full UI/UX audit once the student-facing work is built, with a redesign on the table, and for QA to move to a fitting place | Dakshitha |
| 2026-10-29 | cut order | S22 rebuild cut first, down to the audit's must-fix list; student mode next, down to its floor | Freeze is 5 Nov; a rebuild is the largest and least tested piece of work. Placed by Perch-dev; Dakshitha may reorder | Perch-dev |
| 2026-10-29 | S18, S21 | S18 task 1 added: private mode becomes an app-wide state with a header switch, turned on by construction when personal text is entered or Student is chosen, with a browser-side nudge for CV-like text in the public box; S18 tasks renumbered; the Scout tool may move to S19. S21 checks that the mode is visible to every audience | Student mode needs private mode, and a link on Find was too easy to miss. Dakshitha asked Perch-dev to decide the design | Dakshitha (direction), Perch-dev (design) |
| 2026-10-29 | S18, S19 | S18 task 7 (Scout `search_scholarships`) moves to S19, as the plan allows; S19 also refilms the tracker's UI preview with the student flow, because the preview replays a public brief and a student brief is private | Context budget of the S17 to S20 run; a private brief cannot be recorded for replay | Perch-dev |
| 2026-10-29 | S19, S22 | S19 task 5 (Scout `search_scholarships`, from S18) cut to the student-mode floor in the cut order (Q27); S19 task 6 (the tracker's UI preview of the student flow) moves to S22, whose task 5 refilms the preview anyway | Scout's tools assume a researcher and its tab is hidden on student briefs; a private brief cannot be recorded for the replay preview without new work | Perch-dev |
| 2026-10-29 | S23, S24 | New S23 "Private by default, local models first": every session in memory with no stored briefs, reuse or history (public data stays cached); a Local / Cloud header switch, local by default, with a warning naming the provider before any cloud call; monitoring shelved in `perch/shelved/monitor/`. Freeze and package moves to S24. S22 task 5 (refilm) runs after S23, so the media are filmed once. Older notes that say "S23 task 2" mean S24 task 2 (superseded by the next row: S25 task 2) | Dakshitha: with no user access system nothing should be stored; the no-private-text-to-cloud rule is a challenge rule, and a real deployment may rely on zero-data-retention cloud keys | Dakshitha |
| 2026-10-29 | S22 to S25 | Sessions reordered to the order of work: S22 task 5 (media refilm) becomes its own session S24, after S23 (private by default); freeze and package becomes S25. S22 is done without task 5. Older notes that say "S23 task 2" or "S24 task 2" for freeing the dev GPUs mean S25 task 2 | Dakshitha asked to reorder the tracker phases and cascade the changes | Dakshitha |
| 2026-10-29 | S25, S26 | New S25 "UI/UX review and full QA test": the S21 walk and accessibility checklist rerun on the S23 app, an independent review, a written QA plan run row by row, and the privacy and leakage checks. Freeze and package becomes S26; its regression pass reruns only the QA rows touched since S25. Older notes that say "S25 task 2" for freeing the dev GPUs mean S26 task 2 | Dakshitha asked for a UI/UX review and a full QA test before the freeze | Dakshitha |
| 2026-10-29 | S24, S25 | S24 and S25 swapped: S24 is now the UI/UX review and full QA test, S25 the media refilm, so the media are filmed once, after the QA fixes. S26 freeze reruns the S24 QA rows | Dakshitha asked to switch S24 and S25 | Dakshitha |
| 2026-10-30 | S24 to S27 | New S24 "UI rebuild from the redesign canvas" (spec `docs/design/S24_REBUILD.md`). The UI/UX review and full QA test becomes S25, the media refilm S26, freeze and package S27. Students get Ask Scout (Q27 revised). Older notes that say "S26 task 2" for freeing the dev GPUs mean S27 task 2 | Dakshitha redesigned the app on a design canvas and asked for it to be built before QA and the refilm | Dakshitha |
| 2026-10-30 | S24 | Tasks 7 to 9 added: draft review evaluation (Q32), documents on Cloud after a second warning behind the rule 1 change (Q30), warm demo briefs held in memory (Q31). Rule changes proposed in Q33 for Dakshitha to apply | Dakshitha's answers to Q30 to Q32 | Dakshitha |
| 2026-10-30 | S27, S28 | New S27 "Scout redesign, phase 1" from `docs/design/SCOUT_SPEC.md`; phase 2 waits until after Demo Day. Freeze and package becomes S28. Older notes that say "S27 task 2" for freeing the dev GPUs mean S28 task 2 | Dakshitha approved the Scout spec and mock-up and asked for the redesign in phases, the first in the next session | Dakshitha |
| 2026-10-30 | S27 to S29 | New S27, funding coverage and ranking tune, run live; Scout redesign moves to S28, freeze and package to S29 | Dakshitha found NSF missing in a test and asked for this session to be the current phase | Dakshitha |
| 2026-10-30 | S27, S28 | The Scout mode switch removed from the web app in S27; Scout runs every step by default. The rest of S28 task 1 (the server's ask mode, Approve and Skip code, both APIs) stays in S28 | Dakshitha: the switch should already be gone, and run should be the default | Dakshitha |
| 2026-10-31 | S29 to S33 | New S29 and S30, a workflow review to remove what is redundant in the UI and workflow, diagnosed then fixed; new S31 and S32, a fresh-context UI/UX review, diagnosed then fixed. Freeze and package becomes S33. S30 and S32 narrow first in the cut order. Older notes that say "S29 task 2" for freeing the dev GPUs mean S33 task 2 | Dakshitha asked for both reviews, each run in two parts, diagnose then fix | Dakshitha |
| 2026-10-31 | S28 | Task 1 note updated: the web side of the gate was removed in S27 (switch, Approve and Skip, waiting card); the server side remains. Tasks 2 to 7 are not built, so S28 stays | Dakshitha asked whether the Scout redesign was already done | Dakshitha |
| 2026-10-31 | cut order | "Scout's approve mode (S10)" in the never-cut list becomes "Scout with its allowlist and budgets (S10)" | S28 removed the approve mode by Dakshitha's direction (SCOUT_SPEC section 4) | Dakshitha |

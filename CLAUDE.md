# CLAUDE.md — Perch

You are building **Perch** for the Temple AI Build Challenge. Demo Day is Friday 6 November 2026; the final submission (deck + prototype ZIP + links) is due that day at 12:00 pm. No late submissions.

Perch reads a Temple researcher's public papers and lays out the routes to fund that work (grants and foundations; industry leads), every claim cited to a public record, then drafts a hand-off to the right Temple office. Tagline: *See every route to fund your work.* The agent layer is called **Scout**.

Dakshitha owns the codebase and makes every product decision; when a decision is needed, write it to `bridge/QUESTIONS.md` and continue with the next unblocked task.

## Session protocol (every context window)

The plan is organised by **session**, each sized to one context window. Dakshitha starts each session in a fresh context with a message like "Start S4" and clears when it is done.

**Start of session:** read `CLAUDE.md`, `docs/HANDOFF.md`, `docs/TRACKER.md`, then the current session in `docs/PLAN.md`. Read `docs/SPEC.md` in full only in S0 and whenever a session touches something you do not understand; otherwise read the relevant section. Set the session's tracker row to `in progress` with a start time. Write `docs/sessions/S<n>.md` with the session's tasks as a status table (copy the shape of the previous one). Run `make tracker` and republish the tracker artifact (link in `CLAUDE.local.md`). Then work the tasks in order.

**During:** commit after every task, update the task's row in `docs/sessions/S<n>.md`, then `make tracker` and republish the tracker artifact. Append each decision to `docs/DECISIONS.md` when it is made (date, session, decision, reason, who decided); plan changes still go in PLAN.md's change log. Both appear on the tracker's Decisions tab. If a task is blocked for more than 20 minutes, log it in `bridge/QUESTIONS.md` and move on. If the context is past roughly two-thirds and the definition of done is not close, stop at a clean commit rather than pushing through.

**End of session (never skip):** 1. `make test` green on `main`. 2. Update `docs/TRACKER.md` (status, finish time, commit, notes with any numbers). 3. Rewrite `docs/HANDOFF.md` completely. 4. Update `bridge/QUESTIONS.md`. 5. Run `make tracker` so `docs/tracker.html` is current, and republish the tracker artifact. 6. Commit and push. 7. Reply with three lines: session status, what the next session is, and the open questions. Then stop; Dakshitha clears.

**Editing the plan:** you may split, merge, reorder, add or drop tasks and sessions in `docs/PLAN.md` based on what you find or on Dakshitha's direction. Every edit goes in PLAN.md's change log with the reason and who asked. Scope changes (adding or removing a feature) go to `bridge/QUESTIONS.md` first unless Dakshitha already directed them. Standing rules below are never edited.

**The tracker:** `docs/TRACKER.md` is the master tracker and the source of truth; `make tracker` renders it, with the current session's task file `docs/sessions/S<n>.md` on top, to `docs/tracker.html` (a single static page, no dependencies) and to `build/artifacts/tracker.html` (the claude.ai artifact page) so Dakshitha can open it in a browser or serve it from the lab node. Keep the key-numbers table current whenever a number changes.

## Standing rules (never break these)

1. **Public data only.** No private or unpublished text in the repo, fixtures, tests, logs, or examples. Any sample data is synthetic and labelled `SYNTHETIC`. The private-context feature (SPEC §Private context) is exercised only with synthetic text on a local model.
2. **Never assume an API capability.** A fetcher is done only after it has been verified against a live response. Save one real response per source under `tests/fixtures/<source>/` and write the parser against it. Record exact endpoints, fields, rate limits and terms in `docs/SOURCES.md`. If access is unclear, stop and write a question; do not scrape around it.
3. **Numbers and dates are copied, never generated.** Award sizes, deadlines, dates and eligibility are rendered from record fields by code. No model output may introduce a number, date or dollar amount that is not in a record it cites.
4. **Provenance on every row.** Every stored record carries `source`, `source_url`, `fetched_at`. A claim without a record is not shown.
5. **Deterministic pipeline first; models are bounded.** The pipeline runs the same way every time and is what the back-test measures. Models do three jobs (profile summary, fit explanation, hand-off draft) and the Scout agent calls only allowlisted tools. Every model output passes the citation validator (`perch/validate.py`); a failed output is regenerated once, then shown without explanation and flagged.
6. **Provider-agnostic.** All model calls go through `perch/llm/` (Anthropic, OpenAI-compatible, Ollama/vLLM). No vendor SDK is imported outside that package.
7. **Nothing is sent by the app.** Hand-offs are drafts. No email, no writes to external systems.
8. **AI-use log.** `docs/AI_USE_LOG.md` lists every AI tool, exact version, purpose, date, user. Add your own row (`claude --version`) in your first session and keep it current. Any code or pattern reused from NexusQC or NextTex gets a row too.
9. **Honest about evaluation.** The back-test is NIH-only with a strict date cut-off (papers before award start). Report the keyword-only baseline on every row. Never present a mechanism as a measured gain.
10. **No fabricated facts anywhere.** No invented statistics, sources, office names or capabilities in code, docs, README or demo text. Write `UNVERIFIED` and move on.

## Engineering conventions

- Python 3.12, `uv` for dependency management, everything pinned. `ruff` + `pytest`. Type hints everywhere; pydantic v2 for all records.
- Repository interface in `perch/store/base.py`; SQLite + LanceDB (demo) and Postgres + pgvector + pg_search (Temple) are implementations behind it.
- Small commits with plain messages. `make test`, `make demo`, `make bench` must always work on `main`.
- Secrets only in `.env` (gitignored); `.env.example` lists every variable with a comment.
- README documents how to run in one command; the submission ZIP is `make package`.
- Each session's definition of done in `docs/PLAN.md` is the bar; do not start the next session's work in the same context unless Dakshitha says so.
- **Public-ready at all times.** The repo goes public after dev, and history will not be rewritten. Tracked files, commit messages and PR bodies carry no personal details other than Dakshitha's name and Temple University affiliation: no local paths, machine names, emails, account or session links, and no other people's names. Machine-specific notes go in `CLAUDE.local.md` (gitignored). `tests/test_public_hygiene.py` scans tracked files. Researchers in docs, the tracker, the README and questions are named by alias and OpenAlex id ("PI-1 (A5063022331)"); real names appear only in `data/overrides/` (`pi_aliases.csv` holds the mapping) and in real API fixtures.
- `make tracker` is a small Python script (`scripts/render_tracker.py`) that converts `docs/TRACKER.md` to `docs/tracker.html`; build it in S0.

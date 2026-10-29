# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S13 — Private mode
- Status: done. The live canary passed on the dev node, and a private-only brief returns cited routes.
- Last commit: see `git log`; the ritual commit is last on `main`

## What S13 built
- **`perch/private/`:**
  - `inputs.py` parses paste or upload from bytes: text, Markdown, DOCX, and PDF through `pypdf`.
  - `cv.py` is the deterministic CV parse and the early-stage rule, from NIH's page and its smaller-grants list.
  - `threads.py` turns each document into one thread. The private share is 0.6: proposal 0.5, direction 0.3, unpublished 0.2 (Q21).
  - `store.py` holds the overlay repository (read-only base, writes in memory) and the read-only embedding cache.
  - `session.py` holds `PrivateService` (the pipeline with every write path off) and `PrivateSessions` (30-minute idle timeout, caps).
  - `routes.py` holds the `/private/*` routes. The session id travels in the `X-Perch-Private` header only.
- **The gate:** `perch/privacy.py` has `refuse_if_not_local` and `refuse_endpoints`. `PERCH_PRIVATE_OPERATOR` is required, and `statement()` names that operator.
- **Hooks in shared code:**
  - `route_a(profile=, index_new=)`, `Constraints.career_stage_ok`, `Lead.notes`, and `Profile.salt`, so caches split when text is added.
  - `BriefService._works` and `quiet_errors`; the hand-off may cite private records, and egress decides what leaves.
  - `ScoutHub(private=)`, and Scout handles `private:you`.
- **Normal mode (Q16):** direction, include and exclude keywords, and career stage on Find, under Options. The direction becomes a query thread at 0.3, and Profile shows a "You said" section. These keys are stored only when set, so old briefs are still reused.
- **Web:** `web/private.js` (the Private mode screen, the private bar with End, masked exports and unmask) and `privateApi` in `api.js`. Lock labels on private threads, citations and records. Help has a private-mode step and "How leads are ordered".
- **Tests:** `tests/test_private.py` has 16 tests: canary, isolation, refusal, masking, idle, uploads, context fields, and no browser storage.
- **Live run:** `scripts/private_canary.py`, rerun in S16 on the frozen build.
- **Back-test variant:** `bench/proposal.py` puts the funded abstract in as a stand-in proposal. It is an upper bound: 7 to 16 of 48 in the top 10.
- **Tracker:** a Persona tab shows persona-1 for the team.

## Numbers
- 208 tests pass. No API spend this session; the ledger is $2.05 of $100.
- Live canary: the private-only brief had 8 of 8 explained leads citing private documents. Nothing changed under data/, and no canary turned up anywhere.

## Demo
- Not rebuilt in S13. The public URL still runs the S12 build, and private mode is off there (Q22).
- The new Find fields and Help sections reach the public URL at the next `make demo`.

## Known gaps, for a later session
- **Index lag:** a private brief searches the index the public pipeline keeps. New opportunities appear only after a normal brief indexes them.
- **Scout's search in a private session:** it builds threads from public papers only.
- **Thread labels:** a private thread's label is its most frequent words. On persona-1 the word "synthetic" leads every label.
- **From S12, still open:**
  - The hand-off opening has no layer-2 check.
  - Compare's PAR close dates.
  - Replay mode has no compare or hand-off.
  - OpenAlex company types are trusted.

## Next session: S14 — MCP server
1. Read S14 in `docs/PLAN.md`. The `mcp` SDK on PyPI is 2.3.0, released 2026-10-02; its API has not been checked yet.
2. Build `perch/mcp_server.py` from `perch.scout.tools.TOOLS`, with `check_arguments` and the budgets, over stdio. Private tools go only through stdio, and only behind the gate.
3. Test with the SDK's own stdio client in pytest. Write the `claude mcp add` command into README and check it against `claude mcp --help`. The laptop Ollama agent cannot be tested from this node, so mark it UNVERIFIED.

## Open questions (mirror of bridge/QUESTIONS.md)
- Q20: should a past Temple STTR partner count as an industry lead on its own? Default: no.
- Q21: how the private documents share the 0.6. Default: proposal 0.5, direction 0.3, unpublished 0.2; the CV gets none.
- Q22: turn private mode on at the public demo URL? Default: off.

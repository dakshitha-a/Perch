# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S11 — Route B
- Status: done
- Last commit: see `git log`; the ritual commit is last on `main`

## What Route B is now
- `perch/route_b.py`: `gather()` fetches the signals, `score_leads()` scores them, and `make_leads()` builds Lead records. It uses no model.
- Signals:
  - Company works citing the researcher's papers (OpenAlex `cites:`, chunks of 100 ids).
  - NIH SBIR/STTR awards matching their main topics (RePORTER; the SBIR.gov API returns 403, Q19).
  - Other company works in their top 3 topics, newest 300, last 3 years.
- Rules:
  - A record counts toward one signal only.
  - A lead needs two kinds of signal. The top 5 are kept.
  - Papers with more than 30 authors do not seed Route B.
  - The researcher's own papers are never evidence.
  - Names merge only on an exact match after normalising.
- The service stage `route_b` runs after `route_a`. Lead ids are `<brief>:B<n>`. The lead's `explanation` holds the code-written signal sentences, and `inference` holds the label.
- CLI: `perch brief <id> --route B`. Outputs for 3 PIs and the hand check are in `bench/results/route_b/`.
- Web: a Grants and Industry switch on Routes, industry cards with signals and evidence records, and organisation and lead views in the evidence panel. Help is updated.
- API: Route B leads carry `organisation` and `signal_items`. Export includes the signal records. Briefs from older code (no `route_b` stage) are not reused. The UI offers "Build again" for them.

## Scout
- `get_org_signals` and `search_opportunities(route="B")` return industry leads. On a brief they are the stored leads. Otherwise they are found and kept in memory.
- Repeated-call guard in `loop._answer_repeat`: a repeat within one question is never run and never asked.
- Scout's rules are the S10 text. An added Route B line made Gemma skip the search in t04. The "inferred" label travels in the tool result.
- Bench: 25 tasks (the S10 20 plus b01 to b05). Sonnet 20/20 and 5/5; Gemma 19/20 and 5/5. Gemma t06 fails on the S10 code too. The guard never fired. Sonnet ran with the removed rules line (RESULTS.md says so).
- Spend: S11 $0.34 of a $0.60 cap. The ledger is $1.62 of $100.

## Demo
- Rebuilt. The three demo briefs were built fresh, each with 5 industry leads. The Industry tab was checked on the public URL.

## Known gaps, for a later session
- OpenAlex institution types are trusted. Sciensano, a Belgian public health institute, shows as a company on a demo brief. A small override list in `data/overrides/` would fix such cases.
- Merging is strict. "Samsung Electronics" and "Samsung" stay as two leads.
- The SBIR signal joined a company in only 1 of 14 hand-checked leads, so nearly every lead is the citing signal plus the topic signal.
- Route B precision was judged by Perch-dev on the same PIs used to set the 30-author cap. Dakshitha should spot-check `bench/results/route_b/JUDGMENTS.md`.
- Earlier today PI-2's profile counted 173 papers on the S10 commit and 172 on current code. A rerun of the current code gave 172 twice, and the cause was not found. The store's count matched the session start.
- From S10, still open: the structured fallback rejects inline list numbers. Private Scout sessions still write caches and store records (S13). Route B Scout calls outside a brief also write organisations and evidence to the store (S13 must cover this too).

## Next session: S12 — Compare, hand-off, export
1. Read S12 in `docs/PLAN.md`. Compare needs to handle Route B leads (no money or deadline fields; evidence strength from signals).
2. `compare` and `draft_handoff` in `perch/scout/tools.py` still return "not built" (`NOT_BUILT`).
3. Task 7: Temple STTR partners. The bulk file is already in `data/cache/sbir/award_data.csv` (368 MB, gitignored). 41 rows name Temple in `RI Name`. Never read its contact columns.

## Open questions (mirror of bridge/QUESTIONS.md)
- None. Q19 answered: Route B's SBIR signal stays NIH-only; Temple's past STTR partners come from the bulk file in S12 task 7.

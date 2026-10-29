# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session
- Session: S12 — Compare, hand-off, export
- Status: done. Find → Routes → Compare → Hand off works on the public URL.
- Last commit: see `git log`; the ritual commit is last on `main`

## What S12 built
- **Compare** (`perch/compare.py`, `GET /briefs/{id}/compare`, `web/compare.js`): kept leads in one sortable table.
  - Columns: Money, Closes, Activity code, Instrument or relationship, Evidence, and the office under each lead.
  - Each cell is copied from a record or counted from it by code. An empty cell reads "Not in the record" and sorts last.
  - There is no effort, IP or likelihood column, because no record states them (DECISIONS).
- **Hand off** (`perch/skills/handoff.py`, `POST /briefs/{id}/handoff`, `web/handoff.js`):
  - The model writes a 2 to 4 sentence opening only. Code writes the lead list, the dates, the amounts and the papers.
  - A phrase check bans advice, company intent and claimed collaboration. Two failures give a plain opening and a flag.
  - The To line is empty, and a link opens the office page. Office names are in `perch/offices.py`, from research.temple.edu/about-us.
  - A draft is not a stage. It is never stored and never sent. The limit is 30 drafts an hour per visitor.
- **Export** (`perch/export.py`): `/export.md` and `/export.html`, a print page the browser saves as PDF. Both carry the Grants.gov notice.
- **Scout**: `compare` and `draft_handoff` are built. A draft shows in full on its card. There are 3 new bench tasks: c01, h01 and h02.
- **Egress** (`perch/egress.py`): text citing a `private:` record is withheld from exports and drafts. There is an opt-in `Masker` with an in-memory key. Its UI is S13 work.
- **STTR** (`perch/sttr.py`, `scripts/sbir_temple.py`, `data/sbir/temple_sttr_partners.csv`): 41 Temple STTR awards. It is not wired in, because it adds 0 leads under the two-signal rule (Q20).
- `default_models(fake=True, llm=...)` now uses `llm` for all three skills when it is given.

## Numbers
- 194 tests pass.
- Scout bench: Sonnet 20/20, 5/5 and 3/3 ($0.41). Gemma 18/20, 5/5 and 2/3.
- Gemma t04 failed this time and passed in S11. The cause is not known (RESULTS.md).
- Spend: S12 $0.43 of a $0.50 cap. The ledger is $2.05 of $100.

## Demo
- Rebuilt. The demo briefs were reused, because no stage changed.
- The public flow was checked at 390 px on PI-4 (A5026494099). The two test keeps were restored afterwards.

## Known gaps, for a later session
- The hand-off opening gets no layer-2 grounding check, only layer 1 and the phrase check.
- Compare's "Closes" for PAR announcements is the record's close date, often years away. It is copied, not explained.
- Replay mode has no compare or hand-off. Both say they need the live app.
- From S11, still open: OpenAlex company types are trusted (Sciensano), and name merging is strict.
- Private Scout and Route B Scout calls still write to the store (S13).

## Next session: S13 — Private mode
1. Read S13 in `docs/PLAN.md` and `docs/design/PRIVATE_MODE.md`.
2. Use `perch/egress.py` for exports and drafts in a private session. Add the opt-in mask, the unmask view and the warning to the UI.
3. The validator must accept session records. Then the egress hook in `draft_handoff` is the path that runs, not the validator.

## Open questions (mirror of bridge/QUESTIONS.md)
- Q20: should a past Temple STTR partner in the researcher's topics be an industry lead on its own? Default: no.

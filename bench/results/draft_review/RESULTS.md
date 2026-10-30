# Draft review evaluation, decision-only (S24 task 7, Q32)

**What this measures:** whether a checking model can mark each point a funding record makes as addressed or not in a draft. Code quotes the points from the record (`bench/draft_review/items.py`); no model writes anything.

**Data:** 10 SYNTHETIC drafts (8 draft aims, 2 cover letters), written by Perch-dev with planted omissions, against 5 real Grants.gov records (PAR-25-044, PAR-25-272, PAR-25-235, PAR-25-120, PA-25-422). That is 44 marks: 25 points addressed and 19 left out. The keys were written by Perch-dev with the drafts. They are a planted answer, not an expert judgment. This is a mechanism test on a small set, not a measured result about real drafts.

**Run:** 2026-10-30, demo models. Marks: support above 0.65 is addressed, below 0.35 is not addressed, and between is unclear. These thresholds were fixed before the run. No pass bar was fixed before the run.

| Checker | Correct of 44 | Left-out points caught (of 19) | Addressed points marked missing (of 25) | Unclear | Time |
|---|---|---|---|---|---|
| Clef (the deploy-2gpu grounder) | 36 | 17 | 4 | 4 | 6.4 s |
| Clef-flash | 31 | 18 | 12 | 0 | 2.1 s |
| MiniCheck | 19 | 19 | 25 | 0 | 0.9 s |
| Gemma 4 26B-A4B, `decide` three-way choice | 30 | 5 | 0 | 7 | 37.2 s |

- **Clef is the best checker here.** It got 36 of 44 marks right. It caught 17 of the 19 left-out points. It wrongly called 4 of the 25 addressed points missing.
- **MiniCheck marks everything missing.** Its 19 correct marks are exactly the 19 left-out points.
- **Gemma rarely says a point is missing.** It caught 5 of 19 omissions.
- **Most records give a thin checklist.** Of 663 open NIH listings in the demo store, 300 give no checklist and 125 give one or two points. Grants.gov descriptions are short; the full announcement is not in the record.

## Recommendation

Do not build the draft review into Scout for Demo Day. Reasons:

- **The set is small.** Ten drafts with keys written by the same author as the drafts cannot show the checker is reliable.
- **Most records cannot use it.** 425 of 663 open listings give fewer than three points.
- **A wrong "missing" mark costs the user time.** Clef made 4 such marks in 25.

The decision-only version did better than an LLM making the same decision, so a model writing advice (a rule 5 change) is not needed to try this later. Q34 asks Dakshitha whether to build it anyway, with Clef only and only for records with three or more points.

Files: `marks.csv` (every mark), `summary.csv`, `bench/draft_review/` (the drafts, keys and code).

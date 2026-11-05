# S50: the orchestrator's notes for round 3 (2026-11-05)

From the second live capture on the deploy (real model, fit-4; `scripts/live_capture.py`, output in build/s50_live, not tracked) and the integrated screens.

## Better than in round 1

- **Fit explanations are honest:** a call outside the work says so ("The fit is weak, because these papers center on … malignant blood disorders, while SHINE targets nonmalignant hematology").
- **Scout's "which kept lead fits best":** it now names both kept leads with their ranks and what each card says.
- **Hand-off:** fluent, dates and links copied from the records, kept Temple internal calls left out.

## For round 3

- **Cover points all marked unsupported:** all five points on the top lead carry `unsupported`. The points cite papers as full `https://openalex.org/W…` URLs while the records are keyed `W…`. Check whether the grounder finds the paper text at all; this looks like an id mismatch, not five bad points.
- **Centre and programme grants ranked first:** a P30 Cancer Center Support Grant is rank 1 for one researcher. An individual lab cannot apply for it. The explanation says so, but the rank does not. Consider a code-written note or a rule for institutional mechanisms (P30, P50, U54, P01 parent).
- **Thin student listings:** on a listing that gives only an award's name, the model writes "The record names … and gives no further detail". MiniCheck marks it unsupported, and it tells the student nothing. Skip the model for such records and show a code-written line instead; it also saves spend.
- **Entry labels in student text:** "Your achievement A presented a poster …" reads badly. Use the entry's own first words, or "One of your entries".
- **Same papers on most cards:** the per-lead paper choice helps, but a researcher with few recent papers still sees the same two on most cards. Acceptable; mention it only if a reviewer finds it confusing.
- **Industry leads in the capture** carry OpenAlex institution URLs as their record ids; the screen shows the company name. Check that no screen or export shows the URL as a title.
- **Merged duplicate awards:** carry over an amount stated only on the dropped copy, with that copy's source (decided in S50).

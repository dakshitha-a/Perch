# Student mode: planted-case scoring (SYNTHETIC)

**Everything scored here is invented.** The scholarship corpus and the three student personas are SYNTHETIC (data/synthetic/README.md). These numbers test whether the mechanism (CV parse, rules, gap list, retrieval and the privacy path) does what it was written to do on cases planted for it. They say nothing about accuracy on real scholarships or real students, and they are not a result about Temple.

The answer keys were written by hand from the rules in data/synthetic/README.md before the rule code existed. Positive means "eligible" or "may be eligible".

## Summary

| Persona | Brief | Planted retrieved | Precision | Recall | Verdict exact | Gap list exact |
|---|---|---|---|---|---|---|
| persona-ug | 48 s | 6 of 8 | 1.00 | 1.00 | 6 of 6 | 3 of 3 |
| persona-masters | 39 s | 6 of 8 | 1.00 | 1.00 | 6 of 6 | 3 of 3 |
| persona-phd | 45 s | 7 of 8 | 1.00 | 1.00 | 7 of 7 | 4 of 4 |
| all |  | 19 of 24 | 1.00 | 1.00 | 19 of 19 | 10 of 10 |

## Reading these numbers

- **The rules are expected to match.** The keys and the rule code follow the same written rules, so a perfect match shows the code does what the rules say. It is a check of the code, not evidence that the rules are right for real awards.
- **Retrieval is the real test here.** 5 of 24 planted records never reached a brief, 2 of them ones the student may apply for (sample:sch-0008, sample:sch-0013). The rules never saw them. Each brief keeps the 40 records nearest the interests note out of 500.
- **Precision and recall count only retrieved records.** Counting the missed ones, the student would see 10 of 12 planted records they may apply for (end-to-end recall).
- **Fellowships are not scored.** They are public listings with no key; the best verdict there is "may be eligible" by design.

## Leakage

- `sample_record_public_api`: none
- `public_briefs_checked`: 6
- `sample_in_public_brief`: none
- `persona_canary_in_export`: none
- `export_without_banner`: none
- `persona_canary_in_data_files`: none
- `persona_canary_in_app_log`: none

## Every planted case

| Persona | Record | Key | App | Key gaps | App gaps |
|---|---|---|---|---|---|
| persona-ug | sample:sch-0001 | eligible (None) | eligible (None) | transcript, essay | transcript, essay |
| persona-ug | sample:sch-0002 | not eligible (gpa) | not eligible (gpa) | — | — |
| persona-ug | sample:sch-0003 | not eligible (class_year) | not eligible (class_year) | — | — |
| persona-ug | sample:sch-0004 | not eligible (level) | not eligible (level) | — | — |
| persona-ug | sample:sch-0005 | may be eligible (residency) | may be eligible (residency) | essay, letters | essay, letters |
| persona-ug | sample:sch-0006 | may be eligible (targeted) | may be eligible (targeted) | transcript, fafsa | transcript, fafsa |
| persona-ug | sample:sch-0007 | not eligible (graduation) | not retrieved | — | — |
| persona-ug | sample:sch-0008 | eligible (None) | not retrieved | essay, portfolio | — |
| persona-masters | sample:sch-0009 | eligible (None) | eligible (None) | essay | essay |
| persona-masters | sample:sch-0010 | not eligible (enrolment) | not eligible (enrolment) | — | — |
| persona-masters | sample:sch-0011 | not eligible (level) | not eligible (level) | — | — |
| persona-masters | sample:sch-0012 | may be eligible (citizenship) | may be eligible (citizenship) | transcript | transcript |
| persona-masters | sample:sch-0013 | eligible (None) | not retrieved | essay, interview | — |
| persona-masters | sample:sch-0014 | not eligible (graduation) | not eligible (graduation) | — | — |
| persona-masters | sample:sch-0015 | not eligible (gpa) | not retrieved | — | — |
| persona-masters | sample:sch-0016 | eligible (None) | eligible (None) | transcript | transcript |
| persona-phd | sample:sch-0017 | may be eligible (gpa_unstated) | may be eligible (gpa_unstated) | essay, gpa | essay, gpa |
| persona-phd | sample:sch-0018 | eligible (None) | eligible (None) | transcript | transcript |
| persona-phd | sample:sch-0019 | not eligible (level) | not retrieved | — | — |
| persona-phd | sample:sch-0020 | not eligible (graduation) | not eligible (graduation) | — | — |
| persona-phd | sample:sch-0021 | eligible (None) | eligible (None) | essay, interview | essay, interview |
| persona-phd | sample:sch-0022 | may be eligible (targeted) | may be eligible (targeted) | essay | essay |
| persona-phd | sample:sch-0023 | not eligible (enrolment) | not eligible (enrolment) | — | — |
| persona-phd | sample:sch-0024 | not eligible (major) | not eligible (major) | — | — |

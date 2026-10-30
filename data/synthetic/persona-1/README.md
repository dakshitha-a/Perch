# SYNTHETIC persona 1 — test input for private mode (S13)

Everything in this folder is invented. The person, department, dates, awards and
results do not exist. Do not attach these files to a real researcher's OpenAlex
profile: that would state false facts about a real person. Use them only for a
private-only brief or with a synthetic profile.

- Topic inspiration (public preprints, cited only for the topic; no text copied):
  arXiv 2404.15335 (gait cycle data from shoe-worn sensors for early Parkinson's
  detection) and arXiv 2405.13082 (survey of AI in gait-based neurodegenerative
  disease diagnosis).
- Each file holds a unique canary token (`PERCH-CANARY-…`). The S13 leak test runs a
  full private brief and then checks that no canary appears in any file under
  `data/`, any log, browser storage, `/tmp`, an export, or an outbound request.

| File | Stands in for | Canary |
|---|---|---|
| `cv.md` | a current CV | PERCH-CANARY-CV-7Q4X |
| `specific_aims_draft.md` | an unfinished grant proposal | PERCH-CANARY-AIMS-K2M9 |
| `unpublished_manuscript.md` | unpublished work in preparation | PERCH-CANARY-MS-T8V3 |
| `context.json` | a research direction and keywords, for the pick screen's "Fill with a sample" (S24) | PERCH-CANARY-DIR-Z5P1 |

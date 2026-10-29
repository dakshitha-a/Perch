# DECISIONS.md — decision log

Perch-dev appends one row per decision as it is made, newest at the bottom. Plan changes (tasks and sessions added, moved or dropped) go in the change log at the bottom of `docs/PLAN.md` instead. `make tracker` shows both on the tracker's Decisions tab. Rows before S4 were collected from HANDOFF.md and commit history at the start of S4.

| Date | Session | Decision | Reason | Decided by |
|---|---|---|---|---|
| 2026-10-28 | S0 | Flat package layout, `perch/` at the repo root | Matches the paths in SPEC and PLAN | Perch-dev |
| 2026-10-28 | S0 | Repo kept public-ready: no personal details beyond Dakshitha's name and Temple affiliation; git hooks and a test block secrets, local paths, emails and session links; machine notes in gitignored `CLAUDE.local.md` | Repo goes public after dev; history will not be rewritten later | Dakshitha |
| 2026-10-28 | S0 | History rewritten once to remove session links, a local path and teammate names; names replaced with roles | Clean history before anything is shared | Dakshitha |
| 2026-10-28 | S1 | One tracker artifact with Current, Master and Archive views, republished each session and task | Dakshitha follows progress from the browser | Dakshitha |
| 2026-10-28 | S1 | OpenAlex key optional, sent as a Bearer header, never in URLs | OpenAlex now meters a daily dollar budget; keys must not leak into logs | Perch-dev |
| 2026-10-28 | S1 | Name resolution filters on `last_known_institutions` = Temple | Spec asks for Temple researchers; misses people who left (recorded in SOURCES) | Perch-dev |
| 2026-10-28 | S2 | OpenAlex works page by number, not cursor | Cursor paging past page 1 returns 401 without a key | Perch-dev |
| 2026-10-28 | S2 | Award horizon = latest `end_date` across all fiscal-year records of linked awards | End dates move between fiscal years with extensions | Perch-dev |
| 2026-10-28 | S2 | RePORTER agency shown as the record's own abbreviation, no "NIH" prefix | RePORTER also lists AHRQ, which is not NIH | Perch-dev |
| 2026-10-28 | S2 | Back-test awards should start in FY 2012 or later | `opportunity_number` is mostly empty before FY 2012 | Perch-dev |
| 2026-10-28 | S2 | Key papers skip works with more than 30 authors unless fewer than 5 remain | Consortium papers crowded out the researcher's own work | Perch-dev |
| 2026-10-28 | S2 | `data/*` gitignored except `data/overrides/` (interim answer to Q1) | The override table must be committed; the rest of Q1 is still open | Perch-dev |
| 2026-10-28 | S3 | NIH Guide archive not scraped; Grants.gov archived listings are the back-test source | No documented structured archive; standing rule 2 | Perch-dev |
| 2026-10-28 | S3 | Grants.gov attribution notice shown wherever its data appears (README, CLI, web app in S7) | Required by the Grants.gov API terms | Perch-dev |
| 2026-10-28 | S3 | Activity code read from NIH-style titles such as "(R01 ...)" or "(Parent R01)" | Grants.gov has no activity-code field | Perch-dev |
| 2026-10-28 | S3 | Grants.gov list fields sorted at parse time | Order varies between calls, so refresh reported false changes | Perch-dev |
| 2026-10-28 | after S3 | `decide` primitive added; Clef-flash default local decision model, Clef challenger, Jev hosted, Strands Decider 2B CPU fallback, LLM-logprobs fallback | Calibrated decision models as challengers at two decision points | Dakshitha |
| 2026-10-28 | after S3 | Deployment target is one 32 GB GPU, two at most; profiles deploy-1gpu, deploy-2gpu, dev | Realistic deployment footprint | Dakshitha |
| 2026-10-28 | after S3 | Clef server install stopped at the failed CUDA probe and handed to Dakshitha (Q3) | Instruction: stop on any build, download or CUDA failure | Dakshitha |
| 2026-10-28 | S4 | Torch and sentence-transformers live in an optional `ml` extra; tests use a fake embedder | Keeps `make test` light and offline | Perch-dev |
| 2026-10-28 | S4 | Torch must be a CUDA 12.x build on this node | Default torch 2.15 wheel is CUDA 13.2; the driver (565.57.01) supports CUDA 12.7 and torch reported "driver too old" | Perch-dev |
| 2026-10-28 | S4 | Threads and key papers use research work types only (article, review, preprint, chapter, conference paper or abstract, dissertation, letter) | OpenAlex lists supplement files and "Data from" records as works; 170 of 710 stored works were not research | Perch-dev |
| 2026-10-28 | S4 | A research thread needs at least 3 papers; k with a smaller cluster is rejected | A 1-paper thread appeared in live data |  Perch-dev |

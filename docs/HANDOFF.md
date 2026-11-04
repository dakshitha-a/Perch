# HANDOFF.md — state for the next context window

Written at the close of S38 and S39 (2026-11-04, 09:03 EST). Dakshitha asked for S35 to S48 to run back to back in one orchestrating context ("carry on till everything is finished, all phases"), so this file is updated at each close.

## Read this first

- **Work on `rebuild/v1`.** Every commit and all bookkeeping land there. "`make test` green on `main`" reads as green on `rebuild/v1` until the Friday gate. `main` is not developed.
- **The plan.** `docs/REBUILD_PLAN.md`. Read its "Revision on 4 Nov 2026" section first: it overrides the text below it.
- **The fallback.** The hybrid demo is frozen at d6f6210 (tag `v0.1-demo-fallback`). The local notes list the machine paths.
- **The gate.** Thursday 5 Nov at 6:00 pm. The student path must work end to end on the new stack, or the fallback is submitted on 6 Nov.
- **Compute rules.** Every heavy job runs through `scripts/run_limited.sh`: 16 cores for CPU jobs, or `PERCH_LIMIT_GPU=3` for one GPU with 4 cores. One CPU job and one GPU job at most, each with its own lock. Never GPUs 0, 6 or 7, and never ports 8090, 8093, 8097 or 8098, which are the fallback demo.
- **Background work.** Every background shell, agent or monitor is checked at least every 30 minutes and acted on (Dakshitha, 4 Nov). A stall watch goes on every long job.
- **Credentials.** Agents' worktrees have no `.env`, and copying it is blocked. Real-provider runs happen in the main checkout.

## Where the rebuild stands

- **S34 to S37 done.** Phases 0 to 2: the contract `docs/ARCHITECTURE_V1.md`, Postgres with pgvector, encryption and the key store, the job queue, Redis, and the corpus in `perch_dev`.
- **S38 done (Phase 3).** v1 runs the embedder, reranker and MiniCheck on one GPU, and the model text on Anthropic.
  - **Profile.** `cloud-gpu` is the default, with 100 candidates reranked and dense-only ranking. `cloud-cpu` is the no-GPU fallback, with 14 candidates.
  - **Back-test.** Targeted hit@10 is 0.250 for dense with the 0.6B reranker on GPU, and 0 for keyword-only. The 4B reranker showed no measurable gain.
  - **Cost.** A real researcher brief costs $0.083 on average and takes a median of 37.7 s.
  - **Scout bench.** Sonnet scored 30 of 30.
  - **Where the numbers are.** `docs/RESULTS.md`, in the S38 section.
- **S39 done (Phase 4a).** `perch fetch temple-pages` reads 142 Temple pages into a gitignored cache. `perch extract temple-pages` proposes records on Haiku and keeps only quoted values. The pilot is in `data/temple/pilot_s39.jsonl`.
- **Spend.** The ledger is $3.55. The `.env` cap is $32.60.
- **Tests.** 558 passed and 77 skipped on `rebuild/v1`. test-pg 47.

## Next: S40, Phase 4b

- **Running at the close.** A Sonnet agent is building dedupe, the versioned dataset, the feed importers, the hand-check tool and a generated SOURCES table. It works in a worktree, with the fake model only. When it reports, merge it.
- **Then run in the main checkout:**
  - the full extraction, with about $1 to $2 on Haiku;
  - building the dataset;
  - loading it into `perch_dev`;
  - writing the 10% hand-check sheet.
- **The hand-check.** It needs a reviewer. Perch-dev fills it against the cached pages, and Dakshitha may spot-check.

## Worth knowing

- **Scout hang, cause unknown.** A Scout bench run hung for about 7 hours on a lock (futex wait, 0% CPU) after one Sonnet call. A rerun under a stall watch passed. If it recurs, take a `uv tool run py-spy dump --pid <pid>` before killing it. Model slots (`perch/compute.py`, one slot) are a suspect if a slotted model is ever called while another holds the slot.
- **Student brief cost.** Not measured. The v1 student path arrives in Phases 5 and 6. Measure it in S46.
- **CUDA worker image.** Not built. The Compose worker still says `cloud-cpu` until Phase 10 task 1b.
- **Loose ends from S37.**
  - Redis and the shred hooks are not wired into web startup.
  - Nothing calls quotas yet.
  - Brief rows live in a scratch SQLite file until Phase 5.
  - `perch/user/data.py` must check for no rows before `create=True`.
- **Hygiene.** If a Temple award title contains a demo researcher's last name, `test_researcher_names_stay_out_of_shareable_docs` fails. The fix is a narrow allowlist.
- **Untracked bench output.** Nine `bench/results/scout_s32*` folders are not this rebuild's and stay uncommitted.

## Open questions (mirror of bridge/QUESTIONS.md)

- **Q45 (Dakshitha):** Fox School scholarships. Phase 4 covers the Fox page. Recommendation: close Q45.
- **Q47 (Dakshitha, not blocking):** pg_search's AGPL licence. It matters only if keyword ranking returns. Parked.

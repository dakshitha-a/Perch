# S50 back-end review (round 2 of 3)

Fresh-context review of the back end on `rebuild/v1`, read-only. Scope: the code round 1 added or changed since commit 6e124e2, the round 1 items it deferred, and anything else found on the way. Round 1 is in S49_BACKEND_REVIEW.md and S49_RECHECK.md; its IDs start with B. This round's IDs start with C.

Effort scale: S is under an hour. M is one to three hours. L is half a day or more.

Tests run here: `test_saved.py`, `test_spend_meter.py` and `test_validate.py`. Result: 9 passed and 17 skipped. The skipped tests need Postgres, so the saved-list, job, scheduler and race tests did not run in this review. `make test` supplies the database, so they run there.

## Round 1 deferred items, now

- **Now matter more:** B7, B11, B12, B18 and B23. Round 1's own fixes raised them. The retry fix B8 makes B7 cost money. The permanent timeout from B6 turns B23 into a failed brief. The nightly precache and the Temple internal group load B12 and B23. The saved list loads B11 and B18. They are C1, C8, C13, C14 and C15 below.
- **Still open, same weight:** B19, B21, B22, B24 and B37. B22 is narrower now: a timeout no longer starts a second attempt, so only a lost lease can run two attempts at once.
- **Still open, simplify only:** B29, B30, B32, B33, B34, B35 and B36. B29, B30 and B34 are still a scope call for Dakshitha.
- **Not on the deferred list but still open:** B15. A failed purge-user retry is still lost. This is C9.

## Must-fix

- **C1 A brief that waits for the model slot now fails for good:** Round 1 made a timeout end the job as `failed` instead of requeueing it. The 300-second clock still starts at claim, and the wait for the single model slot counts against it. The slot's own wait limit is also 300 seconds. So when the slot is busy, a brief ends with "This brief took too long and was stopped" and is not retried. The busiest time is the nightly precache, see C2. The fix is to start the deadline when the first stage starts, or to leave time spent waiting for the slot out of the deadline. Treat `SlotTimeout` as retryable. Where: perch/jobs.py:489, perch/jobs.py:527, perch/compute.py:83, perch/compute.py:92. Effort: M.

- **C2 The nightly precache now runs by default and competes with live briefs:** The scheduler is on unless `PERCH_SCHEDULER=0`. Every night at 02:00 UTC it queues one precache job for each Temple-affiliated researcher in the store. That is 9 or 10 pm in Philadelphia. All 16 job threads may take precache jobs, and every one queues on the same model slot as user briefs. The slot is first come, first served, so job priority does not help a brief once it is running. A user who builds a brief in that hour can hit C1. The researcher list also grows with every author anyone looks up. The v1 test deploy runs from this checkout, so its next restart turns this on. The fix is to cap precache at one or two running jobs, or to give precache its own worker with `--kinds precache --concurrency 1`. Set `PERCH_SCHEDULER=0` in the walk server, and decide whether the test deploy should run it before Demo Day. Where: perch/cli.py:778, perch/jobs.py:719, perch/precache.py:42. Effort: S.

- **C3 My Perch shows a dead brief as "running" forever:** The job overlay from B1 runs only in `GET /briefs/{id}`. The My Perch list at `/me/briefs` reads `brief.status` from the stored row, and nothing writes `failed` to that row when the job times out, dies, is cancelled or is refused for consent. My Perch is now the signed-in home, so the user sees "running" there and "failed" on the brief page. The fix is to write the terminal status to the brief row when the job ends. A cheaper fix is to apply `job_overlay` to each summary in the list. Where: perch/user/routes.py:185, perch/user/briefs.py:852, perch/api.py:779. Effort: S.

## Should-fix

- **C4 A double click on Save makes two rows, and Unsave then fails to remove the item:** `save` reads the saved rows and inserts when the record is missing. Two requests that arrive together both insert. `listing` merges them by record id but shows only one `saved_id`. Unsave deletes that one row, and the item is still listed as saved. The fix is to have `remove` delete every saved row with the same record id, or to dedupe in `save` under a lock. Where: perch/user/saved.py:56, perch/user/saved.py:66, perch/user/saved.py:97. Effort: S.

- **C5 Most server errors are still not retried:** `is_transient` accepts only httpx transport errors and `httpx.HTTPStatusError`. The local model adapters raise `ProviderError` on a 503 or a 429, with no httpx error attached. The Anthropic SDK raises its own status errors for 429, 500 and 529. `SlotTimeout` is not covered either. So the model-server errors that B8 was meant for still end the brief at once. The fix is to give `ProviderError` a status code and to treat 429 and 5xx as transient, plus the SDK's overloaded and rate-limit errors and `SlotTimeout`. Where: perch/service.py:770, perch/llm/openai_compat.py:81, perch/llm/ollama.py:85. Effort: S.

- **C6 A refused model call is billed by the provider but metered at zero:** The Anthropic adapter writes the refusal's tokens to its file budget and then raises `Refusal`. `SpendMeter.call` has no result, so it settles the user's hold at zero and writes no ledger row. Round 1 made refusals a normal path that withholds one explanation, so they now pass quietly. The fix is to carry the usage on the `Refusal` exception and settle it like a normal result. Where: perch/llm/anthropic_provider.py:120, perch/user/spend.py:65. Effort: S.

- **C7 A timeout on a free local model is charged to the user:** The B25 fix settles the estimate, 15,000 to 30,000 micro-dollars, on any exception whose class name has "Timeout" in it. A llama.cpp or Ollama server costs nothing, but a slow local server still uses up the user's daily allowance. The user then sees "today's budget is used up" for calls that cost nothing. The fix is to charge the estimate only when the model has a non-zero price in `call_cost`. Where: perch/user/spend.py:72, perch/user/spend.py:99. Effort: S.

- **C8 A retry now pays for every explanation again:** B8 retries a brief after a network failure. The retry runs all stages again, and Route A builds new leads with no explanation, so every fit call is made and paid again. The public text cache saves this only for briefs with public inputs. A signed-in brief with a CV or documents pays twice, and up to three times. The fix is to keep a lead's explanation when the same lead id and record come back, or to skip stages already marked `done`. Where: perch/service.py:310, perch/service.py:556. Effort: M.

- **C9 A failed shred hook still loses its retry:** This is round 1's B15 and it is unchanged. The purge-user handler clears the user's rows, and that deletes its own job row. When a shred hook failed, it raises `RetryableError`, but `finish_error` finds no row, so nothing retries and nothing alerts. Standing rule 1 needs this deletion to finish. The fix is to queue an ownerless follow-up purge before raising, or to write an audit row that the daily purge picks up. Where: perch/user/delete.py:152, perch/user/delete.py:154. Effort: S.

- **C10 The poll cache stores a record before checking that it is public:** `_CachedRepo.get_any` puts the loaded record into the process-wide `PublicReads` dict and only then checks its kind. A brief or a lead sits there until the next line removes it, and another thread could read it in between. Today only public signal ids reach this call, but standing rule 5 says user data is never cached. The fix is to load the record, check its kind, and only then store it. Where: perch/api.py:553. Effort: S.

- **C11 A past-cycle date has no age limit:** The researcher Temple-internal rule and the student rule keep a Temple page whose date is more than 31 days past, with the line "Check the page for this year's date". There is no upper limit, so a page last dated 2019 is shown as open. The open-anytime rule got a ten-year cap. A cap of about 13 months fits "recurs yearly". Where: perch/eligibility.py:221, perch/student.py:209. Effort: S.

- **C12 The Temple internal group embeds every Temple page on each brief:** `temple_internal` lists up to 500 Temple pages and embeds all of them on the GPU for each brief. It then reranks them. The vectors are already in `record_vectors`. This adds model-slot time to every brief, which feeds C1. The 500 limit also cuts the list without a word. The fix is to read the stored vectors, or to cache the page embeddings by record id and ingest epoch. Where: perch/brief.py:52, perch/brief.py:77. Effort: S.

- **C13 The saved list is heavy and loses kept leads:** Each `GET /me/saved` decrypts up to 200 saved rows and the 50 most recently updated full briefs, with all their leads. It then runs one record query per item. The route has no rate limit, and it is the signed-in home. A lead kept in the 51st brief drops off the list without a word. This is B18 made worse. The fix is to batch the record reads, to add `_limit`, and to store kept leads in a small row of their own. Where: perch/user/saved.py:100, perch/user/saved.py:108, perch/user/routes.py:135. Effort: M.

- **C14 The web still uses a 4-connection pool with the worker role:** This is B11. `v1_repo_factory` is now shared by `serve`, `mcp` and `scout`, and it still builds a 4-connection pool with `role="worker"`. The saved list, browse, the brief poll and every record read share those 4 connections. The fix is one pool from `app.state` with `role="web"`. Where: perch/cli.py:466, perch/cli.py:477. Effort: S.

- **C15 The rerank cache is still a local SQLite file:** This is B12. It now has two more users. The nightly precache runs up to 16 threads at once, and the Temple internal group reranks on every brief. Each one opens its own connection with a 5-second lock timeout. A "database is locked" error fails the brief or the precache job. Where: perch/rerank.py:73, perch/service.py:451. Effort: M.

- **C16 Scheduler: a partial precache is never finished:** The tick lists every researcher and submits their jobs inside the maintenance thread, while holding the scheduler's transaction open. If a submit fails part way, the next tick finds some `precache:...:<day>` rows. It then skips the day, so the other researchers get no precache. The worker also writes no heartbeat while the tick runs. The fix is to check each author's key, or to run the enqueue as a job of its own. A bad `PERCH_PURGE_AT` value also stops the worker at start. Where: perch/jobs.py:715, perch/jobs.py:665. Effort: S.

- **C17 A link check passes a cut-off record URL and hides its digits:** `validate.check` accepts a link when it appears anywhere inside a cited record's text or URL. A link cut short, such as the first part of a Grants.gov detail URL, passes. The new M4 step then removes the link's digits before numbers are checked. So a wrong link, and the number inside it, both go through. The fix is to accept a link only when it equals a record's `source_url` or a whole URL in the evidence text. Where: perch/validate.py:143, perch/validate.py:149. Effort: S.

- **C18 The losing twin request is still charged quota:** `quota.admit` runs before the twin check from B4. When two identical requests race, the losing one deletes its brief but keeps its quota charge. The fix is to give the charge back when `_same_request_won` returns a pair. Where: perch/user/briefs.py:707, perch/user/briefs.py:712. Effort: S.

- **C19 The walk does not test the deploy's code paths:** This is B21. The walk worker runs only `brief,purge`, so Scout, cover-point and hand-off jobs queue forever there. The walk and `e2e_student_brief.py` still build `HybridRepository`, which the deploy no longer uses. The scheduler is on in the walk worker too. Where: scripts/walk_server.py:117, scripts/walk_server.py:128, scripts/e2e_student_brief.py:84. Effort: S.

- **C20 Shared per-brief state across threads:** This is B22, now narrower. `BriefService._ctx` is keyed by brief id. Two attempts of the same brief still overlap when a database blip loses the lease and the reaper requeues the job while the old thread runs on. The first attempt to finish removes the entry, and the other fails with a KeyError. Pass the profile through the run instead. Where: perch/service.py:324, perch/service.py:524. Effort: S.

- **C21 Works are fetched only once per author:** This is B24, and precache now depends on it as well. A researcher's new papers never reach a brief or the nightly precache unless ingest refreshes them. Decide on a refresh age. Where: perch/service.py:345. Effort: S.

- **C22 Error bodies have even more shapes:** This is B19. The new saved routes return `{"detail": {"error": code}}`, but their 503 returns a sentence. The cancel route returns `{"id", "cancelled"}`. One envelope for every error is still the fix. Where: perch/user/routes.py:128, perch/api.py:877. Effort: M.

## Simplify or remove

- **C23 Guest brief encryption protects less than it seems:** The guest's brief key is stored in the same Redis as the sealed briefs. A Redis snapshot or replica therefore holds both. The docstring says this honestly. Guest briefs hold only public inputs, and each sealed write costs three more Redis calls and a Postgres transaction for the lease check. Keep it if Q50 asked for it. Otherwise a plain value with the existing one-hour TTL is simpler. Where: perch/user/briefs.py:428, perch/user/briefs.py:540. Effort: S.

- **C24 The plain-JSON fallback in `open_guest` is dead:** Values written before S49 expired after one hour. Remove the branch. Where: perch/user/briefs.py:473. Effort: S.

- **C25 `perch/store/hybrid.py` serves only the walk and one e2e script:** Move both to `PostgresRepository`, as C19 says, and delete the file. Where: perch/store/hybrid.py, scripts/walk_server.py:117. Effort: S.

- **C26 The no-accounts path and the closure runners:** These are B29, B30 and B34, unchanged. Over 1,500 lines serve only the fallback tag. This is still a scope call for Dakshitha. Where: perch/api.py:466, perch/jobs.py:809, perch/cli.py:488. Effort: L.

- **C27 Job settings are written twice, and `ingest` has no handler:** This is B32, unchanged. Where: perch/jobs.py:104, perch/jobs.py:185. Effort: S.

- **C28 The Redis response cache is still unwired:** This is B33. `redisx.cache_get` and `cache_put` still have no callers. Wire them to `/filters` and `/samples`, or delete them. Where: perch/redisx.py:340. Effort: S.

- **C29 Two small leftovers:** `worker_heartbeat.models_loaded` is written as false and never read, which is B35. `api.client_key` and `redisx.client_addr` both find the client address, which is B36. Keep only `client_addr`. Where: perch/jobs.py:614, perch/api.py:466. Effort: S.

- **C30 Full encrypted rewrites per stage:** This is B37, unchanged. The B2 fix adds a decrypt and a second write on each conflict. This is fine at today's size, and it can wait until leads get their own rows. Where: perch/user/briefs.py:305. Effort: M.

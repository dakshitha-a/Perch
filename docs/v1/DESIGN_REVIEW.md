# DESIGN_REVIEW.md — review of ARCHITECTURE_V1.md

Phase 1, task 6 of `docs/REBUILD_PLAN.md`. An independent design review with fresh context, written 2026-11-03 before any v1 code exists. It was given the architecture document, the plan, the reuse map, the provider and SSO notes, and the current code. It was not given the author's conclusions.

## Verdict

The document is a strong base. The envelope design, the ids-only job payloads, the separate keys database and the response-cache rules are sound. It is not yet safe to hand to implementation agents verbatim. Seven items would break on first contact. The row-level security as written blocks its own SECURITY DEFINER functions and guest jobs. The job lease lets one job run twice after a timeout. The OIDC state is not bound to the browser. All address-keyed limits collapse onto the load balancer's address. Exception text can carry user text into logs. The nonce counter has no home. Each fix is small and is listed below. The SHOULD-FIX items are mostly places where an agent would have to guess. Of the twelve decisions in section 12, ten hold. D-6 needs a change, and D-11 needs its arithmetic written down.

Counts: 7 MUST-FIX, 17 SHOULD-FIX, 9 COULD-FIX.

## Findings

### 1. MUST-FIX — FORCE RLS blocks every SECURITY DEFINER function

- **Where:** Section 2.1, the bullets "Cross-user work uses SECURITY DEFINER functions" and "Force RLS".
- **Problem:** The four functions are owned by `perch_owner`, so they run as `perch_owner`. The fenced tables use `FORCE ROW LEVEL SECURITY`, which applies RLS to the owner too. Every policy is written `TO perch_web, perch_worker`. No policy names `perch_owner`, so Postgres denies every row to the owner by default.
- **Failure:** `perch_login_user` cannot see the existing `users` row on a second sign-in. Its INSERT then hits `UNIQUE (issuer_hash, subject_hash)`, so every returning user fails to sign in. `perch_claim_job` would fail the same way if `jobs` is forced. `perch_inactive_users` returns no users, and `perch_delete_user_rows` deletes nothing, so the 12-month purge and delete-my-data silently do nothing.
- **Change:** Create a `NOLOGIN` role `perch_definer` that does not own the tables. It owns only the four functions and holds only the table grants those functions need. Each fenced table gets an explicit policy `TO perch_definer USING (true) WITH CHECK (true)`. This works on managed Postgres, where no superuser exists to grant `BYPASSRLS`. Where the host allows it, `BYPASSRLS` on that role is a shortcut, UNVERIFIED until the host is chosen. `perch_owner` keeps DDL. State in 2.1 that FORCE stays on. Add a test that each function returns rows when called as `perch_web` or `perch_worker` with no `perch.user_id` set.

### 2. MUST-FIX — RLS has no write path for rows with a NULL user

- **Where:** Section 2.2, the policies on `jobs` and `spend_ledger`. Section 3.6, `JobContext.user_tx`.
- **Problem:** The `perch_web` policy on `jobs` is `user_id = current user`, used for INSERT too. A guest job has `user_id` NULL, and `NULL = x` is never true. The guest policy would admit the row only if `perch.guest_sid_hash` is set, but nothing in the contract ever sets it, and `user_tx(None)` is not defined. The `spend_ledger` policy is described as read-only, but the worker must insert ledger rows with a NULL `user_id` for guest, system and bench calls.
- **Failure:** The first guest brief fails at `submit` with an RLS violation. If that is patched, it then fails on its first model call when the ledger insert is refused. The Friday gate is the guest brief, so the gate fails.
- **Change:** Write every policy as full SQL in 2.2, not as prose. For `jobs` and `perch_web`, add a guest policy with both `USING` and `WITH CHECK` on `user_id IS NULL AND guest_sid_hash = decode(current_setting('perch.guest_sid_hash', true), 'hex')`. For `spend_ledger` and `perch_worker`, use `FOR INSERT WITH CHECK (true)`. Add `guest_tx(sid_hash)` beside `user_tx(user_id)` in `perch/store/pg.py`, and say which one each request path uses.

### 3. MUST-FIX — A timed-out job can run twice, and its stale thread can still finish it

- **Where:** Section 3.3, "Lease", "Hard timeout" and the reaper SQL. Section 3.6, `run_forever`.
- **Problem:** At the hard timeout the helper stops heartbeating and the reaper requeues the job. The first handler only stops at its next `ctx.cancelled()` check. A provider call can block for two minutes, so the handler keeps running. `lease_owner` is the worker id, which every thread in that process shares. If a thread in the same process claims the requeued job, the stale thread's heartbeat and its final `UPDATE ... state = 'succeeded'` match the new lease.
- **Failure:** Two copies of one brief run at the same time. Both bill the provider. Both rewrite the same encrypted `brief` row, and the last write wins. The stale copy can then mark the job `succeeded` while the new attempt is still running. The 200-jobs test does not catch this, because it never times a job out.
- **Change:** Make `lease_owner` the pair worker id plus thread id, and use `attempts` as a fencing token. Every heartbeat, `stage`, `save_partial` and terminal update carries `WHERE id = $1 AND lease_owner = $2 AND attempts = $3`. A zero-row update raises `LeaseLost` in the handler. User-data writes made by a job check the same token inside the same transaction. Add a test where the handler sleeps past its timeout and assert one billed run and one terminal update.

### 4. MUST-FIX — The OIDC state is not bound to the browser

- **Where:** Section 7.1, `AuthProvider.begin` and `complete`. Section 7.2, steps 1 and 2. Threat T8.
- **Problem:** State, nonce and the PKCE verifier live only in Redis under `perch:oidc:<state>`. Nothing ties that entry to the browser that started the login. PKCE does not help here, because the server holds the verifier.
- **Failure:** An attacker starts a login, signs in at the IdP as themselves, and stops before the callback. They send the callback URL to a student. The student's browser completes the login and is now signed in to the attacker's account. The student uploads a CV, which the attacker then reads. This is login CSRF.
- **Change:** `GET /auth/login` sets a pre-auth cookie `__Host-perch_oidc` with a random value, a 600-second `Max-Age`, `HttpOnly`, `Secure` and `SameSite=Lax`. The Redis entry stores the SHA-256 of that value. `complete` reads the entry with `GETDEL`, so it is single-use, then compares the hash with `hmac.compare_digest` and clears the cookie. In the same section, also pin the rest of the token checks: an allowlist of signing algorithms, JWKS cached with refresh on an unknown `kid`, `azp` checked when present, a clock skew of 60 seconds, and a `return_to` rule written as code. The `return_to` rule must accept only a value that starts with one `/`, contains no `\`, and does not start with `//`.

### 5. MUST-FIX — Every address-keyed limit collapses onto the load balancer's address

- **Where:** Section 4.1, the guest quota key. Section 4.3, the `login` and `guest_job` scopes. Section 1.1, "Scaling".
- **Problem:** Today `perch/api.py` trusts forwarded headers only from `127.0.0.1` and `::1`, through `SERVE_OPTIONS`. In Compose or behind any load balancer, the peer address is the proxy's. The document never says how the client address is derived. Separately, `PERCH_PEPPER_GUEST` is used in 4.1 but is missing from the table in 1.3. The worker checks the guest quota by `addr_hash`, but a job row carries only `guest_sid_hash`, so the worker cannot find the right counter.
- **Failure:** In production every visitor has the same address. Twenty sign-ins in ten minutes, site-wide, lock out everyone. Five guest briefs in ten minutes, site-wide, stop all judges. One guest spending 0.10 USD stops every guest for the day.
- **Change:** Add `PERCH_TRUSTED_PROXIES` to 1.3, as a list of CIDRs whose `X-Forwarded-For` is honoured. Define `client_addr(request)` in 7 as the rightmost untrusted hop, keyed by /64 for IPv6, as today. Add `PERCH_PEPPER_GUEST` to 1.3, given to `web` only. Put `addr_hash` in the guest job payload as an id-pattern field, so the worker can charge the right counter. Key the `login` limit by address and also by a global ceiling, not by address alone.

### 6. MUST-FIX — Exception text can carry user text into logs

- **Where:** Section 3.5, "Enforcement". Section 6.4, "Never logged". Threat T6.
- **Problem:** The only stated control is the `Crashed` middleware in `web`. The worker has none. Pydantic's `ValidationError` puts the offending input value in its message. Decrypted CV JSON is validated against `perch/user/models.py`, and job payloads are validated at `submit`. Today `BriefService.run` stores `f"{type(e).__name__}: {e}"` on the brief and calls `traceback.print_exc()` in `perch/service.py`. That handler becomes the `brief` job handler. Uncaught exceptions in job threads also go to stderr through `threading.excepthook`.
- **Failure:** One malformed CV field raises a `ValidationError` in a worker. Its message, with a line of the student's CV, goes into the container log and possibly into the brief's error text. This breaks rule 5. The Phase 6 canary scan only catches it if the test happens to trigger that error.
- **Change:** Add a section "Errors and logs" that binds both processes. Handlers never format an exception message into any log, column or response. The worker logs the exception class, the job id and a fixed `error_code` only. `sys.excepthook` and `threading.excepthook` are replaced at start with a scrubbed version. Pydantic errors are reduced to `e.errors(include_input=False, include_url=False)` with locations only. No APM or log handler captures local variables or request bodies. The Phase 6 leakage test adds a case that forces a validation error on a canary CV.

### 7. MUST-FIX — The nonce counter has no column and no transaction

- **Where:** Section 6.1, "Nonces". Table `user_keys` in 2.2.
- **Problem:** The design says `encrypt_field` keeps a per-user counter in the keys database and rotates at 2^30. `user_keys` has no counter column. A write to a second database on every encryption also has no shared transaction with the data write. It adds a cross-database round trip to every `save_partial`, saved item and Scout turn.
- **Failure:** An agent either invents a column or skips the counter, and the two encryption modules built in Phase 2 disagree. If the counter is built, the keys database becomes the busiest write path in the system, and every stage write of every brief waits on it.
- **Change:** Drop the database counter. Keep the process-local count as a guard. State the bound in plain words: a user writes a few thousand blobs a year, so the 2^32 limit for random 96-bit nonces is not reachable, and the 12-month rotation already renews the key. If a counter is wanted anyway, add `encryptions bigint NOT NULL DEFAULT 0` to `user_keys` and increment it in batches of 10,000 reserved at a time.

### 8. SHOULD-FIX — LISTEN does not work through transaction-mode pgbouncer

- **Where:** Section 1.1, the `pgbouncer` row. Section 3.3, "Wake-up".
- **Problem:** `LISTEN` needs a session-level connection. In transaction mode, pgbouncer can hand the next statement to another server connection, so notices are lost. The document also does not name the Postgres driver.
- **Failure:** Notices never arrive in production. Every job waits up to the 2-second poll, which is acceptable, but nobody knows the wake-up path is dead. A driver that caches prepared statements also fails behind transaction pooling.
- **Change:** The worker's listener opens one direct connection to Postgres, set by `PERCH_DATABASE_DIRECT_URL`. All other work goes through the pooler. Name the driver, for example psycopg 3, and state its pooler setting, `prepare_threshold=None`.

### 9. SHOULD-FIX — The worker capacity is not written down and the default cannot meet the target

- **Where:** Section 1.1, "Worker CPU models". Section 1.3, `PERCH_WORKER_CONCURRENCY`. The plan's 40 briefs a minute.
- **Problem:** Each worker process loads three models, roughly 0.6 B, 0.6 B and 0.35 B parameters. With two job threads, a brief that waits on the provider for most of its time holds one of only two slots. No formula links workers, threads and memory to the target.
- **Failure:** At 40 briefs a minute and about 60 seconds each, about 40 briefs are in flight at once. With two threads per process, that needs about 20 worker processes, each with its own copy of the models. All of these numbers are UNVERIFIED until Phase 3 measures them, but the order of magnitude is the issue. Several processes on one host also each start one torch thread per core, so they fight over CPUs.
- **Change:** Write the formula in 1.1: briefs per minute equals processes times threads times 60, divided by seconds per brief. Raise the default thread count, for example to 16, because threads waiting on the provider hold no model lock. State that each process sets `torch.set_num_threads` from `PERCH_TORCH_THREADS`. Say that Phase 3 records the memory per process and the CPU seconds per brief, so Phase 10 can size the pool.

### 10. SHOULD-FIX — No shared limit on provider calls per minute

- **Where:** Section 3.3, "Retry rule". Section 4.2.
- **Problem:** Quotas cap dollars per user, but nothing caps requests or tokens per minute across workers. A 429 from the provider is a `ProviderError`, so the whole job is retried after a backoff.
- **Failure:** At peak, the provider returns 429. Each failed job restarts from its last saved stage, and the stages that already ran may bill again. Retries pile up and make the overload worse. Separately, the plan's Start tier allows 500 USD a month, which equals one day of 1,000 users at the 0.50 USD placeholder.
- **Change:** Add a Redis token bucket per provider and model, keyed `perch:pl:<provider>:<model>:<minute>`, checked inside `perch/llm/` before each call. Retry a 429 inside the adapter, honouring `retry-after`, up to a bound, before it becomes a job error. Write in D-11 the check that users times daily budget stays under both the global cap and the tier's monthly cap.

### 11. SHOULD-FIX — Global cap semantics and in-flight reservation are unclear

- **Where:** Section 1.3, `PERCH_ANTHROPIC_BUDGET_USD`. Section 4.1, `perch:q:global` and `perch:inflight`. Section 4.2.
- **Problem:** Today the cap is a total to the demo. Section 4.1 makes it monthly without saying so. The Lua script reserves against the user's counter only, so parallel workers can pass the global cap together. That is the S17 bug, back on a larger scale. "Rebuilt from `spend_ledger` at worker start" races when several workers start at once. The spend context, meaning which user and job a call belongs to, has no way into `AnthropicProvider`, which builds its own `Budget()` today.
- **Failure:** Many workers reserve at once and the month overshoots the cap. A restart of one worker overwrites counters that other workers have just increased.
- **Change:** State whether the cap is monthly or total. Reserve against the user and the global counter in the same Lua call. Rebuild a counter only when it is missing, with `SET NX`. Define a context variable `perch.llm.budget.spend_context` holding `user_id`, `addr_hash`, `job_id` and `role`, set by `JobContext`, read by the adapter and the audit wrapper.

### 12. SHOULD-FIX — Filtered vector search filters columns on another table, and relaxed order breaks RRF

- **Where:** Section 2.2, `record_vectors` and "Filtered search". Section 2.3, `VectorIndex.dense`.
- **Problem:** `temple_funded`, `school` and `sample` live on `records`, not on `record_vectors`. A filter therefore needs a join, which the HNSW partial index cannot use with iterative scans. `relaxed_order` also returns rows that are not strictly sorted by distance, but `retrieve.py` fuses lists by rank.
- **Failure:** The planner falls back to an exact scan, or the iterative scan returns too few rows after the join filter. Samples could enter a public retrieval if the join is written wrongly, which breaks rule 11. Out-of-order ranks change RRF scores, so the back-test changes for a reason nobody measured.
- **Change:** Copy `sample`, `temple_funded` and `schools` onto `record_vectors` at upsert and filter there. Either use `strict_order`, or re-sort the result in an outer query, as the pgvector notes advise. Note also that at today's corpus size, 1,497 opportunities, an exact scan takes a few milliseconds. So HNSW is for growth, not for today.

### 13. SHOULD-FIX — Three of the four vector indexes have no caller, and the sparse query semantics are not set

- **Where:** Section 2.2, "Index names" and "Sparse search". Section 11.2, step 3.
- **Problem:** Today only the `opportunities` Lance table is built, in `perch/service.py` and `perch/cli.py`. `perch/private/student.py` embeds every scholarship at query time with numpy. `route_b.py` gathers from OpenAlex and NIH live and has no vector index. Step 3 says nothing is re-embedded, but scholarships have no stored vectors to copy. For sparse search, `plainto_tsquery` joins every term with AND. A thread query holds many topic words and titles.
- **Failure:** The migration finds no `scholarships`, `organisations` or `works` tables and either stops or invents them. A BM25 list built with AND matches almost nothing, so hybrid retrieval quietly becomes dense-only, and the back-test drops.
- **Change:** Keep `opportunities` and add `scholarships`, which is embedded once at migration. Drop `organisations` and `works` until a caller exists. Specify the query: lexemes from `to_tsvector('english', q)`, joined with `|` into `to_tsquery`, ranked by `ts_rank_cd`. Phase 3 then compares that against the Lance BM25 lists.

### 14. SHOULD-FIX — `school` is single-valued, and NULL means two things

- **Where:** Section 2.2, `records.school`. Section 2.3, `browse`. Phase 4, task 4 in the plan.
- **Problem:** Phase 4 dedupes awards that appear on several school pages and keeps every page. One `school text` column cannot hold several owners. NULL is described as "All Temple", but every non-Temple opportunity also has NULL.
- **Failure:** A university-wide award shown on three school pages appears under only one school's filter. A school filter that includes NULL to catch Temple-wide awards also pulls in every Grants.gov record.
- **Change:** Use `schools text[] NOT NULL DEFAULT '{}'` with a GIN index, and add a `scope` column with the values `temple_wide`, `school` and `external`. Give a table that maps each denormalised column to its source field for each kind, for example `Scholarship.level_of_study` to `audience_level` and `Opportunity.close_date` to `deadline`.

### 15. SHOULD-FIX — Deleting an account leaves running jobs, and the same person cannot sign in again

- **Where:** Section 6.6, "Delete-my-data order". Section 2.2, `users`. Section 7.5.
- **Problem:** The order ends sessions but does not touch that user's queued or running jobs. A running job holds a cached data key for up to 300 seconds. `users.deleted_at` exists, but no step sets it, and `UNIQUE (issuer_hash, subject_hash)` covers deleted rows.
- **Failure:** A brief job keeps running after the delete, bills the provider, and tries to write rows for a user who is being purged. The student signs in again five minutes later. `perch_login_user` returns the old, shredded user id, and every write fails with `KeyShredded` until the purge job deletes the row.
- **Change:** Add step 1b: set `users.deleted_at`, and cancel that user's queued and running jobs. Make the unique index partial, `WHERE deleted_at IS NULL`, and make `perch_login_user` ignore deleted rows. A returning person then gets a new user id and a new key. List in 2.1 every table that `perch_delete_user_rows` clears, `spend_ledger` included.

### 16. SHOULD-FIX — The backup claim overstates crypto-shredding, and the ledger path does not fit several replicas

- **Where:** Section 6.1, "Crypto-shredding". Section 6.6, "Three tombstone copies" and "Retention". Section 1.3, `PERCH_SHRED_LEDGER_PATH`.
- **Problem:** `perch_keys` backups are kept 35 days and still hold the wrapped key. The master key still unwraps it. So for 35 days, a restore of both backups without the reconcile step brings the data back. The ledger is "a file or object path" written by every web and worker copy. Several containers cannot safely append to one local file.
- **Failure:** The consent text and the README say deletion is immediate in backups, which is not true. Under rule 10, that is a false claim. In Compose with two web copies, ledger lines are lost or interleaved, and the third tombstone copy is incomplete.
- **Change:** Write the honest statement: data is unreadable at once in the live system, and gone from backups when the last keys backup that holds the key expires, 35 days by design. Put that in the consent text. Make the ledger an object store prefix with one object per shred, named by user id, with object lock or versioning. For dev, a single mounted volume is allowed. Make `/ready` fail after a restore until `reconcile-shreds` has run, for example through a marker row the restore runbook clears.

### 17. SHOULD-FIX — Key creation on first use races, and tombstone checks are not atomic

- **Where:** Section 6.4, `new_data_key` and `encrypt_field`.
- **Problem:** Two parallel requests for a new user both create version 1 and collide on the primary key. `new_data_key` checks the tombstone and then inserts, in two steps.
- **Failure:** A user's first two uploads fail at random. A shred landing between the tombstone check and the insert leaves a live key for a deleted user.
- **Change:** Insert with `ON CONFLICT DO NOTHING` and re-read. In the keys database, add a trigger on `user_keys` that refuses an insert when a tombstone exists for that user, so the check and the insert cannot be split.

### 18. SHOULD-FIX — The user-data module has no contract

- **Where:** Section 6.4 says `perch/user/data.py` is the only code that touches `user_data.blob`. Section 2.2 names `perch/user/models.py`.
- **Problem:** Neither module has signatures or models in the document. They are the API every Phase 5 to 8 agent builds against.
- **Failure:** Each agent writes its own read and write helpers, with its own AAD and transaction handling. The single-gate promise for encryption is lost.
- **Change:** Add the class `UserData` with `put(user_id, kind, audience, model) -> UUID`, `get(user_id, row_id, model_cls)`, `list(user_id, kind, audience)`, `update(user_id, row_id, model, *, expect_updated_at)` and `delete(user_id, row_id)`. Each call opens `user_tx`. Name the pydantic class per kind. Say that one current `cv` row per audience is enforced by a partial unique index on `(user_id, audience) WHERE kind = 'cv'`. Say that `Digest` is dropped in v1, since `user_data.kind` has no `digest`.

### 19. SHOULD-FIX — Contact blanking has no enforcement point in this document

- **Where:** Section 0, "Models are bounded". Section 2.2, the `cv` row. Threat T11.
- **Problem:** The document says only that the CV is blanked at parse time. Entries, documents, Scout questions, tool results and hand-off context also reach models. `docs/v1/REUSE_MAP.md` moves `blank_contacts` into `perch/llm/contacts.py` inside the provider wrapper, but the contract does not say so.
- **Failure:** A student types a phone number into a Scout question. It reaches the provider, which breaks rule 5.
- **Change:** State in 1.2 that `AuditedProvider.chat` calls `blank_contacts` on the system prompt, every message's content and every `ToolResult.content` before the inner adapter sees them. State that no user text is put in the system block, so the provider prompt cache in section 5 never holds it. Add a test with a SYNTHETIC email in each place.

### 20. SHOULD-FIX — One records route mixes public rows and the user's own rows

- **Where:** Section 9.1, `GET /records/{record_id:path}`. Section 4.4.
- **Problem:** The route is in the response cache, which requires that it never reads the session. The same route also serves "the user's own rows" through `UserData`.
- **Failure:** A handler that reads the session for a user-owned id leaves the response cacheable, and another user can receive it from the cache. This is threat T9.
- **Change:** Serve user-owned rows only from a `/me/...` route that is never cached. `GET /records/{id}` serves public kinds only. Also remove `GET /health` from the cache, so liveness reflects the live process.

### 21. SHOULD-FIX — Grants contradict the steps that need them

- **Where:** Section 2.1, the grants table. Section 10, `audit_log`. Section 11.2.
- **Problem:** The purge nulls `audit_log.actor` after 90 days, but `perch_worker` has INSERT only on `audit_log`, and no `purge` action is listed for it. `migrate-corpus` runs as `perch_worker` but creates the HNSW indexes, which is DDL. Section 2.2 already creates those indexes in the migration. `status()` returns `queued_ahead`, but under RLS the web role sees only its own jobs, so the count is wrong. `GET /authors/resolve` and `PUT /me/openalex` run in `web`, which has no `OPENALEX_API_KEY` and, by T4, no egress.
- **Failure:** Each of these fails at its first run, or returns a wrong number, and the agent patches it by widening a grant.
- **Change:** Add a definer function `perch_null_old_actors(older_than interval)` and a `purge` action `audit`. Run the index step of `migrate-corpus` as `perch_owner`, or drop it and rely on the migration. Add a definer function `perch_queue_position(job_id) -> int`. Either move author resolution into a short job, or give `web` the OpenAlex key and an egress rule for that one host, and say which.

### 22. SHOULD-FIX — Sync repository in an async web process

- **Where:** Section 1.1, `web`. Section 2.3. Section 7.1.
- **Problem:** `web` is async FastAPI and `SessionStore` is async. `Repository`, `KeyRepository` and `crypto` are sync. The document does not say how they meet. Multipart CV upload is parsed in `web`, and a spooled upload spills to a temporary file on disk above its memory limit.
- **Failure:** A sync database or KMS call inside an `async def` route blocks the event loop, and browse p95 fails under load. A large CV upload writes plaintext to `/tmp`, which breaks rule 5.
- **Change:** State that routes that touch Postgres or the key store are plain `def`, so they run in the thread pool, and that the pool size matches `PERCH_DB_POOL_MAX`. Parse uploads in memory with a hard size cap below the spool threshold, or move the parse into a job.

### 23. SHOULD-FIX — The OpenAlex link is encrypted in one place and plain in others

- **Where:** Section 2.2, "What is encrypted". Section 3.4, the idempotency inputs. Section 5, the `fit` and `precache` keys.
- **Problem:** `users.openalex_id_enc` is encrypted because it ties an account to a named researcher. The brief job payload holds the same author id in plain text next to `user_id`, and `public_cache.meta` holds it too.
- **Failure:** Anyone who can read `jobs` can map accounts to researchers. The encryption of the column protects nothing.
- **Change:** Either declare that the author id is public and store the link in plain text, or keep it encrypted and put only a `user_data` row id in the user's job payload. Choose one and state it. The `public_cache` key may keep the author id, because it holds no `user_id`.

### 24. SHOULD-FIX — `staff` can be self-granted

- **Where:** Section 7.5, D-3. Section 9.2, `POST /me/roles`.
- **Problem:** The CHECK on `users.roles` allows `staff`, and `RolesSet {roles}` does not say it filters it out.
- **Failure:** A student posts `{"roles": ["staff"]}` and holds the staff role, which later staff screens will trust.
- **Change:** Type `RolesSet.roles` as a list of `Literal["student", "researcher"]`. Only `perch grant-role` and `PERCH_STAFF_GROUP` can add `staff`.

### 25. COULD-FIX — The AAD omits `kind` and `audience`

- **Where:** Section 6.2.
- **Problem:** A database writer can change the plain `kind` or `audience` column of a row, and the blob still decrypts.
- **Change:** Add `kind` and `audience` to the AAD for `user_data`. The risk is low, because RLS already blocks other users.

### 26. COULD-FIX — Prompt hashes of short user text can be confirmed by guessing

- **Where:** Section 2.2, `audit_log.prompt_hash`.
- **Problem:** A plain SHA-256 of a prompt that holds a short Scout question lets someone confirm a guessed question.
- **Change:** Use HMAC-SHA256 with a server key for prompts that contain user data.

### 27. COULD-FIX — The shred broadcast can be missed

- **Where:** Section 6.4, "Unwrapped key cache".
- **Problem:** Redis pub/sub does not redeliver. A process that reconnects after a shred keeps the key for up to 300 seconds.
- **Change:** On every pub/sub reconnect, clear the whole key cache.

### 28. COULD-FIX — The `jobs` table has no retention for finished jobs

- **Where:** Section 3.3, "Dead letter". Section 3.1.
- **Problem:** Only dead and guest jobs are deleted. At the plan's peak, finished jobs and their events grow by tens of thousands a day.
- **Change:** Delete `succeeded`, `failed` and `cancelled` jobs after 30 days in the daily purge. Note that this frees their idempotency keys, which is safe because the key includes the date.

### 29. COULD-FIX — The claim function returns a row of NULLs when the queue is empty

- **Where:** Section 3.3, `perch_claim_job`.
- **Problem:** A `LANGUAGE sql` function declared `RETURNS jobs` returns one row of NULLs, not zero rows, when nothing is queued.
- **Change:** Declare `RETURNS SETOF jobs`, or tell the caller to test `id IS NULL`.

### 30. COULD-FIX — Small contract mismatches

- **Where:** Several sections.
- **Problem and change:** Each item below is one line to fix.
  - **Cancel signature:** `JobRunner.cancel` has no `guest_sid_hash` argument, but `POST /jobs/{id}/cancel` allows guests. Add the argument.
  - **Guest Scout state:** `perch:gsess` in 4.1 mentions Scout state, but 7.4 forbids Scout for guests. Remove it.
  - **Previous key id:** `PERCH_MASTER_KEY_PREV_ID` has no row in 1.3. Add one.
  - **Consent version:** `PERCH_CONSENT_VERSION` is given to `web` only, but the worker checks consent. Give it to both.
  - **Withdraw route:** Consent withdrawal sets `withdrawn_at`, but section 9.2 has no route for it. Add `POST /me/consent/withdraw`.
  - **Durable epoch:** Section 4 says Redis holds no durable truth, yet the epoch lives in `perch:epoch`. Keep the epoch in Postgres and copy it to Redis.
  - **Fit cache key:** The `fit` entry expires "until fetched_at changes", but `fetched_at` is not a key part. Add it as a part.
  - **Sample CHECK:** It enforces only one direction. Make it `CHECK ((source = 'synthetic') = (id LIKE 'sample:%'))`. All 500 rows in today's sample store satisfy both directions.
  - **Search depth:** `hnsw.ef_search` must be at least the requested `k`. `PER_LIST` is 100 and `ef_search` is 100, so say that they must move together.

### 31. COULD-FIX — Redis access is not specified

- **Where:** Section 1.1, `redis`. Section 1.3, `PERCH_REDIS_URL`.
- **Problem:** Redis holds sessions and CSRF tokens. Anyone who reaches it can forge a session. The session hash also keeps `id_token_hint`, which may carry IdP claims.
- **Change:** Require a Redis ACL user and TLS, `rediss://`, in prod. Keep only the `sid` claim needed for logout, or drop `id_token_hint` if the IdP accepts `client_id` on logout.

### 32. COULD-FIX — The session index set never shrinks

- **Where:** Section 4.1, `perch:usess:<uid>`.
- **Problem:** Members are removed only on logout. Sessions that expire stay in the set forever.
- **Change:** Give the set the absolute session lifetime as its TTL, and refresh it at each login.

### 33. COULD-FIX — The nightly pre-cache has no size estimate

- **Where:** Section 3.1, `precache`. Section 8.
- **Problem:** The job reranks for every Temple-affiliated author on CPU, and its 900-second timeout covers one job. The document does not say whether that is one job per author or one job for all.
- **Change:** Say it is one job per author, enqueued by the scheduler. Record the author count and CPU seconds per author in Phase 3.

## Section 12 decisions

- **D-1, one records table:** Holds. Fix the column mapping, the multi-school column and the vector filter columns in findings 12 and 14.
- **D-2, tsvector instead of pg_search:** Holds, if the OR query in finding 13 is specified. Otherwise the back-test drop will come from the AND query, not from the ranking function.
- **D-3, self-selected roles:** Holds, with the `staff` filter in finding 24.
- **D-4, self-asserted OpenAlex link:** Holds. Decide its encryption status, finding 23.
- **D-5, no purge warning:** Holds. The consent text must state the 12-month rule and the 35-day backup window from finding 16.
- **D-6, guest scope:** Risky as written. A per-address guest budget punishes everyone behind one campus address. Key the guest budget by guest session, with a much higher per-address ceiling, and fix the address derivation in finding 5. Whether Temple's networks share one egress address is UNVERIFIED.
- **D-7, synchronizer CSRF and Lax cookie:** Holds. Add the pre-auth cookie in finding 4 for the login flow, which the session token does not cover.
- **D-8, separate keys database:** Holds. Fix the ledger and the honest backup window in finding 16.
- **D-9, gate in the worker:** Holds. Scout turns at priority 0 still sit behind any job that holds a thread, so finding 9 matters for Scout latency.
- **D-10, job states:** Holds. Add the fencing in finding 3.
- **D-11, placeholder numbers:** Holds as honest placeholders. Write the arithmetic check in finding 10, so the placeholders are at least consistent with each other.
- **D-12, roles and profile:** Holds.

## Rule compliance

- **Rules with gaps:** Rule 5 is covered by findings 6, 19, 22 and 23. Rule 10 is covered by finding 16. Rule 11 is covered by findings 12 and 30.
- **Rules with no gap found:** Rules 3, 4, 6 and 7 showed no gap. Provenance columns are NOT NULL, numbers are copied by code, model calls stay inside `perch/llm/`, and hand-offs are stored drafts only.

## Re-check

Written 2026-11-03 against the revised `docs/ARCHITECTURE_V1.md`. The re-check covered the seven must-fix items and the sections the revision touched. The other 26 findings were not re-checked.

### The seven must-fix items

- **1, Closed:** Section 2.1 now has a NOLOGIN role `perch_definer` that owns the functions and not the tables. Every fenced table has an explicit all-rows policy for that role, FORCE stays on, and there is a test that calls each function with no user set.
- **2, Closed:** Every policy is now written in SQL. `jobs_web_guest` has both `USING` and `WITH CHECK` on `guest_sid_hash = gsh()`. `guest_tx` sets `perch.guest_sid_hash`. `sl_worker_ins` allows ledger rows with a NULL user. Section 2.1 says which helper each path uses.
- **3, Closed:** The lease owner is now worker plus thread. `attempts` is the fencing token on every heartbeat, stage, partial save and terminal update. `ctx.user_tx()` first takes a `FOR SHARE` lock on the job row with the token, so the reaper cannot requeue mid-write. A timeout test is added.
- **4, Closed:** A binder cookie, `__Host-perch_oidc`, is set at login. Its hash is stored in the state entry, which is read once with `GETDEL` and compared in constant time. The token checks and `safe_return_to` are written as code.
- **5, Closed:** Section 7.6 adds `PERCH_TRUSTED_PROXIES` and `client_addr`, and `PERCH_PEPPER_GUEST` is now in 1.3. The guest budget is charged by `jobs.guest_sid_hash` instead of an address, which removes the worker's need for one. That is an acceptable equivalent. See N1 and N2 for two gaps that remain.
- **6, Closed:** The new section 3.7 binds both processes. It bans exception messages in logs, columns and responses. It replaces both exception hooks, strips pydantic inputs, bans capture of local variables and bodies, and adds a forced-error canary test. See N4 for one detail.
- **7, Closed:** The database counter is gone. The bound is stated, and a process-local guard is kept.

Result: 7 closed, 0 open.

### New items the revision introduced

None is a must-fix.

- **N1, SHOULD-FIX, section 7.6, client address can be spoofed:** The `client_addr` docstring walks `X-Forwarded-For` whenever trusted proxies are configured. It does not first check that the peer is one of them. If the web port is reachable directly, as host port 8090 is in Compose, a client can send its own header and pick any address. That resets its `login` and `guest_new` limits at will. The fix is to read the header only when the peer address is inside `PERCH_TRUSTED_PROXIES`, and otherwise return the peer.
- **N2, SHOULD-FIX, section 4.3, shared addresses can still be locked out:** The text says one address behind a shared proxy cannot lock out everyone. But `login` is still 20 per 600 seconds per address. So on a campus that shares one address, the 21st student in ten minutes cannot sign in. A site-wide ceiling does not help that case. The fix is to either raise the per-address `login` limit well above the expected sign-ins from one campus, or key it by the binder cookie with only a loose address ceiling. The sentence should also be corrected. Whether Temple shares one egress address stays UNVERIFIED.
- **N3, COULD-FIX, section 3.3, the timeout test asserts too much:** The test asserts one billed run. A stale thread's provider call that is already in flight still completes and bills, and ledger writes are not fenced. Fencing stops the stale thread's writes, not its spend. The fix is to change the assertion: one terminal update, no user-data write from the stale attempt, and every ledger row tagged with its attempt.
- **N4, COULD-FIX, section 3.7, pydantic context can leak:** `e.errors(include_input=False, include_url=False)` still returns `msg` and `ctx`. A custom validator whose `ValueError` text includes the value would leak through them. The fix is to add `include_context=False`, log only `type` and `loc`, and state that validators in `perch/user/models.py` raise fixed messages.
- **N5, COULD-FIX, section 6.5, stale wording:** Section 6.5 still lists "at the nonce counter limit" as a rotation trigger. It should now say the process-local guard in 6.1.
- **N6, COULD-FIX, section 2.1, function ownership needs a grant:** To hand a function to `perch_definer`, `perch_owner` must be a member of that role. Write `GRANT perch_definer TO perch_owner` into the first migration, so the `ALTER FUNCTION ... OWNER TO` step does not fail.

# ARCHITECTURE_V1.md — Perch v1 contract

Phase 1, task 5 of `docs/REBUILD_PLAN.md`. Written 2026-11-03. Later implementation agents cite this file by section number. Decisions in the plan are settled and are not re-opened here. Choices the plan left open are marked **D-n** and listed in section 12. Findings from `docs/v1/DESIGN_REVIEW.md` are answered in the review log at the end.

Reads with: `docs/REBUILD_PLAN.md`, `docs/v1/REUSE_MAP.md`, `docs/v1/PROVIDER_AND_SSO.md`. Anything those files mark UNVERIFIED stays UNVERIFIED here.

## As built after S48 (read this first)

This file is the design contract written on 2026-11-03. Where the code differs, the code on `rebuild/v1` is the truth, and this list says how. Each line was checked against the code on 2026-11-04.

- **Health route.** There is no `/ready` route. Readiness is `GET /health?ready=true`, which checks Postgres, Redis and the keys database and answers 503 when one is down. Plain `GET /health` is liveness. `GET /health?deep=true` checks model services. `GET /metrics` answers loopback callers only. Wherever this file says `/ready`, read `/health?ready=true`.
- **Default profile.** The default is `cloud-gpu`, not `cloud-cpu` (`DEFAULT_PROFILE` in `perch/profiles.py`, set 2026-11-04). `cloud-cpu` stays as the no-GPU profile with 14 candidates reranked. The profiles `dev`, `deploy-2gpu` and `deploy-1gpu` and the `systemone` grounder entries are still in `perch/profiles.py`; section 1.2 says they are removed, and that has not been done.
- **Compose files.** The services are in `deploy/compose/docker-compose.v1.yml` and one `deploy/compose/Dockerfile.v1` with targets `web`, `worker` and `worker-gpu`. The `docker/*.Dockerfile` paths in section 1.1 do not exist. The Compose `worker` uses the GPU image and reserves one GPU by index; `docker-compose.cpu.yml` is the CPU override. A `backup` service is in the stack. `pgbouncer` is not in the Compose file.
- **Native demo worker.** The demo node has no NVIDIA container runtime, so its worker runs natively on one GPU against the Compose services. See `docs/deploy.md` section 3b.
- **One brief service per process.** The worker builds one `BriefService` per process and shares it across job threads (`cmd_worker` in `perch/cli.py`). A new service per job failed at four or more concurrent briefs in the S47 load test.
- **Scheduler.** There is no `perch scheduler` command. The worker's maintenance thread submits the daily `purge` actions and the nightly `precache` instead, behind a Postgres advisory lock (S49; `Scheduler` in `perch/jobs.py`, `docs/deploy.md` section 1). Ingest is still run by hand. Sections 3.1 and 3.6 describe the design.
- **Rate limits.** The per-address `RateLimiter` in `perch/api.py` is still used for hand-offs. Section 4.2 says the Redis limiter replaces it everywhere; that is true for the quota path only.
- **Spend metering.** Every paid call goes through the adapter's spend meter and ledger, with the spend ledger on the `spend` volume. Guests have a per-session and a global daily budget (`PERCH_GUEST_DAILY_BUDGET_USD` default 0.10, `PERCH_GUEST_GLOBAL_DAILY_BUDGET_USD` default 5.00).
- **Hand-offs.** For a signed-in account, `POST /briefs/{id}/handoff` admits the draft, queues a worker job of kind `handoff` and answers 202. The browser then reads the draft with `GET /briefs/{id}/handoff`. Other callers (the fallback path without accounts) draft in the web process under the per-address limiter.
- **Logs and metrics.** `PERCH_LOG_FORMAT=json` writes one JSON object a line. User text is not logged.
- **Backups and restore.** Backups are kept 35 days (`BACKUP_RETENTION_DAYS`, `deploy/compose/backup.sh`). The restore marker is the file `RESTORE_PENDING` on the shred-ledger volume, written by `perch restore-mark`. The worker reconciles at start and clears it, and while it exists `/health?ready=true` fails. Section 6.6 has the detail.
- **Key operations.** `perch keys rekey` re-encrypts blobs under each user's newest key, and `perch keys tombstones purge` removes old tombstones (dry run unless `--apply`).
- **Identity provider.** The Keycloak realm in `deploy/compose/keycloak/perch-realm.json` imports no user. The SYNTHETIC end-to-end user is created by `scripts/e2e_oidc_login.py`.
- **Concurrent users.** The target is 250 (Dakshitha, 2026-11-04), not 1,000. See the note under section 4.2.1.

## 0. Rules this design must keep

- **Public data only in the repo.** Tests of user data use SYNTHETIC text with a canary token.
- **Provenance on every public row.** `source`, `source_url`, `fetched_at` are NOT NULL columns.
- **Numbers and dates are copied.** Nothing in this design lets a model write a value into a record.
- **Models are bounded.** Four skills, the scope gate and Scout, all through `perch/llm/`.
- **Nothing is sent by the app.** Hand-offs are stored drafts only.
- **User text never appears in plain text** in logs, caches, the audit log, job payloads or any column except encrypted blobs.

## 1. Process layout

### 1.1 Compose services

| Service | Image or build | Port inside | Host port in dev | Role |
|---|---|---|---|---|
| `web` | `deploy/compose/Dockerfile.v1`, target `web` | 8000 | 8090 | Async FastAPI. Stateless. Serves `web/` static files. Never loads a model and never calls a model provider. |
| `worker` | `deploy/compose/Dockerfile.v1`, target `worker-gpu` (or `worker` on CPU) | none | none | `perch worker`. Loads the three CPU models once per process. Runs jobs. Calls the cloud provider. |
| `postgres` | `pgvector/pgvector:0.8.0-pg16` | 5432 | 5433 | Postgres 16 with pgvector 0.8. Two databases: `perch` and `perch_keys`. |
| `redis` | `redis:7` | 6379 | 6380 | Sessions, quotas, rate limits, response cache. Append-only file on, no user text stored. In prod: a Redis ACL user per service and TLS, `rediss://`. |
| `keycloak` | `quay.io/keycloak/keycloak` pinned in Phase 2 | 8080 | 8180 | Development identity provider only. Realm `perch` is imported from `deploy/compose/keycloak/perch-realm.json`, which ships no user. |
| `migrate` | same image as `web` | none | none | One-shot `perch migrate`. Runs as `perch_owner`. `web` and `worker` depend on it finishing. |
| `pgbouncer` | pinned in Phase 2 | 6432 | none | Connection pooler in front of `postgres`, transaction mode. Optional in dev, required at scale. `LISTEN` does not go through it, see section 3.3. |

- **Pooler caveat.** Transaction pooling is compatible with `SET LOCAL perch.user_id` because that setting lives inside one transaction. Session-level `SET` is forbidden in code.
- **Driver.** psycopg 3, with `prepare_threshold=None` on every pooled connection, because cached prepared statements fail behind transaction pooling. The worker's `LISTEN` connection is the one exception and connects directly through `PERCH_DATABASE_DIRECT_URL`.
- **Sync routes.** The Repository, `UserData` and `KeyRepository` are synchronous. Every route that touches Postgres or the key store is a plain `def`, so FastAPI runs it in its thread pool, and the pool size is set equal to `PERCH_DB_POOL_MAX`. Only routes that touch Redis alone or the IdP are `async def`. Upload parsing runs in memory with a hard size cap of 5 MB per file, below the spool threshold. The cap is a design value, not measured.
- **Worker CPU models.** Embedder `Qwen/Qwen3-Embedding-0.6B`, reranker `Qwen/Qwen3-Reranker-0.6B`, grounder `lytang/MiniCheck-RoBERTa-Large`. The names come from `perch/embed`, `perch/rerank.py` and `perch/grounding.py` today. Each worker process loads them once at start and shares them across its job threads behind one lock per model.
- **Scaling.** Add `web` copies behind any load balancer. Add `worker` copies, optionally split by `--kinds` so that `ingest` and `precache` do not starve interactive jobs.
- **Worker capacity.** Briefs per minute is `processes x threads x 60 / seconds_per_brief`, and in-flight briefs is `processes x threads`. At the plan's 40 briefs a minute and 60 seconds a brief, 40 briefs are in flight, so 3 processes of 16 threads would carry it. Those two inputs are placeholders. The CPU stages of a brief hold a lock per model, so the real limit is CPU seconds per brief. Phase 3 records memory per process, CPU seconds per brief and seconds per brief, and Phase 10 sizes the pool from them. Threads that wait on the provider hold no model lock, which is why the default thread count is 16.
- **CPU threads.** Each process calls `torch.set_num_threads(PERCH_TORCH_THREADS)` at start, so several processes on one host do not each take every core. Default: cores divided by processes, set in the Compose file.
- **Health.** `web` serves `GET /health` for liveness and `GET /health?ready=true` for readiness, which checks Postgres, Redis and the keys database. `worker` writes a heartbeat row, see section 3.

### 1.2 Profile

`perch/profiles.py` gains the profile `cloud-cpu` and makes it the default (design; as built the default is `cloud-gpu`, see the status list at the top). The `dev`, `deploy-1gpu` and `deploy-2gpu` profiles and the `systemone:` grounder entries are removed.

```python
_CLOUD_CPU = ModelProfile(
    chat="anthropic:claude-sonnet-5-5",
    grounder="minicheck",
    embedder="Qwen/Qwen3-Embedding-0.6B",
    reranker="Qwen/Qwen3-Reranker-0.6B",
)
DEFAULT_PROFILE = "cloud-cpu"
```

- **Contact blanking has one enforcement point.** `AuditedProvider.chat` calls `blank_contacts` on the system prompt, on every message's content and on every `ToolResult.content` before the inner adapter sees them. `blank_contacts` moves from `perch/privacy.py` into `perch/llm/`. No user text is ever put in the `system` block, so the provider's prompt cache in section 5 never holds it. A test plants a SYNTHETIC email and phone number in each of those places and asserts the fake provider receives none.

`ROLES` in `perch/llm/__init__.py` becomes `("gate", "profile_summary", "fit_explainer", "handoff", "cover_points", "scout")`. The `decide` role is removed. Per-role defaults follow `docs/v1/PROVIDER_AND_SSO.md`: Haiku 5.5 for `gate` and `profile_summary`, Sonnet 5.5 for the rest. Phase 3 confirms or changes them by measurement.

### 1.3 Environment variables

Status column: **exists** is in `.env.example` today and stays; **changed** exists with a new meaning; **new**; **removed** is deleted from `.env.example`.

| Variable | Status | Used by | Meaning |
|---|---|---|---|
| `PERCH_ENV` | new | all | `dev`, `test` or `prod`. `prod` refuses the Env key store, refuses `PERCH_COOKIE_INSECURE`, and refuses start without TLS settings. |
| `PERCH_PROFILE` | changed | worker | Model profile. The design default is `cloud-cpu`; as built it is `cloud-gpu`. Old values are removed. |
| `PERCH_DATABASE_URL` | new | web, worker, migrate | Postgres URL for database `perch`. Each process gets the URL for its own role: `perch_web`, `perch_worker`, or `perch_owner` for migrate. |
| `PERCH_KEYS_DATABASE_URL` | new | web, worker | Postgres URL for database `perch_keys`, role `perch_keys`. Read only by `perch/keystore.py`. |
| `PERCH_REDIS_URL` | new | web, worker | Redis URL. In prod it must be `rediss://` with an ACL user. |
| `PERCH_DATABASE_DIRECT_URL` | new | worker | Direct Postgres URL, no pooler, used only for `LISTEN perch_jobs`. |
| `PERCH_DB_POOL_MAX` | new | web, worker | Pool size per process. Default 10. Also the size of the web thread pool. |
| `PERCH_TRUSTED_PROXIES` | new | web | Comma list of CIDRs whose `X-Forwarded-For` is honoured. Empty means the peer address is used as is. See section 7.6. |
| `PERCH_TORCH_THREADS` | new | worker | Value for `torch.set_num_threads` in each worker process. |
| `PERCH_KEYSTORE` | new | web, worker | `env` or `kms`. Default `env` in dev, required `kms` in prod. |
| `PERCH_MASTER_KEY` | new | web, worker | Dev only. Base64 of 32 random bytes. Wraps data keys. Never set in prod. |
| `PERCH_MASTER_KEY_ID` | new | web, worker | Short label for the master key, for example `m1`. Stored beside every wrapped key. |
| `PERCH_MASTER_KEY_PREV` | new | web, worker | Optional. Previous master key during a rotation. |
| `PERCH_MASTER_KEY_PREV_ID` | new | web, worker | Label of the previous master key. |
| `PERCH_KMS_KEY_URI` | new | web, worker | Prod key store reference. Format depends on the KMS and is UNVERIFIED until a host is chosen. |
| `PERCH_PEPPER` | new | web | Base64 of 32 bytes. Keys the HMAC of the IdP subject into `users.subject_hash`. Not the master key. |
| `PERCH_PEPPER_GUEST` | new | web | Base64 of 32 bytes. Keys the hash of guest session ids and client addresses. |
| `PERCH_AUDIT_KEY` | new | worker | Base64 of 32 bytes. Keys the HMAC used for `audit_log.prompt_hash` when a prompt holds user data. |
| `PERCH_SHRED_LEDGER_URI` | new | web, worker | Object store prefix with object lock or versioning. One object per shred, named by user id. Dev: a mounted directory. See section 6.6. |
| `PERCH_PUBLIC_URL` | changed | web | Public base URL. Used for OIDC redirect URIs, the cookie origin check and the CSRF origin check. |
| `PERCH_COOKIE_INSECURE` | new | web | `1` in dev over plain HTTP. Drops the `__Host-` prefix and the Secure flag. Refused when `PERCH_ENV=prod`. |
| `PERCH_AUTH_PROVIDER` | new | web | `oidc`. Later values `saml` or `cas` are served by the IdP, not by Perch. |
| `PERCH_OIDC_ISSUER` | new | web | Issuer URL. Dev: `http://keycloak:8080/realms/perch`. |
| `PERCH_OIDC_CLIENT_ID` | new | web | Dev: `perch-web`. |
| `PERCH_OIDC_CLIENT_SECRET` | new | web | Client secret for the confidential client. |
| `PERCH_OIDC_SCOPES` | new | web | Default `openid profile`. No email scope is requested. |
| `PERCH_STAFF_GROUP` | new | web | Optional group or role claim value that maps to the `staff` role. UNVERIFIED for Temple until Temple IT lists released attributes. |
| `PERCH_SESSION_IDLE_S` | new | web | Idle timeout. Default 1800. |
| `PERCH_SESSION_ABSOLUTE_S` | new | web | Absolute lifetime. Default 28800. |
| `PERCH_GUEST_TTL_S` | new | web | Guest session lifetime. Default 3600. |
| `PERCH_CONSENT_VERSION` | new | web, worker | Integer. Bump to require fresh consent. |
| `PERCH_CONSENT_PROVIDER_NAME` | new | web | Name shown in the consent text, for example the contracted provider. Required. |
| `PERCH_DAILY_BUDGET_USD` | new | web, worker | Per-account daily model spend. Placeholder default 0.50, not measured. Phase 5 sets it from Phase 3 numbers, see section 4.2.1. |
| `PERCH_GUEST_DAILY_BUDGET_USD` | new | web, worker | Per guest session, not per address. Placeholder default 0.10, not measured. |
| `PERCH_GUEST_GLOBAL_DAILY_BUDGET_USD` | new | web, worker | Ceiling on all guest spend together per UTC day. Placeholder default 3.00, not measured; keep it times 30 below the month cap. |
| `PERCH_GUEST_ADDR_DAILY_BUDGET_USD` | new | web, worker | Per hashed client address, guest spend per UTC day, counted at `perch:q:ga:<addr_hash>:<yyyymmdd>`. Placeholder default 0.30, not measured. |
| `PERCH_GUEST_SESSIONS_PER_ADDRESS_HOUR` | new | web | Ceiling on new guest sessions from one client address. Placeholder default 60, not measured. |
| `PERCH_PROVIDER_RPM`, `PERCH_PROVIDER_TPM` | new | worker | Shared per-minute request and token ceilings per provider and model, below the contract tier. Set at deploy time. UNVERIFIED until Temple's tier is known. |
| `PERCH_ANTHROPIC_BUDGET_USD` | changed | worker | Global hard cap. It is a monthly cap per UTC calendar month, summed from `spend_ledger`. The old per-demo total is retired. Default 100. |
| `PERCH_WORKER_CONCURRENCY` | new | worker | Job threads per worker process. Default 16, because threads waiting on the provider hold no model lock. See section 1.1. |
| `PERCH_WORKER_KINDS` | new | worker | Comma list of job kinds this worker claims. Empty means all. |
| `PERCH_RESPONSE_CACHE_TTL_S` | new | web | Default 300. |
| `PERCH_RATE_LIMITS` | new | web | JSON overriding the table in section 4.3. |
| `ANTHROPIC_API_KEY` | exists | worker | Provider key. Not given to `web`. |
| `PERCH_LLM_DEFAULT`, `PERCH_LLM_<ROLE>` | exists | worker | Role overrides. Roles per section 1.2. |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY` | exists | worker | OpenAI-compatible provider. |
| `OPENALEX_API_KEY` | exists | web, worker | OpenAlex key. `web` uses it only for `GET /authors/resolve`, with an egress rule for that one host. See D-13. |
| `OLLAMA_BASE_URL` | exists | worker | Dev only. Kept so the Ollama adapter still works for local experiments. |
| `PERCH_CORS_ORIGINS` | exists | web | Extra origins, empty by default. |
| `PERCH_CLEF_FLASH_URL`, `PERCH_CLEF_URL`, `PERCH_MODEL_SERVER` | removed | none | GPU decision servers and the model server are deleted. |
| `PERCH_BRIEFS_PER_HOUR`, `PERCH_HANDOFF_PER_HOUR`, `PERCH_SCOUT_PER_HOUR`, `PERCH_SESSIONS_PER_HOUR`, `PERCH_SESSIONS_PER_ADDRESS`, `PERCH_DOCUMENTS_PER_HOUR` | removed | none | Replaced by section 4.2 and 4.3. |
| `PERCH_PRIVATE_MODE`, `PERCH_PRIVATE_ENDPOINTS`, `PERCH_TLS_AT`, `PERCH_PRIVATE_OPERATOR`, `PERCH_CLOUD`, `PERCH_CLOUD_BRIEFS_PER_DAY`, `PERCH_CLOUD_DOCUMENTS`, `PERCH_PUBLIC_CACHE`, `PERCH_STORED_BRIEFS`, `PERCH_WARM_AUTHORS`, `PERCH_WATCH`, `PERCH_SAMPLE_DB` | removed | none | Private mode, warm briefs and the shelved monitor are gone. Sample records move into `records`, see section 2.2. |

- **Secrets rule.** `.env.example` lists every variable above with a comment and an empty value. Secrets are never in an image layer.
- **Per-process secrets.** `web` does not receive `ANTHROPIC_API_KEY`. `worker` does not receive `PERCH_OIDC_CLIENT_SECRET`, `PERCH_PEPPER` or `PERCH_PEPPER_GUEST`.

## 2. Postgres schema

Two databases on one server in dev. In production the keys database should be a separate instance, see section 6.6.

### 2.1 Roles

| Role | Login | Owns | Used by | Grants |
|---|---|---|---|---|
| `perch_owner` | yes, migrate only | all objects in `perch` | `migrate` | DDL. Never used at runtime. |
| `perch_web` | yes | nothing | `web` | See table below. Row-level security applies. |
| `perch_worker` | yes | nothing | `worker` | See table below. Row-level security applies. |
| `perch_keys` | yes | all objects in `perch_keys` | `perch/keystore.py` in both processes | SELECT, INSERT and UPDATE on `user_keys`, SELECT and INSERT on `key_tombstones`, through functions that take an advisory lock per user. The tables are owned by `perch_keys_owner`, a non-login role, so the runtime role cannot drop tombstones or disable the trigger (S37 crypto review). No grant in `perch`. |
| `perch_definer` | no, NOLOGIN | the SECURITY DEFINER functions only, not the tables | called through those functions | Only the table grants those functions need, plus an explicit RLS policy `TO perch_definer USING (true) WITH CHECK (true)` on every fenced table. |

| Table (database `perch`) | `perch_web` | `perch_worker` |
|---|---|---|
| `records`, `record_vectors` | SELECT | SELECT, INSERT, UPDATE |
| `public_cache` | SELECT | SELECT, INSERT, UPDATE, DELETE |
| `users` | SELECT, UPDATE via RLS | SELECT, UPDATE via RLS |
| `consents` | SELECT, INSERT via RLS | SELECT via RLS |
| `user_data` | SELECT, INSERT, UPDATE, DELETE via RLS | SELECT, INSERT, UPDATE, DELETE via RLS |
| `jobs` | SELECT, INSERT, UPDATE via RLS. UPDATE only the cancel transition, enforced by a trigger. Guests through `guest_tx`. | all, policy `USING (true)` |
| `job_events` | SELECT via join policy | INSERT |
| `audit_log` | INSERT | INSERT |
| `spend_ledger` | SELECT via RLS | INSERT with any `user_id` including NULL, and SELECT of all rows for counter rebuild |
| `shred_log` | INSERT | SELECT, INSERT |
| `ingest_runs`, `worker_heartbeat` | SELECT | all |
| `schema_migrations` | none | none |

- **No role can read `user_keys`.** It lives in another database.
- **Cross-user work uses SECURITY DEFINER functions** owned by `perch_definer`, `search_path` pinned to `public, pg_temp`, execute granted to named roles only. `perch_owner` owns the tables and holds DDL, and is never the function owner.
  - `perch_login_user(issuer_hash, subject_hash) -> uuid` finds or creates the user, ignoring rows with `deleted_at` set. Granted to `perch_web`.
  - `perch_claim_job(worker text, kinds text[], lease_s int) -> setof jobs` is the claim SQL in section 3.3. Granted to `perch_worker`.
  - `perch_inactive_users(older_than interval, lim int) -> setof uuid` returns users past the 12 month limit. Granted to `perch_worker`.
  - `perch_delete_user_rows(user_id uuid) -> void` clears that user in `user_data`, `consents`, `jobs` with their `job_events`, `spend_ledger`, and the `users` row. It runs the same way for delete-my-data and the inactivity purge. Granted to `perch_worker`.
  - `perch_null_old_actors(older_than interval) -> int` sets `audit_log.actor` to NULL on old rows. Granted to `perch_worker`.
  - `perch_queue_position(job_id uuid) -> int` counts queued jobs ahead in claim order, for the waiting message. Granted to `perch_web`.
- **Migration grant.** The first migration runs `GRANT perch_definer TO perch_owner WITH INHERIT FALSE`, which needs PG 16, before any `ALTER FUNCTION ... OWNER TO perch_definer`, because a role can hand an object to another role only if it is a member of it. Without `INHERIT FALSE` the owner inherits the definer policies and can read user rows, so FORCE RLS would not bind it (found in S36).
- **Why a separate definer role.** FORCE row-level security applies to a table's owner too. A function owned by `perch_owner` would see zero rows. A non-owner role with an explicit all-rows policy works on managed Postgres, where no superuser can grant BYPASSRLS. BYPASSRLS on `perch_definer` is an allowed shortcut where the host permits it, and is UNVERIFIED until the host is chosen. FORCE stays on.
- **Test.** Each function is called as `perch_web` or `perch_worker` with no `perch.user_id` set and must return the rows it should.
- **Transaction helpers** in `perch/store/pg.py`, each opening one transaction:
  - `user_tx(user_id)` runs `SET LOCAL perch.user_id`. Used for every signed-in request and for a job's user-data work.
  - `guest_tx(sid_hash)` runs `SET LOCAL perch.guest_sid_hash` with the hex of the hash. Used for guest job submit, status, cancel and result reads.
  - `public_tx()` sets nothing. Used for records, vectors and public cache. A fenced table read here returns zero rows.
- **Policies.** Written in full here. Every fenced table has ENABLE and FORCE.

```sql
-- uid() is NULLIF(current_setting('perch.user_id', true), '')::uuid
-- gsh() is decode(NULLIF(current_setting('perch.guest_sid_hash', true), ''), 'hex')
CREATE POLICY users_fence    ON users     TO perch_web, perch_worker USING (id = uid())      WITH CHECK (id = uid());
CREATE POLICY consents_fence ON consents  TO perch_web, perch_worker USING (user_id = uid()) WITH CHECK (user_id = uid());
CREATE POLICY ud_fence       ON user_data TO perch_web, perch_worker USING (user_id = uid()) WITH CHECK (user_id = uid());
CREATE POLICY jobs_web_user  ON jobs TO perch_web USING (user_id = uid()) WITH CHECK (user_id = uid());
CREATE POLICY jobs_web_guest ON jobs TO perch_web
  USING      (user_id IS NULL AND guest_sid_hash = gsh())
  WITH CHECK (user_id IS NULL AND guest_sid_hash = gsh());
CREATE POLICY jobs_worker    ON jobs TO perch_worker USING (true) WITH CHECK (true);
CREATE POLICY je_web   ON job_events FOR SELECT TO perch_web
  USING (EXISTS (SELECT 1 FROM jobs j WHERE j.id = job_id));   -- inherits the jobs policies
CREATE POLICY je_worker ON job_events TO perch_worker USING (true) WITH CHECK (true);
CREATE POLICY sl_web_read ON spend_ledger FOR SELECT TO perch_web USING (user_id = uid());
CREATE POLICY sl_worker_ins ON spend_ledger FOR INSERT TO perch_worker WITH CHECK (true);
CREATE POLICY sl_worker_sel ON spend_ledger FOR SELECT TO perch_worker USING (true);
-- and for each of users, consents, user_data, jobs, job_events, spend_ledger:
CREATE POLICY definer_all ON <table> TO perch_definer USING (true) WITH CHECK (true);
```

- **Which helper each path uses.** Signed-in browse of own data, briefs, saved items, uploads: `user_tx`. Guest brief submit and poll: `guest_tx`. Worker claim: no helper, the definer function runs. Worker handler for a signed-in job: `ctx.user_tx()`. Worker handler for a guest job: `ctx.guest_tx()`. Ledger insert: no helper, policy allows it. `audit_log` has no RLS and no read grant to `web` or `worker`.

### 2.2 Tables

**D-1 Records are one table.** The single `records` table with a `kind` column and a JSONB `data` column matches the SQLite store and `Repository`, which key everything by `(kind, id)`. The pydantic classes in `perch/schemas.py` stay the source of truth, so a field added in Phase 4 needs no migration. Typed tables would force eight table definitions to track eight classes and would break `get_any(id)`. Hot filters are denormalised into plain columns by `PostgresRepository.upsert`.

```sql
-- Public records: Researcher, Work, Award, Opportunity, Organisation, Scholarship.
-- Brief, Lead and Digest are NOT stored here in v1; they are user data (user_data).
CREATE TABLE records (
  kind          text        NOT NULL CHECK (kind IN
                  ('researcher','work','award','opportunity','organisation','scholarship')),
  id            text        NOT NULL CHECK (id <> ''),
  source        text        NOT NULL CHECK (source <> ''),
  source_url    text        NOT NULL CHECK (source_url <> ''),
  fetched_at    timestamptz NOT NULL,
  data          jsonb       NOT NULL,
  -- denormalised filter columns, written by PostgresRepository.upsert from data
  sample        boolean     GENERATED ALWAYS AS (source = 'synthetic') STORED,
  scope         text        NOT NULL DEFAULT 'external' CHECK (scope IN ('temple_wide','school','external')),
  schools       text[]      NOT NULL DEFAULT '{}',  -- owner schools, empty unless scope = 'school'
  temple_funded boolean     NOT NULL DEFAULT false,
  audience_level text[]     NOT NULL DEFAULT '{}',
  deadline      date,                 -- Opportunity.close_date or Scholarship.deadline
  amount_max    numeric,              -- Opportunity.award_ceiling or Scholarship.amount_max
  status        text,
  PRIMARY KEY (kind, id),
  CHECK ((source = 'synthetic') = (id LIKE 'sample:%')),            -- standing rule 11, both directions
  CHECK (scope = 'school' OR schools = '{}')
);
CREATE INDEX records_id         ON records (id);                    -- get_any
CREATE INDEX records_browse     ON records (kind, temple_funded, scope, deadline) WHERE NOT sample;
CREATE INDEX records_schools    ON records USING gin (schools) WHERE NOT sample;
CREATE INDEX records_sample     ON records (kind) WHERE sample;
CREATE INDEX records_work_auth  ON records USING gin ((data->'author_ids') jsonb_path_ops)
                                WHERE kind = 'work';                -- works_by_author
```

- **Synthetic records.** They sit in the same table with `source = 'synthetic'`. The `sample` column makes the "never in the same list" rule a WHERE clause the repository adds by default: `list(cls, include_samples=False)`. The CHECK enforces the `sample:` prefix. The canary lives inside `data`.
- **Scholarship fields from Phase 4.** `schools`, `scope`, `temple_funded` and the per-value source sentences go into `data`. The columns are the only fields the browse routes filter on.
- **School and scope.** `scope = 'temple_wide'` means a university-wide program and shows under "All Temple". `scope = 'school'` means one or more owner schools in `schools`, because a program may sit on several school pages. `scope = 'external'` means not a Temple award. A record whose page states no school and does not say it is university-wide is stored as `external` until a reviewer sets its scope, because the CHECK forbids `school` with an empty list. The UI tag row is built from `unnest(schools)` plus the "All Temple" entry.
- **Column sources.** `PostgresRepository.upsert` fills each denormalised column from the record's own fields. No model sets them.

| Column | Opportunity | Scholarship | Other kinds |
|---|---|---|---|
| `deadline` | `close_date` | `deadline` | NULL |
| `amount_max` | `award_ceiling` | `amount_max` | NULL |
| `status` | `status` | NULL | NULL |
| `audience_level` | empty | `level_of_study` | empty |
| `schools`, `scope`, `temple_funded` | new Phase 4 fields | new Phase 4 fields | `external`, empty, false |

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- Replaces LanceIndex. One row per embedded record per index.
CREATE TABLE record_vectors (
  index_name  text        NOT NULL CHECK (index_name IN ('opportunities','scholarships')),
  record_id   text        NOT NULL,
  record_kind text        NOT NULL,
  text        text        NOT NULL,                -- the embedded text, public records only
  embedding   vector(1024) NOT NULL,
  embedder    text        NOT NULL,                -- e.g. 'Qwen/Qwen3-Embedding-0.6B'
  embedded_at timestamptz NOT NULL,
  sample        boolean   NOT NULL,                  -- copied from records at upsert
  temple_funded boolean   NOT NULL,                  -- copied from records at upsert
  schools       text[]    NOT NULL DEFAULT '{}',     -- copied from records at upsert
  tsv         tsvector    GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
  PRIMARY KEY (index_name, record_id),
  FOREIGN KEY (record_kind, record_id) REFERENCES records (kind, id) ON DELETE CASCADE
);
CREATE INDEX rv_opp_hnsw  ON record_vectors USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64) WHERE index_name = 'opportunities';
CREATE INDEX rv_sch_hnsw  ON record_vectors USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64) WHERE index_name = 'scholarships';
CREATE INDEX rv_tsv       ON record_vectors USING gin (tsv);
CREATE INDEX rv_schools   ON record_vectors USING gin (schools);
```

- **Dimension.** 1024. Confirmed: the Qwen3-Embedding-0.6B model card and config give `hidden_size` 1024, and the code does not hardcode it, since `perch/embed/__init__.py` reads `self.dim` from the loaded model. `perch/store/pg.py:EMBED_DIM = 1024` is the one constant, and `migrate` still asserts `embedder.dim == EMBED_DIM` and that every Lance vector has that length. A different embedder needs a new migration and a re-embed.
- **Index names, resolved from the code.** Reading `perch/retrieve.py`, `perch/route_b.py` and `perch/store/lance.py` shows that only one index exists today. `LanceIndex` defaults to the table name `opportunities`, and the only caller is `retrieve.index_opportunities` through `brief.py`, with the Lance directory built in `service.py` and `cli.py`. `route_b.py` embeds nothing through an index. Student scholarship ranking embeds in memory in `perch/private/student.py`. So v1 has two index names: `opportunities`, migrated from Lance, and `scholarships`, which is new. Scholarship vectors are computed once at migration with the same embedder, which is the only new embedding the migration makes. Indexes for organisations and works are not created until a caller exists.
- **Filtered search.** `sample`, `temple_funded` and `schools` are copied onto `record_vectors` at upsert, so a filtered query touches one table. Dense queries run in a transaction with `SET LOCAL hnsw.iterative_scan = strict_order`, because relaxed order returns results out of distance order and the RRF fusion in `retrieve.py` depends on the rank order. `SET LOCAL hnsw.ef_search` must be at least the requested `k`: `PER_LIST` is 100, so `ef_search` is 100, and the two move together. At the current corpus size, about 1,500 opportunities per the design review and UNVERIFIED here, an exact scan takes milliseconds, so HNSW is for growth and not needed today. Each partial index serves one `index_name`, so every dense query names it in WHERE.
- **Sparse search.** **D-2** `VectorIndex.bm25` is implemented with `tsvector` in stock Postgres, not `pg_search`, which needs a non-stock image. The query is built in code: lexemes from `to_tsvector('english', q)`, joined with `|` into a `to_tsquery`, ranked by `ts_rank_cd`, limited to `k`. Scores differ from Lance BM25. Phase 3 compares the top lists against Lance and reruns the back-test on the shipped setup, and reports the change. A `pg_search` implementation can be added behind the same interface later.

```sql
CREATE TABLE users (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  issuer_hash      bytea       NOT NULL,           -- sha256 of the IdP issuer URL
  subject_hash     bytea       NOT NULL,           -- HMAC-SHA256(PERCH_PEPPER, IdP subject)
  roles            text[]      NOT NULL DEFAULT '{}' CHECK (roles <@ ARRAY['student','researcher','staff']),
  openalex_id_enc  bytea,                          -- encrypted, see section 6; the self-asserted link
  openalex_linked_at timestamptz,                  -- plain; changes the idempotency key when the link changes
  last_audience    text        CHECK (last_audience IN ('researcher','student')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  last_active_at   timestamptz NOT NULL DEFAULT now(),
  deleted_at       timestamptz
);
CREATE UNIQUE INDEX users_subject ON users (issuer_hash, subject_hash) WHERE deleted_at IS NULL;
-- No name, no email, no IdP claim is stored. The display name lives only in the Redis session.
-- A person who deleted their account and signs in again gets a new user id and a new key.

CREATE TABLE consents (
  id            bigserial   PRIMARY KEY,
  user_id       uuid        NOT NULL REFERENCES users ON DELETE CASCADE,
  version       int         NOT NULL,
  provider_name text        NOT NULL,             -- copied from PERCH_CONSENT_PROVIDER_NAME at accept time
  text_sha256   bytea       NOT NULL,             -- hash of the exact text shown
  accepted_at   timestamptz NOT NULL DEFAULT now(),
  withdrawn_at  timestamptz
);

CREATE TABLE user_data (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid        NOT NULL REFERENCES users ON DELETE CASCADE,
  kind        text        NOT NULL CHECK (kind IN
                ('cv','entry','doc','brief','saved_item','handoff','cover_points','scout_session')),
  audience    text        NOT NULL CHECK (audience IN ('researcher','student')),
  key_version int         NOT NULL,
  blob        bytea       NOT NULL,               -- section 6.2 format; the only column holding content
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ud_user_kind ON user_data (user_id, audience, kind, updated_at DESC);
CREATE UNIQUE INDEX ud_one_cv ON user_data (user_id, audience) WHERE kind = 'cv';   -- one current CV per side
```

- **What is encrypted.** All content of `user_data`, including titles, record ids a user saved, lead state and the OpenAlex link. Plaintext columns are `kind`, `audience`, the timestamps and the key version. Those reveal that a user has a CV, not what it says.
- **Blob content by kind.** JSON documents defined by pydantic models in `perch/user/models.py`:

| `kind` | Blob holds |
|---|---|
| `cv` | Parsed CV facts and cleaned text. Contact details are already blanked at parse time. One current row per audience. |
| `entry` | One achievement or note the user typed. |
| `doc` | An uploaded document's cleaned text and a label. |
| `brief` | The `Brief` and its `Lead` list, including lead status keep or dismiss and the explanation text. Written at the end of a brief job and at each stage via `ctx.save_partial()`. |
| `saved_item` | A saved award or lead: record id, note, audience. |
| `handoff` | One hand-off draft. |
| `cover_points` | One cover-point set for one record. |
| `scout_session` | The Scout message history and tool cards for one session. |

- **Per-side saved items.** `audience` is the column that keeps researcher and student saved items apart for one account, as the plan requires.
- **RLS.** The policies are written in full in section 2.1.
- **Digest is dropped in v1.** `user_data.kind` has no `digest`. The weekly monitor was shelved in S23.
- **OpenAlex link choice.** The link between a person and an author id is personal, so it stays encrypted in `users.openalex_id_enc`. The author id itself is public. A job payload therefore holds the author id only when the user typed it into a request, and holds the flag `author_source: "link"` when the worker must read the link. The worker decrypts it inside `user_tx`. The `public_cache` keys may hold an author id, because they hold no user id.
- **Typed access.** `perch/user/data.py` is the only code that reads or writes `user_data.blob`, through the class in section 6.4.

```sql
CREATE TABLE jobs (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  kind            text        NOT NULL CHECK (kind IN
                    ('brief','scout_turn','handoff','cover_points','ingest','purge','precache')),
  state           text        NOT NULL DEFAULT 'queued' CHECK (state IN
                    ('queued','running','succeeded','failed','dead','cancelled')),
  user_id         uuid        REFERENCES users ON DELETE CASCADE,   -- NULL for system and guest jobs
  guest_sid_hash  bytea,                                           -- guest jobs only, sha256 of the session id
  audience        text        CHECK (audience IN ('researcher','student')),
  payload         jsonb       NOT NULL DEFAULT '{}',               -- ids only, see section 3.5
  idempotency_key text        NOT NULL,
  priority        smallint    NOT NULL DEFAULT 5,
  attempts        int         NOT NULL DEFAULT 0,
  max_attempts    int         NOT NULL,
  run_after       timestamptz NOT NULL DEFAULT now(),
  lease_owner     text,
  lease_expires_at timestamptz,
  heartbeat_at    timestamptz,
  result_ref      text,                                            -- 'user_data:<uuid>', 'public_cache:<key>' or 'redis:<key>'
  error_code      text,                                            -- code from a fixed list, never a message with user text
  created_at      timestamptz NOT NULL DEFAULT now(),
  started_at      timestamptz,
  finished_at     timestamptz
);
CREATE UNIQUE INDEX jobs_idem ON jobs (kind, COALESCE(user_id, '00000000-0000-0000-0000-000000000000'),
  COALESCE(guest_sid_hash, '\x'::bytea), idempotency_key) WHERE state IN ('queued','running','succeeded');
CREATE INDEX jobs_claim ON jobs (priority, run_after, created_at) WHERE state = 'queued';
CREATE INDEX jobs_lease ON jobs (lease_expires_at) WHERE state = 'running';
CREATE INDEX jobs_user  ON jobs (user_id, created_at DESC);

CREATE TABLE job_events (        -- the stage list the page polls; stage names and codes only
  id         bigserial   PRIMARY KEY,
  job_id     uuid        NOT NULL REFERENCES jobs ON DELETE CASCADE,
  at         timestamptz NOT NULL DEFAULT now(),
  stage      text        NOT NULL,
  status     text        NOT NULL CHECK (status IN ('pending','running','done','skipped','failed')),
  detail     text        CHECK (length(detail) <= 120),   -- built by code from counts, never user text
  ms         int
);
CREATE INDEX je_job ON job_events (job_id, id);
```

- **Policies.** Section 2.1 has the full SQL for `jobs`, including the guest policy that admits `user_id IS NULL` rows only when `perch.guest_sid_hash` matches, and the all-rows policy for `perch_worker`.
- **Cancelling.** A trigger lets `perch_web` change `state` only from `queued` or `running` to `cancelled`.

```sql
CREATE TABLE audit_log (
  id          bigserial   PRIMARY KEY,
  at          timestamptz NOT NULL DEFAULT now(),
  event       text        NOT NULL,   -- login, logout, consent, consent_withdrawn, delete_request, shred,
                                      -- purge_inactive, model_call, validation, quota_denied, rate_limited,
                                      -- job_dead, key_rotate_master, key_rotate_data, csrf_reject, authz_deny
  actor       uuid,                   -- user id; nulled by the purge job after 90 days
  job_id      uuid,
  role        text,                   -- model role for model_call and validation
  provider    text, model text,
  prompt_hash bytea,                  -- sha256 as perch/llm/audit.py does today; HMAC-SHA256 under PERCH_AUDIT_KEY when the prompt holds user data
  input_tokens int, output_tokens int, cost_usd numeric(12,6),
  passed      boolean, layer smallint, attempt smallint,
  detail      jsonb NOT NULL DEFAULT '{}'   -- ids, codes, counts. Never text. A CHECK on size < 2 kB.
);
CREATE INDEX audit_at ON audit_log (at);  CREATE INDEX audit_event ON audit_log (event, at);

CREATE TABLE spend_ledger (      -- replaces data/logs/anthropic_spend.jsonl
  id          bigserial   PRIMARY KEY,
  at          timestamptz NOT NULL DEFAULT now(),
  user_id     uuid,                -- NULL for guest, gate on guests, system and bench calls
  job_id      uuid,
  role        text        NOT NULL,
  provider    text        NOT NULL,
  model       text        NOT NULL,
  input_tokens int NOT NULL, output_tokens int NOT NULL,
  cache_read_tokens int NOT NULL DEFAULT 0, cache_write_tokens int NOT NULL DEFAULT 0,
  attempt     smallint,            -- job attempt that made the call, for fencing audits
  cost_usd    numeric(12,6) NOT NULL    -- from perch.llm.budget.call_cost, unknown price charged at the dearest model
);
CREATE INDEX sl_user_day ON spend_ledger (user_id, at);  CREATE INDEX sl_at ON spend_ledger (at);

CREATE TABLE public_cache (      -- model text and stage outputs that depend on public inputs only
  key          text        PRIMARY KEY,                 -- sha256 hex, built as in section 5
  namespace    text        NOT NULL CHECK (namespace IN
                 ('fit','profile_summary','author','precache')),
  value        jsonb       NOT NULL,
  meta         jsonb       NOT NULL,                    -- inputs of the key in the clear, for invalidation
  ingest_epoch bigint      NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz
);
CREATE INDEX pc_ns ON public_cache (namespace, expires_at);

CREATE TABLE shred_log (         -- second copy of the tombstone, section 6.6
  user_id uuid PRIMARY KEY, shredded_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE ingest_runs (id bigserial PRIMARY KEY, source text NOT NULL, started_at timestamptz NOT NULL,
  finished_at timestamptz, rows_written int, epoch bigint, error_code text);
CREATE TABLE worker_heartbeat (worker text PRIMARY KEY, at timestamptz NOT NULL, kinds text[], models_loaded boolean);
CREATE TABLE schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
```

Keys database `perch_keys`:

```sql
CREATE TABLE user_keys (
  user_id        uuid        NOT NULL,                  -- no foreign key: other database
  key_version    int         NOT NULL,
  wrapped_key    bytea       NOT NULL,                  -- section 6.3
  master_key_id  text        NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  retired_at     timestamptz,                           -- set when a newer version exists and old rows are re-encrypted
  PRIMARY KEY (user_id, key_version)
);
CREATE TABLE key_tombstones (user_id uuid PRIMARY KEY, shredded_at timestamptz NOT NULL DEFAULT now());
```

- **Briefs and leads are not in `records`.** The current store keeps `Brief`, `Lead` and `Digest` as records. In v1 they are user data and live encrypted in `user_data`. A brief built from public inputs only for a guest is held in Redis, see section 7.
- **Cache entries in Postgres.** Only `public_cache`. All other caches are Redis, section 4.
- **Migrations.** Plain SQL files in `perch/store/migrations/NNNN_name.sql`, applied in order by `perch migrate` as `perch_owner`, recorded in `schema_migrations`. The keys database has its own directory `migrations_keys/`.
- **SQLite.** Stays behind `Repository` and `VectorIndex` for unit tests. It implements `records` without RLS, and a numpy brute-force `VectorIndex` replaces Lance in tests. The shared repository tests run against both backends.

### 2.3 Repository interface changes

`perch/store/base.py` keeps `Repository` and `VectorIndex` as they are, with these additions.

```python
class Repository(ABC):
    # existing: upsert, get, list, get_any, works_by_author, close
    @abstractmethod
    def list(self, cls: type[R], *, include_samples: bool = False) -> list[R]: ...
    @abstractmethod
    def browse(self, cls: type[R], *, temple_only: bool = False, schools: Sequence[str] = (),
               audience_level: Sequence[str] = (), q: str | None = None,
               closes_after: date | None = None, limit: int = 50, cursor: str | None = None
               ) -> Page[R]: ...
    @abstractmethod
    def epoch(self) -> int: ...          # current ingest epoch, section 4.4
    @abstractmethod
    def bump_epoch(self) -> int: ...

class VectorIndex(ABC):
    # existing: upsert, dense, bm25, ids
    # dense and bm25 gain the same optional filter arguments as browse
    @abstractmethod
    def dense(self, vector: list[float], k: int, *, temple_only: bool = False,
              schools: Sequence[str] = (), include_samples: bool = False) -> list[tuple[str, float]]: ...
```

`Page[R]` is `class Page(BaseModel, Generic[R]): items: list[R]; next_cursor: str | None; total: int | None`. A `PostgresRepository(dsn, role)` and a `PgVectorIndex(dsn, index_name)` implement them in `perch/store/pg.py`. `perch/store/lance.py` is deleted after the migration in section 11.

## 3. Job manager

Replaces the closure interface in `perch/jobs.py`. The old `submit(job_id, fn)` cannot cross a process boundary, so a job is now a named kind plus an ids-only payload.

### 3.1 Kinds

| Kind | Who submits | Priority | Timeout (s) | Max attempts | Result |
|---|---|---|---|---|---|
| `scout_turn` | web | 0 | 180 | 2 | `user_data` row of kind `scout_session` |
| `handoff` | web | 1 | 120 | 3 | `user_data` row of kind `handoff` |
| `cover_points` | web | 1 | 120 | 3 | `user_data` row of kind `cover_points` |
| `brief` | web | 2 | 300 | 3 | `user_data` row of kind `brief`, or `redis:` for a guest |
| `precache` | scheduler | 8 | 900 | 3 | `public_cache` rows, namespace `precache` |
| `ingest` | scheduler, CLI | 9 | 3600 | 5 | `ingest_runs` row |
| `purge` | scheduler, web on delete | 5 | 600 | 5 | none |

- **`purge` payload.** `{"action": "user", "user_id": "<uuid>"}`, `{"action": "inactive"}`, `{"action": "guests"}`, `{"action": "jobs"}`, `{"action": "audit"}`, `{"action": "rekey", "user_id": "<uuid>"}` or `{"action": "tombstones"}`. `jobs` deletes `succeeded`, `failed`, `cancelled` and `dead` jobs after 30 days, which frees their idempotency keys, and that is safe because keys include the date. `audit` calls `perch_null_old_actors(90 days)`. The action is a code, not user text.
- **Scheduler.** A `perch scheduler` command, one copy only, enqueues `ingest` per source, a nightly `precache` with one job per Temple-affiliated author, and a daily `purge` for `inactive`, `guests`, `jobs`, `audit` and `tombstones`. Phase 3 records the author count and CPU seconds per author. It uses idempotency keys that contain the date, so a second copy does nothing harmful.

### 3.2 States

```python
class JobState(StrEnum):
    QUEUED    = "queued"      # waiting, including waiting for a retry: run_after may be in the future
    RUNNING   = "running"     # leased by a worker
    SUCCEEDED = "succeeded"   # terminal
    FAILED    = "failed"      # terminal, not retried: the handler raised PermanentError
    DEAD      = "dead"        # terminal dead letter: attempts used up or lease expired on the last attempt
    CANCELLED = "cancelled"   # terminal: cancelled while queued, or cooperatively while running
```

| From | To | Trigger |
|---|---|---|
| none | `queued` | `submit` |
| `queued` | `running` | claim |
| `queued` | `cancelled` | `cancel` by the owner |
| `running` | `succeeded` | handler returns |
| `running` | `queued` | handler raised a retryable error and `attempts < max_attempts`, or the lease expired and `attempts < max_attempts`. `run_after` is set by the backoff. |
| `running` | `failed` | handler raised `PermanentError` |
| `running` | `dead` | retryable error or lease expiry with `attempts >= max_attempts` |
| `running` | `cancelled` | the handler saw `ctx.cancelled()` and stopped |

### 3.3 Claim, lease and heartbeat

```sql
CREATE FUNCTION perch_claim_job(p_worker text, p_kinds text[], p_lease_s int) RETURNS SETOF jobs
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  UPDATE jobs SET state = 'running', lease_owner = p_worker, attempts = attempts + 1,
         lease_expires_at = now() + make_interval(secs => p_lease_s),
         heartbeat_at = now(), started_at = COALESCE(started_at, now())
   WHERE id = (SELECT id FROM jobs
                WHERE state = 'queued' AND run_after <= now()
                  AND (cardinality(p_kinds) = 0 OR kind = ANY (p_kinds))
                ORDER BY priority, run_after, created_at
                FOR UPDATE SKIP LOCKED LIMIT 1)
  RETURNING *;
$$;
```

- **Lease owner.** `p_worker` is the pair `<worker id>/<thread id>`, so two threads in one process never share an owner. `attempts` is the fencing token: it rises by one at each claim.
- **Empty queue.** The function returns no rows, and the caller treats that as nothing to do.
- **Wake-up.** `submit` runs `NOTIFY perch_jobs` after insert. One worker thread holds a direct connection from `PERCH_DATABASE_DIRECT_URL` and does `LISTEN perch_jobs`, because `LISTEN` does not survive transaction pooling. All other work goes through the pooler. The same thread polls every 2 seconds, so a lost notice costs at most 2 seconds.
- **Lease.** 60 seconds. A helper thread heartbeats every 15 seconds.
- **Fencing.** Every heartbeat, `stage`, `save_partial` and terminal update is `... WHERE id = $1 AND lease_owner = $2 AND attempts = $3`. A zero-row update raises `LeaseLost` in the handler, which must stop and write nothing more. Every user-data write a job makes starts inside `ctx.user_tx()`, which first runs `SELECT 1 FROM jobs WHERE id = $1 AND lease_owner = $2 AND attempts = $3 FOR SHARE` and raises `LeaseLost` on no row, so a stale thread cannot overwrite the new attempt's rows.
- **Hard timeout.** Each kind has the timeout in section 3.1. The helper stops heartbeating when it passes, so the lease expires and the reaper acts. The old thread is asked to stop through `ctx.cancelled()` and is fenced out by the token even if it runs on.
- **Test.** A handler sleeps past its timeout. The test asserts one terminal update, no user-data write from the stale attempt, `LeaseLost` on its fenced writes, and that every `spend_ledger` row carries its attempt number. Fencing stops the stale thread's writes, not a provider call already in flight, which still bills. `spend_ledger` gains `attempt smallint`.
- **Reaper.** Every worker runs this every 30 seconds. It is safe to run in many workers.

```sql
-- retry or dead-letter jobs whose lease expired
UPDATE jobs SET lease_owner = NULL, lease_expires_at = NULL,
       state = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END,
       error_code = 'lease_expired',
       run_after = now() + (LEAST(120, 5 * power(3, attempts - 1)) || ' seconds')::interval,
       finished_at = CASE WHEN attempts >= max_attempts THEN now() END
 WHERE state = 'running' AND lease_expires_at < now();
```

- **Backoff.** `min(120, 5 * 3^(attempts-1))` seconds plus up to 20 percent jitter added in code. So 5, 15, 45, 120.
- **Provider limit.** A Redis token bucket per provider and model, key `perch:pl:<provider>:<model>:<minute>`, is checked inside `perch/llm/` before each call against `PERCH_PROVIDER_RPM` and `PERCH_PROVIDER_TPM`. A provider 429 is retried inside the adapter, honouring `retry-after`, up to 3 tries with the delay capped at 30 seconds, before it becomes a job error. This keeps an overload from restarting whole jobs.
- **Retry rule.** Retryable: `ProviderError` that is not `Refusal`, network errors, `lease_expired`. Permanent: `Refusal`, `BudgetExceeded`, `QuotaExceeded`, `ConsentRequired`, input validation errors, a missing user key. `PermanentError` ends the job as `failed` with a fixed `error_code`.
- **Retries cost money.** A retried model job may bill twice. Handlers write results keyed by `job_id` and skip stages whose result row already exists, so a retry resumes. Every billed call is in `spend_ledger` regardless.
- **Dead letter.** `dead` rows stay for inspection 30 days, then the `purge` action `jobs` deletes them. A `job_dead` audit event is written and the page shows a plain failure message with the `error_code`.

### 3.4 Idempotency

- **Key.** `idempotency_key` is NOT NULL. The web layer builds it from the `Idempotency-Key` header when sent, otherwise `sha256(kind | audience | canonical_json(request_options) | input_ids | utc_date)` hex. Input ids are the `user_data` ids of the CV in use, the OpenAlex author id when the user typed one, and for a linked author the string `link` plus `users.openalex_linked_at`. They are never text.
- **Effect.** The unique index in section 2.2 covers `queued`, `running` and `succeeded` rows. A second `submit` with the same key by the same user returns the existing `job_id`. A `failed`, `dead` or `cancelled` job frees its key.
- **Scope of the key.** It includes the UTC date, so the next day's identical brief is a new job.

### 3.5 Payload rule

- **Ids only.** `payload` holds ids, enums, numbers and option flags. It never holds CV text, entry text, questions, drafts, names or contact details.
- **Where the question goes.** A Scout question is first stored as an encrypted `user_data` row by the web process. The job payload holds that row's id.
- **Enforcement.** `submit` validates `payload` against a per-kind pydantic model with `extra="forbid"`. Every string field is typed as an id pattern (`^[A-Za-z0-9:_./-]{1,200}$`) or a closed enum. A test plants the SYNTHETIC canary in a CV and a question, runs the jobs, and scans the `jobs` table.

### 3.6 Python contract

Module `perch/jobs.py`. Handlers register by name.

```python
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

JobKind = Literal["brief", "scout_turn", "handoff", "cover_points", "ingest", "purge", "precache"]
Audience = Literal["researcher", "student"]

class PermanentError(Exception):
    code: str                      # fixed list in perch/jobs.py ERROR_CODES

class RetryableError(Exception):
    code: str

@dataclass(frozen=True)
class JobStatus:
    job_id: UUID
    kind: JobKind
    state: JobState
    stages: list[dict]             # {"name", "status", "detail", "ms"} from job_events
    result_ref: str | None
    error_code: str | None
    attempts: int
    queued_ahead: int | None       # from perch_queue_position, for the "waiting" message
    created_at: datetime
    finished_at: datetime | None

class JobContext:
    job_id: UUID
    kind: JobKind
    user_id: UUID | None
    audience: Audience | None
    attempt: int
    payload: Mapping[str, Any]     # validated, ids only
    def stage(self, name: str, status: str, detail: str | None = None, ms: int | None = None) -> None: ...
    def heartbeat(self) -> None: ...             # also called by a helper thread
    def cancelled(self) -> bool: ...             # lease lost, owner cancelled, or hard timeout passed
    def user_tx(self): ...                       # context manager: transaction with perch.user_id set, fenced by the lease token
    def guest_tx(self): ...                      # same for a guest job, sets perch.guest_sid_hash
    lease_owner: str                             # '<worker>/<thread>'
    # LeaseLost(Exception) is raised by any fenced write that matches no row
    def save_partial(self, ref: str) -> None: ...  # sets jobs.result_ref so the page can read partial text

Handler = Callable[[JobContext], str | None]   # returns result_ref, or None

def register(kind: JobKind, *, max_attempts: int, timeout_s: int, priority: int
             ) -> Callable[[Handler], Handler]:
    """Decorator. One handler per kind; registering twice raises. Used as
    @register("brief", max_attempts=3, timeout_s=300, priority=2)"""

class JobRunner(ABC):
    @abstractmethod
    def submit(self, kind: JobKind, payload: Mapping[str, Any], user_id: UUID | None,
               idempotency_key: str, *, audience: Audience | None = None,
               guest_sid_hash: bytes | None = None, run_after: datetime | None = None) -> UUID:
        """Insert a queued job, or return the id of the live job with the same key."""
    @abstractmethod
    def status(self, job_id: UUID, user_id: UUID | None, *, guest_sid_hash: bytes | None = None
               ) -> JobStatus | None:
        """None when the job is unknown or belongs to someone else."""
    @abstractmethod
    def cancel(self, job_id: UUID, user_id: UUID | None, *, guest_sid_hash: bytes | None = None) -> bool:
        """Queued: cancelled at once. Running: asks the handler to stop. False when finished."""
    def wait(self, job_id: UUID, timeout: float | None = None) -> JobStatus:  # tests and CLI
        ...

class PostgresRunner(JobRunner): ...      # web uses submit, status, cancel; worker uses run_forever
    def run_forever(self, worker_id: str, kinds: Sequence[JobKind], concurrency: int,
                    stop: threading.Event) -> None: ...

class LeaseLost(Exception): ...
class InProcessRunner(JobRunner): ...     # dev without Docker: SQLite-free thread pool, same handlers
class InlineRunner(JobRunner): ...        # tests: runs the handler inside submit
```

- **Closures are gone.** `JobRunner.submit(job_id, fn)` is removed. `BriefService.run(brief_id)` becomes the handler registered for `brief`. `perch/scout/hub.py` becomes `scout_turn` plus `user_data` rows.
- **Tests.** A test starts ten `run_forever` loops against one Postgres, submits 200 jobs, and asserts each ran exactly once. Another test kills a worker mid-job and asserts a retry. A third asserts that a `DEAD` job appears after `max_attempts`. A fourth is the timeout test in section 3.3.
- **Status polling.** `GET /jobs/{id}` reads `status`. The page polls every 1 second for 10 seconds, then every 2 seconds. Server-sent events are not used in v1.

### 3.7 Errors and logs

Binds `web` and `worker` alike. Rule 5 says user text is never in a log.

- **No message text.** Handlers and routes never format an exception message into a log line, a column or a response. The worker logs the exception class name, the job id and a fixed `error_code` only. The old pattern in `perch/service.py` that stores `f"{type(e).__name__}: {e}"` and calls `traceback.print_exc()` is removed when `BriefService.run` becomes the `brief` handler.
- **Hooks.** At start, each process replaces `sys.excepthook` and `threading.excepthook` with a version that prints the class name, the job id when known and a stack of file and line numbers without local variables.
- **Pydantic.** Validation errors are reduced to `e.errors(include_input=False, include_url=False, include_context=False)`, and only `type` and `loc` are logged, never `msg` or `ctx`. Validators in `perch/user/models.py` and the payload models raise fixed messages that never contain the value. This applies to job payload checks and to decrypted blobs validated against `perch/user/models.py`.
- **No capture.** No error tracker, APM or log handler is configured to capture local variables, request bodies or response bodies.
- **Tests.** The Phase 6 leakage test adds a case that forces a validation error on a SYNTHETIC canary CV in the worker and in the web process, and scans the log output, `jobs.error_code`, the brief row and `audit_log`.

## 4. Redis

Redis holds no durable truth. A flush loses sessions and caches and nothing else. A missing quota counter is rebuilt from `spend_ledger` with `SET NX`, so a restart never overwrites a counter other workers have raised. The ingest epoch is kept in Postgres and copied to Redis.

### 4.1 Key layout

| Key | Type | TTL | Content |
|---|---|---|---|
| `perch:sess:<sid>` | hash | idle `PERCH_SESSION_IDLE_S`, slid on use, capped by `abs_exp` | `uid` (uuid or empty for guest), `guest` (0 or 1), `roles`, `audience`, `csrf`, `name` (display name from the IdP, never stored in Postgres), `created`, `abs_exp`, `gsid_hash`. No `id_token_hint` is kept, see section 7.2. |
| `perch:usess:<uid>` | set | `PERCH_SESSION_ABSOLUTE_S`, refreshed at each login | session ids of that user, so delete-my-data can end them all |
| `perch:oidc:<state>` | hash | 600 | `nonce`, `code_verifier`, `return_to`, `binder_sha256`. Read once with `GETDEL`. |
| `perch:rl:<scope>:<subject>:<window>` | string counter | window length | Fixed-window rate counter. |
| `perch:q:u:<uid>:<yyyymmdd>` | hash | 172800 | `usd_micro` (integer micro dollars), `in_tok`, `out_tok`, `calls`, `gate_calls` |
| `perch:q:gs:<gsid_hash>:<yyyymmdd>` | hash | 172800 | Same fields for one guest session. `gsid_hash` is `sha256(PERCH_PEPPER_GUEST + sid)`, the same value as `jobs.guest_sid_hash`, so the worker finds it. |
| `perch:q:gglobal:<yyyymmdd>` | string | 172800 | Micro dollars spent by all guests together that day. |
| `perch:q:global:<yyyymm>` | string | 3456000 | Calendar month spend in micro dollars, checked against `PERCH_ANTHROPIC_BUDGET_USD`. |
| `perch:pl:<provider>:<model>:<minute>` | hash | 120 | Requests and tokens used in that minute, for the provider token bucket. |
| `perch:inflight:<scope>` | string | 900 | Reserved micro dollars of calls in flight, one key per scope: the user, the guest session, the guest ceiling and the global month. Replaces the in-process `_IN_FLIGHT` dict in `perch/llm/budget.py`. |
| `perch:rc:<epoch>:<route>:<sha256>` | string | `PERCH_RESPONSE_CACHE_TTL_S` | Cached public GET response body. |
| `perch:epoch` | string | none | Copy of the ingest epoch, which is kept in Postgres in `ingest_runs.epoch` and read back if this key is missing. |
| `perch:mt:<key>` | string | 86400 | Hot copy of a `public_cache` row. |
| `perch:gres:<job_id>` | string | 3600 | Guest job result, JSON of public-derived content. |
| `perch:gsess:<gsid_hash>:brief:<brief_id>` | string | `PERCH_GUEST_TTL_S` | A guest brief before the job writes its result, JSON of public-derived content. `gsid_hash` is as in `perch:q:gs`. |
| `perch:gsess:<gsid_hash>:job:<brief_id>` | string | `PERCH_GUEST_TTL_S` | The job id of that guest brief, so the read finds `perch:gres:<job_id>`. Guests have no Scout. |
| `perch:shred` | pub/sub channel | none | Message `<user_id>`. Every process evicts that user's cached data key. |
| `perch:lastseen:<uid>` | string | 86400 | Throttle: `users.last_active_at` is written at most once a day. |

- **Session id.** 32 random bytes, URL-safe base64, from `secrets`. A new id is issued at login and the old one is deleted, which prevents fixation.
- **No user text in Redis.** The only user-derived value is the display name in the session hash.
- **Persistence.** Redis runs with AOF `everysec`. Losing it logs everyone out and nothing more.

### 4.2 Quotas

- **Unit.** Micro dollars from `perch.llm.budget.call_cost`, counted per account per UTC day. Budget `PERCH_DAILY_BUDGET_USD`. **D-6** A guest is counted per guest session against `PERCH_GUEST_DAILY_BUDGET_USD`, and all guests together against `PERCH_GUEST_GLOBAL_DAILY_BUDGET_USD`. A hashed client address is also capped per UTC day (`PERCH_GUEST_ADDR_DAILY_BUDGET_USD`, default 0.30), so one address cannot spend the whole guest ceiling; a campus behind one address shares that cap. Whether Temple's networks share one egress address is UNVERIFIED.
- **Spend context.** `perch.llm.budget.spend_context` is a context variable holding `user_id`, `guest_sid_hash`, `job_id` and `role`. `JobContext` sets it when a handler starts. `AnthropicProvider` and `AuditedProvider` read it, so a call is charged to the right counter and the ledger row carries the right ids. `AnthropicProvider` no longer builds its own `Budget()` from a file.
- **Flow.** Before any model call, one Lua script reads and reserves against every counter that applies: the user or guest session, the guest ceiling for guests, and the global month. It refuses with `QuotaExceeded` if any `used + inflight + estimate` passes its limit, else adds `estimate` to each `inflight` key. After the call it subtracts the estimate and adds the true cost to `usd_micro`. The same call writes `spend_ledger`. The scope gate call counts at its real cost with a minimum charge of one micro dollar, so repeated out-of-scope questions run out.
- **Visible to the user.** `GET /usage` returns spent, limit and reset time. The numbers are copied from the counter.
- **Global cap.** `PERCH_ANTHROPIC_BUDGET_USD` is a monthly cap on the calendar month. `Budget.check` reads the Redis counter, and a missing counter is rebuilt from the ledger with `SET NX`.
- **Replaces.** The `RateLimiter` per address in `perch/api.py` and the `PERCH_*_PER_HOUR` variables.

#### 4.2.1 Spend arithmetic (D-11)

Every input marked placeholder is a design value and not a measurement. The point is to show whether the placeholders agree with each other and with the provider's limits.

| Quantity | Value | Basis |
|---|---|---|
| Active accounts U | 1,000 | The plan's definition of 1,000 concurrent users |
| Per-account daily budget B | 0.50 USD | Placeholder |
| Worst-case day, U x B | 500 USD | 1,000 x 0.50 |
| Start tier monthly spend cap | 500 USD | `docs/v1/PROVIDER_AND_SSO.md` |
| Build tier monthly spend cap | 1,000 USD | `docs/v1/PROVIDER_AND_SSO.md` |
| Worst-case month, U x B x 30 | 15,000 USD | 500 x 30 |
| Utilisation u that fits the Start tier, 500 / 15,000 | 0.033 | Share of the budget the average account may use |
| Utilisation u that fits the Build tier, 1,000 / 15,000 | 0.067 | |
| Default global cap `PERCH_ANTHROPIC_BUDGET_USD` | 100 USD a month | Existing default |
| Account-days of full budget inside that cap, 100 / 0.50 | 200 | |
| Researcher brief cost, measured | about 0.09 USD | 0.0123 summary plus 0.0792 fit step, Sonnet 5.5, from the provider notes. It predates the S27 to S31 changes. |
| Full briefs per account-day at B, 0.50 / 0.09 | about 5 | |
| Guest session budget | 0.10 USD | Placeholder |
| Guest global ceiling per day | 5.00 USD | Placeholder, equals 50 guest sessions at full budget |

**250-user figures (Dakshitha, 2026-11-04).** The target is 250 concurrent users, so U is 250 here. Plain arithmetic from the table above, with B and the caps unchanged: worst-case day U x B is 250 x 0.50 = 125 USD. Worst-case month is 125 x 30 = 3,750 USD. The utilisation that fits the Start tier is 500 / 3,750 = 0.133 and the Build tier is 1,000 / 3,750 = 0.267. The 100 USD default global cap is 100 / 125 = 0.8 of one worst-case day. The 1,000-user rows above are superseded; they are kept to show the method. Measured load figures are in `docs/RESULTS.md` and `docs/deploy.md`, not here.

- **Consistency check.** The deployment is consistent only if `U x B x u x 30 <= min(global cap, tier monthly cap)` and `guest global ceiling x 30` fits inside what is left. With the placeholders it holds only when `u` is at most 0.033 on the Start tier. So B is not fixed. Phase 3 measures cost per brief and Phase 5 sets `B = cap / (U x u x 30)` from a measured or agreed `u`, and the global cap is set to the contract number.
- **Both guards.** The per-account budget protects against one user. The global monthly cap protects against all users together. Both must hold.

### 4.3 Rate limits

Fixed window, key `perch:rl:<scope>:<subject>:<floor(now/window)>`, `INCR` then `EXPIRE` in one Lua call. Subject is the user id, the guest session hash, or the address hash from `client_addr` in section 7.6. Address-keyed scopes use a high per-address ceiling plus a site-wide ceiling. Whether Temple's networks share one egress address is UNVERIFIED, so the sign-in limit that matters is keyed by the pre-auth binder cookie and not by address, and a shared campus address is not locked out by it. Defaults, overridable through `PERCH_RATE_LIMITS`:

| Scope | Subject | Limit | Window (s) |
|---|---|---|---|
| `login_start` | address hash | 600 | 600 |
| `login_callback` | sha256 of the `__Host-perch_oidc` binder | 5 | 600 |
| `login_global` | site | 1200 | 600 |
| `api_read` | user or address | 300 | 60 |
| `api_write` | user | 60 | 60 |
| `submit_job` | user | 10 | 60 |
| `upload` | user | 20 | 600 |
| `guest_job` | guest session | 5 | 600 |
| `guest_new` | address hash | `PERCH_GUEST_SESSIONS_PER_ADDRESS_HOUR` | 3600 |
| `guest_new_global` | site | 600 | 3600 |

These numbers are placeholders chosen for the design and are not measured. Phase 10 sets them from the load test. A refused call returns 429 with `Retry-After` and writes a `rate_limited` audit event with ids only.

### 4.4 Response cache and invalidation

- **What is cached.** Only routes whose output depends on no user: `GET /awards`, `GET /opportunities`, `GET /filters`, `GET /records/{id}`, which serves public kinds only. `GET /health` is never cached, so liveness reflects the live process.
- **Key.** `perch:rc:<epoch>:<route>:<sha256(canonical query string)>`. The request must carry no session-specific variation, so these routes never read the session, and the response has no `Set-Cookie`.
- **TTL.** 300 seconds by default.
- **Invalidation.** The `ingest` job ends with `Repository.bump_epoch()`, which increments the epoch in Postgres and copies it to `perch:epoch`. The epoch is part of every key, so old entries become unreachable at once and expire by TTL. There is no key scan.
- **Samples.** Sample records are excluded from these routes by default. The sample list is its own route, `GET /samples`, and is cached the same way under its own route name.

## 5. Cache keys for model text on public inputs

Applies only when every input to the call is public. The check is code: `perch/cache.py:is_public_input(ctx) -> bool` returns False if the call reads any `user_data` row, any CV, entry, document, added direction text, or an unlinked free-text constraint.

```python
def cache_key(namespace: str, *parts: str) -> str:
    """sha256 hex of 'perch-cache-v1|' + namespace + '|' + '|'.join(parts)"""
```

| Namespace | Parts, in order | TTL | Notes |
|---|---|---|---|
| `fit` | `record_id`, `record_fetched_at`, `profile_hash`, `prompt_version`, `model_id`, `validator_version` | none, a changed `fetched_at` changes the key | The fit explanation for a researcher whose profile is public. `profile_hash` is `sha256(canonical_json({"author": id, "work_ids": sorted, "as_of": date, "threads": thread work ids}))`. |
| `profile_summary` | `profile_hash`, `prompt_version`, `model_id`, `validator_version` | 7 days | |
| `author` | `author_id`, `openalex_fetch_date` | 7 days | OpenAlex author data and topic threads, shared across users, as the plan says. |
| `precache` | `author_id`, `profile_hash`, `ingest_epoch` | until the next epoch | Retrieval, rules and rerank output as record ids and scores. No model text. |

- **Prompt version.** A constant per skill in `perch/skills/`, bumped by hand when the prompt or schema changes. A test fails if a skill's prompt text hash changes without the constant changing.
- **Model id.** The `model` string the provider reports in `ChatResult.model`.
- **Validator version.** Constant in `perch/validate.py`. A changed validator invalidates cached text, so a cache hit never skips a stricter check.
- **Only validated text is cached.** A flagged or failed output is never written.
- **Rule for user data.** Any text produced from a user's CV, entries, documents or private direction text, for a student or a researcher, is written only into that user's encrypted `user_data` rows. It is never written to `public_cache`, Redis, a log or the audit log. The leakage check in Phase 6 enforces this by scanning each store for the canary.
- **Provider prompt cache.** System prompts and tool lists are sent with `cache_system=True`. This is the provider's cache, not ours, and keeps no copy in Perch.

## 6. Encryption

### 6.1 Design

- **Envelope.** One random 256-bit data key per user and version. Each field is encrypted under the data key with AES-256-GCM from the `cryptography` package. The data key is stored only wrapped by a master key, in the keys database.
- **Master key.** Dev: `PERCH_MASTER_KEY` from the environment. Prod: a KMS, behind the `KeyStore` interface. The production master key never leaves the KMS, so wrapping happens inside the KMS call.
- **Nonces.** 96 bits from `os.urandom(12)` per encryption. Random 96-bit nonces are safe for up to 2^32 encryptions under one key. A user writes a few thousand blobs a year, so that bound is not reachable, and the 12-month data-key rotation renews the key anyway. There is no database counter. A process-local count per key version is kept as a guard and raises `CryptoError` at 2^30. If a counter is ever wanted, the change is `encryptions bigint NOT NULL DEFAULT 0` on `user_keys`, incremented in blocks of 10,000 reserved at a time.
- **Binding.** The additional authenticated data names the user, table, column and row, and for `user_data` also the `kind` and `audience`, so a blob moved to another row, user, kind or side fails to decrypt.
- **Crypto-shredding.** Deleting a user's wrapped keys makes every blob for that user undecryptable at once in the live system. Copies in backups become unreadable when the last backup of the keys database that holds the key has expired, 35 days by design. Until then a restore of an old keys backup could revive the key, which section 6.6 guards against. The consent text states this window.

### 6.2 Blob format

```
byte 0        format version, 0x01
bytes 1-4     key_version, big-endian uint32
bytes 5-16    nonce, 12 bytes
bytes 17-end  AES-256-GCM ciphertext followed by the 16-byte tag
```

- **AAD bytes.** `b"perch/v1\x00" + user_id.bytes + b"\x00" + table + b"\x00" + column + b"\x00" + row_id + b"\x00" + extra + b"\x00" + key_version(4 bytes)`. `extra` is `kind + ":" + audience` for `user_data` and empty elsewhere. The key version is bound so a downgrade to an older key fails.
- **Row id for inserts.** The row's uuid is generated in code before the insert, so the AAD is known at encryption time.
- **Plaintext encoding.** UTF-8 JSON bytes, no compression.

### 6.3 Wrapped key format

`wrapped_key = byte 0x01 | nonce(12) | AES-256-GCM(master_key, data_key)`, with AAD `b"perch/v1/wrap\x00" + user_id.bytes + key_version(4) + master_key_id`. With a KMS key store, `wrapped_key` is the KMS ciphertext and the AAD is passed as the KMS encryption context. The KMS call format is UNVERIFIED until a host is chosen.

### 6.4 Python contract

Two modules. Both are imported only through `perch/user/data.py`, which is the only code that reads or writes `user_data.blob` or `users.openalex_id_enc`.

```python
# perch/crypto.py
from dataclasses import dataclass
from uuid import UUID

@dataclass(frozen=True)
class Aad:
    user_id: UUID
    table: str            # "user_data", "users"
    column: str           # "blob", "openalex_id_enc"
    row_id: str           # uuid text of the row
    extra: str = ""       # "<kind>:<audience>" for user_data
    def to_bytes(self, key_version: int) -> bytes: ...

class CryptoError(Exception): ...
class KeyShredded(CryptoError): ...      # tombstone present or no key rows: data is gone for good
class DecryptError(CryptoError): ...     # tag mismatch, wrong AAD, truncated blob

def new_data_key(user_id: UUID) -> int:
    """Create version N+1: 32 random bytes, wrap, store. Returns the new key_version.
    Refuses if the user has a tombstone. A trigger on user_keys also refuses the insert when
    a tombstone row exists, so the check and the insert cannot be split by a race."""

def encrypt_field(user_id: UUID, plaintext: bytes, aad: Aad) -> bytes:
    """Encrypt under the user's newest key version, creating version 1 on first use.
    aad.user_id must equal user_id. Returns the blob of section 6.2. Creation inserts with
    ON CONFLICT DO NOTHING and re-reads, so two racing first writes agree on one key."""

def decrypt_field(user_id: UUID, blob: bytes, aad: Aad) -> bytes:
    """Raises KeyShredded, DecryptError. Uses the version in the blob header."""

def key_version_of(blob: bytes) -> int: ...

def shred(user_id: UUID) -> None:
    """In order: write tombstone to key_tombstones, delete every user_keys row, write shred_log
    and the ledger line (section 6.6), publish perch:shred. After this, decrypt_field raises
    KeyShredded for any blob of this user. Idempotent."""

def rotate_master(old_id: str, new_id: str, *, batch: int = 500) -> int:
    """Re-wrap every user_keys row whose master_key_id == old_id under new_id. Resumable and
    safe to run while the system serves. Returns rows rewrapped. Data blobs are untouched."""

def rotate_data_key(user_id: UUID) -> int:
    """new_data_key, then enqueue purge(action='rekey') which re-encrypts that user's rows
    under the new version and sets retired_at on old versions once no blob uses them."""
```

```python
# perch/keystore.py
class WrappedKey(NamedTuple):
    user_id: UUID; key_version: int; wrapped: bytes; master_key_id: str

class KeyStore(ABC):
    """Wraps and unwraps data keys. Holds no per-user state."""
    @property
    @abstractmethod
    def current_master_id(self) -> str: ...
    @abstractmethod
    def wrap(self, data_key: bytes, *, user_id: UUID, key_version: int) -> tuple[bytes, str]:
        """Returns (wrapped_bytes, master_key_id)."""
    @abstractmethod
    def unwrap(self, wk: WrappedKey) -> bytes: ...

class EnvKeyStore(KeyStore):  ...   # PERCH_MASTER_KEY, PERCH_MASTER_KEY_ID, optional _PREV pair. Refused when PERCH_ENV=prod.
class KmsKeyStore(KeyStore):  ...   # PERCH_KMS_KEY_URI. Vendor client stays inside this class. UNVERIFIED until a host is chosen.

class KeyRepository:                 # the only code that opens PERCH_KEYS_DATABASE_URL
    def get(self, user_id: UUID, key_version: int) -> WrappedKey | None: ...
    def latest(self, user_id: UUID) -> WrappedKey | None: ...
    def put(self, wk: WrappedKey) -> None: ...
    def delete_all(self, user_id: UUID) -> int: ...
    def tombstone(self, user_id: UUID) -> None: ...
    def is_tombstoned(self, user_id: UUID) -> bool: ...
    def all_for_master(self, master_key_id: str, limit: int) -> list[WrappedKey]: ...

def key_store() -> KeyStore: ...     # chosen by PERCH_KEYSTORE
```

- **Unwrapped key cache.** An in-process LRU of 1024 entries, each with a 300 second TTL, zeroed on eviction as far as Python allows. A message on `perch:shred` evicts a user at once in every process, and every pub/sub reconnect clears the whole cache, because a message may have been missed.
- **Never logged.** Keys, wrapped keys, plaintext and blobs never appear in any log line, and section 3.7 forbids exception text in logs. `repr` of `Aad` shows ids only.
- **Dev check.** `PERCH_ENV=prod` with `PERCH_KEYSTORE=env` stops the process at start.

```python
# perch/user/data.py — the only reader and writer of user_data.blob
class UserData:
    """Each call opens user_tx(user_id), builds the Aad, encrypts or decrypts, and validates
    against the pydantic model for the kind. A foreign or missing id returns None or raises
    NotFound, never a different user's row."""
    def put(self, user_id: UUID, kind: UserKind, audience: Audience, model: BaseModel) -> UUID: ...
    def get(self, user_id: UUID, row_id: UUID, model_cls: type[M]) -> M | None: ...
    def list(self, user_id: UUID, kind: UserKind, audience: Audience, model_cls: type[M],
             *, limit: int = 50) -> list[tuple[UUID, M]]: ...
    def update(self, user_id: UUID, row_id: UUID, model: BaseModel, *,
               expect_updated_at: datetime) -> None:     # raises Conflict on a stale write
        ...
    def delete(self, user_id: UUID, row_id: UUID) -> bool: ...
    def link_openalex(self, user_id: UUID, author_id: str | None) -> None: ...
    def linked_openalex(self, user_id: UUID) -> str | None: ...
```

| `kind` | Pydantic model in `perch/user/models.py` |
|---|---|
| `cv` | `CvDoc` |
| `entry` | `EntryDoc` |
| `doc` | `UserDoc` |
| `brief` | `StoredBrief` holding `Brief` and `list[Lead]` |
| `saved_item` | `SavedItem` |
| `handoff` | `HandoffDraft` |
| `cover_points` | `CoverPointSet` |
| `scout_session` | `ScoutSessionDoc` |

- **One CV per side.** The partial unique index `ud_one_cv` allows one `cv` row per user and audience. `put` for a new CV replaces the old one in one transaction.
- **Job writes.** When called from a handler, the `user_tx` is the lease-fenced one from section 3.3.

### 6.5 Versioning and rotation

- **Master key rotation.** Set the new key as `PERCH_MASTER_KEY` and the old one as `PERCH_MASTER_KEY_PREV`. Run `perch keys rotate-master`. When it reports zero rows left on the old id, remove the old key. In KMS mode, key rotation inside the KMS needs no Perch step.
- **Data key rotation.** Each blob header carries its key version, so old and new blobs coexist. Rotation runs on a schedule of 12 months, on request, or when the process-local guard in 6.1 trips.
- **Data key re-encryption.** The `rekey` purge action re-encrypts a user's rows one batch per transaction. Each row is re-read with `FOR UPDATE` and written with the same AAD but the new version, so a concurrent write cannot be lost.
- **Compromise response.** Rotating the master key does not help if a data key leaked. Rotate that user's data key and re-encrypt, or shred.

### 6.6 Shredding, backups and restore

- **Delete-my-data order.** 1) Tombstone and key deletion in the keys database. 1b) Set `users.deleted_at` and cancel the user's queued and running jobs, so a running job cannot re-create a key, which the trigger also refuses. 2) Insert into `shred_log` and write the ledger object. 3) End sessions through `perch:usess:<uid>`. 4) Enqueue `purge(action="user")`, which clears the user through `perch_delete_user_rows`. Step 1 is the point of no return. Rows may linger until step 4 and are already unreadable. The next sign-in by the same person creates a new user id and a new key.
- **Separate database and backup.** `perch_keys` has its own backup schedule, its own backup storage account and its own retention, independent of `perch` backups. In production it should be its own instance.
- **Why separate.** Restoring a data backup must not bring back a deleted key. Restoring the keys database alone must not bring back a deleted key either.
- **Three tombstone copies.** `key_tombstones` in the keys database, `shred_log` in the data database, and one object per shred under `PERCH_SHRED_LEDGER_URI`, an object store prefix with object lock or versioning, outside both databases and safe for several replicas. The object is named by the user id and holds a UTC date, nothing else. In dev a mounted directory is allowed.
- **Reconcile after any restore.** `perch reconcile-shreds` is required by the restore runbook. It reads the three sources, takes the union, deletes any `user_keys` rows and any user rows for those ids, and re-asserts the tombstones. The `purge(action="tombstones")` job runs it daily as well. The restore marker is a file, `RESTORE_PENDING`, in the ledger directory, written by `perch restore-mark` before a restore (S48). While it exists the web answers 503 on account routes and `/health?ready=true` fails; the worker reconciles at start and clears it. It is a file and not a row, because a row in the data database can be erased by the restore it guards. See `docs/deploy.md` section 9.
- **Retention.** Tombstones are kept at least as long as the longest retained backup of either database, and never fewer than 400 days. Backups of `perch` are kept 35 days. Backups of `perch_keys` are kept 35 days. These numbers are design values. The ops runbook in Phase 10 confirms them.
- **Honest limit.** `perch_keys` credentials sit in both the `web` and `worker` processes, because both call `KeyRepository`. The separate role stops a SQL bug in a data query from reading keys. It does not stop an attacker who runs code inside a process. See threat T2.

## 7. Auth

### 7.1 Interface

Module `perch/auth/base.py`. Implementations: `perch/auth/oidc.py` (`OidcProvider`). SAML and CAS are reached through the IdP, which presents OIDC to Perch, so no second implementation is needed for Temple. If Temple IT can offer only SAML, a `SamlProvider` is added behind the same interface. That is UNVERIFIED and depends on the answer to the questions listed in `docs/v1/PROVIDER_AND_SSO.md`.

```python
@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str                    # IdP's stable id for the user
    display_name: str | None        # session only, never stored in Postgres
    claims: Mapping[str, Any]       # raw claims, read by role mapping, never stored

@dataclass(frozen=True)
class AuthRedirect:
    url: str
    state: str
    binder: str                     # random value set as the __Host-perch_oidc cookie

class AuthProvider(ABC):
    name: str
    @abstractmethod
    async def begin(self, return_to: str) -> AuthRedirect:
        """Create state, nonce, a PKCE verifier and a binder. Store the first three plus
        sha256(binder) in perch:oidc:<state>. Return the authorisation URL and the binder.
        return_to is passed through safe_return_to before it is stored."""
    @abstractmethod
    async def complete(self, params: Mapping[str, str], binder: str | None) -> tuple[Identity, str]:
        """GETDEL perch:oidc:<state>, so it is single use. Compare sha256(binder) with the stored
        hash using hmac.compare_digest. Exchange the code with the verifier. Validate the ID token as
        in section 7.2. Return (Identity, return_to). Any failure raises AuthError with a fixed code."""
    @abstractmethod
    async def end_session_url(self, post_logout_redirect: str) -> str | None:
        """Uses client_id and post_logout_redirect_uri. No id token hint is stored, so none is sent.
        Whether the IdP accepts that is UNVERIFIED for Temple; Keycloak does."""
```

```python
# perch/auth/session.py
@dataclass
class Session:
    sid: str; user_id: UUID | None; guest: bool; roles: frozenset[str]
    audience: Audience; csrf: str; display_name: str | None; created: float; abs_exp: float
    consent_version: int = 0  # accepted consent version; 0 when none or withdrawn

class SessionStore:
    async def create_user(self, user_id: UUID, roles, identity: Identity) -> Session: ...
    async def create_guest(self, audience: Audience) -> Session: ...
    async def get(self, sid: str) -> Session | None: ...     # slides the idle TTL, checks abs_exp
    async def set_audience(self, sid: str, audience: Audience) -> None: ...
    async def destroy(self, sid: str) -> None: ...
    async def destroy_all(self, user_id: UUID) -> int: ...   # via perch:usess:<uid>

# perch/auth/deps.py — FastAPI dependencies
async def session_optional(request) -> Session | None
async def require_session(request) -> Session                       # 401 when none
async def require_user(request) -> Session                          # 401 for none, 403 for guest
def require_role(*roles: str) -> Callable[..., Session]             # 403 when not held
async def require_csrf(request, session=Depends(require_session)) -> None   # on every non-GET
def require_consent(session) -> None                                # 403 consent_required
```

### 7.2 Flow

1. **Start.** `GET /auth/login?return_to=/path` calls `begin`, sets the pre-auth cookie `__Host-perch_oidc` with the binder, `Max-Age=600`, `HttpOnly`, `Secure`, `SameSite=Lax`, and redirects. The authorisation request uses response type `code`, scope `PERCH_OIDC_SCOPES`, `code_challenge_method=S256`, `state` and `nonce`. The binder ties the login to this browser, so a callback URL sent to someone else fails, which stops login CSRF.
2. **Callback.** `GET /auth/callback` reads the binder cookie, calls `complete`, and clears the cookie. On success the web process calls `perch_login_user(issuer_hash, subject_hash)`, which creates the user on first sign-in.
3. **New user.** A user with no roles and no consent is sent to `/welcome`, where they pick a side, student or researcher, or both, and see the consent text. `POST /me/consent` stores the `consents` row and `POST /me/roles` stores the roles, typed as a list of `Literal["student", "researcher"]` so `staff` cannot be self-granted.
4. **Session.** `SessionStore.create_user` writes the Redis hash and sets the cookie. A new `sid` is issued even if one existed.
5. **Logout.** `POST /auth/logout` destroys the Redis session, clears the cookie, and returns the IdP end-session URL if the IdP offers one.
6. **Dev IdP.** Keycloak realm `perch`, confidential client `perch-web`, standard flow on, direct grants off, PKCE S256 required, valid redirect URI `PERCH_PUBLIC_URL/auth/callback`. Two SYNTHETIC test users are in the imported realm file.

#### Token checks and return_to

- **Algorithms.** An allowlist: `RS256` and `ES256`. `none` and symmetric algorithms are refused.
- **Keys.** The JWKS is cached and refreshed once when an unknown `kid` appears, at most once a minute.
- **Claims.** `iss` equals `PERCH_OIDC_ISSUER`. `aud` contains `PERCH_OIDC_CLIENT_ID`. `azp` equals the client id when present. `exp` and `iat` are checked with 60 seconds of clock skew. `nonce` equals the stored nonce.
- **return_to rule.**

```python
def safe_return_to(v: str | None) -> str:
    if v and v.startswith("/") and not v.startswith("//") and "\\" not in v and "\n" not in v:
        return v
    return "/"
```

### 7.3 Cookie and CSRF

| Item | Value |
|---|---|
| Name | `__Host-perch_sid`. With `PERCH_COOKIE_INSECURE=1` in dev: `perch_sid`. A second cookie `__Host-perch_oidc` lives 600 seconds and only during login. |
| Attributes | `HttpOnly; Secure; SameSite=Lax; Path=/`, no `Domain`, `Max-Age` is not set so it is a session cookie |
| Why Lax | The return from the IdP is a top-level cross-site navigation. A Strict cookie would not accompany a link from another site. |
| Idle timeout | 1800 s, slid on each request |
| Absolute | 28800 s |
| CSRF method | Synchronizer token. The token is in the Redis session and returned by `GET /auth/session`. |
| Sent as | Header `X-CSRF-Token` on every POST, PUT, PATCH and DELETE |
| Plus | `Origin` must equal `PERCH_PUBLIC_URL`, or the request is refused with 403 and a `csrf_reject` audit event |
| Comparison | `hmac.compare_digest` |

- **Other headers.** The existing strict Content-Security-Policy, `X-Content-Type-Options`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store` on every authenticated route. No third-party scripts.
- **Chosen over double submit.** Every session already lives in Redis, so a synchronizer token costs nothing and avoids cookie-injection weaknesses of double submit.

### 7.4 Guest mode

- **Entry.** `POST /auth/guest` with a CSRF-exempt, same-origin check. It creates a guest session with `guest=1` and `uid` empty. TTL is `PERCH_GUEST_TTL_S` absolute, with no sliding.
- **Can do.** Browse and filter awards and funding. Build a brief for a public OpenAlex author id, or for a built-in SYNTHETIC student persona. Compare, export. Read the Help page.
- **Cannot do.** Upload or paste a CV or entries. Scout. Hand-off drafts. Cover points. Save anything. These need an account.
- **Stored.** No row in `users`, `user_data` or `consents`. A guest brief is a job with `user_id` NULL and `guest_sid_hash` set, submitted and read through `guest_tx`, and its result is a Redis key `perch:gres:<job_id>` that expires in an hour. Every guest brief value in Redis is sealed with AES-GCM under a random key of that guest session, `perch:gsess:<gsid_hash>:bkey` (S49 Q50); the worker knows only the session hash, so the key sits beside the values rather than in the session cookie. The `jobs` row has public ids only and is deleted by `purge(action="guests")` after 24 hours.
- **Limits.** The `guest_job` rate limit and the guest daily budget are keyed by the guest session. A site-wide guest ceiling and a per-address ceiling on new guest sessions bound abuse, see sections 4.2 and 4.3.
- **Banner.** Every guest page shows a banner stating that nothing is saved and the session ends in an hour. Exports from a guest session carry the banner text.
- **Model use.** The brief's model text for a public author id is public-input text and may hit `public_cache`. The synthetic persona brief carries the sample badge and banner required by rule 11.

### 7.5 Roles, OpenAlex link and consent

- **Roles.** `users.roles` holds any of `student`, `researcher`, `staff`. **D-3** A user picks `student`, `researcher` or both at first sign-in. Nothing from the IdP decides this, because the school and role claims are UNVERIFIED. `staff` is granted only by the operator command `perch grant-role <user_id> staff` or, when Temple confirms a claim, by `PERCH_STAFF_GROUP`; `POST /me/roles` never accepts it. Staff screens are out of scope for v1. Roles gate screens and the `audience` parameter. They never change which rows a user can read.
- **Audience switch.** `POST /me/audience {audience}` changes `session.audience` and `users.last_audience`. A request with an `audience` the user does not hold gets 403.
- **OpenAlex link.** `PUT /me/openalex {author_id}` validates the id with the `GET /authors/resolve` logic, then stores it encrypted in `users.openalex_id_enc`. **D-4** The link is a self-asserted claim, since OpenAlex offers no proof of identity. It pre-fills the researcher brief and nothing more. Briefs for other public author ids stay allowed, because the data is public.
- **Consent.** Shown at first sign-in and again when `PERCH_CONSENT_VERSION` rises. The text names `PERCH_CONSENT_PROVIDER_NAME` and states that CV and entry text, with contact details blanked, may be sent to that provider to write briefs, hand-offs and cover points, that data is stored encrypted, and how to delete it. The `consents` row stores the version, the provider name and the text hash. Jobs that send user data call `require_consent` and end as `failed` with `consent_required` without it. Withdrawing through `POST /me/consent/withdraw` sets `withdrawn_at` and blocks those jobs, but does not delete data. The consent text also says that a deleted account's backups clear within 35 days, section 6.1. Delete-my-data is separate.
- **Delete-my-data.** `POST /me/delete` with body `{"confirm": "delete"}` runs the order in section 6.6 and returns 202. The session ends.
- **12-month purge.** `purge(action="inactive")` calls `perch_inactive_users('12 months', 500)` and runs the same delete order for each. `last_active_at` is updated at most once a day per user. **D-5** No warning is sent before the purge, because the app stores no email address and sends nothing, rule 7. The consent text states the 12-month rule.

### 7.6 Client address

Rate limits and guest session creation need the client address, and behind a load balancer the peer address is the proxy's.

```python
def client_addr(request) -> str:
    """Read X-Forwarded-For only when the direct peer address is inside PERCH_TRUSTED_PROXIES;
    otherwise ignore the header and return the peer address. When it is read, walk from the right,
    skip hops inside PERCH_TRUSTED_PROXIES, and the first hop outside them is the client.
    IPv6 is truncated to its /64. The result is hashed with PERCH_PEPPER_GUEST before use as a key."""
```

- **Network.** The web port binds to the proxy network only. In Compose, `web` publishes no host port in production, and the dev mapping to 8090 is for local use with `PERCH_TRUSTED_PROXIES` empty. So a client cannot reach `web` directly and forge the header.
- **Replaces** `client_key` and `SERVE_OPTIONS` in `perch/api.py`, which trust forwarded headers only from loopback.
- **Keys.** Signed-in limits use the user id. Guest limits use the guest session hash. Only `login_start`, `guest_new` and unauthenticated reads use the address, and each also has a site-wide ceiling.

## 8. Request paths

`audience` is a request parameter and a session field. Nothing below forks on audience except the record kinds, the eligibility rules, the profile source and the receiving offices, as the plan fixes.

| Path | Process | Tables | Redis | Model | Result |
|---|---|---|---|---|---|
| Browse and filter | web | `records` read | response cache `perch:rc:*`, rate counter | none | JSON page. Researcher: `opportunity`. Student: `scholarship`. Temple-only and school tags are WHERE clauses. |
| Build brief | web submits, worker runs | web: `jobs`, `user_data` (the CV row is read by id in the worker). Worker: `records`, `record_vectors` read, `public_cache` r/w, `user_data` write, `job_events`, `spend_ledger`, `audit_log` | session, quota, `perch:mt` | Embedder, reranker, MiniCheck on CPU. `profile_summary` and `fit_explainer` on the provider. | `brief` row. The page polls `/jobs/{id}`, shows deterministic leads first, then fills in text. |
| Scout turn | web stores the question and submits, worker runs | `user_data` (`scout_session`, plus read tools: `brief`, `cv`, `entry`, `saved_item`), `records`, `jobs`, `spend_ledger` | quota, rate | `gate` first. Then `scout` with read tools if in scope. MiniCheck on CPU. | `scout_session` row. A code-written refusal for out of scope, with no large model call. |
| Hand-off | web submits, worker runs | `user_data` read of brief and CV, write of `handoff` | quota | `handoff` | A stored draft. Nothing is sent. |
| Cover points | web submits, worker runs | `user_data` read of CV, entries, brief; write of `cover_points` | quota | `cover_points` | A stored point set for one record. |
| Export | web | `user_data` read of the brief, `records` read | none | none | JSON, Markdown or HTML built by `brief_blocks(audience, ...)` from stored fields. Carries the sample banner where needed. |
| Compare, keep, dismiss | web | `user_data` read and write on `brief` or `saved_item` | none | none | Pure code. |
| Ingest | worker | `records`, `record_vectors`, `ingest_runs`; epoch bump | `perch:epoch` | Embedder on CPU. No cloud call. | New records and vectors. |
| Pre-cache | worker | `records`, `record_vectors`, `public_cache` | none | none in v1 | Retrieval, rules and rerank results for every Temple-affiliated OpenAlex author. |

- **Web never runs a model.** The scope gate runs in the worker as the first step of a `scout_turn` job, which costs one queue hop. If Phase 3 shows that hop is too slow, a bounded gate call from the web process is a design change to be recorded in the plan.
- **Streaming of text.** The worker calls `ctx.save_partial` after each stage, and the page re-reads the `brief` row through `GET /briefs/{id}`.
- **Error paths.** `ConsentRequired`, `QuotaExceeded` and `BudgetExceeded` end the job as `failed` with a fixed `error_code` and a fixed plain message in the UI.

## 9. API surface

All routes sit under one FastAPI app. "Auth" is the weakest allowed session: `none`, `session` (guest or user), `user`, `user+role`. Every non-GET needs CSRF except where marked. Request and response names are pydantic models in `perch/request_models.py` and `perch/response_models.py`.

### 9.1 Kept, changed or removed

| Route today | Verdict | Note |
|---|---|---|
| `GET /health` | kept | Adds `?ready=true` for readiness. |
| `GET /authors/resolve` | kept | Auth `session`. Rate limited. Runs in `web` with the OpenAlex key and a single-host egress rule, D-13. Results are cached in Redis for the author cache TTL. |
| `POST /briefs` | changed | Body gains `audience`. Returns `JobAccepted`. Auth `session`. |
| `GET /briefs/{id}` | changed | Reads the encrypted `brief` row. Auth `session`. Guest reads Redis. Carries the brief's `job` (state, error code, attempts, queue place, whether a worker is alive); a brief whose job ended without it shows as `failed` with a code-written sentence (S49 B1). |
| `POST /briefs/{id}/cancel` | new (S49) | Auth `session` and CSRF. Cancels the job that builds the brief. |
| `POST /briefs/{id}/leads/{lead_id}/keep`, `dismiss`, `restore` | changed | Auth `session`, so a guest can keep and compare as section 7.4 says. A user updates the `brief` row. A guest updates the brief's Redis key and does not extend its hour. |
| `GET /briefs/{id}/export.json`, `export.md`, `export.html` | changed | Shared `brief_blocks`. Auth `session`. |
| `GET /briefs/{id}/compare` | changed | Shared `compare_rows`. Auth `session`. Reads the session's own brief. |
| `POST /briefs/{id}/handoff` | changed | Now a job. Returns `JobAccepted`. Auth `user`. |
| `GET /records/{record_id:path}` | changed | Public kinds only, served from the response cache. The user's own rows are served only from `/me/...` routes, which are never cached. |
| `POST /briefs/{id}/scout` | changed | Creates a `scout_session` row and the first `scout_turn` job. Auth `user`. |
| `GET /scout/{sid}`, `POST /scout/{sid}/{action}` | changed | Backed by `user_data` and jobs, not memory. |
| `GET /private`, `/private/samples/{name}`, `POST /private/session`, `GET /private/session`, `POST /private/end`, `POST /private/cloud`, `POST /private/documents`, `POST /private/documents/{kind}/remove`, `POST /private/brief`, `POST /private/student/brief`, `GET /private/brief`, `POST /private/leads/{lead_id}/{action}`, `GET /private/records/{record_id:path}`, `GET /private/student/note`, `GET /private/compare`, `POST /private/handoff`, `GET /private/export.json`, `GET /private/export.md`, `GET /private/export.html`, `POST /private/unmask`, `POST /private/scout`, `GET /private/scout/{sid}`, `POST /private/scout/{sid}/{action}` | removed | Private mode is gone. Their jobs are done by the routes above and the account routes below. `/private/unmask` has no successor, because masks are gone. |

### 9.2 New routes

| Method and path | Auth | Request | Response |
|---|---|---|---|
| `GET /auth/login` | none | query `return_to` | 302 to the IdP |
| `GET /auth/callback` | none | IdP query | 302, sets cookie |
| `POST /auth/logout` | session | none | `LogoutResult` |
| `POST /auth/guest` | none, same-origin | `GuestStart {audience}` | `SessionView` |
| `GET /auth/session` | none | none | `SessionView {signed_in, guest, roles, audience, csrf, display_name, consent_ok, usage}` |
| `GET /welcome` | none | query `return_to` | 302 to `/#/welcome`, the app's own screen |
| `POST /me/consent` | user | `ConsentAccept {version}` | `Ok` |
| `POST /me/roles` | user | `RolesSet {roles: list[Literal["student","researcher"]]}` | `Ok` |
| `POST /me/audience` | user | `AudienceSet {audience}` | `Ok` |
| `PUT /me/openalex` | user+researcher | `OpenAlexLink {author_id}` | `Ok` |
| `GET /me` | user | none | `MeView` without content of any row |
| `POST /me/delete` | user | `DeleteConfirm {confirm}` | 202 `Ok` |
| `GET /me/docs` | user | query `audience` | `list[DocView]`, labels only decrypted for the owner |
| `POST /me/docs` | user | `DocAdd {kind, label, text}` or multipart file | `DocView` |
| `DELETE /me/docs/{id}` | user | none | `Ok` |
| `GET /me/saved` | user | query `audience` | `list[SavedItemView]` |
| `PUT /me/saved/{record_id:path}` | user | `SavedItemSet {note, audience}` | `SavedItemView` |
| `DELETE /me/saved/{record_id:path}` | user | none | `Ok` |
| `GET /me/briefs` | user | query `audience` | `list[BriefSummary]` |
| `GET /usage` | session | none | `UsageView {spent_usd, limit_usd, resets_at}` |
| `GET /jobs/{id}` | session | none | `JobStatusView` |
| `POST /jobs/{id}/cancel` | session | none | `Ok`. Guests are checked through `guest_tx`. |
| `POST /me/consent/withdraw` | user | none | `Ok` |
| `GET /awards` | none | query `temple_only, school, scope, level[], q, closes_after, group, cursor, limit` | `{kind, groups[{key, label, total, next_cursor, items[]}]}`. One group `all`; with `school`, two groups, `school` then `open` ("Open across Temple": scope `temple_wide` or `unstated`), never mixed. `temple_only` keeps records whose source is a Temple page. |
| `GET /opportunities` | none | same query set | same shape |
| `GET /filters` | none | query `audience` | `FilterView {audience, schools[{name,count}], levels[], total, temple_total}` from the stored rows; samples never count |
| `GET /samples` | none | query `audience, cursor, limit` | `{audience, sample: true, notice, total, next_cursor, items[]}`, SYNTHETIC records only, every item `sample: true` |
| `POST /briefs/{id}/cover-points` | user | `CoverRequest {record_id}` | `JobAccepted` |
| `GET /briefs/{id}/cover-points/{record_id:path}` | user | none | `CoverView` |
| `GET /briefs/{id}/handoff/{draft_id}` | user | none | `DraftView` |

- **Auth failures.** 401 with `{"error":"auth_required"}` when no session. 403 with a code for a role, consent or CSRF failure. 429 with `Retry-After`. 404 for another user's id, never 403, so ids are not confirmable.
- **Static files.** `web/` is served unchanged in kind. `private.js` and the Local or Cloud dialog are removed in Phase 7.
- **MCP server.** `perch/mcp_server.py` stays a read-only extra door for public records and needs no session. It never reads `user_data`.

## 10. Threat model

### 10.1 Assets

| Asset | Where | Sensitivity |
|---|---|---|
| CV, entries, documents, briefs, drafts, Scout history | `user_data.blob` | High. A student's records. |
| Data keys | `perch_keys.user_keys`, wrapped | Critical. |
| Master key | env in dev, KMS in prod | Critical. |
| IdP subject links | `users.subject_hash` | Medium. A hash with a pepper. |
| Sessions | Redis | High while live. |
| Provider key and spend cap | worker env, ledger | Money. |
| Public corpus | `records` | Integrity matters, not secrecy. |

### 10.2 Actors and trust boundaries

- **Actors.** Other signed-in users. A guest or anonymous visitor. An attacker who controls text in a fetched web page, a record, a CV or a document. A person with a stolen laptop or backup. An operator with database access. The model provider, which sees user text after consent.
- **Boundaries.** Browser to web. Web to Postgres and Redis. Worker to the cloud provider. Worker to public sources. Web or worker to the keys database. Postgres to its backups. Perch to the IdP.

### 10.3 Threats and mitigations

| ID | Threat | Mitigation | Where |
|---|---|---|---|
| T1 | A user reads another user's rows through a bug, an id guess or a SQL error. | RLS with FORCE on every user table. `SET LOCAL perch.user_id` per transaction. Zero rows when unset. AAD binds user and row, so a swapped blob fails to decrypt. 404 for foreign ids. A test connects as `perch_web` with another user's id and asserts zero rows and failed decrypts. | 2.1, 2.2, 6.2, 9 |
| T2 | Key theft: an attacker gets wrapped keys, the master key, or code execution in a process. | Wrapped keys sit in another database under another role. The master key is in the KMS in prod and never on disk. Data keys live only in a short-lived in-process cache. Honest limit: code execution in `web` or `worker` can call the key repository. Mitigations are short cache TTL, no key in logs, network policy that lets only those two services reach `perch_keys`, and the option to split a key service into its own process later. | 6.1, 6.4, 6.6 |
| T3 | Prompt injection through record text, a fetched page or a CV: instructions in text steer the model. | Models only read, never write or send. Scout tools are an allowlist of read tools and take validated arguments. Tool results are fenced as data in the prompt. Every output goes through Layer 1 and MiniCheck, and numbers, dates and links must come from cited records. Hand-offs are drafts. The scope gate sees the question only, not tool results. A Phase 8 Opus review attacks this. | rule 5, 8 |
| T4 | SSRF in fetchers: a record or CV link makes the worker request an internal address. | Fetchers use a fixed host allowlist per source in `perch/sources/`. User-supplied URLs are never fetched. Workers run with an egress policy that allows only the provider, OpenAlex and the listed public hosts. Redirects are not followed to other hosts. | 1.1, 8 |
| T5 | Quota abuse and cost burn: scripted briefs, Scout spam, guest farming. | Daily micro-dollar budget per account and per guest session, plus a global guest ceiling and a global monthly cap, all reserved in one step before each call. Provider token bucket. Rate limits with site-wide ceilings. Out-of-scope questions still cost. Guests cannot use Scout, hand-offs or uploads. | 4.2, 4.3, 7.4, 7.6 |
| T6 | Log leakage: user text lands in logs, traces, error pages, job rows, the audit log or caches. | Structured logs carry ids and hashes. `Crashed` middleware returns a fixed body and logs exception class and ids only. Job payloads are schema-checked. Section 3.7 bans exception text in logs and scrubs the excepthooks and Pydantic errors. `audit_log.detail` is size-limited and built from codes. Redis holds no user text. The Phase 6 leakage check plants a canary in a SYNTHETIC CV and scans logs, Redis, `jobs`, `audit_log`, `public_cache`, caches and every non-blob column, and is proved to fail on a planted leak first. | 3.5, 3.7, 4.1, 5 |
| T7 | A backup restore revives a deleted key or deleted rows. | Separate keys database and backup. Three tombstone copies, one outside both databases. `reconcile-shreds` is a mandatory restore step and runs daily. | 6.6 |
| T8 | Session theft or fixation, CSRF, login CSRF, open redirect. | Random 256-bit ids, `__Host-` HttpOnly Secure SameSite cookies, new id at login, idle and absolute limits, synchronizer token plus Origin check, `safe_return_to`, PKCE and nonce, and the `__Host-perch_oidc` binder cookie with single-use state, which stops login CSRF. | 7.2, 7.3, 7.6 |
| T9 | Cross-user cache poisoning: user-derived text served to another user. | Only `is_public_input` calls write `public_cache`. The response cache holds only routes that never read the session. Cache keys name their inputs. | 4.4, 5 |
| T10 | Dead or stuck jobs lose a user's work or double-bill. | Leases, retries with caps, dead letter, resume by stage, idempotency keys, ledger rows for every billed call. | 3 |
| T11 | Provider sees user text. | One consent naming the provider before any such call, contact details blanked before any model sees text, no use beyond the contracted provider. Provider retention terms are UNVERIFIED until a contract exists. | 7.5 |
| T12 | Weak IdP claims or an unverified OpenAlex link let a user pose as an author. | Roles never gate data access. The link is self-asserted and only pre-fills. Public data is public anyway. | 7.5 |

## 11. Fallback, v1 drops, and corpus migration

### 11.1 What the fallback keeps that v1 drops

| Fallback (tag `v0.1-demo-fallback`) | v1 |
|---|---|
| Local-model option and the "Local only" promise of private mode | Gone. A signed-in user's text goes to the contracted provider after consent. |
| Memory-only sessions and the write overlay | Gone. Encrypted rows in Postgres. |
| Gemma on Ollama as chat, Clef and Clef-flash as grounder and decider | Gone. Cloud chat, MiniCheck grounder. Clef rows stay in old results as history. |
| `perch/model_server.py` and GPU profiles | Gone. CPU models in the worker. |
| SQLite and LanceDB as the store | SQLite for unit tests only. Lance deleted. |
| Per-address caps and 20 sessions per address | Per-account budgets and Redis rate limits. |
| Warm briefs, the weekly monitor shelf, the egress filter and masks | Gone. Pre-cache job replaces warm briefs. |
| Tailscale Funnel demo host | The fallback keeps it. v1 uses Compose. |

- **The fallback itself is untouched.** `main` stays on it until the gate in `docs/REBUILD_PLAN.md`.

### 11.2 Migration of the public corpus

Command: `perch migrate-corpus --sqlite <perch.db> --lance <dir> --pg <dsn>`. Data steps run as `perch_worker`. The index step runs as `perch_owner`, because only the owner may create indexes. Idempotent.

1. **Records.** Open `SQLiteRepository`. For each class in `{Researcher, Work, Award, Opportunity, Organisation, Scholarship}` call `list` and `upsert` into `PostgresRepository` in batches of 1000. Provenance columns are copied unchanged. Kinds `brief`, `lead` and `digest` are skipped, and the count skipped is printed.
2. **Samples.** Read the sample database (`data/sample.db` or the demo copy). Insert with `source='synthetic'`. The CHECK in section 2.2 rejects any row without the `sample:` prefix.
3. **Vectors.** Open the Lance table `opportunities`, read `id`, `text` and `vector`, and insert into `record_vectors` under `index_name = 'opportunities'`, copying `sample`, `temple_funded` and `schools` from `records`. No opportunity text is re-embedded, so those vectors are computed once and the back-test rows stay comparable. The `scholarships` index has no Lance source, so its vectors are computed once here with the same embedder from the same record text that `perch/private/student.py` embeds today, and then stored. That is the only new embedding the migration makes. The command first asserts that each vector has length 1024, and that the embedder recorded for the corpus is `Qwen/Qwen3-Embedding-0.6B`, and stops otherwise.
4. **Indexes.** As `perch_owner`, create the HNSW indexes after the bulk load, then `ANALYZE`.
5. **Verify.** For each table, row counts in SQLite, Lance and Postgres must match. Twenty random records per index are searched by their own vector and must return themselves first. The report prints counts and any mismatch. Counts are not stated in this document, because they come from running the command.
6. **Epoch.** `bump_epoch()` so no stale response is served.
7. **New data.** Temple scholarship records from Phase 4 load through the same `upsert`, with `schools`, `scope` and `temple_funded` set from the reviewed dataset file.

## 12. Decisions this document made that the plan did not settle

| ID | Decision | Reason |
|---|---|---|
| D-1 | One `records` table with `kind` and JSONB, plus filter columns. `Brief`, `Lead`, `Digest` leave it and become encrypted `user_data`. | Matches `Repository` keyed by `(kind, id)` and the pydantic schemas. |
| D-2 | Sparse search uses stock Postgres `tsvector` with `ts_rank_cd`, not `pg_search`. | No custom image. The back-test is rerun and reported. |
| D-3 | Roles are self-selected `student` and `researcher`, either or both. `staff` is operator-granted. | School and role claims are UNVERIFIED. |
| D-4 | The OpenAlex link is self-asserted and only pre-fills. Briefs for other public ids stay allowed. | No proof of identity exists in OpenAlex. |
| D-5 | No warning before the 12-month purge. | The app stores no email and sends nothing. |
| D-6 | Guests may browse, build a brief for a public id or a SYNTHETIC persona, compare and export. No uploads, Scout, hand-offs or cover points. The guest budget is keyed by guest session, with a global guest ceiling and a per-address ceiling on new guest sessions. | Guest stores nothing and spends little. Address keys would punish a shared campus address. |
| D-7 | Session CSRF is a synchronizer token in Redis, with an Origin check. Cookie is `SameSite=Lax`. | Sessions are already server-side. |
| D-8 | Keys live in a separate database `perch_keys` with a tombstone copy in `perch`, plus an append-only ledger. | Restore must not revive a key. |
| D-9 | Scope gate runs in the worker as the first step of `scout_turn`, so `web` never calls a model. | Keeps `web` stateless and keyless. |
| D-10 | Job state enum is `queued, running, succeeded, failed, dead, cancelled`. | Section 3.2. |
| D-11 | Quota and rate-limit numbers in 4.3 and the budgets are placeholders until Phases 3 and 10 measure. The arithmetic is in section 4.2.1. | Rule 10: no invented numbers. |
| D-12 | `ROLES` gains `gate` and `cover_points`, loses `decide`. Profile `cloud-cpu` replaces the others. | Matches the plan's cloud models and removed Clef. |
| D-13 | `web` holds the OpenAlex key for `GET /authors/resolve`, with an egress rule for that one host and a Redis cache. | A short job would add a queue hop to a lookup the page waits on. |
| D-14 | Records carry `scope` and `schools text[]` instead of one `school`. | A program can sit on several school pages, and "All Temple" must differ from "not Temple". |
| D-15 | Only two vector indexes exist: `opportunities` and `scholarships`. | The code shows one caller today. |
| D-16 | Worker default is 16 job threads per process, and the global cap is a calendar-month cap. | Threads waiting on the provider hold no model lock. The tier caps are monthly. |
| D-17 | Pre-auth binder cookie `__Host-perch_oidc` and a definer role `perch_definer`. | Review findings 1 and 4. |

## Review log

Each finding in `docs/v1/DESIGN_REVIEW.md`, with its answer. Fixed means the text above changed as the review asked or with the equivalent stated.

| # | Class | Result | Where and note |
|---|---|---|---|
| 1 | MUST | Fixed | 2.1. New NOLOGIN role `perch_definer` owns the functions, explicit all-rows policies, FORCE kept, test added. |
| 2 | MUST | Fixed | 2.1 full policy SQL, guest policy, worker insert policy on `spend_ledger`, `guest_tx`. |
| 3 | MUST | Fixed | 3.3. Lease owner is worker and thread, `attempts` is the fencing token, `LeaseLost`, timeout test. |
| 4 | MUST | Fixed | 7.1 and 7.2. Binder cookie, `GETDEL`, token checks, `safe_return_to`. |
| 5 | MUST | Fixed with an equivalent | 7.6, 1.3, 4.1 to 4.3. Trusted proxies, `client_addr`, `PERCH_PEPPER_GUEST`, site-wide ceilings. Instead of putting `addr_hash` in the guest job payload, the worker charges `jobs.guest_sid_hash`, because D-6 keys the guest budget by session, so no address is needed in the worker. |
| 6 | MUST | Fixed | New 3.7 Errors and logs. |
| 7 | MUST | Fixed | 6.1. No database counter, process-local guard, bound stated. |
| 8 | SHOULD | Fixed | 1.1, 1.3, 3.3. Direct URL for LISTEN, psycopg 3 and `prepare_threshold=None`. |
| 9 | SHOULD | Fixed | 1.1 capacity formula, default 16 threads, `PERCH_TORCH_THREADS`. Numbers marked placeholders. |
| 10 | SHOULD | Fixed | 3.3 provider bucket and 429 retry, 4.2.1 arithmetic table. |
| 11 | SHOULD | Fixed | 4.1, 4.2. Monthly cap, one Lua call across counters, `SET NX` rebuild, `spend_context`. |
| 12 | SHOULD | Fixed | 2.2. Filter columns copied onto `record_vectors`, `strict_order`, `ef_search` rule, corpus-size note. |
| 13 | SHOULD | Fixed | 2.2 and 11.2. Two indexes, sparse query defined, code reading recorded. |
| 14 | SHOULD | Fixed | 2.2. `schools[]`, `scope`, column source table. |
| 15 | SHOULD | Fixed | 2.1, 2.2, 6.6. Step 1b, partial unique index, tables cleared are listed. |
| 16 | SHOULD | Fixed | 6.1, 6.6, 1.3. Honest backup statement, object-store ledger, `/health?ready=true` restore marker. |
| 17 | SHOULD | Fixed | 6.4. `ON CONFLICT DO NOTHING`, tombstone trigger. |
| 18 | SHOULD | Fixed | 6.4 `UserData` class and model table, `ud_one_cv`, Digest dropped in 2.2. |
| 19 | SHOULD | Fixed | 1.2 enforcement point in `AuditedProvider.chat`, test. |
| 20 | SHOULD | Fixed | 4.4, 9.1. Public-only records route, `/health` uncached. |
| 21 | SHOULD | Fixed | 2.1 new definer functions, 11.2 owner index step, D-13 for author resolution. |
| 22 | SHOULD | Fixed | 1.1. Plain `def` routes, pool size, upload cap. |
| 23 | SHOULD | Fixed | 2.2. The link stays encrypted, payload holds the id only when typed, else `author_source: "link"`. |
| 24 | SHOULD | Fixed | 7.5, 9.2. `RolesSet` typed without `staff`. |
| 25 | COULD | Fixed | 6.2. `extra` carries kind and audience. |
| 26 | COULD | Fixed | 2.2 `prompt_hash`, `PERCH_AUDIT_KEY`. |
| 27 | COULD | Fixed | 6.4. Cache cleared on reconnect. |
| 28 | COULD | Fixed | 3.1 `purge` action `jobs`. |
| 29 | COULD | Fixed | 3.3. `RETURNS SETOF jobs`. |
| 30 | COULD | Fixed | Cancel signature, guest Scout key, `_PREV_ID`, consent version for both, withdraw route, epoch in Postgres, `fit` key part, both-direction sample CHECK, `ef_search` rule. |
| 31 | COULD | Fixed | 1.1 Redis ACL and TLS. `id_token_hint` is dropped, 7.2. |
| 32 | COULD | Fixed | 4.1. TTL on `perch:usess`. |
| 33 | COULD | Fixed | 3.1. One precache job per author, Phase 3 records the numbers. |
| N1 | SHOULD | Fixed | 7.6. `X-Forwarded-For` is read only when the peer is in `PERCH_TRUSTED_PROXIES`. The web port binds to the proxy network only. |
| N2 | SHOULD | Fixed | 4.3. `login_start` has a high per-address ceiling, `login_callback` is keyed by the binder cookie hash, sentence corrected, address sharing UNVERIFIED. |
| N3 | COULD | Fixed | 3.3. Test asserts one terminal update, no stale user-data write and attempt-tagged ledger rows. |
| N4 | COULD | Fixed | 3.7. `include_context=False`, log `type` and `loc` only, fixed validator messages. |
| N5 | COULD | Fixed | 6.5. Trigger is the process-local guard. |
| N6 | COULD | Fixed | 2.1. First migration grants `perch_definer` to `perch_owner`. |

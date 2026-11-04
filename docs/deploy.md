# Deploying Perch v1: runbook

[Back to the README](../README.md) · [Running Perch](running.md) · [Architecture](ARCHITECTURE_V1.md)

This page is for the person who runs Perch. Every command was checked against the files named beside it. Where the repo cannot back a claim, the page says `UNVERIFIED`. Names of variables are listed here; values never are. Put values in `.env`, which is gitignored.

## 1. What runs where

| Part | What it is | Where it runs in the Compose stack |
|---|---|---|
| **web** | `perch serve`, the HTTP API and the static app. Loads no model. | Service `web`, image `perch-v1-web`, host port `127.0.0.1:8190`. |
| **worker** | `perch worker`, job threads that claim jobs from the Postgres queue. Loads the embedder, reranker and MiniCheck on one GPU. | Service `worker` (GPU), or natively on the host, see section 3. |
| **Postgres with pgvector** | Database `perch`: public records, the vector index, jobs, encrypted user data. Image `pgvector/pgvector:0.8.0-pg16`. | Service `postgres`, `127.0.0.1:5433`. |
| **Key database** | Database `perch_keys`, role `perch_keys`: wrapped data keys and tombstones. Kept apart on purpose, see section 4. | Same server in Compose, created by `deploy/compose/initdb/10-databases.sh`. |
| **Redis** | Sessions, quotas, rate limits, the response cache. Append-only file on. | Service `redis`, `127.0.0.1:6380`. |
| **Identity provider** | OIDC sign-in. Compose runs Keycloak 26.0 in dev mode with the realm in `deploy/compose/keycloak/`. | Service `keycloak`, `127.0.0.1:8180`. Temple's real provider: `UNVERIFIED`, see `docs/v1/PROVIDER_AND_SSO.md`. |

- **Model calls:** the explainer, gate, hand-off, cover points and Scout call Anthropic from the worker. Embedding, reranking and grounding run on the worker's GPU.
- **Ports:** every published port is bound to 127.0.0.1. Put a TLS reverse proxy in front of `web`.
- **The live fallback demo is separate:** the root `docker-compose.yml` on port 8090 never shares a file with `deploy/compose/docker-compose.v1.yml`. See section 12.

## 2. Secrets and `.env`

Copy `.env.example` to `.env`. Never commit `.env` and never paste a value into a ticket, a log or this page. The Compose file refuses to start when a required name is empty.

- **Required by Compose:** `POSTGRES_PASSWORD`, `PERCH_OWNER_PASSWORD`, `PERCH_WEB_PASSWORD`, `PERCH_WORKER_PASSWORD`, `PERCH_KEYS_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`, `PERCH_OIDC_CLIENT_SECRET`, `PERCH_MASTER_KEY`.
- **Optional in Compose:** `PERCH_MASTER_KEY_ID`, `PERCH_PEPPER`, `PERCH_PEPPER_GUEST`, `PERCH_AUDIT_KEY`, `PERCH_LOG_FORMAT`, `PERCH_TORCH_THREADS`, `PERCH_WORKER_CONCURRENCY`, `PERCH_WORKER_GPU`, `BACKUP_RETENTION_DAYS`, `ANTHROPIC_API_KEY`.
- **Model and cost:** `ANTHROPIC_API_KEY`, `PERCH_ANTHROPIC_BUDGET_USD` (default 100), `PERCH_LLM_DEFAULT`, `PERCH_MODEL_SLOTS`, `PERCH_MODEL_SLOT_TIMEOUT`, `PERCH_ANTHROPIC_TIMEOUT`. `PERCH_DAILY_BUDGET_USD` is read by `perch/redisx.py` (default 0.50 per account per UTC day) but is not listed in `.env.example`.
- **Keys:** `PERCH_KEYSTORE`, `PERCH_MASTER_KEY`, `PERCH_MASTER_KEY_ID`, `PERCH_MASTER_KEY_PREV`, `PERCH_MASTER_KEY_PREV_ID`, `PERCH_KMS_KEY_URI`, `PERCH_KEYS_DATABASE_URL`.
- **Dev stack only:** the Compose file sets `PERCH_ENV=dev`, `PERCH_KEYSTORE=env` and `PERCH_COOKIE_INSECURE=1`. With `PERCH_ENV=prod` the env key store is refused (`perch/keystore.py`) and an OIDC issuer must start with `https://` (`perch/auth/oidc.py`). A production master key lives in a KMS; the reference format for `PERCH_KMS_KEY_URI` is `UNVERIFIED` until a host is chosen.
- **Roles:** the migrate service sets the passwords of four database roles: `perch_owner`, `perch_web`, `perch_worker`, `perch_keys`. Migrations never hold a password.
- **Rotation:** to rotate the master key set `PERCH_MASTER_KEY_PREV` and its id, then run `perch keys rotate-master`. Remove the old key when it reports zero rows on the old id.

## 3. One host with Compose

All commands run from the repository root.

```sh
cp .env.example .env        # fill in the names from section 2
make v1-up                  # docker compose -f deploy/compose/docker-compose.v1.yml --env-file .env up -d --build
make v1-down                # stop; volumes are kept
```

`make v1-up` brings up Postgres, Redis, Keycloak, the one-shot `migrate` service, `web`, the GPU `worker` and `backup`. Start order is enforced with health conditions.

### 3a. Host with the NVIDIA container toolkit

The `worker` service uses the `worker-gpu` image target and reserves one GPU by index.

- **Choose the GPU:** set `PERCH_WORKER_GPU` in `.env` (default 3). Keep it off GPUs other services use.
- **Driver:** the image keeps the locked `torch 2.14.1+cu126`, so the host driver must support CUDA 12.6 or newer (`Dockerfile.v1` header).
- **Size:** the GPU image was 23.3 GB when built in S47.
- **Check:** `docker compose -f deploy/compose/docker-compose.v1.yml ps` shows the worker `healthy` after its 120 s start period.

### 3b. Host without the container toolkit: worker natively on one GPU

This is how the demo node runs (decision S47, 2026-11-04): this host has no NVIDIA container runtime, and installing one needs root. Postgres, Redis, Keycloak and web stay in Compose; the worker runs on the host against their published ports.

1. Start the other services without the GPU worker: `docker compose -f deploy/compose/docker-compose.v1.yml --env-file .env up -d --build postgres redis keycloak migrate web backup`.
2. Install the worker's dependencies once: `uv sync --extra ml --extra anthropic`.
3. Export the worker's environment in the shell or unit, using the same names as the Compose `worker` service, pointed at the published ports: `PERCH_PROFILE=cloud-gpu`, `PERCH_DATABASE_URL` and `PERCH_DATABASE_DIRECT_URL` (role `perch_worker`, host `127.0.0.1`, port `5433`, database `perch`), `PERCH_REDIS_URL` (`127.0.0.1:6380`), `PERCH_KEYSTORE`, `PERCH_MASTER_KEY`, `PERCH_MASTER_KEY_ID`, `PERCH_KEYS_DATABASE_URL` (role `perch_keys`, port `5433`, database `perch_keys`), `PERCH_PUBLIC_URL`, `ANTHROPIC_API_KEY`.
4. Run it on one GPU. On the shared lab node, `scripts/run_limited.sh` is the only allowed way to run a heavy job; with `PERCH_LIMIT_GPU` it exposes that one GPU, uses 4 cores by default, caps memory at 24 GB, and refuses to start (exit 75) while another GPU job holds the lock:

```sh
PERCH_LIMIT_GPU=3 scripts/run_limited.sh uv run --extra ml --extra anthropic perch worker
```

- **Not a general rule:** `run_limited.sh` is a guard for the shared lab node. On your own host run `CUDA_VISIBLE_DEVICES=<index> uv run --extra ml --extra anthropic perch worker`, or a systemd user unit.
- **systemd unit:** the repo has no worker unit. `deploy/systemd/` holds only the demo model-server units (Clef-flash, Clef, the model server, Ollama) of the fallback demo. A unit for the worker with `Restart=on-failure`, an `EnvironmentFile`, `Environment=CUDA_VISIBLE_DEVICES=<index>` and the `ExecStart` above is `UNVERIFIED`; no such unit has been run.
- **Health of a native worker:** the Compose healthcheck does not cover it. `perch worker --check` matches a heartbeat row by the host name, so run it on the same host with the same database variables. It exits 0 when a heartbeat under 90 seconds old exists.
- **Stop it:** the worker handles SIGTERM and SIGINT and stops claiming jobs.

### 3c. Host with no GPU: the CPU override

```sh
docker compose -f deploy/compose/docker-compose.v1.yml -f deploy/compose/docker-compose.cpu.yml --env-file .env up -d --build
```

- **What changes:** the worker builds the `worker` target (CPU torch wheel), sets `PERCH_PROFILE=cloud-cpu`, hides the GPU, and drops the GPU reservation.
- **Cost:** reranking 100 candidates takes about 53 s on CPU and about 0.8 s on GPU (S38, `docs/DECISIONS.md`). Use the CPU profile as a fallback, not for load.

## 4. Many hosts: managed Postgres and Redis

Everything below follows the design in `ARCHITECTURE_V1.md`. A multi-host deployment has not been run; treat each step as `UNVERIFIED` until it has.

- **What changes:** drop the `postgres`, `redis` and `keycloak` services. Point `PERCH_DATABASE_URL`, `PERCH_REDIS_URL` and `PERCH_OIDC_ISSUER` at managed services and Temple's identity provider. Use `rediss://` and a Redis ACL user per service in production.
- **Web:** stateless. Run as many as needed behind a proxy. Set `PERCH_TRUSTED_PROXIES` to the proxy's CIDRs so `X-Forwarded-For` is honoured, and set `PERCH_PUBLIC_URL` to the public HTTPS address.
- **Workers:** each worker host runs `perch worker` with a GPU. Claims use leases, so several workers are safe on one queue. `PERCH_WORKER_KINDS` limits the job kinds a worker takes.
- **Migrations:** run `deploy/compose/migrate.py` once per release from one place. It needs an admin URL for each database.
- **Must stay separate:** the key database `perch_keys` and its role.
  - **Why:** restoring a data backup must not bring back a deleted key, and restoring the key database alone must not either (`ARCHITECTURE_V1.md` 6.6).
  - **In production:** its own instance, its own backup storage and its own retention. `backup.sh` takes `BACKUP_KEYS_DIR` for a second root.
  - **Network:** let only web and worker reach it.
  - **Honest limit:** web and worker both hold the `perch_keys` credentials. The separate role protects against a SQL bug in a data query, not against code running inside a process.
- **Shred ledger:** `PERCH_SHRED_LEDGER_URI` is a third copy of each tombstone, an object store prefix with object lock or versioning, outside both databases. Compose sets none; set it before production. The concrete object store is `UNVERIFIED`.
- **Pool sizes:** `PERCH_DB_POOL_MAX` is per process (default 10). Total connections are roughly processes times pool size; check the server's limit.

## 5. First start

1. **Migrations:** the `migrate` service runs `deploy/compose/migrate.py`. It applies the `perch` and `perch_keys` migrations, creates the roles and the pgvector extension, and sets the four role passwords. Its log lists applied migrations by name and ends with `role passwords set`. Check it: `docker compose -f deploy/compose/docker-compose.v1.yml logs migrate`. To migrate by hand: `uv run perch db migrate --dsn <admin url>`.
2. **Temple dataset:** versioned files are in `data/temple/dataset/` (`temple_awards_v1.jsonl` to `v3.jsonl`, each with a manifest). Load the newest one into Postgres; the load is idempotent:

   ```sh
   uv run perch temple load-dataset data/temple/dataset/temple_awards_v3.jsonl --dsn <perch_owner or admin url>
   ```

   Which dataset version to ship is the owner's decision; `v3` is only the newest file present.
3. **Public corpus and the vector index:** `uv run perch db migrate-corpus --dsn <write url>` copies the public records, the Lance vectors, the SYNTHETIC samples and the embedding cache from the fallback stores into Postgres, then verifies row counts and exits 1 on a mismatch. Run it from a checkout that has `data/perch.db` and `data/lance`. The worker queries the Postgres index; it does not build it on start. Building the index from scratch without the fallback stores: `UNVERIFIED`.
4. **Sign-in:** open `PERCH_PUBLIC_URL`, sign in through the identity provider, accept consent once.
5. **Check:** section 6.

## 6. Health checks

| Check | What it tells you |
|---|---|
| `GET /health` | The web process is up. Nothing else. Used by the web container healthcheck every 10 s. |
| `GET /health?ready=true` | Postgres answers `SELECT 1`, Redis answers ping, and the keys database answers a read. Status 200 and `"status": "ok"` when none is down; 503 and `"degraded"` otherwise. A part that is not configured shows as `not_configured` and does not fail the check. |
| `GET /health?deep=true` | Each model service the profile uses, up or down. Fallback GPU profiles use this; v1 runs its models in the worker, so it is not the signal for the worker. |
| `perch worker --check` | Exit 0 when this host's worker wrote a heartbeat under 90 seconds old. Compose runs it every 30 s with a 120 s start period. Starts nothing. |
| Postgres | `pg_isready -U postgres -d perch` every 5 s. |
| Redis | `redis-cli ping` every 5 s. |
| Keycloak | `GET /realms/perch` returns 200, with a 40 s start period. |
| Backup | The loop touches `/tmp/backup-heartbeat` after each run; healthy while it is under 1,500 minutes old. |

`ARCHITECTURE_V1.md` names a separate `GET /ready`, and a restore marker that makes it fail until `perch reconcile-shreds` has run. Neither is in the code: the routes are `/health` and `/health?ready=true`, and nothing sets a restore marker. Run `reconcile-shreds` by hand after a restore (section 9).

## 7. Logs

- **Format:** set `PERCH_LOG_FORMAT=json` (the Compose file defaults to it). Each line is one JSON object with `ts`, `level`, `logger`, `msg`, and `exc` when there is an exception (`perch/logs.py`).
- **No user data:** `exc` holds the exception class name only, never its message. The formatter adds no field from a request, body or user. Call sites log lengths, ids and class names.
- **Read them:** `docker compose -f deploy/compose/docker-compose.v1.yml logs -f web worker`. A native worker writes to the terminal or the journal of its unit.
- **Request logs:** uvicorn's own log runs in the same JSON form. `perch serve --log-level` defaults to `warning`.

## 8. Metrics

- **Where:** `GET /metrics` on the web process, Prometheus text format.
- **Loopback only:** the route answers 404 to any caller that is not 127.0.0.1 or ::1 or that carries `X-Forwarded-For`, `Forwarded` or `X-Real-IP`. It is not reachable through the proxy or a published port. Read it from inside the container: `docker compose -f deploy/compose/docker-compose.v1.yml exec web /opt/venv/bin/python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').read().decode())"`.
- **What it holds:** a request counter and summed handler seconds per status class (2xx, 3xx, 4xx, 5xx), and `perch_workers_alive`, the count of heartbeat rows under 90 seconds old (-1 when the query fails). Counts only: no path, user, query or body. Counters are per web process.

## 9. Backups and restore

- **What:** the `backup` service runs `deploy/compose/backup.sh`. Every 86,400 seconds (`BACKUP_INTERVAL_S`) it runs `pg_dump --format=custom` of `perch` and of `perch_keys`.
- **Where:** `perch` dumps go to volume `backups` under `/backups/perch/`; `perch_keys` dumps go to volume `backups-keys` under `/backups-keys/perch_keys/` (`BACKUP_KEYS_DIR`). Files are named `<db>-<UTC timestamp>.dump`. In production point the two at separate storage accounts.
- **Retention:** 35 days (`BACKUP_RETENTION_DAYS`, default 35), pruned after each dump. The script deletes files older than 35 days less one interval, so no dump is older than 35 days when it is deleted. This is what the consent text, "backups clear within 35 days", promises (`docs/DECISIONS.md`, S43).
- **If you change the retention:** change the consent text and raise `PERCH_CONSENT_VERSION` in the same release.
- **Run one now:** `docker compose -f deploy/compose/docker-compose.v1.yml exec backup /bin/sh /backup.sh once`. A failed dump leaves no partial file and logs `backup FAILED`.
- **Check the log:** `docker compose ... logs backup` shows `backup ok db=... bytes=...`.

### Restore test

`deploy/compose/restore_test.sh [SOURCE_DB] [DUMP_FILE]` dumps a database, or takes a dump file, restores it into a scratch database named `perch_restore_scratch_<timestamp>`, compares the row count of every public table, drops the scratch database, and exits 0 only if every table matches. It prints counts, never row text. Through the Compose Postgres container:

```sh
PG_EXEC="docker compose -f deploy/compose/docker-compose.v1.yml exec -T postgres" \
  deploy/compose/restore_test.sh perch
```

S47 ran it on the end-to-end test databases: 14 tables and 6,423 rows for the data database, 4 tables and 8 rows for the keys database. Whether the `PG_EXEC` line above works as written against the Compose stack: `UNVERIFIED` (the script's own example uses `docker exec -i`). Run it at least once a month and after any change of Postgres version.

### Restoring for real

1. Stop `web` and the worker.
2. Restore the `perch` dump and, if needed, the `perch_keys` dump with `pg_restore`. Restore each one on its own schedule; do not restore an old keys backup together with a new data backup without step 3.
3. Run `perch reconcile-shreds` before serving. It reads all three tombstone sources (keys database, `shred_log`, the ledger) and re-deletes any key or user row for a shredded user. Skipping it can revive a deleted user's key.
4. Start `web` and the worker and check section 6.

## 10. Capacity

Every number is copied from `bench/results/s47_load/report.md` (S47, 4 Nov 2026, measured on the lab node with the fake provider using sleeps drawn from 51 real Sonnet explainer calls; no real model calls; caches off).

- **One GPU, briefs:** about 41 briefs a minute at saturation (41.21 a minute at 48 in flight, p95 80.4 s). The target of 33 a minute is met at 24 in flight: 37.13 a minute, p95 49.0 s, under the 90 s goal, 0 errors. At 16 in flight: 28.54 a minute, p95 41.2 s.
- **GPU memory:** 6,544 MiB at 24 in flight and 8,940 MiB at 48 in flight, on a 32 GB card.
- **Cap:** with `PERCH_MODEL_SLOTS=1` the GPU work caps the rate at 34 to 44 a minute. Slot wait per brief grows from 0.1 s at 1 in flight to 18.4 s at 24 and 93.5 s at 48.
- **MiniCheck batching:** 1.07 times faster; not worth a change.
- **One web process:** about 62 requests a second (62.3 and 64.6 in two runs) at 1,000 simulated users. Browse p95 was 59 to 62 s with 97 of 20,184 requests timing out.
- **Four web processes:** 156.0 requests a second, 4 errors of 48,255, browse p95 15.1 to 15.5 s. Each process used 6 database connections in that run.
- **The target is 250 concurrent users (Dakshitha, 4 Nov), and one web process meets it.** The 1,000-user target was dropped because it was not met. Browse p95 under 300 ms held at 250 users on one process (132 to 190 ms, 58 requests a second). To serve 1,000 users, run more web processes and re-measure; how many are enough is `UNVERIFIED`.
- **Caveat:** the node is shared and the runs were at nice 19, so waits are not purely our code.
- **Queue:** the worker drained 38 to 40 briefs a minute at concurrency 24, with 0 failed.
- **Fix needed before trusting the first table:** the report found that the worker built a new `BriefService` per job and failed at four or more concurrent briefs. The commit after the report made it one per process (`cmd_worker` in `perch/cli.py`). The "one service per worker" column is the one that applies; a re-run of the as-shipped numbers on the fixed worker: `UNVERIFIED`.
- **Provider tier:** at the S38 mean of 7,076 output tokens a researcher brief, the worker's 39.6 a minute is about 280K output tokens a minute; the offered peak was about 474K. `docs/RESULTS.md` gives the start tier as 400K output tokens and 4,000 requests a minute, so the offered peak exceeds it and the worker rate fits. Input-token limits and higher tiers: `UNVERIFIED`, not in the repo. Student brief token counts: `UNMEASURED`.
- **Not in the mix:** hand-offs, cover points, Scout model turns, ingest.

## 11. Upgrades and rollbacks

- **Upgrade:** `git pull`, then `make v1-up`. It rebuilds the images and reruns `migrate`, which applies only new migrations and resets the role passwords from `.env`. A native worker: stop it, `uv sync --extra ml --extra anthropic`, start it again.
- **Order:** back up first (`backup.sh once`). Migrate, then web, then the worker.
- **Rollback of code:** check out the previous commit and run `make v1-up`. Migrations are not reversed; `UNVERIFIED` whether every migration is backward compatible. Restore the database from a dump (section 9) if a migration must be undone.
- **Rollback of the whole product:** the fallback is the tag `v0.1-demo-fallback` (branch `fallback/v0.1-demo`). It runs on SQLite and LanceDB with no accounts. Check it out in a separate directory and use its own `make demo`; it does not share a store with v1.
- **Never** run `docker compose down -v` on a live stack. It deletes the data, backup and key volumes.

## 12. The fallback demo

The fallback is the root `docker-compose.yml` on `127.0.0.1:8090`, brought up with `make demo` on a node with two GPUs, Docker and llama.cpp. Stop it with `make demo-down`. Its models run as systemd user units rendered from `deploy/systemd/demo/`. For the public address, `tailscale funnel --bg 8090` publishes it, and `tailscale funnel --https=443 off` stops that. These commands came from the previous version of this page and were not re-run for this rewrite.

If the node is down on Demo Day, `uv run python scripts/build_ui_preview.py` writes `build/artifacts/ui.html`, a replay page with no server and no network.

## 13. Incident basics

**A stuck job**

- **Why it happens:** a job holds a 60 s lease, renewed by a heartbeat every 15 s. If the worker dies, a reaper (every 30 s, in every worker) returns the job to `queued` with a back-off, or marks it `dead` when attempts are used up, and writes a `job_dead` row to the audit log.
- **Check workers first:** `/metrics` `perch_workers_alive` is 0 or -1, or `perch worker --check` exits 1. Restart the worker.
- **A job that stays `queued` with a live worker:** the worker is saturated. Compare the queue with section 10.
- **Cancel:** the owner cancels through the app. Other manual SQL on the `jobs` table: `UNVERIFIED`; do not edit rows by hand.

**A full GPU**

- **Sign:** jobs fail with a CUDA out-of-memory error, or wait for a model slot and fail after `PERCH_MODEL_SLOT_TIMEOUT` (default 300 s).
- **Look:** `nvidia-smi` on the worker's GPU. At 24 in flight the worker used about 6.5 GB (section 10), so a card near full means something else is on it.
- **Fix:** stop the other process, or set `PERCH_WORKER_GPU` to a free index and recreate the worker. Lower `PERCH_WORKER_CONCURRENCY` (default 16) to reduce load. Restart the worker.

**The spend cap**

- **How it works:** the Anthropic adapter appends each billed call to a JSONL ledger, `data/logs/anthropic_spend.jsonl`, warns at 80% of `PERCH_ANTHROPIC_BUDGET_USD` (default 100) and refuses calls at the cap. Calls reserve their cost under a lock before they run, so parallel calls cannot pass the cap together. Unknown prices are charged at the most expensive listed model.
- **Sign:** jobs end with the error code `budget_exceeded`.
- **File ledger is per process:** inside the Compose worker the path is relative to the container, and no volume is mounted for it. The cross-process guards are the per-account daily budget (`PERCH_DAILY_BUDGET_USD`, default 0.50) and the quotas in Redis and Postgres. Whether the file ledger survives a container recreate: `UNVERIFIED`, probably not.
- **Raise the cap:** change `PERCH_ANTHROPIC_BUDGET_USD` in `.env` and restart the worker. This is the owner's decision.
- **Distress screening is never stopped by the budget:** the cheap gate still runs, with a small daily cap per account.

**Redis lost:** everyone is signed out and guest briefs (kept one hour) are gone. Nothing else is lost (`ARCHITECTURE_V1.md`).

**Suspected key exposure:** rotate the master key (section 2) and see threat T2 in `ARCHITECTURE_V1.md`.

**After any restore:** run `perch reconcile-shreds` (section 9).

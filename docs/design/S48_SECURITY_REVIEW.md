# S48 security review: Perch v1

Fresh-context Opus review, read-only, 2026-11-04, at 86647a9.

## Must-fix
- **M1. User-derived text in a plaintext log (rule 5).** `AuditLog.validation` (perch/llm/audit.py:48-52) writes the validator's error strings to `logs/model_calls.jsonl`. They quote model sentences that paraphrase the CV (cover.py:307, 365; fit.py:198; validate.py:139-153). The same strings also accumulate in memory. Fix: codes and counts only in the log.
- **M2. The spend cap does not hold for brief jobs.** Brief jobs' Haiku and Sonnet calls bypass `RedisMeter` (perch/jobs.py:644). The file ledger is a relative path with no volume in Compose, so it resets when a container is recreated. Guests can start 5 briefs per 10 minutes, with explanations on. Fix: meter every brief-job call per account and against the global month scope, and put the ledger on a volume.
- **M3. A backup restore can revive a deleted user.** With `PERCH_SHRED_LEDGER_URI` unset (Compose does not set it), the shred ledger is off. A restore of both databases from before a shred reverts the key rows, the tombstone and `shred_log` together. Fix: a mandatory ledger directory on its own volume, and refuse to serve until a restore marker is cleared.

## Should-fix
- **S1.** `reconcile-shreds` deletes only key rows; a restored `users` row comes back (perch/cli.py:782-797).
- **S2.** No `PERCH_TRUSTED_PROXIES` in Compose puts every visitor in one rate-limit bucket. The site-wide `login_global` and `guest_new_global` caps let a few addresses lock everyone out (perch/redisx.py:269-271, 401).
- **S3.** The hand-off draft is unmetered and runs in the web process, which has no API key in Compose (perch/api.py:839-856).
- **S4.** `/authors/resolve` has no limit and uses the deployment's OpenAlex key (perch/api.py:550).
- **S5.** `scout_start` creates a session row before any limit, and the distress path appends rows without a limit (perch/api.py:960; perch/scout/web.py:183-192).
- **S6.** PDF parsing has no page or time bound and runs in the web thread (perch/user/inputs.py:123-127).
- **S7.** An empty guest pepper is accepted, which makes rate-limit keys reversible (perch/redisx.py:422).
- **S8.** The access log records `/auth/callback?code=…` and client addresses (perch/logs.py:53).
- **S9.** The shipped Keycloak realm imports a SYNTHETIC user with a fixed password (deploy/compose/keycloak/perch-realm.json:12-19).

## Nice-to-have
- **N1.** One audit row per 429 response.
- **N2.** `rotate_data_key` queues a rekey purge. This was answered by c63087e, which added the handler.
- **N3.** `KmsKeyStore` always raises, so every deployment today uses the dev env key store.
- **N4.** `walk_server.py` sets fixed role passwords on whatever host it is pointed at; add a guard to the test port.

## Clean
Encryption (AES-256-GCM with bound AAD, tombstone checked before decrypt, no recreation of a shredded key), sign-in (state, nonce, PKCE, binder cookie, new session ids, `__Host-` cookies, CSRF and Origin on every POST), authorization (forced row-level security, narrow definer functions, session-scoped routes), rendering (textContent only, `safeUrl`), and the new metrics, worker check, cover-points `again` path and shared brief service.

## Re-check (fresh-context Opus, 2026-11-04)

No item is NOT FIXED and there is no new must-fix. Verdicts:
- **Fixed:** M1, M2, S1, S2, S4, S5, S9, N1 and N4.
- **Partly fixed:** M3, S6 and S7.
- **Fixed with limits:** S3 on the account path, and S8 in JSON mode.

Must-fix for safety:
- **The forgotten restore marker (M3):** a restore without `restore-mark` leaves a deleted user live until the daily reconcile.

Should-fix:
- Never restore the ledger volume.
- A per-address guest spend cap, with the guest day times 30 below the month.
- An HMAC prompt hash.
- Compose refuses a missing pepper.
- The access filter in plain mode.
- Worst-case reserves.
- The PDF decompression bound.

A follow-up agent is fixing the first six. Open for Dakshitha: Q50, guest briefs in Redis as plain JSON for an hour.

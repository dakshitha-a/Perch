# Crypto and key store review (rebuild Phase 2, task 9)

Independent review with fresh context, 2026-11-03, branch `rebuild/v1` at `7952ed0`. Reviewed the code, not a builder's summary: `perch/crypto.py`, `perch/keystore.py`, `perch/db/keys_migrate.py`, `perch/db/migrations/keys/0001_keys.sql`, `perch/db/migrations/perch/0001`–`0005`, `perch/store/pg.py`, `tests/test_crypto.py`, `tests/test_keystore.py`, against `docs/ARCHITECTURE_V1.md` sections 2.1, 3.7, 6 and 10 and standing rules 1 and 5. `make test-keys` passed: 38 tests. Two findings were reproduced with throwaway scripts outside the repo. No repo file other than this one was changed.

## Verdict

The core construction is sound.

- **AES-GCM:** It uses 256-bit keys from `os.urandom(32)` and fresh 96-bit random nonces. The tag is checked and errors are fixed text.
- **AAD binding:** The AAD binds user, table, column, row, kind, audience and key version with unambiguous separators. A blob moved to another row, user, kind, side or older key version fails to decrypt, and tests cover each case.
- **Wrapped keys:** The wrapping AAD binds user, version and master id.
- **Tombstones:** The tombstone check on every decrypt correctly beats a stale cache and a restored key row.

One defect is a real confidentiality break and must be fixed before any user data is written.

- **The defect:** The key cache zeroes key buffers in place while another thread may still hold them.
- **The effect:** An encryption that races an eviction runs under the all-zero key. Anyone who reads the blob can then decrypt it.

The other important findings are about shred and restore guarantees that the contract states but the code does not quite deliver:

- A race leaves a key row behind after a shred.
- The runtime role can delete tombstones.
- `shred_log` takes inserts for any user id.
- A missing key row silently forks the user's key.

Finding 16 lists the test gaps and comes after the COULD-FIX items on purpose, because it covers all the findings.

## Findings

### 1. MUST-FIX: a cached key buffer is zeroed while a caller still uses it

- **Where:** `perch/crypto.py:176` returns the cached `bytearray` itself. `perch/crypto.py:156`, `:163`, `:173` and `:187` zero that same buffer on eviction, clear, expiry and LRU overflow. `perch/crypto.py:260` and `:277` read it later, outside the lock.
- **Problem:** `_data_key` hands out a reference to the buffer, not a copy. Any eviction in another thread between that return and `bytes(key)` turns the key into 32 zero bytes.
- **Failure scenario:** A worker thread is encrypting a CV. A Redis reconnect calls `clear_cache()`, a `perch:shred` message calls `evict_user`, or another user's first write pushes the LRU past 1024. The blob is then sealed under the all-zero key and stored. Anyone with read access to `user_data` or a backup can decrypt it. The real key never opens it again, so the owner also loses the data. Reproduced: with `clear_cache()` injected after `_count`, `encrypt_field` produced a blob that `AESGCM(bytes(32))` decrypted to the plaintext. The same race on decrypt gives a false `DecryptError`.
- **Change:** Copy under the lock. `_cache_get` and `_cache_put` should return `bytes(buf)` taken inside `with _S.lock`, so callers never hold the live buffer. Simpler still: cache an immutable `bytes` or an `AESGCM` object and drop the in-place zeroing, which Python cannot make complete anyway. Add a regression test that clears the cache between key fetch and use, as in the reproduction, and asserts the blob does not open under a zero key.

### 2. SHOULD-FIX: shred racing a key insert leaves a key row alive

- **Where:** `perch/db/migrations/keys/0001_keys.sql:31-41` is the trigger. `perch/crypto.py:289-290` runs tombstone and delete as two autocommit statements. `docs/ARCHITECTURE_V1.md:836` claims the check and the insert "cannot be split by a race".
- **Problem:** Under READ COMMITTED, the trigger's `EXISTS` cannot see a tombstone that has not been committed yet. The later `DELETE` cannot see a key insert that has not been committed yet.
- **Failure scenario:** A user's first write runs `INSERT` and passes the trigger. Delete-my-data then commits the tombstone and runs `DELETE`, which removes 0 rows. The insert then commits. Reproduced against the test Postgres: after the shred, one key row remained next to the tombstone.
- **How wide the window is:** Production `KeyRepository.put` runs in autocommit, so the window is the length of one INSERT statement, not an open transaction as in the reproduction. The window is still real. A slow statement or a lock wait widens it. So would any future path that is not autocommit. Section 6.6 also cancels running jobs only in step 1b, after step 1.
- **Impact:** Live decrypts are still refused by the tombstone check. However, the key material survives the shred. It goes into every keys backup until a reconcile happens to run, and `rotate_master` keeps re-wrapping it.
- **Related ordering bug:** `reconcile_shreds` (`perch/crypto.py:306-308`) deletes before it tombstones. That reopens the same window during a restore.
- **Change:** Serialise per user with a lock.
  - In the trigger, run `PERFORM pg_advisory_xact_lock(hashtextextended(NEW.user_id::text, 0))`.
  - In `shred`, add a single `KeyRepository.shred(user_id)` method. In one transaction it takes the same lock, inserts the tombstone and deletes the keys.
  - In `reconcile_shreds`, tombstone first, then delete.
- **Why the lock closes the window:** Under READ COMMITTED, each statement inside the plpgsql trigger takes a fresh snapshot. An `EXISTS` that runs after `pg_advisory_xact_lock` therefore sees a tombstone that the shred transaction committed while holding the lock.
- **Test:** Add a two-connection test like the reproduction.

### 3. SHOULD-FIX: the runtime key role owns the key tables and can erase tombstones

- **Where:** `perch/db/migrations/keys/0001_keys.sql:46-49`.
- **Problem:** `perch_keys` is the login role that both `web` and `worker` use. It owns `user_keys`, `key_tombstones` and the trigger function, and it holds `ALL` on both tables. That means it can `DELETE` or `TRUNCATE` tombstones, `ALTER TABLE ... DISABLE TRIGGER`, or drop the trigger.
- **Failure scenario:** A bug in the web process, or an attacker with code execution there (threat T2), can remove a tombstone and the trigger. A restored key row then decrypts again. This undoes the T7 guarantee from inside the system it protects. The main database already avoids this pattern: its owner role is never used at runtime.
- **Change:** Split the role in two.
  - **Owner:** Add a `perch_keys_owner` role that owns the objects and is used only by `keys_migrate`.
  - **Runtime grants on `user_keys`:** `perch_keys` keeps `SELECT, INSERT, DELETE` and `UPDATE (wrapped_key, master_key_id, retired_at)`.
  - **Runtime grants on `key_tombstones`:** `SELECT, INSERT` only. There is no delete grant and no TRUNCATE grant.
- **Contract:** Update the `perch_keys` row in ARCHITECTURE section 2.1.
- **Test:** Assert that `perch_keys` cannot delete a tombstone or disable the trigger.

### 4. SHOULD-FIX: `shred_log` accepts an insert for any user id

- **Where:** `perch/db/migrations/perch/0005_grants.sql:23`. `perch/db/migrations/perch/0002_tables.sql:175` defines the table, and `0004_rls.sql` gives it no RLS.
- **Problem:** `perch_web` can insert a `shred_log` row for any user id. `reconcile-shreds` takes the union of the three tombstone sources and runs daily (section 6.6).
- **Failure scenario:** A route bug writes the wrong id, for example a row id instead of the session user id. At the next daily reconcile, the other user's keys are deleted and their data is destroyed for good, with no one asking.
- **Change:**
  - Enable and force RLS on `shred_log`, with `CREATE POLICY sl_web_ins ON shred_log FOR INSERT TO perch_web WITH CHECK (user_id = perch_uid())`.
  - Give `perch_worker` a separate policy for the inactivity purge.
  - Optionally, have reconcile shred an id only when the keys-database tombstone or the ledger object agrees, and only log an id that appears in `shred_log` alone.

### 5. SHOULD-FIX: a missing key row means "shredded" on read but "new user" on write

- **Where:** `perch/crypto.py:201-203` and `:231-241`.
- **Problem:** The code cannot tell "no key because it was shredded" apart from "no key because the keys database is wrong".
  - On a read, `_data_key` raises `KeyShredded` when the row is missing, even with no tombstone.
  - On a write, `_newest` creates version 1 whenever `latest()` is empty.
- **Failure scenario:** `PERCH_KEYS_DATABASE_URL` points at a fresh database, or the keys database is restored from a backup older than a user's newest version.
  - Reads report the data as shredded, so the UI tells the user their data is gone.
  - Writes mint a new version 1, or a new version N+1, with a different key under a version number that existing blobs already use.
  - When the real keys come back, the `(user, version)` primary key keeps only one of the two keys. One set of blobs is lost for good.
- **Change:**
  - Raise `KeyShredded` only when a tombstone exists. Otherwise raise a new `KeyMissing(CryptoError)`.
  - Create version 1 only when the caller says this is a first write, for example `encrypt_field(..., create=True)` passed by `UserData.put` after it has checked that the user has no `user_data` rows.
- **Test:** Add a test with an empty keys repository and an existing blob.

### 6. SHOULD-FIX: nothing ties a master key id to its key material

- **Where:** `perch/keystore.py:92` defaults the id to `m1`. `perch/crypto.py:313-337` and `docs/ARCHITECTURE_V1.md:931` describe rotation.
- **Problem 1: the id can be reused with a different key.**
  - **Scenario:** An operator sets a new `PERCH_MASTER_KEY` but forgets `PERCH_MASTER_KEY_ID`. The new key is labelled `m1` too. Every existing unwrap fails with `DecryptError`, while new users' keys are wrapped under the new key with the same id. The database now holds two keys called `m1` and no record of which is which.
- **Problem 2: a stale process breaks the "zero rows left" step.**
  - **Scenario:** Any web or worker process still running the old environment keeps wrapping new keys under the old id after `rotate-master` reports 0. The operator then removes the old key, and those users' data is lost.
- **Change:**
  - Require `PERCH_MASTER_KEY_ID` whenever `PERCH_MASTER_KEY` is set.
  - Store a key check value per master id in the keys database, for example HMAC-SHA256(master, `"perch/v1/kcv"`) in a `key_masters` table. Verify it at start and refuse to start on a mismatch.
  - Have `rotate-master` refuse to report done until every process has started with the new id, for example through the heartbeat table, and re-count rows on the old id just before the key is removed.
- **Test:** Add a test for "same id, different key fails at start".

### 7. SHOULD-FIX: `repr(WrappedKey)` prints the wrapped key

- **Where:** `perch/keystore.py:37-41`.
- **Problem:** `WrappedKey` is a `NamedTuple`, so its default repr includes the `wrapped` bytes. Section 6.4 promises that wrapped keys never appear in logs, and `Aad` already overrides its repr for this reason.
- **Failure scenario:** A future `log.debug("unwrap %r", wk)` writes the wrapped key to the log. So does a traceback printer that shows locals, such as rich, pytest `-l` or an APM that someone enables against section 3.7.
- **Change:** Define `__repr__` to show only `user_id`, `key_version` and `master_key_id`.
- **Test:** Add a test like `test_repr_has_ids_only`.

### 8. SHOULD-FIX: every key operation opens a new connection, and every decrypt queries the tombstone table

- **Where:** `perch/keystore.py:177-181`, called from `perch/crypto.py:195` and `:201`.
- **Problem:** Each call to `is_tombstoned`, `get`, `latest` or `put` makes a fresh `psycopg.connect`, with TCP, TLS and auth each time. A `UserData.list(limit=50)` does at least 50 connects, even when every key is cached.
- **Failure scenario:** Under normal load, `perch_keys` hits `max_connections` or connect latency. Decrypts then fail, and every signed-in page fails with them.
- **Change:**
  - Give `KeyRepository` a small `psycopg_pool.ConnectionPool`.
  - Add `decrypt_many` or a per-request tombstone check, so one check covers a batch of blobs from one transaction.
  - Keep the per-call check for single reads.

### 9. COULD-FIX: an older blob of the same row can replace the current one

- **Where:** `perch/crypto.py:75-89`.
- **Problem:** The AAD has no revision number. Any older ciphertext of the same row and key version authenticates against that row.
- **Failure scenario:** An operator with database access, or a restored `perch` backup merged row by row, swaps in last month's blob for a CV row. It decrypts cleanly, with no sign that it was rolled back.
- **Change:** Accept the risk and say so in section 10. Alternatively, bind a revision column that is incremented on every update into `extra`.

### 10. COULD-FIX: every integrity error is reported as "tombstoned"

- **Where:** `perch/keystore.py:218-219`.
- **Problem:** `except psycopg.errors.IntegrityConstraintViolation` catches the trigger's error, but it also catches CHECK and NOT NULL violations. Those get mislabelled as `KeyShredded`, which callers treat as "data gone for good".
- **Change:** Raise a dedicated SQLSTATE in the trigger, for example `USING ERRCODE = 'P0K01'`, and match on `e.sqlstate`. Re-raise other integrity errors as a generic `CryptoError` with fixed text. Psycopg's own message for those can include the failing row, which means the wrapped key.

### 11. COULD-FIX: unwrap does not check the data key's length

- **Where:** `perch/keystore.py:120-122`.
- **Problem:** Any authenticated plaintext is accepted as the data key. `AESGCM` also accepts 16-byte and 24-byte keys.
- **Change:** After unwrapping, require `len(key) == 32` and raise `DecryptError("wrapped key is malformed")` otherwise. This guards against a future key store or migration bug that wraps a short key.

### 12. COULD-FIX: one failing shred hook stops the hooks after it

- **Where:** `perch/crypto.py:295-296`.
- **Problem:** The first hook that raises stops the loop. If the `shred_log` insert fails, the ledger object and the `perch:shred` publish never run. The tombstone then exists only in the keys database.
- **Failure scenario:** Before anyone retries, a keys-database restore removes the only tombstone. Nothing is left to reconcile against.
- **Change:** Run every hook, collect the failures, and raise one `CryptoError` with fixed text at the end. Write the ledger object, the copy outside both databases, before `shred_log`.

### 13. COULD-FIX: the nonce guard's counter dict never shrinks

- **Where:** `perch/crypto.py:244-250`.
- **Problem:** `_S.counts` gets one entry per (user, version) that ever encrypts in the process. Entries go only on shred or `configure()`. In a long-lived worker this grows without bound. The guard is also per process and resets on restart, which section 6.1 already admits.
- **Change:** Bound the dict like the cache, or accept and document it. The 2^32 analysis in 6.1 stays correct.

### 14. COULD-FIX: the keys server may log wrapped keys as statement parameters

- **Where:** This is deployment configuration that sits next to `perch/keystore.py:205-229`.
- **Problem:** Wrapped keys travel as bound parameters. If `log_statement = 'all'` or `log_parameter_max_length_on_error` is non-zero on the keys server, they land in the Postgres log.
- **Change:** In the ops runbook, require `log_statement = 'none'`, `log_parameter_max_length = 0` and `log_parameter_max_length_on_error = 0` for the keys instance. Add a start-up check that reads them through `SHOW`.

### 15. COULD-FIX: `Aad` accepts any table, column or row id

- **Where:** `perch/crypto.py:70-73`.
- **Problem:** A row id written as uppercase or braced UUID text gives a different AAD from the canonical form.
- **Failure scenario:** One code path builds `str(uuid)` and another passes a value as the database returns it. Valid blobs then fail with `DecryptError`. This is a data loss risk, not a confidentiality risk.
- **Change:** Normalise or require `row_id == str(UUID(row_id))`, and check table and column against an allowlist of `("user_data","blob")` and `("users","openalex_id_enc")`.

### 16. SHOULD-FIX: important properties are not tested

The current tests are good on AAD binding, tampering, the version downgrade, restore and reconcile, and secrets in errors. These properties have no test:

- **Concurrent eviction:** Nothing tests eviction during encrypt or decrypt, the property behind finding 1.
- **Shred racing a key insert:** Nothing tests a shred racing a first write through Postgres, the property behind finding 2. The in-memory repository checks tombstones under a lock, so it hides this race.
- **Swapped wrapped keys:** Nothing tests moving a `wrapped_key` between two `user_keys` rows of different users. AAD covers this, and the test is cheap.
- **Tombstone protection:** Nothing tests that the runtime key role cannot delete tombstones or disable the trigger (finding 3).
- **Threat T1 end to end:** Nothing connects as `perch_web` with another user's `perch.user_id` and asserts zero rows plus a failed decrypt of a copied blob. This lands with `perch/user/data.py`.
- **`shred_log` insert check:** Nothing tests that `perch_web` cannot insert a `shred_log` row for a different user (finding 4).
- **Missing key versus shredded key:** Nothing tests a missing key row with no tombstone (finding 5).
- **Master id mismatch:** Nothing tests a master id that matches with key material that does not (finding 6).
- **Wrapped key repr:** Nothing tests `repr(WrappedKey)` (finding 7).
- **The user id inside the AAD:** The `{"user_id": uuid4()}` case in `test_wrong_aad_fails` passes because of the guard at `perch/crypto.py:272`, which checks `aad.user_id != user_id`. It never reaches the user-id bytes inside the AAD. The test should call `decrypt_field` with a matching but different user id on both arguments, with that user's own key. `test_users_have_distinct_keys` comes close, but it also changes the key, so it does not isolate the AAD.

### 17. COULD-FIX: reconcile does not delete the user's rows in `perch` yet

- **Where:** `perch/crypto.py:300-310`.
- **Problem:** Section 6.6 says `reconcile-shreds` "deletes any `user_keys` rows and any user rows for those ids". `crypto.reconcile_shreds` touches only the keys repository. No other code in `perch/` calls it or deletes the `perch` side.
- **Change:** When the `perch reconcile-shreds` command is built, it must also call `perch_delete_user_rows` for each id. It must also clear the `ingest_runs` restore marker. Track this so the contract and the code do not drift apart.

## Checked and found sound

- **Blob format:** The format version byte is checked. The key version is bound in the AAD, so a header downgrade fails, and a test covers it. The nonce is fresh per call. Truncated blobs are rejected before decryption.
- **Wrapping:** The wrapped-key format has a version byte. Its AAD binds user, version and master id. Rotation re-wraps conditionally on the old master id, so a row that races away is skipped, and the loop cannot spin.
- **Master key loading:** Loading uses strict base64 and requires exactly 32 bytes. Error messages do not echo the value. The env key store is refused in prod. A previous id must differ from the current one.
- **Tombstone check:** The tombstone is checked before the cache on every read and write. A cached key in another process therefore cannot outlive a shred, and a test covers it.
- **Error handling:** Errors carry fixed text and `from None` suppresses the context. The only log line is `shredded user=<uuid>`. The secrets-in-errors tests cover plaintext, the data key, the wrapped key and the blob.
- **Role isolation:** `perch_web` and `perch_worker` have no CONNECT on the keys database, because CONNECT is revoked from PUBLIC. They hold no membership in `perch_keys`. In `perch`, `user_data` is fenced with ENABLE and FORCE RLS, and `perch_owner` is kept out of the definer policies with `INHERIT FALSE`.
- **Timing and oracles:** No padding or timing oracle exists. GCM verifies the tag in constant time inside OpenSSL, and the distinct error classes reveal nothing beyond what the caller already owns.

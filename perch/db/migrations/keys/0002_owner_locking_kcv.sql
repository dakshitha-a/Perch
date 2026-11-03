-- Keys database, second migration (docs/v1/CRYPTO_REVIEW.md findings 2, 3, 6, 10).
-- Run by the operator or a superuser through keys_migrate, never by the runtime role.

-- Finding 3: the tables belong to a role that is never used at runtime, so perch_keys cannot
-- delete tombstones, truncate, disable the trigger or drop it.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'perch_keys_owner') THEN
    CREATE ROLE perch_keys_owner NOLOGIN;
  END IF;
EXCEPTION WHEN duplicate_object THEN
  NULL;
END $$;

ALTER TABLE user_keys OWNER TO perch_keys_owner;
ALTER TABLE key_tombstones OWNER TO perch_keys_owner;
ALTER FUNCTION user_keys_refuse_tombstoned() OWNER TO perch_keys_owner;

REVOKE ALL ON user_keys, key_tombstones FROM perch_keys;
GRANT SELECT, INSERT, DELETE ON user_keys TO perch_keys;
GRANT UPDATE (wrapped_key, master_key_id, retired_at) ON user_keys TO perch_keys;
GRANT SELECT, INSERT ON key_tombstones TO perch_keys;   -- no DELETE, no TRUNCATE

-- Finding 6: one key check value per master id, so an id cannot be reused for a new key.
CREATE TABLE key_masters (
  master_key_id text        PRIMARY KEY,
  kcv           bytea       NOT NULL,   -- HMAC-SHA256(master key, 'perch/v1/kcv')
  created_at    timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE key_masters OWNER TO perch_keys_owner;
REVOKE ALL ON key_masters FROM PUBLIC;
GRANT SELECT, INSERT ON key_masters TO perch_keys;

-- Findings 2 and 10: serialise per user with shred (KeyRepository.shred takes the same lock),
-- and raise a dedicated SQLSTATE so only a tombstone refusal is reported as "shredded".
CREATE OR REPLACE FUNCTION user_keys_refuse_tombstoned() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.user_id::text, 0));
  IF EXISTS (SELECT 1 FROM key_tombstones t WHERE t.user_id = NEW.user_id) THEN
    RAISE EXCEPTION 'tombstoned' USING ERRCODE = 'P0K01';
  END IF;
  RETURN NEW;
END $$;

-- Keys database `perch_keys` (docs/ARCHITECTURE_V1.md sections 2.1, 2.2, 6).
-- Run as a role that may create roles and own objects (the operator or a superuser).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'perch_keys') THEN
    -- The password is set by the operator, never in a migration.
    CREATE ROLE perch_keys LOGIN;
  END IF;
EXCEPTION WHEN duplicate_object THEN
  NULL;  -- lost a race with another creator
END $$;

CREATE TABLE user_keys (
  user_id        uuid        NOT NULL,   -- no foreign key: other database
  key_version    int         NOT NULL CHECK (key_version >= 1),
  wrapped_key    bytea       NOT NULL,   -- section 6.3
  master_key_id  text        NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  retired_at     timestamptz,
  PRIMARY KEY (user_id, key_version)
);
CREATE INDEX user_keys_master ON user_keys (master_key_id);

CREATE TABLE key_tombstones (
  user_id     uuid        PRIMARY KEY,
  shredded_at timestamptz NOT NULL DEFAULT now()
);

-- A key cannot be created for a shredded user, so a racing first write cannot revive one.
CREATE FUNCTION user_keys_refuse_tombstoned() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM key_tombstones t WHERE t.user_id = NEW.user_id) THEN
    RAISE EXCEPTION 'tombstoned' USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER user_keys_no_revive BEFORE INSERT ON user_keys
  FOR EACH ROW EXECUTE FUNCTION user_keys_refuse_tombstoned();

-- Only perch_keys touches these tables.
REVOKE ALL ON user_keys, key_tombstones FROM PUBLIC;
REVOKE ALL ON FUNCTION user_keys_refuse_tombstoned() FROM PUBLIC;
ALTER TABLE user_keys OWNER TO perch_keys;
ALTER TABLE key_tombstones OWNER TO perch_keys;
ALTER FUNCTION user_keys_refuse_tombstoned() OWNER TO perch_keys;
GRANT ALL ON user_keys, key_tombstones TO perch_keys;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO perch_keys;
DO $$
BEGIN
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO perch_keys', current_database());
END $$;

-- Roles, extension and schema privileges (ARCHITECTURE_V1 section 2.1).
-- Runs as the connecting user (a superuser in dev and test, a CREATEROLE user in prod).
-- Every later migration runs as perch_owner (the runner issues SET ROLE).
-- Roles are cluster-wide, so each CREATE is guarded. Passwords are set by the operator,
-- never in a migration. perch_keys and its database belong to the keys migrations.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'perch_owner') THEN
    CREATE ROLE perch_owner LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'perch_definer') THEN
    CREATE ROLE perch_definer NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'perch_web') THEN
    CREATE ROLE perch_web LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'perch_worker') THEN
    CREATE ROLE perch_worker LOGIN;
  END IF;
END
$$;

-- A role can hand an object to another role only if it is a member of that role.
GRANT perch_definer TO perch_owner;

DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO perch_owner, perch_web, perch_worker',
                 current_database());
END
$$;

CREATE EXTENSION IF NOT EXISTS vector;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO perch_owner WITH GRANT OPTION;
GRANT USAGE ON SCHEMA public TO perch_web, perch_worker, perch_definer;
-- ALTER FUNCTION ... OWNER TO perch_definer needs CREATE on the schema; 0003 grants and revokes it.

-- The runner creates schema_migrations before this file runs; hand it to the owner.
ALTER TABLE schema_migrations OWNER TO perch_owner;

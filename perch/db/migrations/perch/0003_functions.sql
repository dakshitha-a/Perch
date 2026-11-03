-- Session helpers, the cancel trigger and the SECURITY DEFINER functions (sections 2.1, 3.3).

CREATE FUNCTION perch_uid() RETURNS uuid LANGUAGE sql STABLE
AS $$ SELECT NULLIF(current_setting('perch.user_id', true), '')::uuid $$;

CREATE FUNCTION perch_gsh() RETURNS bytea LANGUAGE sql STABLE
AS $$ SELECT decode(NULLIF(current_setting('perch.guest_sid_hash', true), ''), 'hex') $$;

GRANT EXECUTE ON FUNCTION perch_uid(), perch_gsh() TO perch_web, perch_worker, perch_definer;

-- perch_web may only move a job from queued or running to cancelled.
CREATE FUNCTION perch_jobs_web_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF current_user = 'perch_web' THEN
    IF NOT (OLD.state IN ('queued','running') AND NEW.state = 'cancelled'
            AND (to_jsonb(NEW) - 'state' - 'finished_at' - 'error_code')
              = (to_jsonb(OLD) - 'state' - 'finished_at' - 'error_code')) THEN
      RAISE EXCEPTION 'perch_web may only cancel a job' USING ERRCODE = '42501';
    END IF;
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER jobs_web_guard BEFORE UPDATE ON jobs
  FOR EACH ROW EXECUTE FUNCTION perch_jobs_web_guard();

-- Definer functions. Table privileges for perch_definer are in 0005.
CREATE FUNCTION perch_login_user(p_issuer_hash bytea, p_subject_hash bytea) RETURNS uuid
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  INSERT INTO users (issuer_hash, subject_hash) VALUES (p_issuer_hash, p_subject_hash)
  ON CONFLICT (issuer_hash, subject_hash) WHERE deleted_at IS NULL
  DO UPDATE SET last_active_at = now()
  RETURNING id;
$$;

CREATE FUNCTION perch_claim_job(p_worker text, p_kinds text[], p_lease_s int) RETURNS SETOF jobs
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
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

CREATE FUNCTION perch_inactive_users(p_older_than interval, p_lim int) RETURNS SETOF uuid
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT id FROM users
   WHERE deleted_at IS NULL AND last_active_at < now() - p_older_than
   ORDER BY last_active_at LIMIT p_lim;
$$;

CREATE FUNCTION perch_delete_user_rows(p_user_id uuid) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  DELETE FROM job_events WHERE job_id IN (SELECT id FROM jobs WHERE user_id = p_user_id);
  DELETE FROM jobs WHERE user_id = p_user_id;
  DELETE FROM spend_ledger WHERE user_id = p_user_id;
  DELETE FROM consents WHERE user_id = p_user_id;
  DELETE FROM user_data WHERE user_id = p_user_id;
  DELETE FROM users WHERE id = p_user_id;
$$;

CREATE FUNCTION perch_null_old_actors(p_older_than interval) RETURNS int
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  WITH u AS (UPDATE audit_log SET actor = NULL
              WHERE actor IS NOT NULL AND at < now() - p_older_than RETURNING 1)
  SELECT count(*)::int FROM u;
$$;

CREATE FUNCTION perch_queue_position(p_job_id uuid) RETURNS int
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT count(*)::int FROM jobs o, jobs me
   WHERE me.id = p_job_id AND me.state = 'queued' AND o.state = 'queued'
     AND (o.priority, o.run_after, o.created_at) < (me.priority, me.run_after, me.created_at);
$$;

-- Hand the definer functions to perch_definer (perch_owner is a member since 0001).
GRANT CREATE ON SCHEMA public TO perch_definer;
ALTER FUNCTION perch_login_user(bytea, bytea) OWNER TO perch_definer;
ALTER FUNCTION perch_claim_job(text, text[], int) OWNER TO perch_definer;
ALTER FUNCTION perch_inactive_users(interval, int) OWNER TO perch_definer;
ALTER FUNCTION perch_delete_user_rows(uuid) OWNER TO perch_definer;
ALTER FUNCTION perch_null_old_actors(interval) OWNER TO perch_definer;
ALTER FUNCTION perch_queue_position(uuid) OWNER TO perch_definer;
REVOKE CREATE ON SCHEMA public FROM perch_definer;

REVOKE EXECUTE ON FUNCTION perch_login_user(bytea, bytea), perch_claim_job(text, text[], int),
  perch_inactive_users(interval, int), perch_delete_user_rows(uuid),
  perch_null_old_actors(interval), perch_queue_position(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION perch_login_user(bytea, bytea) TO perch_web;
GRANT EXECUTE ON FUNCTION perch_queue_position(uuid) TO perch_web;
GRANT EXECUTE ON FUNCTION perch_claim_job(text, text[], int) TO perch_worker;
GRANT EXECUTE ON FUNCTION perch_inactive_users(interval, int) TO perch_worker;
GRANT EXECUTE ON FUNCTION perch_delete_user_rows(uuid) TO perch_worker;
GRANT EXECUTE ON FUNCTION perch_null_old_actors(interval) TO perch_worker;

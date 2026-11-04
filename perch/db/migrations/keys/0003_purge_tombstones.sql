-- Keys database, third migration (ARCHITECTURE_V1 section 6.6, "Retention").
-- The runtime role still has no DELETE on key_tombstones. It may call this function, which
-- deletes only tombstones older than the given age and never accepts an age under 400 days,
-- so a bug or a bad setting cannot shorten the window that keeps a restored backup from
-- reviving a deleted user. With p_dry it counts and deletes nothing.
CREATE FUNCTION perch_keys_purge_tombstones(p_older_than interval, p_dry boolean DEFAULT true)
RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE n int;
BEGIN
  IF p_older_than < interval '400 days' THEN
    RAISE EXCEPTION 'retention below the 400 day floor';
  END IF;
  IF p_dry THEN
    SELECT count(*)::int INTO n FROM key_tombstones WHERE shredded_at < now() - p_older_than;
  ELSE
    WITH d AS (DELETE FROM key_tombstones WHERE shredded_at < now() - p_older_than RETURNING 1)
    SELECT count(*)::int INTO n FROM d;
  END IF;
  RETURN n;
END $$;

GRANT USAGE ON SCHEMA public TO perch_keys_owner;  -- the function runs as its owner
REVOKE ALL ON FUNCTION perch_keys_purge_tombstones(interval, boolean) FROM PUBLIC;
ALTER FUNCTION perch_keys_purge_tombstones(interval, boolean) OWNER TO perch_keys_owner;
GRANT EXECUTE ON FUNCTION perch_keys_purge_tombstones(interval, boolean) TO perch_keys;

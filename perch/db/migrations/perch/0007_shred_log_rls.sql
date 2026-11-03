-- shred_log row-level security (docs/v1/CRYPTO_REVIEW.md finding 4).
-- reconcile-shreds trusts every id in shred_log, so the web role may insert only the id of the
-- signed-in user. The worker records inactivity purges and so may insert any id.

ALTER TABLE shred_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE shred_log FORCE ROW LEVEL SECURITY;

CREATE POLICY sl_web_ins ON shred_log FOR INSERT TO perch_web
  WITH CHECK (user_id = perch_uid());
CREATE POLICY sl_worker_ins ON shred_log FOR INSERT TO perch_worker WITH CHECK (true);
CREATE POLICY sl_worker_sel ON shred_log FOR SELECT TO perch_worker USING (true);

-- Row-level security (section 2.1). ENABLE and FORCE on every fenced table.

ALTER TABLE users        ENABLE ROW LEVEL SECURITY; ALTER TABLE users        FORCE ROW LEVEL SECURITY;
ALTER TABLE consents     ENABLE ROW LEVEL SECURITY; ALTER TABLE consents     FORCE ROW LEVEL SECURITY;
ALTER TABLE user_data    ENABLE ROW LEVEL SECURITY; ALTER TABLE user_data    FORCE ROW LEVEL SECURITY;
ALTER TABLE jobs         ENABLE ROW LEVEL SECURITY; ALTER TABLE jobs         FORCE ROW LEVEL SECURITY;
ALTER TABLE job_events   ENABLE ROW LEVEL SECURITY; ALTER TABLE job_events   FORCE ROW LEVEL SECURITY;
ALTER TABLE spend_ledger ENABLE ROW LEVEL SECURITY; ALTER TABLE spend_ledger FORCE ROW LEVEL SECURITY;

CREATE POLICY users_fence    ON users     TO perch_web, perch_worker USING (id = perch_uid())      WITH CHECK (id = perch_uid());
CREATE POLICY consents_fence ON consents  TO perch_web, perch_worker USING (user_id = perch_uid()) WITH CHECK (user_id = perch_uid());
CREATE POLICY ud_fence       ON user_data TO perch_web, perch_worker USING (user_id = perch_uid()) WITH CHECK (user_id = perch_uid());
CREATE POLICY jobs_web_user  ON jobs TO perch_web USING (user_id = perch_uid()) WITH CHECK (user_id = perch_uid());
CREATE POLICY jobs_web_guest ON jobs TO perch_web
  USING      (user_id IS NULL AND guest_sid_hash = perch_gsh())
  WITH CHECK (user_id IS NULL AND guest_sid_hash = perch_gsh());
CREATE POLICY jobs_worker    ON jobs TO perch_worker USING (true) WITH CHECK (true);
CREATE POLICY je_web   ON job_events FOR SELECT TO perch_web
  USING (EXISTS (SELECT 1 FROM jobs j WHERE j.id = job_id));
CREATE POLICY je_worker ON job_events TO perch_worker USING (true) WITH CHECK (true);
CREATE POLICY sl_web_read   ON spend_ledger FOR SELECT TO perch_web    USING (user_id = perch_uid());
CREATE POLICY sl_worker_ins ON spend_ledger FOR INSERT TO perch_worker WITH CHECK (true);
CREATE POLICY sl_worker_sel ON spend_ledger FOR SELECT TO perch_worker USING (true);

CREATE POLICY definer_all ON users        TO perch_definer USING (true) WITH CHECK (true);
CREATE POLICY definer_all ON consents     TO perch_definer USING (true) WITH CHECK (true);
CREATE POLICY definer_all ON user_data    TO perch_definer USING (true) WITH CHECK (true);
CREATE POLICY definer_all ON jobs         TO perch_definer USING (true) WITH CHECK (true);
CREATE POLICY definer_all ON job_events   TO perch_definer USING (true) WITH CHECK (true);
CREATE POLICY definer_all ON spend_ledger TO perch_definer USING (true) WITH CHECK (true);

-- Table grants (section 2.1). schema_migrations: no grant to anyone but the owner.

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;

GRANT SELECT ON records, record_vectors TO perch_web;
GRANT SELECT, INSERT, UPDATE ON records, record_vectors TO perch_worker;
GRANT SELECT ON public_cache TO perch_web;
GRANT SELECT, INSERT, UPDATE, DELETE ON public_cache TO perch_worker;

GRANT SELECT, UPDATE ON users TO perch_web, perch_worker;
GRANT SELECT, INSERT ON consents TO perch_web;
GRANT SELECT ON consents TO perch_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_data TO perch_web, perch_worker;

GRANT SELECT, INSERT, UPDATE ON jobs TO perch_web;
GRANT SELECT, INSERT, UPDATE, DELETE ON jobs TO perch_worker;
GRANT SELECT ON job_events TO perch_web;
GRANT INSERT ON job_events TO perch_worker;

GRANT INSERT ON audit_log TO perch_web, perch_worker;
GRANT SELECT ON spend_ledger TO perch_web;
GRANT SELECT, INSERT ON spend_ledger TO perch_worker;
GRANT INSERT ON shred_log TO perch_web;
GRANT SELECT, INSERT ON shred_log TO perch_worker;
GRANT SELECT ON ingest_runs, worker_heartbeat TO perch_web;
GRANT SELECT, INSERT, UPDATE, DELETE ON ingest_runs, worker_heartbeat TO perch_worker;

GRANT USAGE ON SEQUENCE consents_id_seq TO perch_web;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO perch_web, perch_worker;
GRANT USAGE ON SEQUENCE job_events_id_seq, spend_ledger_id_seq, ingest_runs_id_seq TO perch_worker;

-- perch_definer: only what the definer functions need.
GRANT SELECT, INSERT, UPDATE, DELETE ON users TO perch_definer;
GRANT DELETE ON consents, user_data, job_events, spend_ledger TO perch_definer;
GRANT SELECT, UPDATE, DELETE ON jobs TO perch_definer;
GRANT SELECT (at, actor), UPDATE (actor) ON audit_log TO perch_definer;

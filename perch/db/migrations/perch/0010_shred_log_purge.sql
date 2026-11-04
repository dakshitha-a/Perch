-- Tombstone retention (ARCHITECTURE_V1 section 6.6). The worker may delete shred_log rows, but
-- row-level security lets it see only rows older than the 400 day floor, so it cannot remove a
-- recent shred record. The retention job passes the same cutoff or a longer one.
GRANT DELETE ON shred_log TO perch_worker;
CREATE POLICY sl_worker_del ON shred_log FOR DELETE TO perch_worker
  USING (shredded_at < now() - interval '400 days');

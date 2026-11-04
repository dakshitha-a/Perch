-- Withdrawing consent (section 7.5) sets consents.withdrawn_at. The web role had SELECT and
-- INSERT only; it gets UPDATE on that one column. Row-level security still fences it to the
-- signed-in user's own rows, and nothing else in the table can be changed.
GRANT UPDATE (withdrawn_at) ON consents TO perch_web;

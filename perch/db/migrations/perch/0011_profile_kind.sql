-- S53: a user's optional citizenship and state of residence are one encrypted `profile` row per
-- user and side (kind 'profile'), like the CV. The kind CHECK is inline and unnamed in 0002, so
-- it is found by definition, as 0009 does.
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'user_data'::regclass AND contype = 'c'
             AND pg_get_constraintdef(oid) LIKE '%scout_session%'
  LOOP
    EXECUTE format('ALTER TABLE user_data DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;

ALTER TABLE user_data ADD CONSTRAINT user_data_kind_check CHECK (kind IN
  ('cv','entry','doc','brief','saved_item','handoff','cover_points','scout_session','profile'));
CREATE UNIQUE INDEX ud_one_profile ON user_data (user_id, audience) WHERE kind = 'profile';

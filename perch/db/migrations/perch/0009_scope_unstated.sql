-- S43 fork F2: a Temple-page record with no stated scope stays inside Temple. It gets the scope
-- 'unstated' (the UI says "Scope not stated on the page"), and a record keeps the schools it
-- names whatever its scope. So the scope CHECK gains 'unstated' and the "schools only when
-- scope is school" CHECK goes. The constraints are found by definition, not by generated name.
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'records'::regclass AND contype = 'c'
             AND (pg_get_constraintdef(oid) LIKE '%scope = ANY%'
                  OR pg_get_constraintdef(oid) LIKE '%schools = %{}%'
                  OR pg_get_constraintdef(oid) LIKE '%scope = ''school''%')
  LOOP
    EXECUTE format('ALTER TABLE records DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;

ALTER TABLE records ADD CONSTRAINT records_scope_check
  CHECK (scope IN ('temple_wide', 'school', 'external', 'unstated'));
ALTER TABLE records ADD CONSTRAINT records_school_scope_names_schools
  CHECK (scope <> 'school' OR schools <> '{}');

-- Re-derive the two columns for the rows already stored, from each record's own fields, the
-- way perch.store.denorm.columns does. Both source names are the Temple pages' sources.
UPDATE records r SET
  schools = COALESCE((SELECT array_agg(s ORDER BY s COLLATE "C")
                      FROM (SELECT DISTINCT s FROM jsonb_array_elements_text(
                              CASE WHEN jsonb_typeof(r.data->'schools') = 'array'
                                   THEN r.data->'schools' ELSE '[]'::jsonb END) s
                            WHERE s <> '') t), '{}'),
  scope = CASE
    WHEN r.data->>'scope' IN ('temple_wide', 'external') THEN r.data->>'scope'
    WHEN r.data->>'scope' = 'school'
         AND jsonb_array_length(COALESCE(NULLIF(r.data->'schools', 'null'::jsonb), '[]'::jsonb)) > 0
      THEN 'school'
    WHEN r.source IN ('temple_pages', 'temple_sdfa') THEN 'unstated'
    ELSE 'external' END
WHERE r.kind IN ('scholarship', 'opportunity');

UPDATE record_vectors v SET schools = r.schools
FROM records r WHERE r.kind = v.record_kind AND r.id = v.record_id;

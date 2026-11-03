-- Tables of database perch (ARCHITECTURE_V1 section 2.2).

CREATE TABLE records (
  kind          text        NOT NULL CHECK (kind IN
                  ('researcher','work','award','opportunity','organisation','scholarship')),
  id            text        NOT NULL CHECK (id <> ''),
  source        text        NOT NULL CHECK (source <> ''),
  source_url    text        NOT NULL CHECK (source_url <> ''),
  fetched_at    timestamptz NOT NULL,
  data          jsonb       NOT NULL,
  sample        boolean     GENERATED ALWAYS AS (source = 'synthetic') STORED,
  scope         text        NOT NULL DEFAULT 'external' CHECK (scope IN ('temple_wide','school','external')),
  schools       text[]      NOT NULL DEFAULT '{}',
  temple_funded boolean     NOT NULL DEFAULT false,
  audience_level text[]     NOT NULL DEFAULT '{}',
  deadline      date,
  amount_max    numeric,
  status        text,
  PRIMARY KEY (kind, id),
  CHECK ((source = 'synthetic') = (id LIKE 'sample:%')),
  CHECK (scope = 'school' OR schools = '{}')
);
CREATE INDEX records_id         ON records (id);
CREATE INDEX records_browse     ON records (kind, temple_funded, scope, deadline) WHERE NOT sample;
CREATE INDEX records_schools    ON records USING gin (schools) WHERE NOT sample;
CREATE INDEX records_sample     ON records (kind) WHERE sample;
CREATE INDEX records_work_auth  ON records USING gin ((data->'author_ids') jsonb_path_ops)
                                WHERE kind = 'work';

CREATE TABLE record_vectors (
  index_name  text        NOT NULL CHECK (index_name IN ('opportunities','scholarships')),
  record_id   text        NOT NULL,
  record_kind text        NOT NULL,
  text        text        NOT NULL,
  embedding   vector(1024) NOT NULL,
  embedder    text        NOT NULL,
  embedded_at timestamptz NOT NULL,
  sample        boolean   NOT NULL,
  temple_funded boolean   NOT NULL,
  schools       text[]    NOT NULL DEFAULT '{}',
  tsv         tsvector    GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
  PRIMARY KEY (index_name, record_id),
  FOREIGN KEY (record_kind, record_id) REFERENCES records (kind, id) ON DELETE CASCADE
);
CREATE INDEX rv_opp_hnsw  ON record_vectors USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64) WHERE index_name = 'opportunities';
CREATE INDEX rv_sch_hnsw  ON record_vectors USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64) WHERE index_name = 'scholarships';
CREATE INDEX rv_tsv       ON record_vectors USING gin (tsv);
CREATE INDEX rv_schools   ON record_vectors USING gin (schools);

CREATE TABLE users (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  issuer_hash      bytea       NOT NULL,
  subject_hash     bytea       NOT NULL,
  roles            text[]      NOT NULL DEFAULT '{}' CHECK (roles <@ ARRAY['student','researcher','staff']),
  openalex_id_enc  bytea,
  openalex_linked_at timestamptz,
  last_audience    text        CHECK (last_audience IN ('researcher','student')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  last_active_at   timestamptz NOT NULL DEFAULT now(),
  deleted_at       timestamptz
);
CREATE UNIQUE INDEX users_subject ON users (issuer_hash, subject_hash) WHERE deleted_at IS NULL;

CREATE TABLE consents (
  id            bigserial   PRIMARY KEY,
  user_id       uuid        NOT NULL REFERENCES users ON DELETE CASCADE,
  version       int         NOT NULL,
  provider_name text        NOT NULL,
  text_sha256   bytea       NOT NULL,
  accepted_at   timestamptz NOT NULL DEFAULT now(),
  withdrawn_at  timestamptz
);

CREATE TABLE user_data (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid        NOT NULL REFERENCES users ON DELETE CASCADE,
  kind        text        NOT NULL CHECK (kind IN
                ('cv','entry','doc','brief','saved_item','handoff','cover_points','scout_session')),
  audience    text        NOT NULL CHECK (audience IN ('researcher','student')),
  key_version int         NOT NULL,
  blob        bytea       NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ud_user_kind ON user_data (user_id, audience, kind, updated_at DESC);
CREATE UNIQUE INDEX ud_one_cv ON user_data (user_id, audience) WHERE kind = 'cv';

CREATE TABLE jobs (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  kind            text        NOT NULL CHECK (kind IN
                    ('brief','scout_turn','handoff','cover_points','ingest','purge','precache')),
  state           text        NOT NULL DEFAULT 'queued' CHECK (state IN
                    ('queued','running','succeeded','failed','dead','cancelled')),
  user_id         uuid        REFERENCES users ON DELETE CASCADE,
  guest_sid_hash  bytea,
  audience        text        CHECK (audience IN ('researcher','student')),
  payload         jsonb       NOT NULL DEFAULT '{}',
  idempotency_key text        NOT NULL,
  priority        smallint    NOT NULL DEFAULT 5,
  attempts        int         NOT NULL DEFAULT 0,
  max_attempts    int         NOT NULL,
  run_after       timestamptz NOT NULL DEFAULT now(),
  lease_owner     text,
  lease_expires_at timestamptz,
  heartbeat_at    timestamptz,
  result_ref      text,
  error_code      text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  started_at      timestamptz,
  finished_at     timestamptz
);
CREATE UNIQUE INDEX jobs_idem ON jobs (kind, COALESCE(user_id, '00000000-0000-0000-0000-000000000000'),
  COALESCE(guest_sid_hash, '\x'::bytea), idempotency_key) WHERE state IN ('queued','running','succeeded');
CREATE INDEX jobs_claim ON jobs (priority, run_after, created_at) WHERE state = 'queued';
CREATE INDEX jobs_lease ON jobs (lease_expires_at) WHERE state = 'running';
CREATE INDEX jobs_user  ON jobs (user_id, created_at DESC);

CREATE TABLE job_events (
  id         bigserial   PRIMARY KEY,
  job_id     uuid        NOT NULL REFERENCES jobs ON DELETE CASCADE,
  at         timestamptz NOT NULL DEFAULT now(),
  stage      text        NOT NULL,
  status     text        NOT NULL CHECK (status IN ('pending','running','done','skipped','failed')),
  detail     text        CHECK (length(detail) <= 120),
  ms         int
);
CREATE INDEX je_job ON job_events (job_id, id);

CREATE TABLE audit_log (
  id          bigserial   PRIMARY KEY,
  at          timestamptz NOT NULL DEFAULT now(),
  event       text        NOT NULL,
  actor       uuid,
  job_id      uuid,
  role        text,
  provider    text, model text,
  prompt_hash bytea,
  input_tokens int, output_tokens int, cost_usd numeric(12,6),
  passed      boolean, layer smallint, attempt smallint,
  detail      jsonb NOT NULL DEFAULT '{}' CHECK (pg_column_size(detail) < 2048)
);
CREATE INDEX audit_at ON audit_log (at);
CREATE INDEX audit_event ON audit_log (event, at);

CREATE TABLE spend_ledger (
  id          bigserial   PRIMARY KEY,
  at          timestamptz NOT NULL DEFAULT now(),
  user_id     uuid,
  job_id      uuid,
  role        text        NOT NULL,
  provider    text        NOT NULL,
  model       text        NOT NULL,
  input_tokens int NOT NULL, output_tokens int NOT NULL,
  cache_read_tokens int NOT NULL DEFAULT 0, cache_write_tokens int NOT NULL DEFAULT 0,
  attempt     smallint,
  cost_usd    numeric(12,6) NOT NULL
);
CREATE INDEX sl_user_day ON spend_ledger (user_id, at);
CREATE INDEX sl_at ON spend_ledger (at);

CREATE TABLE public_cache (
  key          text        PRIMARY KEY,
  namespace    text        NOT NULL CHECK (namespace IN
                 ('fit','profile_summary','author','precache')),
  value        jsonb       NOT NULL,
  meta         jsonb       NOT NULL,
  ingest_epoch bigint      NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz
);
CREATE INDEX pc_ns ON public_cache (namespace, expires_at);

CREATE TABLE shred_log (
  user_id uuid PRIMARY KEY, shredded_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE ingest_runs (id bigserial PRIMARY KEY, source text NOT NULL, started_at timestamptz NOT NULL,
  finished_at timestamptz, rows_written int, epoch bigint, error_code text);

CREATE TABLE worker_heartbeat (worker text PRIMARY KEY, at timestamptz NOT NULL, kinds text[], models_loaded boolean);

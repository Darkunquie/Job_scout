CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
  id            bigserial PRIMARY KEY,
  email         text UNIQUE NOT NULL,
  password_hash text,
  role          text NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
  active        boolean NOT NULL DEFAULT true,
  daily_quota   int NOT NULL DEFAULT 30,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invites (
  token      text PRIMARY KEY,
  email      text NOT NULL,
  role       text NOT NULL DEFAULT 'user',
  created_by bigint REFERENCES users(id),
  expires_at timestamptz NOT NULL,
  used_at    timestamptz
);

CREATE TABLE IF NOT EXISTS user_prefs (
  user_id      bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  region_mode  text NOT NULL DEFAULT 'india' CHECK (region_mode IN ('india','countries','all')),
  countries    text[] NOT NULL DEFAULT '{}',
  include_remote boolean NOT NULL DEFAULT true,
  remote_scope text NOT NULL DEFAULT 'any',
  boards       jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS feature_flags (
  key     text PRIMARY KEY,
  enabled boolean NOT NULL
);
INSERT INTO feature_flags VALUES ('workday', true), ('linkedin', true), ('naukri', true), ('indeed', true)
  ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS companies (
  id              bigserial PRIMARY KEY,
  name            text,
  host            text,
  careers_url     text NOT NULL,
  ats_type        text NOT NULL,
  ats_slug        text NOT NULL,
  ats_extra       jsonb NOT NULL DEFAULT '{}',
  is_seed         boolean NOT NULL DEFAULT false,
  status          text NOT NULL DEFAULT 'new' CHECK (status IN ('new','ok','error','unsupported','blocked','needs_attention')),
  last_scraped_at timestamptz,
  last_error      text,
  job_count       int NOT NULL DEFAULT 0,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (ats_type, ats_slug)
);

CREATE TABLE IF NOT EXISTS user_companies (
  user_id    bigint REFERENCES users(id) ON DELETE CASCADE,
  company_id bigint REFERENCES companies(id) ON DELETE CASCADE,
  added_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, company_id)
);

CREATE TABLE IF NOT EXISTS recipes (
  host        text PRIMARY KEY,
  mode        text NOT NULL CHECK (mode IN ('http','browser')),
  request     jsonb NOT NULL,
  pagination  jsonb NOT NULL,
  field_map   jsonb NOT NULL,
  verified_at timestamptz,
  fail_count  int NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scrape_tasks (
  id         bigserial PRIMARY KEY,
  kind       text NOT NULL CHECK (kind IN ('company','board','resume')),
  payload    jsonb NOT NULL,
  user_id    bigint REFERENCES users(id) ON DELETE SET NULL,
  priority   smallint NOT NULL DEFAULT 0,
  status     text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','error')),
  attempts   int NOT NULL DEFAULT 0,
  run_after  timestamptz NOT NULL DEFAULT now(),
  locked_at  timestamptz,
  progress   jsonb NOT NULL DEFAULT '{}',
  error      text,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS scrape_tasks_claim ON scrape_tasks (status, priority DESC, run_after);

CREATE TABLE IF NOT EXISTS jobs (
  id               bigserial PRIMARY KEY,
  source           text NOT NULL,
  external_id      text NOT NULL,
  company_id       bigint REFERENCES companies(id) ON DELETE CASCADE,
  company_name     text,
  url              text,
  apply_url        text,
  title            text NOT NULL,
  department       text,
  description      text,
  location_raw     text,
  country_code     char(2),
  countries        text[] NOT NULL DEFAULT '{}',
  city             text,
  is_remote        boolean NOT NULL DEFAULT false,
  remote_scope     text,
  work_arrangement text,
  employment_type  text,
  exp_min          int,
  exp_max          int,
  exp_level        text,
  salary_min       numeric,
  salary_max       numeric,
  salary_currency  text,
  salary_period    text,
  salary_inr_year  numeric,
  skills           text[] NOT NULL DEFAULT '{}',
  visa_sponsorship boolean,
  posted_at        timestamptz,
  first_seen_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at     timestamptz NOT NULL DEFAULT now(),
  status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active','closed')),
  closed_at        timestamptz,
  content_hash     text,
  dedupe_key       text,
  cluster_id       bigint,
  embedding        vector(384),
  search           tsvector GENERATED ALWAYS AS
                     (to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(company_name,'') || ' ' || coalesce(department,''))) STORED,
  UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS jobs_list   ON jobs (status, country_code, posted_at DESC);
CREATE INDEX IF NOT EXISTS jobs_company ON jobs (company_id, status);
CREATE INDEX IF NOT EXISTS jobs_skills ON jobs USING gin (skills);
CREATE INDEX IF NOT EXISTS jobs_countries ON jobs USING gin (countries);
CREATE INDEX IF NOT EXISTS jobs_search ON jobs USING gin (search);
CREATE INDEX IF NOT EXISTS jobs_dedupe ON jobs (dedupe_key);
CREATE INDEX IF NOT EXISTS jobs_cluster ON jobs (cluster_id);
CREATE INDEX IF NOT EXISTS jobs_embedding ON jobs USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS scrape_runs (
  id          bigserial PRIMARY KEY,
  task_id     bigint REFERENCES scrape_tasks(id) ON DELETE SET NULL,
  company_id  bigint REFERENCES companies(id) ON DELETE CASCADE,
  adapter     text NOT NULL,
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  complete    boolean NOT NULL DEFAULT false,
  fetched     int NOT NULL DEFAULT 0,
  inserted    int NOT NULL DEFAULT 0,
  updated     int NOT NULL DEFAULT 0,
  closed      int NOT NULL DEFAULT 0,
  blocked     boolean NOT NULL DEFAULT false,
  error       text
);

CREATE TABLE IF NOT EXISTS resumes (
  id         bigserial PRIMARY KEY,
  user_id    bigint REFERENCES users(id) ON DELETE CASCADE,
  filename   text,
  text       text,
  skills     text[] NOT NULL DEFAULT '{}',
  embedding  vector(384),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS applications (
  id         bigserial PRIMARY KEY,
  user_id    bigint REFERENCES users(id) ON DELETE CASCADE,
  job_id     bigint REFERENCES jobs(id) ON DELETE CASCADE,
  stage      text NOT NULL DEFAULT 'saved' CHECK (stage IN ('saved','applied','interview','offer','rejected')),
  notes      text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, job_id)
);

CREATE TABLE IF NOT EXISTS shortlists (
  token      text PRIMARY KEY,
  user_id    bigint REFERENCES users(id) ON DELETE CASCADE,
  job_ids    bigint[] NOT NULL,
  expires_at timestamptz NOT NULL
);

-- added after the first release: marks a job the local LLM has already read (see app/llm.py)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS enriched_at timestamptz;

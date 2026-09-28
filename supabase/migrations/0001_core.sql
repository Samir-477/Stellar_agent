-- 0001 core schema: clients, snapshots, evidence, runs, task queue, results, LLM usage.
-- Plain Postgres 17 (no Supabase-only features), so it also runs self-hosted.
-- RLS is enabled on every table with no policies: only the backend (table owner /
-- service role) can read or write. Supabase's public REST API sees nothing.

create table orgs (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);
insert into orgs (id, name) values ('00000000-0000-0000-0000-000000000001', 'Default');

create table clients (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null default '00000000-0000-0000-0000-000000000001' references orgs(id),
  name text not null,
  primary_url text not null,
  archetype text check (archetype in ('hospitality', 'loans', 'retail', 'logistics')),
  archetype_source text check (archetype_source in ('detected', 'confirmed')),
  locations text[] not null default '{}',
  competitors text[] not null default '{}',
  crawl_consent_by text,
  crawl_consent_at timestamptz,
  created_at timestamptz not null default now()
);

create table snapshots (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null default '00000000-0000-0000-0000-000000000001' references orgs(id),
  client_id uuid not null references clients(id) on delete cascade,
  crawl_cap int not null,
  status text not null default 'open',
  created_at timestamptz not null default now()
);
create index on snapshots (client_id, created_at desc);

create table pages (
  id uuid primary key,
  snapshot_id uuid not null references snapshots(id) on delete cascade,
  url text not null,
  final_url text,
  status int,
  template_id text,
  raw_html_key text,
  rendered_html_key text,
  render_status text not null default 'not_requested',
  fetch_meta jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index on pages (snapshot_id);

create table evidence (
  id uuid primary key,
  snapshot_id uuid not null references snapshots(id) on delete cascade,
  collector_id text not null,
  type text not null,
  page_id uuid references pages(id) on delete cascade,
  payload jsonb not null default '{}',
  blob_key text,
  source_label text,
  captured_at timestamptz not null default now()
);
create index on evidence (snapshot_id, type);

create table runs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null default '00000000-0000-0000-0000-000000000001' references orgs(id),
  client_id uuid not null references clients(id) on delete cascade,
  snapshot_id uuid not null references snapshots(id) on delete cascade,
  type text not null check (type in ('full', 'agent')),
  agents text[] not null,
  crawl_cap int not null,
  status text not null default 'queued'
    check (status in ('queued', 'running', 'awaiting_confirmation', 'completed', 'completed_partial', 'failed', 'cancelled')),
  token_budget int,
  tokens_used int not null default 0,
  note text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create index on runs (client_id, created_at desc);

-- The task queue. Claimed with FOR UPDATE SKIP LOCKED plus a lease (see engine/orchestrator/repo.py).
create table tasks (
  id uuid primary key,
  run_id uuid not null references runs(id) on delete cascade,
  key text not null,
  kind text not null,
  ref text,
  unit jsonb,
  deps uuid[] not null default '{}',
  barrier_id uuid,
  is_barrier boolean not null default false,
  status text not null default 'pending'
    check (status in ('pending', 'running', 'succeeded', 'partial', 'failed', 'skipped')),
  attempts int not null default 0,
  not_before timestamptz not null default now(),
  lease_until timestamptz,
  lease_token uuid,
  output jsonb,
  error text,
  created_at timestamptz not null default clock_timestamp(),
  started_at timestamptz,
  finished_at timestamptz
);
create index tasks_ready on tasks (status, not_before) where status in ('pending', 'running');
create index on tasks (run_id);

create table findings (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references runs(id) on delete cascade,
  agent_id text not null,
  agent_version text not null,
  check_id text not null,
  pillar text not null,
  status text not null,
  severity text,
  confidence text not null,
  title text not null,
  pages text[] not null default '{}',
  fingerprint text not null,
  payload jsonb not null,
  created_at timestamptz not null default now()
);
create index on findings (run_id, agent_id);

create table patches (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references runs(id) on delete cascade,
  agent_id text not null,
  key text not null,
  page_url text,
  type text not null,
  locator jsonb,
  before text,
  after text not null,
  rationale text not null,
  confidence text not null,
  review_status text not null default 'proposed'
    check (review_status in ('proposed', 'approved', 'edited', 'rejected')),
  reviewed_by text,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  unique (run_id, agent_id, key)
);

create table reports (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references runs(id) on delete cascade,
  kind text not null check (kind in ('agent', 'intelligence')),
  agent_id text,
  body jsonb not null,
  created_at timestamptz not null default now()
);
create index on reports (run_id, kind, agent_id);

create table llm_cache (
  key text primary key,
  provider text not null,
  model text not null,
  response text not null,
  created_at timestamptz not null default now()
);

create table llm_calls (
  id bigint generated always as identity primary key,
  run_id uuid references runs(id) on delete set null,
  task_id uuid,
  prompt_ref text not null,
  cache_key text not null,
  provider text not null,
  model text,
  tokens_in int not null default 0,
  tokens_out int not null default 0,
  fallback_used boolean not null default false,
  error text,
  created_at timestamptz not null default now()
);
create index on llm_calls (run_id);

create table provider_usage (
  provider text not null,
  day date not null default current_date,
  units int not null default 0,
  primary key (provider, day)
);

do $$
declare t text;
begin
  foreach t in array array['orgs','clients','snapshots','pages','evidence','runs','tasks','findings',
                           'patches','reports','llm_cache','llm_calls','provider_usage']
  loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;

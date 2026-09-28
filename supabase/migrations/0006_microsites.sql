-- 0006: microsites. An approved Output preview of a run's diagnosed URL, published at
-- /microsites/{archetype}/{client_slug}/{page_path}. Each row is one immutable version; publishing
-- the same slug again supersedes the live row, and unpublishing hides it (history is kept).
create table microsites (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients(id) on delete cascade,
  run_id uuid not null references runs(id) on delete cascade,
  archetype text not null check (archetype in ('hospitality', 'loans', 'retail', 'logistics')),
  client_slug text not null check (client_slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  page_path text not null check (page_path ~ '^[a-z0-9]+([-/][a-z0-9]+)*$'),
  client_name text not null,
  source_url text not null,
  page_title text,
  fixed_key text not null,
  annotated_key text not null,
  original_key text not null,
  issues jsonb not null default '[]',
  changes_placed int not null default 0,
  changes_total int not null default 0,
  published_by text,
  published_at timestamptz not null default now(),
  superseded_at timestamptz,
  unpublished_at timestamptz
);
create unique index microsites_live_slug on microsites (archetype, client_slug, page_path)
  where superseded_at is null and unpublished_at is null;
create index microsites_client_idx on microsites (client_slug, published_at desc);
alter table microsites enable row level security;

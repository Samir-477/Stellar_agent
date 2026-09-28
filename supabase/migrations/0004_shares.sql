-- 0004: share links (docs/spec/06). Tokens are stored hashed; links expire and can be revoked.
create table shares (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references runs(id) on delete cascade,
  token_hash text not null unique,
  bundle_prefix text not null,
  expires_at timestamptz not null,
  password_hash text,
  revoked_at timestamptz,
  view_count int not null default 0,
  created_by text,
  created_at timestamptz not null default now()
);
create index on shares (run_id);
alter table shares enable row level security;

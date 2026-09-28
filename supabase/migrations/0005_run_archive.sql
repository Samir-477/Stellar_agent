-- A hidden run keeps its evidence and reports intact and can be restored.
alter table runs add column archived_at timestamptz;
create index runs_archived_created_idx on runs (archived_at, created_at desc);

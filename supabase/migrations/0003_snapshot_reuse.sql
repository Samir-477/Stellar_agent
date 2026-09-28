-- 0003: record which collectors have finished for a snapshot, so later runs can
-- reuse the evidence instead of re-crawling (docs/spec/03 "reuse fresh evidence").
alter table snapshots add column collectors_done text[] not null default '{}';

-- Backfill from evidence already captured.
update snapshots s
set collectors_done = coalesce((select array_agg(distinct e.collector_id) from evidence e where e.snapshot_id = s.id), '{}');

-- Archetype confirmation gate (docs/spec/03 step 4).
alter table runs add column archetype_gate text not null default 'open'
  check (archetype_gate in ('open', 'awaiting', 'confirmed'));

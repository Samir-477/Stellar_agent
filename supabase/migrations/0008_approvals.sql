-- 0008: approvals (user decision, 2026-10-02). Some proposed changes wait for the team's approval
-- before they are applied in the preview and the microsite (Patch.approval = "required"). One row per
-- approved change; it survives an agent re-run because patch keys are stable for the same change.
create table approvals (
  run_id uuid not null references runs(id) on delete cascade,
  patch_key text not null,
  approved_by text,
  approved_at timestamptz not null default now(),
  primary key (run_id, patch_key)
);
alter table approvals enable row level security;

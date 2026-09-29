-- Runs are now deleted for good from Sessions (user decision, 2026-09-29), and share links were
-- replaced by microsites. Drop the soft-delete column and the share-link table, and stop requiring an
-- "original" copy for microsites (the Before view was removed).
drop table if exists shares;
alter table runs drop column if exists archived_at;
alter table microsites alter column original_key drop not null;

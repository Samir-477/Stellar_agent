-- 0002 Supabase Storage buckets (skip this file when self-hosting without Supabase).
-- All buckets are private; files are served only through the app.
insert into storage.buckets (id, name, public)
values ('snapshots', 'snapshots', false),
       ('assets', 'assets', false),
       ('share-bundles', 'share-bundles', false)
on conflict (id) do nothing;

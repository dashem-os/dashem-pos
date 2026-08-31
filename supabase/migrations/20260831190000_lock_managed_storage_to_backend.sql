-- DASHEM managed buckets are backend-authoritative. The service role bypasses
-- RLS; authenticated and anonymous clients must never upload, list, overwrite,
-- move or delete these objects directly because that would bypass quota
-- reservations and the canonical tenant context.

drop policy if exists dashem_managed_storage_select_backend_only on storage.objects;
drop policy if exists dashem_managed_storage_insert_backend_only on storage.objects;
drop policy if exists dashem_managed_storage_update_backend_only on storage.objects;
drop policy if exists dashem_managed_storage_delete_backend_only on storage.objects;

create policy dashem_managed_storage_select_backend_only
on storage.objects as restrictive
for select to authenticated, anon
using (
  bucket_id <> all (array[
    'tenant-assets',
    'tenant-documents',
    'tenant-exports',
    'tenant-integrations'
  ]::text[])
);

create policy dashem_managed_storage_insert_backend_only
on storage.objects as restrictive
for insert to authenticated, anon
with check (
  bucket_id <> all (array[
    'tenant-assets',
    'tenant-documents',
    'tenant-exports',
    'tenant-integrations'
  ]::text[])
);

create policy dashem_managed_storage_update_backend_only
on storage.objects as restrictive
for update to authenticated, anon
using (
  bucket_id <> all (array[
    'tenant-assets',
    'tenant-documents',
    'tenant-exports',
    'tenant-integrations'
  ]::text[])
)
with check (
  bucket_id <> all (array[
    'tenant-assets',
    'tenant-documents',
    'tenant-exports',
    'tenant-integrations'
  ]::text[])
);

create policy dashem_managed_storage_delete_backend_only
on storage.objects as restrictive
for delete to authenticated, anon
using (
  bucket_id <> all (array[
    'tenant-assets',
    'tenant-documents',
    'tenant-exports',
    'tenant-integrations'
  ]::text[])
);

-- The shared DASHEM library is written only through the authenticated Control
-- plane. It is private at the provider and is served to tenants exclusively by
-- short-lived server-signed URLs. Tenant-owned objects remain in their own
-- UUID prefix and are never copied into this bucket.

drop policy if exists dashem_platform_library_select_backend_only on storage.objects;
drop policy if exists dashem_platform_library_insert_backend_only on storage.objects;
drop policy if exists dashem_platform_library_update_backend_only on storage.objects;
drop policy if exists dashem_platform_library_delete_backend_only on storage.objects;

create policy dashem_platform_library_select_backend_only
on storage.objects as restrictive
for select to authenticated, anon
using (bucket_id <> 'dashem-library');

create policy dashem_platform_library_insert_backend_only
on storage.objects as restrictive
for insert to authenticated, anon
with check (bucket_id <> 'dashem-library');

create policy dashem_platform_library_update_backend_only
on storage.objects as restrictive
for update to authenticated, anon
using (bucket_id <> 'dashem-library')
with check (bucket_id <> 'dashem-library');

create policy dashem_platform_library_delete_backend_only
on storage.objects as restrictive
for delete to authenticated, anon
using (bucket_id <> 'dashem-library');

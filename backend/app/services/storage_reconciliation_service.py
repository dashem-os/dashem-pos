"""Trusted reconciliation from the Supabase Storage administrative API."""

import hashlib
import json
import uuid
from datetime import datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.models.storage import StorageMeasurement, StorageMeterSource, StorageProviderMeasurement
from app.models.identity import Tenant
from app.services.supabase_storage import SupabaseStorageClient, SupabaseStorageUnavailable


class StorageInventoryUnavailable(RuntimeError):
    pass


def configure_supabase_sources(session: Session, tenant_id: uuid.UUID, actor_id: uuid.UUID) -> list[StorageMeterSource]:
    sources: list[StorageMeterSource] = []
    now = datetime.utcnow()
    for bucket in settings.supabase_storage_buckets:
        key = f"supabase:{bucket}"
        source = session.exec(select(StorageMeterSource).where(
            StorageMeterSource.tenant_id == tenant_id,
            StorageMeterSource.source_key == key,
        )).first()
        locator = f"{bucket}/{tenant_id}"
        if source is None:
            source = StorageMeterSource(
                tenant_id=tenant_id, source_key=key, provider="SUPABASE",
                locator_reference=locator, status="ACTIVE", created_by=actor_id,
            )
        else:
            source.provider = "SUPABASE"
            source.locator_reference = locator
            source.status = "ACTIVE"
            source.updated_at = now
        session.add(source)
        sources.append(source)
    session.flush()
    return sources


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def reconcile_supabase_storage(
    session: Session, tenant_id: uuid.UUID, actor_id: uuid.UUID, *, now: datetime | None = None,
    client: SupabaseStorageClient | None = None,
) -> tuple[StorageMeasurement, StorageProviderMeasurement]:
    """Persist tenant and project facts; no caller may submit byte counts."""

    if not settings.supabase_storage_configured:
        raise StorageInventoryUnavailable("Supabase Storage e sua capacidade física não estão configurados.")
    now = now or datetime.utcnow()
    storage = client or SupabaseStorageClient()
    sources = configure_supabase_sources(session, tenant_id, actor_id)
    source_rows: list[dict[str, object]] = []
    for source in sources:
        bucket = source.locator_reference.split("/", 1)[0]
        try:
            inventory = storage.inventory(bucket, str(tenant_id))
        except SupabaseStorageUnavailable as exc:
            raise StorageInventoryUnavailable(str(exc)) from exc
        source_rows.append({
            "source_key": source.source_key,
            "bucket": bucket,
            "used_bytes": inventory.used_bytes,
            "object_count": inventory.object_count,
            "watermark": inventory.watermark,
        })
    tenant_payload = {
        "tenant_id": str(tenant_id), "sources": source_rows, "measured_at": now.isoformat(),
    }
    tenant_measurement = StorageMeasurement(
        tenant_id=tenant_id,
        status="RECONCILED",
        used_bytes=sum(int(row["used_bytes"]) for row in source_rows),
        object_count=sum(int(row["object_count"]) for row in source_rows),
        source_keys=[source.source_key for source in sources],
        watermark="|".join(f"{row['source_key']}:{row['watermark']}" for row in source_rows),
        source_fingerprint=_fingerprint(tenant_payload),
        evidence={"adapter": "SUPABASE_STORAGE_SCHEMA_V1", "sources": source_rows},
        measured_at=now,
        recorded_by=actor_id,
    )
    session.add(tenant_measurement)

    try:
        project_inventory, provider_buckets = storage.project_inventory()
    except SupabaseStorageUnavailable as exc:
        raise StorageInventoryUnavailable(str(exc)) from exc
    known_tenants = {str(item) for item in session.exec(select(Tenant.id)).all()}
    managed = set(settings.supabase_storage_buckets)
    orphan_hashes: list[str] = []
    for provider_path in project_inventory.object_paths:
        bucket, _, object_path = provider_path.partition("/")
        prefix = object_path.split("/", 1)[0] if object_path else ""
        if bucket in managed and prefix not in known_tenants:
            orphan_hashes.append(hashlib.sha256(provider_path.encode()).hexdigest())
    global_payload = {
        "provider": "SUPABASE", "scope": "PROJECT_ALL_BUCKETS",
        "used_bytes": project_inventory.used_bytes,
        "object_count": project_inventory.object_count,
        "watermark": project_inventory.watermark,
        "provider_buckets": provider_buckets,
        "orphan_object_hashes": sorted(orphan_hashes),
        "measured_at": now.isoformat(),
    }
    provider_measurement = StorageProviderMeasurement(
        provider="SUPABASE", status="RECONCILED",
        used_bytes=project_inventory.used_bytes, object_count=project_inventory.object_count,
        source_keys=list(provider_buckets),
        watermark=str(global_payload["watermark"]),
        source_fingerprint=_fingerprint(global_payload),
        evidence={
            "adapter": "SUPABASE_STORAGE_ADMIN_API_V1", "scope": "PROJECT_ALL_BUCKETS",
            "orphan_object_count": len(orphan_hashes),
            "orphan_object_hashes": sorted(orphan_hashes),
        },
        measured_at=now, recorded_by=actor_id,
    )
    session.add(provider_measurement)
    session.flush()
    return tenant_measurement, provider_measurement

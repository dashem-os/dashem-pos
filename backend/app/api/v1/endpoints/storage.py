"""Storage inventory control plane and tenant-visible quota state."""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import PLATFORM_MANAGERS
from app.core.access import require_platform_role
from app.core.context import TenantContext, get_tenant_context
from app.core.context import resolve_actor
from app.core.config import settings
from app.core.database import get_session
from app.core.security import AuthPrincipal, get_current_principal
from app.models.identity import Tenant
from app.models.storage import StorageMeasurement, StorageMeterSource
from app.services import reliability_service
from app.services.storage_quota_service import active_storage_sources, storage_quota_read_model
from app.services.storage_quota_service import (
    StorageCapacityUnavailableError, finalize_storage_reservation, reserve_storage_capacity,
)
from app.services.storage_reconciliation_service import (
    StorageInventoryUnavailable, reconcile_supabase_storage,
)
from app.services.supabase_storage import (
    SupabaseStorageClient, SupabaseStorageRejected, SupabaseStorageUnavailable, managed_bucket,
    tenant_object_path, validate_content_signature, validate_filename_content_type,
)


router = APIRouter()


def _safe_locator_reference(value: str) -> str:
    locator = value.strip()
    lowered = locator.lower()
    if "?" in locator or any(marker in lowered for marker in ("token=", "secret=", "password=", "signature=")):
        raise HTTPException(
            status_code=422,
            detail="locator_reference deve identificar o namespace sem credenciais ou query assinada.",
        )
    return locator


def _utc_naive(value: datetime) -> datetime:
    """Normalize API timestamps before comparing with PostgreSQL's UTC-naive columns."""

    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class StorageSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str = PydanticField(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]+$")
    provider: str = PydanticField(min_length=2, max_length=60)
    locator_reference: str = PydanticField(min_length=4, max_length=240)
    status: str = PydanticField(default="ACTIVE", pattern=r"^(ACTIVE|INACTIVE)$")


class StorageMeasurementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = PydanticField(pattern=r"^(PARTIAL|RECONCILED|DIVERGENT|UNAVAILABLE)$")
    used_bytes: Optional[int] = PydanticField(default=None, ge=0)
    object_count: Optional[int] = PydanticField(default=None, ge=0)
    source_keys: list[str] = PydanticField(min_length=1)
    watermark: str = PydanticField(min_length=4, max_length=240)
    evidence_reference: str = PydanticField(min_length=4, max_length=500)
    measured_at: datetime


class StorageSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    source_key: str
    provider: str
    locator_reference: str
    status: str
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class StorageMeasurementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    used_bytes: Optional[int]
    object_count: Optional[int]
    source_keys: list[str]
    watermark: str
    source_fingerprint: str
    evidence: dict[str, Any]
    measured_at: datetime
    recorded_by: uuid.UUID
    recorded_at: datetime


class StorageObjectRead(BaseModel):
    bucket_id: str
    object_path: str
    size_bytes: int
    provider_reference: str
    idempotent_replay: bool = False


class SignedStorageUrl(BaseModel):
    url: str
    expires_in: int


def _provider_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


def _resolve_storage_target(tenant_id: uuid.UUID, bucket_id: str, relative_path: str) -> tuple[str, str]:
    try:
        return managed_bucket(bucket_id), tenant_object_path(tenant_id, relative_path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/quota")
def tenant_storage_quota(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return storage_quota_read_model(session, context.tenant_id)


@router.put("/objects/{bucket_id}/{relative_path:path}", response_model=StorageObjectRead)
async def upload_tenant_object(
    bucket_id: str,
    relative_path: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    bucket, object_path = _resolve_storage_target(context.tenant_id, bucket_id, relative_path)
    content_type = request.headers.get("content-type", "application/octet-stream").split(";", 1)[0].lower()
    allowed = {
        "tenant-assets": {"image/jpeg", "image/png", "image/webp"},
        "tenant-documents": {"application/pdf", "image/jpeg", "image/png"},
        "tenant-exports": {"text/csv", "application/pdf", "application/json"},
        "tenant-integrations": {"text/csv", "application/json"},
    }
    if content_type not in allowed.get(bucket, set()):
        raise HTTPException(status_code=415, detail="Tipo de arquivo não permitido para este bucket.")
    try:
        validate_filename_content_type(relative_path, content_type)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Content-Length inválido.") from exc
        if declared_size > settings.STORAGE_MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Arquivo excede o limite individual do DASHEM.")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > settings.STORAGE_MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Arquivo excede o limite individual do DASHEM.")
        chunks.append(chunk)
    if total < 1:
        raise HTTPException(status_code=422, detail="Arquivo vazio não é aceito.")
    content = b"".join(chunks)
    try:
        validate_content_signature(content, content_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    actor_id = resolve_actor(context)
    try:
        reservation = reserve_storage_capacity(
            session, context.tenant_id, operation_key=idempotency_key,
            requested_bytes=total, actor_id=actor_id, bucket_id=bucket, object_path=object_path,
        )
    except StorageCapacityUnavailableError as exc:
        raise HTTPException(status_code=409, detail=exc.evaluation.reason) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if reservation.status == "COMMITTED" and reservation.provider_reference:
        return StorageObjectRead(
            bucket_id=bucket, object_path=object_path, size_bytes=reservation.requested_bytes,
            provider_reference=reservation.provider_reference, idempotent_replay=True,
        )
    session.commit()
    try:
        stored = SupabaseStorageClient().upload(bucket, object_path, content, content_type)
    except SupabaseStorageRejected as exc:
        finalize_storage_reservation(session, reservation.id, committed=False, reason="Falha confirmada pelo adaptador Supabase")
        session.commit()
        raise _provider_error(exc) from exc
    except (SupabaseStorageUnavailable, httpx.RequestError) as exc:
        # A timeout or 5xx is ambiguous: the provider may have persisted the
        # object. Keep the reservation active so retries cannot reclaim those
        # bytes before the next inventory or TTL expiration.
        raise _provider_error(exc) from exc
    finalize_storage_reservation(
        session, reservation.id, committed=True, reason="Objeto confirmado pelo adaptador Supabase",
        provider_reference=stored.provider_reference,
    )
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=context.store_id, actor_id=actor_id,
        action="storage.object.uploaded", target=f"{bucket}:{object_path}",
        audit_payload={"bucket": bucket, "object_path": object_path, "size_bytes": total},
        aggregate_type="storage_object", aggregate_id=stored.provider_reference,
        event_type="storage.object.uploaded", outbox_payload={"bucket": bucket, "object_path": object_path},
    )
    session.commit()
    return StorageObjectRead(**stored.__dict__)


@router.delete("/objects/{bucket_id}/{relative_path:path}", status_code=204)
def delete_tenant_object(
    bucket_id: str, relative_path: str,
    context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session),
):
    bucket, object_path = _resolve_storage_target(context.tenant_id, bucket_id, relative_path)
    actor_id = resolve_actor(context)
    try:
        SupabaseStorageClient().delete(bucket, object_path)
    except (SupabaseStorageUnavailable, httpx.RequestError) as exc:
        raise _provider_error(exc) from exc
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=context.store_id, actor_id=actor_id,
        action="storage.object.deleted", target=f"{bucket}:{object_path}",
        audit_payload={"bucket": bucket, "object_path": object_path}, aggregate_type="storage_object",
        aggregate_id=object_path, event_type="storage.object.deleted",
        outbox_payload={"bucket": bucket, "object_path": object_path},
    )
    session.commit()


@router.get("/objects/{bucket_id}/{relative_path:path}/signed-url", response_model=SignedStorageUrl)
def sign_tenant_download(
    bucket_id: str, relative_path: str,
    context: TenantContext = Depends(get_tenant_context),
):
    bucket, object_path = _resolve_storage_target(context.tenant_id, bucket_id, relative_path)
    try:
        return SignedStorageUrl(url=SupabaseStorageClient().signed_download_url(bucket, object_path), expires_in=60)
    except (SupabaseStorageUnavailable, httpx.RequestError) as exc:
        raise _provider_error(exc) from exc


@router.get("/platform/tenants/{tenant_id}/sources", response_model=list[StorageSourceRead])
def list_storage_sources(
    tenant_id: uuid.UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    return list(
        session.exec(
            select(StorageMeterSource)
            .where(StorageMeterSource.tenant_id == tenant_id)
            .order_by(StorageMeterSource.source_key)
        ).all()
    )


@router.post(
    "/platform/tenants/{tenant_id}/sources",
    response_model=StorageSourceRead,
    status_code=201,
)
def configure_storage_source(
    tenant_id: uuid.UUID,
    data: StorageSourceCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    if session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    locator_reference = _safe_locator_reference(data.locator_reference)
    source = session.exec(
        select(StorageMeterSource).where(
            StorageMeterSource.tenant_id == tenant_id,
            StorageMeterSource.source_key == data.source_key,
        )
    ).first()
    now = datetime.utcnow()
    if source is None:
        source = StorageMeterSource(
            tenant_id=tenant_id,
            source_key=data.source_key,
            provider=data.provider.strip().upper(),
            locator_reference=locator_reference,
            status=data.status,
            created_by=actor.id,
        )
    else:
        source.provider = data.provider.strip().upper()
        source.locator_reference = locator_reference
        source.status = data.status
        source.updated_at = now
    session.add(source)
    session.flush()
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=tenant_id,
        store_id=None,
        actor_id=actor.id,
        action="platform.storage_source.configured",
        target=f"storage_source:{source.id}",
        audit_payload={
            "source_key": source.source_key,
            "provider": source.provider,
            "status": source.status,
        },
        aggregate_type="storage_meter_source",
        aggregate_id=str(source.id),
        event_type="platform.storage_source.configured",
        outbox_payload={"tenant_id": str(tenant_id), "source_key": source.source_key},
    )
    session.commit()
    session.refresh(source)
    return source


def _measurement_fingerprint(tenant_id: uuid.UUID, data: StorageMeasurementCreate) -> str:
    measured_at = _utc_naive(data.measured_at)
    canonical = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "status": data.status,
            "used_bytes": data.used_bytes,
            "object_count": data.object_count,
            "source_keys": sorted(set(data.source_keys)),
            "watermark": data.watermark.strip(),
            "evidence_reference": data.evidence_reference.strip(),
            "measured_at": measured_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_storage_measurement(
    tenant_id: uuid.UUID,
    data: StorageMeasurementCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    session.exec(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()).first()
    if session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    active_keys = {item.source_key for item in active_storage_sources(session, tenant_id)}
    measured_keys = set(data.source_keys)
    if len(measured_keys) != len(data.source_keys):
        raise HTTPException(status_code=422, detail="source_keys não pode conter duplicidades.")
    if not active_keys:
        raise HTTPException(
            status_code=409,
            detail="Configure ao menos uma fonte física antes de registrar uma medição.",
        )
    if not measured_keys.issubset(active_keys):
        raise HTTPException(status_code=422, detail="A medição contém fonte não configurada ou inativa.")
    measured_at = _utc_naive(data.measured_at)
    if data.status == "RECONCILED":
        if measured_keys != active_keys:
            raise HTTPException(
                status_code=422,
                detail="Uma medição reconciliada deve cobrir exatamente todas as fontes ativas.",
            )
        if data.used_bytes is None or data.object_count is None:
            raise HTTPException(
                status_code=422,
                detail="Medição reconciliada exige bytes utilizados e quantidade de objetos.",
            )
        latest_source_change = max(item.updated_at for item in active_storage_sources(session, tenant_id))
        if measured_at < latest_source_change:
            raise HTTPException(
                status_code=422,
                detail="A medição antecede a configuração atual das fontes físicas.",
            )
    if measured_at > datetime.utcnow() + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="measured_at não pode estar no futuro.")

    fingerprint = _measurement_fingerprint(tenant_id, data)
    existing = session.exec(
        select(StorageMeasurement).where(
            StorageMeasurement.tenant_id == tenant_id,
            StorageMeasurement.source_fingerprint == fingerprint,
        )
    ).first()
    if existing:
        return existing
    measurement = StorageMeasurement(
        tenant_id=tenant_id,
        status=data.status,
        used_bytes=data.used_bytes,
        object_count=data.object_count,
        source_keys=sorted(measured_keys),
        watermark=data.watermark.strip(),
        source_fingerprint=fingerprint,
        evidence={"reference": data.evidence_reference.strip()},
        measured_at=measured_at,
        recorded_by=actor.id,
    )
    session.add(measurement)
    session.flush()
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=tenant_id,
        store_id=None,
        actor_id=actor.id,
        action="platform.storage_measurement.recorded",
        target=f"storage_measurement:{measurement.id}",
        audit_payload={
            "measurement_id": str(measurement.id),
            "status": measurement.status,
            "source_keys": measurement.source_keys,
            "watermark": measurement.watermark,
            "source_fingerprint": measurement.source_fingerprint,
        },
        aggregate_type="storage_measurement",
        aggregate_id=str(measurement.id),
        event_type="platform.storage_measurement.recorded",
        outbox_payload={"tenant_id": str(tenant_id), "measurement_id": str(measurement.id)},
    )
    session.commit()
    session.refresh(measurement)
    return measurement


@router.post("/platform/tenants/{tenant_id}/bootstrap")
def bootstrap_supabase_storage(
    tenant_id: uuid.UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    if session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    try:
        buckets = SupabaseStorageClient().ensure_private_buckets()
        tenant_measurement, provider_measurement = reconcile_supabase_storage(session, tenant_id, actor.id)
    except (SupabaseStorageUnavailable, StorageInventoryUnavailable, httpx.RequestError) as exc:
        session.rollback()
        raise _provider_error(exc) from exc
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=tenant_id, store_id=None, actor_id=actor.id,
        action="platform.storage.bootstrap.completed", target=f"tenant:{tenant_id}",
        audit_payload={"buckets": buckets, "measurement_id": str(tenant_measurement.id)},
        aggregate_type="storage_measurement", aggregate_id=str(tenant_measurement.id),
        event_type="platform.storage.reconciled",
        outbox_payload={"tenant_id": str(tenant_id), "provider_measurement_id": str(provider_measurement.id)},
    )
    session.commit()
    return storage_quota_read_model(session, tenant_id)


@router.post("/platform/tenants/{tenant_id}/reconcile")
def reconcile_tenant_storage(
    tenant_id: uuid.UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    try:
        reconcile_supabase_storage(session, tenant_id, actor.id)
    except StorageInventoryUnavailable as exc:
        session.rollback()
        raise _provider_error(exc) from exc
    session.commit()
    return storage_quota_read_model(session, tenant_id)


@router.get(
    "/platform/tenants/{tenant_id}/measurements",
    response_model=list[StorageMeasurementRead],
)
def list_storage_measurements(
    tenant_id: uuid.UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    return list(
        session.exec(
            select(StorageMeasurement)
            .where(StorageMeasurement.tenant_id == tenant_id)
            .order_by(StorageMeasurement.measured_at.desc())
            .limit(100)
        ).all()
    )

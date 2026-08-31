"""Storage inventory control plane and tenant-visible quota state."""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import PLATFORM_MANAGERS
from app.core.access import require_platform_role
from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.core.security import AuthPrincipal, get_current_principal
from app.models.identity import Tenant
from app.models.storage import StorageMeasurement, StorageMeterSource
from app.services import reliability_service
from app.services.storage_quota_service import active_storage_sources, storage_quota_read_model


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


@router.get("/quota")
def tenant_storage_quota(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return storage_quota_read_model(session, context.tenant_id)


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


@router.post(
    "/platform/tenants/{tenant_id}/measurements",
    response_model=StorageMeasurementRead,
    status_code=201,
)
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

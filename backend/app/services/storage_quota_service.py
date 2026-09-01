"""Canonical storage meter, reconciliation policy and fail-closed reservations.

No route may claim storage enforcement merely because a contract has a number.
Enforcement becomes available only after all configured physical namespaces have
a fresh, append-only RECONCILED inventory measurement.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlmodel import Session, select

from app.core.config import settings
from app.models.identity import Tenant
from app.models.platform import TenantContract
from app.models.storage import StorageMeasurement, StorageMeterSource, StorageProviderMeasurement, StorageReservation
from app.modules.governance.contracts import MeasurementStatus, QuotaDecision, QuotaEvaluation
from app.services.contract_entitlement_service import latest_contract, resolve_contract_entitlements


class StorageCapacityUnavailableError(ValueError):
    def __init__(self, evaluation: QuotaEvaluation):
        super().__init__(evaluation.reason)
        self.evaluation = evaluation


def active_storage_sources(session: Session, tenant_id: uuid.UUID) -> list[StorageMeterSource]:
    return list(
        session.exec(
            select(StorageMeterSource)
            .where(
                StorageMeterSource.tenant_id == tenant_id,
                StorageMeterSource.status == "ACTIVE",
            )
            .order_by(StorageMeterSource.source_key)
        ).all()
    )


def latest_storage_measurement(
    session: Session, tenant_id: uuid.UUID
) -> StorageMeasurement | None:
    return session.exec(
        select(StorageMeasurement)
        .where(StorageMeasurement.tenant_id == tenant_id)
        .order_by(StorageMeasurement.measured_at.desc(), StorageMeasurement.recorded_at.desc())
    ).first()


def _active_reserved_bytes(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    now: datetime,
    reconciled_through: datetime | None,
) -> int:
    reservations = session.exec(
        select(StorageReservation).where(
            StorageReservation.tenant_id == tenant_id,
            StorageReservation.status.in_({"ACTIVE", "COMMITTED"}),
        )
    ).all()
    return sum(
        int(item.requested_bytes)
        for item in reservations
        if (
            (item.status == "ACTIVE" and item.expires_at > now)
            or (
                item.status == "COMMITTED"
                and (
                    reconciled_through is None
                    or item.finalized_at is None
                    or item.finalized_at > reconciled_through
                )
            )
        )
    )


def _contracted_storage_bytes(session: Session, tenant_id: uuid.UUID) -> int | None:
    snapshot = resolve_contract_entitlements(session, tenant_id)
    if snapshot is None:
        return None
    limit_mb = snapshot.storage_entitlement.get("limit_mb")
    return int(limit_mb) * 1024 * 1024 if limit_mb is not None else None


def evaluate_storage_quota(
    *,
    contracted_bytes: int | None,
    measurement_status: MeasurementStatus,
    used_bytes: int | None,
    reserved_bytes: int,
    requested_bytes: int = 0,
    unavailable_reason: str = "O inventário de storage não está reconciliado.",
) -> QuotaEvaluation:
    if reserved_bytes < 0 or requested_bytes < 0 or (used_bytes is not None and used_bytes < 0):
        raise ValueError("Storage usage and requests must be non-negative")
    occupied = used_bytes + reserved_bytes if used_bytes is not None else None
    if contracted_bytes is None:
        return QuotaEvaluation(
            resource="STORAGE", contracted=None, occupied=occupied,
            requested=requested_bytes, remaining=None, decision=QuotaDecision.UNKNOWN,
            reason="Limite contratual de storage não informado; novas gravações são bloqueadas.",
        )
    if measurement_status != MeasurementStatus.RECONCILED or occupied is None:
        return QuotaEvaluation(
            resource="STORAGE", contracted=contracted_bytes, occupied=occupied,
            requested=requested_bytes, remaining=None, decision=QuotaDecision.UNKNOWN,
            reason=unavailable_reason,
        )
    remaining = max(contracted_bytes - occupied, 0)
    projected = occupied + requested_bytes
    if projected > contracted_bytes:
        decision = QuotaDecision.DENIED
        reason = (
            f"Quota de storage excedida: {occupied} byte(s) ocupados, "
            f"{requested_bytes} solicitado(s), teto {contracted_bytes}."
        )
    elif contracted_bytes and projected / contracted_bytes >= settings.STORAGE_TENANT_CRITICAL_PERCENT / 100:
        decision = QuotaDecision.WARNING
        reason = f"Uso projetado atingiu ao menos {settings.STORAGE_TENANT_CRITICAL_PERCENT}% da quota contratual de storage."
    elif contracted_bytes and projected / contracted_bytes >= settings.STORAGE_TENANT_WARNING_PERCENT / 100:
        decision = QuotaDecision.WARNING
        reason = f"Uso projetado atingiu ao menos {settings.STORAGE_TENANT_WARNING_PERCENT}% da quota contratual de storage."
    else:
        decision = QuotaDecision.ALLOWED
        reason = "Capacidade de storage reconciliada e disponível."
    return QuotaEvaluation(
        resource="STORAGE", contracted=contracted_bytes, occupied=occupied,
        requested=requested_bytes, remaining=remaining, decision=decision, reason=reason,
    )


def latest_provider_measurement(session: Session, *, lock: bool = False) -> StorageProviderMeasurement | None:
    query = (
        select(StorageProviderMeasurement)
        .where(StorageProviderMeasurement.provider == "SUPABASE")
        .order_by(StorageProviderMeasurement.measured_at.desc())
    )
    if lock:
        query = query.with_for_update()
    return session.exec(query).first()


def evaluate_provider_capacity(
    *, configured: bool, capacity_bytes: int | None, reserved_margin_bytes: int,
    measurement_status: str, used_bytes: int | None, reserved_bytes: int,
    requested_bytes: int = 0, unavailable_reason: str,
) -> QuotaEvaluation:
    """Evaluate the shared physical ceiling independently from tenant contracts."""

    usable = (
        max(capacity_bytes - reserved_margin_bytes, 0)
        if capacity_bytes is not None else None
    )
    occupied = used_bytes + reserved_bytes if used_bytes is not None else None
    if not configured or usable is None:
        return QuotaEvaluation(
            resource="STORAGE_PROVIDER", contracted=usable, occupied=occupied,
            requested=requested_bytes, remaining=None, decision=QuotaDecision.UNKNOWN,
            reason=unavailable_reason,
        )
    if measurement_status != "RECONCILED" or occupied is None:
        return QuotaEvaluation(
            resource="STORAGE_PROVIDER", contracted=usable, occupied=occupied,
            requested=requested_bytes, remaining=None, decision=QuotaDecision.UNKNOWN,
            reason=unavailable_reason,
        )
    remaining = max(usable - occupied, 0)
    projected = occupied + requested_bytes
    if projected > usable:
        decision = QuotaDecision.DENIED
        reason = "Capacidade física global do Storage seria excedida."
    elif usable and projected / usable >= settings.STORAGE_TENANT_CRITICAL_PERCENT / 100:
        decision = QuotaDecision.WARNING
        reason = "Capacidade física global atingiu o patamar crítico."
    elif usable and projected / usable >= settings.STORAGE_TENANT_WARNING_PERCENT / 100:
        decision = QuotaDecision.WARNING
        reason = "Capacidade física global atingiu o patamar preventivo."
    else:
        decision = QuotaDecision.ALLOWED
        reason = "Capacidade física compartilhada reconciliada."
    return QuotaEvaluation(
        resource="STORAGE_PROVIDER", contracted=usable, occupied=occupied,
        requested=requested_bytes, remaining=remaining, decision=decision, reason=reason,
    )


def _provider_capacity_state(
    session: Session, *, now: datetime, lock: bool
) -> dict[str, object]:
    now = now or datetime.utcnow()
    capacity = settings.SUPABASE_STORAGE_CAPACITY_BYTES
    margin = settings.SUPABASE_STORAGE_RESERVED_MARGIN_BYTES
    measurement = latest_provider_measurement(session, lock=lock)
    configured = settings.supabase_storage_configured
    status = "NOT_CONFIGURED" if not configured else "NOT_MEASURED"
    used: int | None = None
    reserved = 0
    measured_at: datetime | None = None
    object_count: int | None = None
    if measurement is not None:
        used = measurement.used_bytes
        measured_at = measurement.measured_at
        object_count = measurement.object_count
        if configured:
            fresh = now - measurement.measured_at <= timedelta(hours=settings.STORAGE_MEASUREMENT_MAX_AGE_HOURS)
            if measurement.status == "RECONCILED" and fresh:
                status = "RECONCILED"
                reserved = int(session.connection().execute(text(
                    "SELECT dashem_storage_reserved_after(:measured_at)"
                ), {"measured_at": measurement.measured_at}).scalar_one())
            elif not fresh:
                status = "UNAVAILABLE"
            else:
                status = measurement.status
    usable = max(capacity - margin, 0) if capacity is not None else None
    occupied = used + reserved if used is not None else None
    observable = configured and status == "RECONCILED" and occupied is not None
    return {
        "provider": "SUPABASE", "configured": configured, "capacity_bytes": capacity,
        "reserved_margin_bytes": margin, "used_bytes": used, "reserved_bytes": reserved,
        "occupied_bytes": occupied,
        "available_bytes": max(usable - occupied, 0) if observable and usable is not None else None,
        "object_count": object_count,
        "measurement_status": status,
        "measured_at": measured_at, "managed_buckets": list(settings.supabase_storage_buckets),
        "egress_measurement_status": "NOT_INSTRUMENTED",
    }


def provider_capacity_read_model(
    session: Session, *, now: datetime | None = None
) -> dict[str, object]:
    """Return observed provider facts without evaluating a future upload."""

    return _provider_capacity_state(
        session, now=now or datetime.utcnow(), lock=False
    )


def evaluate_platform_storage_capacity(
    session: Session,
    *,
    requested_bytes: int,
    now: datetime | None = None,
) -> tuple[dict[str, object], QuotaEvaluation]:
    """Evaluate one concrete upload against locked physical-capacity facts."""

    state = _provider_capacity_state(
        session, now=now or datetime.utcnow(), lock=True
    )
    status = str(state["measurement_status"])
    unavailable_reason = {
        "NOT_CONFIGURED": "Supabase Storage ou sua capacidade física não foram configurados.",
        "NOT_MEASURED": "A capacidade física ainda não possui inventário persistido.",
        "UNAVAILABLE": "O inventário físico global expirou.",
    }.get(status, "O inventário físico global não está reconciliado.")
    evaluation = evaluate_provider_capacity(
        configured=bool(state["configured"]),
        capacity_bytes=state["capacity_bytes"],
        reserved_margin_bytes=int(state["reserved_margin_bytes"]),
        measurement_status=status,
        used_bytes=state["used_bytes"],
        reserved_bytes=int(state["reserved_bytes"]),
        requested_bytes=requested_bytes,
        unavailable_reason=unavailable_reason,
    )
    return state, evaluation


def _storage_unavailable_reason(code: str) -> str:
    return {
        "NO_CONTRACT_QUOTA": "Limite contratual de storage não informado.",
        "NO_SOURCES": "Nenhuma fonte física de storage foi configurada para este tenant.",
        "NO_MEASUREMENT": "As fontes estão configuradas, mas ainda não existe inventário persistido.",
        "SOURCE_COVERAGE_MISMATCH": "O inventário não cobre exatamente todas as fontes ativas do tenant.",
        "ADAPTER_NOT_RECONCILED": "O adaptador não produziu um inventário reconciliado.",
        "SOURCES_CHANGED": "A configuração física mudou depois do inventário.",
        "MEASUREMENT_STALE": "A última medição reconciliada expirou.",
    }.get(code, "A medição de storage não está disponível para enforcement.")


def storage_quota_read_model(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return tenant storage facts without simulating a future write."""

    now = now or datetime.utcnow()
    sources = active_storage_sources(session, tenant_id)
    expected_source_keys = {item.source_key for item in sources}
    source_changed_at = max((item.updated_at for item in sources), default=None)
    measurement = latest_storage_measurement(session, tenant_id)
    contracted_bytes = _contracted_storage_bytes(session, tenant_id)

    status = MeasurementStatus.NOT_MEASURED
    used_bytes: int | None = None
    measured_at: datetime | None = None
    object_count: int | None = None
    watermark: str | None = None
    measurement_id: uuid.UUID | None = None
    measured_source_keys: set[str] = set()
    status_code = "NO_SOURCES"
    if sources and measurement is None:
        status_code = "NO_MEASUREMENT"
    elif sources and measurement is not None:
        measured_at = measurement.measured_at
        used_bytes = measurement.used_bytes
        object_count = measurement.object_count
        watermark = measurement.watermark
        measurement_id = measurement.id
        measured_sources = set(measurement.source_keys)
        measured_source_keys = measured_sources
        is_fresh = now - measurement.measured_at <= timedelta(
            hours=settings.STORAGE_MEASUREMENT_MAX_AGE_HOURS
        )
        if measured_sources != expected_source_keys:
            status = MeasurementStatus.PARTIAL
            status_code = "SOURCE_COVERAGE_MISMATCH"
        elif measurement.status != MeasurementStatus.RECONCILED.value:
            status = MeasurementStatus(measurement.status)
            status_code = "ADAPTER_NOT_RECONCILED"
        elif source_changed_at is not None and measurement.measured_at < source_changed_at:
            status = MeasurementStatus.UNAVAILABLE
            status_code = "SOURCES_CHANGED"
        elif not is_fresh:
            status = MeasurementStatus.UNAVAILABLE
            status_code = "MEASUREMENT_STALE"
        else:
            status = MeasurementStatus.RECONCILED
            status_code = "READY"

    reserved_bytes = _active_reserved_bytes(
        session,
        tenant_id,
        now=now,
        reconciled_through=measured_at if status == MeasurementStatus.RECONCILED else None,
    )

    if contracted_bytes is None:
        status_code = "NO_CONTRACT_QUOTA"

    return storage_quota_facts(
        contracted_bytes=contracted_bytes,
        measurement_status=status,
        used_bytes=used_bytes,
        reserved_bytes=reserved_bytes,
    ) | {
        "resource": "STORAGE",
        "object_count": object_count,
        "status_code": status_code,
        "measured_at": measured_at,
        "measurement_age_seconds": (
            max((now - measured_at).total_seconds(), 0) if measured_at else None
        ),
        "watermark": watermark,
        "measurement_id": measurement_id,
        "expected_source_keys": sorted(expected_source_keys),
        "measured_source_keys": sorted(measured_source_keys),
    }


def storage_quota_facts(
    *,
    contracted_bytes: int | None,
    measurement_status: MeasurementStatus,
    used_bytes: int | None,
    reserved_bytes: int,
) -> dict[str, object]:
    """Project observed storage facts without evaluating a future write."""

    occupied = used_bytes + reserved_bytes if used_bytes is not None else None
    quota_observable = (
        measurement_status == MeasurementStatus.RECONCILED and occupied is not None
    )
    available = (
        max(contracted_bytes - occupied, 0)
        if quota_observable and contracted_bytes is not None
        else None
    )
    overage = (
        max(occupied - contracted_bytes, 0)
        if quota_observable and contracted_bytes is not None
        else None
    )
    quota_status = (
        "UNKNOWN"
        if not quota_observable or contracted_bytes is None
        else "OVER_LIMIT"
        if occupied > contracted_bytes
        else "AT_LIMIT"
        if occupied == contracted_bytes
        else "WITHIN_LIMIT"
    )
    return {
        "contracted_bytes": contracted_bytes,
        "used_bytes": used_bytes,
        "reserved_bytes": reserved_bytes,
        "occupied_bytes": occupied,
        "available_bytes": available,
        "overage_bytes": overage,
        "quota_status": quota_status,
        "measurement_status": measurement_status.value,
        "enforcement_active": quota_observable and contracted_bytes is not None,
    }


def evaluate_tenant_storage_quota(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    requested_bytes: int,
    now: datetime | None = None,
) -> tuple[dict[str, object], QuotaEvaluation]:
    """Evaluate a concrete write against the latest observed facts."""

    state = storage_quota_read_model(session, tenant_id, now=now)
    status = MeasurementStatus(str(state["measurement_status"]))
    evaluation = evaluate_storage_quota(
        contracted_bytes=state["contracted_bytes"],
        measurement_status=status,
        used_bytes=state["used_bytes"],
        reserved_bytes=int(state["reserved_bytes"]),
        requested_bytes=requested_bytes,
        unavailable_reason=_storage_unavailable_reason(str(state["status_code"])),
    )
    return state, evaluation


def platform_storage_capacity_read_model(
    session: Session,
    *,
    offset: int = 0,
    limit: int = 50,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return physical capacity and paginated tenant observations as separate facts."""

    now = now or datetime.utcnow()
    provider = provider_capacity_read_model(session, now=now)
    contracts = list(
        session.exec(
            select(TenantContract).order_by(
                TenantContract.tenant_id, TenantContract.version.desc()
            )
        ).all()
    )
    latest_by_tenant: dict[uuid.UUID, TenantContract] = {}
    for contract in contracts:
        latest_by_tenant.setdefault(contract.tenant_id, contract)

    active_contracts = [
        contract for contract in latest_by_tenant.values() if contract.status == "ACTIVE"
    ]
    committed_bytes = 0
    for contract in active_contracts:
        limit_mb = contract.storage_entitlement.get("limit_mb")
        if limit_mb is None:
            limit_mb = contract.limits.get("storage_mb")
        if limit_mb is not None:
            committed_bytes += int(limit_mb) * 1024 * 1024

    tenants = list(session.exec(select(Tenant).order_by(Tenant.name)).all())
    page = tenants[offset : offset + limit]
    allocations: list[dict[str, object]] = []
    for tenant in page:
        contract = latest_by_tenant.get(tenant.id)
        state = storage_quota_read_model(session, tenant.id, now=now)
        allocations.append({
            "tenant_id": tenant.id,
            "tenant_name": tenant.name,
            "contract_id": contract.id if contract else None,
            "contract_version": contract.version if contract else None,
            "contracted_bytes": state["contracted_bytes"],
            "used_bytes": state["used_bytes"],
            "reserved_bytes": state["reserved_bytes"],
            "available_bytes": state["available_bytes"],
            "overage_bytes": state["overage_bytes"],
            "quota_status": state["quota_status"],
            "measurement_status": state["measurement_status"],
            "status_code": state["status_code"],
            "measured_at": state["measured_at"],
        })

    capacity = provider["capacity_bytes"]
    margin = int(provider["reserved_margin_bytes"])
    usable = max(int(capacity) - margin, 0) if capacity is not None else None
    return {
        "observed_at": now,
        "provider": provider["provider"],
        "configured": provider["configured"],
        "measurement_status": provider["measurement_status"],
        "measured_at": provider["measured_at"],
        "capacity_bytes": capacity,
        "reserved_margin_bytes": margin,
        "usable_capacity_bytes": usable,
        "used_bytes": provider["used_bytes"],
        "pending_reservation_bytes": provider["reserved_bytes"],
        "remaining_physical_bytes": provider["available_bytes"],
        "object_count": provider["object_count"],
        "managed_source_keys": provider["managed_buckets"],
        "egress_measurement_status": provider["egress_measurement_status"],
        "commercial_committed_bytes": committed_bytes,
        "active_contract_count": len(active_contracts),
        "commercial_commitment_ratio": (
            committed_bytes / usable if usable not in {None, 0} else None
        ),
        "total": len(tenants),
        "offset": offset,
        "limit": limit,
        "items": allocations,
    }


def reserve_storage_capacity(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    operation_key: str,
    requested_bytes: int,
    actor_id: uuid.UUID,
    bucket_id: str | None = None,
    object_path: str | None = None,
    now: datetime | None = None,
) -> StorageReservation:
    """Idempotently reserve bytes; UNKNOWN is denied, never treated as zero usage."""

    if requested_bytes < 1:
        raise ValueError("requested_bytes must be positive")
    if len(operation_key.strip()) < 4:
        raise ValueError("operation_key must be a stable non-empty identifier")
    now = now or datetime.utcnow()
    session.exec(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()).first()
    existing = session.exec(
        select(StorageReservation).where(
            StorageReservation.tenant_id == tenant_id,
            StorageReservation.operation_key == operation_key,
        )
    ).first()
    if existing:
        if existing.requested_bytes != requested_bytes:
            raise ValueError("operation_key already exists with different requested_bytes")
        if existing.status == "ACTIVE" and existing.expires_at <= now:
            raise ValueError("operation_key belongs to an expired reservation; use a new operation key")
        if existing.status not in {"ACTIVE", "COMMITTED"}:
            raise ValueError("operation_key belongs to a finalized reservation")
        if existing.bucket_id != bucket_id or existing.object_path != object_path:
            raise ValueError("operation_key already exists for a different storage object")
        return existing

    state, evaluation = evaluate_tenant_storage_quota(
        session, tenant_id, requested_bytes=requested_bytes, now=now
    )
    if evaluation.decision not in {QuotaDecision.ALLOWED, QuotaDecision.WARNING}:
        raise StorageCapacityUnavailableError(evaluation)
    _, provider_evaluation = evaluate_platform_storage_capacity(
        session, requested_bytes=requested_bytes, now=now
    )
    if provider_evaluation.decision not in {
        QuotaDecision.ALLOWED,
        QuotaDecision.WARNING,
    }:
        raise StorageCapacityUnavailableError(provider_evaluation)
    contract: TenantContract | None = latest_contract(session, tenant_id)
    measurement_id = state["measurement_id"]
    if contract is None or not isinstance(measurement_id, uuid.UUID):
        raise StorageCapacityUnavailableError(evaluation)
    reservation = StorageReservation(
        tenant_id=tenant_id,
        operation_key=operation_key.strip(),
        requested_bytes=requested_bytes,
        contract_id=contract.id,
        contract_version=contract.version,
        measurement_id=measurement_id,
        bucket_id=bucket_id,
        object_path=object_path,
        created_by=actor_id,
        expires_at=now + timedelta(minutes=settings.STORAGE_RESERVATION_TTL_MINUTES),
    )
    session.add(reservation)
    session.flush()
    return reservation


def finalize_storage_reservation(
    session: Session,
    reservation_id: uuid.UUID,
    *,
    committed: bool,
    reason: str,
    provider_reference: str | None = None,
    now: datetime | None = None,
) -> StorageReservation:
    """Commit or release a reservation; committed bytes remain occupied until metered."""

    if len(reason.strip()) < 4:
        raise ValueError("Storage reservation finalization requires a reason")
    reservation = session.exec(
        select(StorageReservation)
        .where(StorageReservation.id == reservation_id)
        .with_for_update()
    ).first()
    if reservation is None:
        raise ValueError("Storage reservation not found")
    target_status = "COMMITTED" if committed else "RELEASED"
    if reservation.status == target_status:
        return reservation
    if reservation.status != "ACTIVE":
        raise ValueError("Only an active storage reservation can be finalized")
    reservation.status = target_status
    reservation.finalized_at = now or datetime.utcnow()
    reservation.final_reason = reason.strip()
    reservation.provider_reference = provider_reference if committed else None
    session.add(reservation)
    session.flush()
    return reservation

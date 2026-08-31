"""Canonical storage meter, reconciliation policy and fail-closed reservations.

No route may claim storage enforcement merely because a contract has a number.
Enforcement becomes available only after all configured physical namespaces have
a fresh, append-only RECONCILED inventory measurement.
"""

import uuid
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.core.config import settings
from app.models.identity import Tenant
from app.models.platform import TenantContract
from app.models.storage import StorageMeasurement, StorageMeterSource, StorageReservation
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
    elif contracted_bytes and projected / contracted_bytes >= 0.8:
        decision = QuotaDecision.WARNING
        reason = "Uso projetado atingiu ao menos 80% da quota contratual de storage."
    else:
        decision = QuotaDecision.ALLOWED
        reason = "Capacidade de storage reconciliada e disponível."
    return QuotaEvaluation(
        resource="STORAGE", contracted=contracted_bytes, occupied=occupied,
        requested=requested_bytes, remaining=remaining, decision=decision, reason=reason,
    )


def storage_quota_read_model(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    requested_bytes: int = 0,
    now: datetime | None = None,
) -> dict[str, object]:
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
    reason = "Nenhuma fonte física de storage foi configurada para este tenant."
    if sources and measurement is None:
        reason = "As fontes estão configuradas, mas ainda não existe inventário persistido."
    elif sources and measurement is not None:
        measured_at = measurement.measured_at
        used_bytes = measurement.used_bytes
        object_count = measurement.object_count
        watermark = measurement.watermark
        measurement_id = measurement.id
        measured_sources = set(measurement.source_keys)
        is_fresh = now - measurement.measured_at <= timedelta(
            hours=settings.STORAGE_MEASUREMENT_MAX_AGE_HOURS
        )
        if measured_sources != expected_source_keys:
            status = MeasurementStatus.PARTIAL
            reason = "O inventário não cobre exatamente todas as fontes ativas do tenant."
        elif measurement.status != MeasurementStatus.RECONCILED.value:
            status = MeasurementStatus(measurement.status)
            reason = "O adaptador registrou o inventário sem reconciliação conclusiva."
        elif source_changed_at is not None and measurement.measured_at < source_changed_at:
            status = MeasurementStatus.UNAVAILABLE
            reason = "A configuração física mudou depois do inventário; uma nova reconciliação é obrigatória."
        elif not is_fresh:
            status = MeasurementStatus.UNAVAILABLE
            reason = "A última medição reconciliada expirou; novas gravações permanecem bloqueadas."
        else:
            status = MeasurementStatus.RECONCILED
            reason = "Inventário completo e recente; a quota pode ser aplicada."

    reserved_bytes = _active_reserved_bytes(
        session,
        tenant_id,
        now=now,
        reconciled_through=measured_at if status == MeasurementStatus.RECONCILED else None,
    )

    evaluation = evaluate_storage_quota(
        contracted_bytes=contracted_bytes,
        measurement_status=status,
        used_bytes=used_bytes,
        reserved_bytes=reserved_bytes,
        requested_bytes=requested_bytes,
        unavailable_reason=reason,
    )
    occupied = evaluation.occupied

    return {
        "resource": "STORAGE",
        "contracted_bytes": contracted_bytes,
        "used_bytes": used_bytes,
        "reserved_bytes": reserved_bytes,
        "occupied_bytes": occupied,
        "available_bytes": evaluation.remaining,
        "object_count": object_count,
        "measurement_status": status.value,
        "decision": evaluation.decision.value,
        "reason": evaluation.reason,
        "measured_at": measured_at,
        "watermark": watermark,
        "measurement_id": measurement_id,
        "source_keys": sorted(expected_source_keys),
        "enforcement_active": status == MeasurementStatus.RECONCILED,
    }


def reserve_storage_capacity(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    operation_key: str,
    requested_bytes: int,
    actor_id: uuid.UUID,
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
        return existing

    state = storage_quota_read_model(
        session, tenant_id, requested_bytes=requested_bytes, now=now
    )
    evaluation = QuotaEvaluation(
        resource="STORAGE",
        contracted=state["contracted_bytes"],
        occupied=state["occupied_bytes"],
        requested=requested_bytes,
        remaining=state["available_bytes"],
        decision=QuotaDecision(str(state["decision"])),
        reason=str(state["reason"]),
    )
    if evaluation.decision not in {QuotaDecision.ALLOWED, QuotaDecision.WARNING}:
        raise StorageCapacityUnavailableError(evaluation)
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
    session.add(reservation)
    session.flush()
    return reservation

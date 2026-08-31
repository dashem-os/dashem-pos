"""Canonical count-quota policy and operational usage read model.

Contract limits come exclusively from the immutable contract snapshot. Usage
comes from operational tenant records. Keeping both paths here prevents the UI
and mutation guards from interpreting quota state differently.
"""

import uuid
from datetime import datetime

from sqlmodel import Session, select

from app.models.device import OperationalDevice, OperationalDeviceStatusEnum
from app.models.identity import Membership, MembershipStatusEnum, Store, Tenant
from app.modules.governance.contracts import (
    CountResource,
    CountUsageSnapshot,
    QuotaDecision,
    QuotaEvaluation,
)
from app.services.contract_entitlement_service import contracted_limit


_CONTRACT_RESOURCE = {
    CountResource.USERS: "users",
    CountResource.DEVICES: "devices",
    CountResource.UNITS: "units",
}
_RESOURCE_LABEL = {
    CountResource.USERS: "usuários",
    CountResource.DEVICES: "dispositivos",
    CountResource.UNITS: "unidades",
}


class QuotaCapacityExceededError(ValueError):
    def __init__(self, evaluation: QuotaEvaluation):
        super().__init__(evaluation.reason)
        self.evaluation = evaluation


def count_usage_snapshot(
    session: Session,
    tenant_id: uuid.UUID,
    resource: CountResource,
) -> CountUsageSnapshot:
    measured_at = datetime.utcnow()
    if resource == CountResource.USERS:
        rows = session.exec(
            select(Membership.user_id, Membership.status).where(
                Membership.tenant_id == tenant_id,
                Membership.status.in_(
                    {MembershipStatusEnum.ACTIVE, MembershipStatusEnum.INVITED}
                ),
            )
        ).all()
        active_users = {
            user_id
            for user_id, status in rows
            if status == MembershipStatusEnum.ACTIVE
        }
        invited_users = {
            user_id
            for user_id, status in rows
            if status == MembershipStatusEnum.INVITED and user_id not in active_users
        }
        configured = len(active_users)
        reserved = len(invited_users)
    elif resource == CountResource.DEVICES:
        configured = len(
            session.exec(
                select(OperationalDevice.id).where(
                    OperationalDevice.tenant_id == tenant_id,
                    OperationalDevice.status != OperationalDeviceStatusEnum.REVOKED,
                )
            ).all()
        )
        reserved = 0
    elif resource == CountResource.UNITS:
        configured = len(
            session.exec(
                select(Store.id).where(
                    Store.tenant_id == tenant_id,
                    Store.is_active == True,  # noqa: E712
                )
            ).all()
        )
        reserved = 0
    else:  # pragma: no cover - defensive for future enum members
        raise ValueError(f"Unsupported count resource: {resource}")
    return CountUsageSnapshot(
        tenant_id=tenant_id,
        resource=resource,
        configured=configured,
        reserved=reserved,
        observed=configured,
        measured_at=measured_at,
    )


def evaluate_count_quota(
    *,
    resource: CountResource,
    contracted: int | None,
    usage: CountUsageSnapshot,
    requested: int = 0,
    warning_ratio: float = 0.8,
) -> QuotaEvaluation:
    if requested < 0:
        raise ValueError("requested must be non-negative")
    occupied_after_request = usage.occupied + requested
    if contracted is None:
        return QuotaEvaluation(
            resource=resource.value,
            contracted=None,
            occupied=usage.occupied,
            requested=requested,
            remaining=None,
            decision=QuotaDecision.UNKNOWN,
            reason="Quota contratual não informada; não há teto verificável.",
        )
    remaining = max(contracted - usage.occupied, 0)
    if occupied_after_request > contracted:
        decision = QuotaDecision.DENIED
        reason = (
            f"Limite contratual de {_RESOURCE_LABEL[resource]} excedido: "
            f"{usage.occupied} ocupado(s), {requested} solicitado(s), teto {contracted}."
        )
    elif contracted > 0 and occupied_after_request / contracted >= warning_ratio:
        decision = QuotaDecision.WARNING
        reason = (
            f"Quota preventiva: {occupied_after_request} de {contracted} "
            f"{_RESOURCE_LABEL[resource]} ocupados após esta operação."
        )
    else:
        decision = QuotaDecision.ALLOWED
        reason = "Capacidade contratual disponível."
    return QuotaEvaluation(
        resource=resource.value,
        contracted=contracted,
        occupied=usage.occupied,
        requested=requested,
        remaining=remaining,
        decision=decision,
        reason=reason,
    )


def evaluate_tenant_count_quota(
    session: Session,
    tenant_id: uuid.UUID,
    resource: CountResource,
    *,
    requested: int = 0,
) -> tuple[CountUsageSnapshot, QuotaEvaluation]:
    usage = count_usage_snapshot(session, tenant_id, resource)
    limit = contracted_limit(session, tenant_id, _CONTRACT_RESOURCE[resource])
    return usage, evaluate_count_quota(
        resource=resource,
        contracted=limit,
        usage=usage,
        requested=requested,
    )


def require_count_capacity(
    session: Session,
    tenant_id: uuid.UUID,
    resource: CountResource,
    *,
    requested: int = 1,
) -> QuotaEvaluation:
    # Serialize competing capacity mutations for the same tenant. Without this
    # lock, two requests could both observe the last available slot.
    session.exec(
        select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
    ).first()
    _, evaluation = evaluate_tenant_count_quota(
        session, tenant_id, resource, requested=requested
    )
    if evaluation.decision == QuotaDecision.DENIED:
        raise QuotaCapacityExceededError(evaluation)
    return evaluation


def tenant_count_quota_read_model(
    session: Session, tenant_id: uuid.UUID
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for resource in CountResource:
        usage, evaluation = evaluate_tenant_count_quota(
            session, tenant_id, resource, requested=0
        )
        result[resource.value] = {
            "resource": resource.value,
            "contracted": evaluation.contracted,
            "configured": usage.configured,
            "reserved": usage.reserved,
            "occupied": usage.occupied,
            "available": evaluation.remaining,
            "decision": evaluation.decision.value,
            "reason": evaluation.reason,
            "measured_at": usage.measured_at,
        }
    return result

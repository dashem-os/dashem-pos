import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import (
    CapabilitySelectionMode,
    ContractDiscountReason,
    ContractDiscountType,
    FINANCE_MANAGE_BILLING,
    OwnerBillingCreate,
    OwnerContractDiscount,
    OwnerQuotaCreate,
    PLATFORM_MANAGERS,
    OwnerTenantContractUpdate,
    _contract_offer,
    _apply_owner_tenant_contract,
)
from app.core.access import require_platform_permission, require_platform_role
from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.core.security import AuthPrincipal, get_current_principal
from app.models.commercial_catalog import CommercialActivity, CommercialActivityCapability
from app.models.identity import RoleEnum, ServicePlan, SubscriptionStatusEnum, Tenant, TenantSubscription, User
from app.models.owner_finance import SaasBillingAccount
from app.models.platform import (
    CommercialChangeDecisionRecord,
    CommercialChangeRequestRecord,
    TenantContract,
)
from app.modules.capabilities.registry import CAPABILITY_REGISTRY, IMPLEMENTED_CAPABILITIES
from app.modules.governance.contracts import CommercialChangeKind, OwnerDecisionKind
from app.services import reliability_service
from app.services.contract_entitlement_service import latest_contract


router = APIRouter()
TENANT_REQUEST_ROLES = {RoleEnum.OWNER, RoleEnum.TENANT_OWNER, RoleEnum.ADMIN}


class CommercialChangeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CommercialChangeKind
    payload: dict[str, Any]
    reason: str = PydanticField(min_length=4, max_length=500)


class CommercialDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: OwnerDecisionKind
    reason: str = PydanticField(min_length=4, max_length=500)


class CommercialDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    decision: str
    reason: str
    decided_by: uuid.UUID
    resulting_contract_id: Optional[uuid.UUID] = None
    decided_at: datetime


class CommercialChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: Optional[str] = None
    kind: str
    payload: dict[str, Any]
    reason: str
    requested_by: uuid.UUID
    source_contract_id: uuid.UUID
    source_contract_version: int
    status: str
    requested_at: datetime
    decided_at: Optional[datetime] = None
    decision: Optional[CommercialDecisionRead] = None


def _validated_payload(
    session: Session,
    contract: TenantContract,
    kind: CommercialChangeKind,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if kind == CommercialChangeKind.ACTIVITY:
        key = str(payload.get("activity_key", "")).strip().upper()
        activity = session.get(CommercialActivity, key)
        if not activity or activity.status != "ACTIVE":
            raise HTTPException(status_code=422, detail="Atividade comercial inexistente ou inativa.")
        if key in contract.activity_keys:
            raise HTTPException(status_code=409, detail="A atividade já está contratada.")
        plan = session.get(ServicePlan, contract.plan_id) if contract.plan_id else None
        if plan and key not in plan.activity_keys:
            raise HTTPException(status_code=422, detail="A atividade não é compatível com o plano atual.")
        return {"activity_key": key, "action": "ADD"}

    if kind in {CommercialChangeKind.CAPABILITY, CommercialChangeKind.INTEGRATION}:
        key = str(payload.get("capability_key", "")).strip().lower()
        if key not in CAPABILITY_REGISTRY or key not in IMPLEMENTED_CAPABILITIES:
            raise HTTPException(status_code=422, detail="Capability inexistente ou ainda não executável.")
        if key in contract.capability_keys:
            raise HTTPException(status_code=409, detail="A capability já está contratada.")
        allowed = session.exec(
            select(CommercialActivityCapability.capability_key).where(
                CommercialActivityCapability.activity_key.in_(contract.activity_keys),
                CommercialActivityCapability.capability_key == key,
                CommercialActivityCapability.role == "OPTIONAL",
            )
        ).first()
        if not allowed:
            raise HTTPException(
                status_code=422,
                detail="A capability não é um add-on das atividades atualmente contratadas.",
            )
        return {"capability_key": key, "action": "ENABLE"}

    field_by_kind = {
        CommercialChangeKind.USER_LIMIT: "users",
        CommercialChangeKind.DEVICE_LIMIT: "devices",
        CommercialChangeKind.UNIT_LIMIT: "units",
        CommercialChangeKind.STORAGE_LIMIT: "storage_mb",
    }
    field = field_by_kind[kind]
    requested = payload.get("requested_limit")
    if not isinstance(requested, int) or isinstance(requested, bool) or requested < 1:
        raise HTTPException(status_code=422, detail="Informe requested_limit como inteiro positivo.")
    current = int(contract.limits.get(field) or 0)
    if requested <= current:
        raise HTTPException(
            status_code=422,
            detail=f"O novo limite deve ser maior que o valor contratado ({current}).",
        )
    plan = session.get(ServicePlan, contract.plan_id) if contract.plan_id else None
    ceiling_by_field = {
        "users": plan.user_limit if plan else None,
        "devices": plan.terminal_limit if plan else None,
        "units": plan.store_limit if plan else None,
        "storage_mb": plan.storage_limit_mb if plan else None,
    }
    ceiling = ceiling_by_field[field]
    if ceiling is not None and requested > int(ceiling):
        raise HTTPException(
            status_code=422,
            detail=(
                f"O limite solicitado excede o teto do plano atual ({ceiling}). "
                "A troca de plano deve ser tratada pelo Owner antes desta ampliação."
            ),
        )
    return {"resource": field, "requested_limit": requested}


def _view(
    request: CommercialChangeRequestRecord,
    *,
    tenant_name: Optional[str],
    decision: Optional[CommercialChangeDecisionRecord],
) -> CommercialChangeRead:
    return CommercialChangeRead(
        **request.model_dump(),
        tenant_name=tenant_name,
        decision=CommercialDecisionRead.model_validate(decision) if decision else None,
    )


def _request_views(
    session: Session, requests: list[CommercialChangeRequestRecord]
) -> list[CommercialChangeRead]:
    request_ids = [item.id for item in requests]
    decisions = {
        item.request_id: item
        for item in session.exec(
            select(CommercialChangeDecisionRecord).where(
                CommercialChangeDecisionRecord.request_id.in_(request_ids)
            )
        ).all()
    } if request_ids else {}
    tenant_ids = {item.tenant_id for item in requests}
    tenants = {
        item.id: item.name
        for item in session.exec(select(Tenant).where(Tenant.id.in_(tenant_ids))).all()
    } if tenant_ids else {}
    return [
        _view(item, tenant_name=tenants.get(item.tenant_id), decision=decisions.get(item.id))
        for item in requests
    ]


@router.get("", response_model=list[CommercialChangeRead])
def list_tenant_commercial_requests(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    requests = session.exec(
        select(CommercialChangeRequestRecord)
        .where(CommercialChangeRequestRecord.tenant_id == context.tenant_id)
        .order_by(CommercialChangeRequestRecord.requested_at.desc())
    ).all()
    return _request_views(session, list(requests))


@router.post("", response_model=CommercialChangeRead, status_code=201)
def create_tenant_commercial_request(
    data: CommercialChangeCreate,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    if context.role not in TENANT_REQUEST_ROLES or context.user_id is None:
        raise HTTPException(status_code=403, detail="Somente um administrador do tenant pode solicitar alteração comercial.")
    session.exec(
        select(Tenant.id).where(Tenant.id == context.tenant_id).with_for_update()
    ).first()
    contract = latest_contract(session, context.tenant_id)
    if contract is None:
        raise HTTPException(status_code=409, detail="Não existe contrato vigente para receber uma solicitação.")
    payload = _validated_payload(session, contract, data.kind, data.payload)
    pending_same_kind = session.exec(
        select(CommercialChangeRequestRecord).where(
            CommercialChangeRequestRecord.tenant_id == context.tenant_id,
            CommercialChangeRequestRecord.kind == data.kind.value,
            CommercialChangeRequestRecord.status == "PENDING",
        )
    ).all()
    duplicate = next((item for item in pending_same_kind if item.payload == payload), None)
    if duplicate:
        raise HTTPException(status_code=409, detail="Já existe uma solicitação pendente igual.")
    request = CommercialChangeRequestRecord(
        tenant_id=context.tenant_id,
        kind=data.kind.value,
        payload=payload,
        reason=data.reason.strip(),
        requested_by=context.user_id,
        source_contract_id=contract.id,
        source_contract_version=contract.version,
    )
    session.add(request)
    session.flush()
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=None,
        actor_id=context.user_id,
        action="tenant.commercial_change.requested",
        target=f"commercial_request:{request.id}",
        audit_payload={"request_id": str(request.id), "kind": request.kind, "payload": payload},
        aggregate_type="commercial_change_request",
        aggregate_id=str(request.id),
        event_type="tenant.commercial_change.requested",
        outbox_payload={"request_id": str(request.id), "tenant_id": str(context.tenant_id)},
    )
    session.commit()
    session.refresh(request)
    return _view(request, tenant_name=None, decision=None)


@router.get("/catalog")
def tenant_commercial_request_catalog(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    contract = latest_contract(session, context.tenant_id)
    if contract is None:
        raise HTTPException(status_code=409, detail="Não existe contrato vigente para consultar expansões.")
    plan = session.get(ServicePlan, contract.plan_id) if contract.plan_id else None
    activities = session.exec(
        select(CommercialActivity)
        .where(CommercialActivity.status == "ACTIVE")
        .order_by(CommercialActivity.name)
    ).all()
    plan_activity_keys = set(plan.activity_keys if plan else [])
    plan_capability_keys = set(plan.capability_keys if plan else [])
    optional_capabilities = set(session.exec(
        select(CommercialActivityCapability.capability_key).where(
            CommercialActivityCapability.activity_key.in_(contract.activity_keys),
            CommercialActivityCapability.role == "OPTIONAL",
        )
    ).all())
    return {
        "contract_version": contract.version,
        "activities": [
            {"key": item.key, "name": item.name, "description": item.description}
            for item in activities
            if item.key in plan_activity_keys and item.key not in contract.activity_keys
        ],
        "capabilities": [
            {
                "key": key,
                "name": CAPABILITY_REGISTRY[key].name,
                "description": CAPABILITY_REGISTRY[key].description,
            }
            for key in sorted(plan_capability_keys & optional_capabilities - set(contract.capability_keys))
            if key in CAPABILITY_REGISTRY and key in IMPLEMENTED_CAPABILITIES
        ],
        "contracted_limits": {
            key: contract.limits.get(key)
            for key in ("users", "devices", "units", "storage_mb")
        },
        "plan_limits": {
            "users": plan.user_limit if plan else None,
            "devices": plan.terminal_limit if plan else None,
            "units": plan.store_limit if plan else None,
            "storage_mb": plan.storage_limit_mb if plan else None,
        },
    }


@router.get("/platform", response_model=list[CommercialChangeRead])
def list_platform_commercial_requests(
    tenant_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    query = select(CommercialChangeRequestRecord)
    if tenant_id:
        query = query.where(CommercialChangeRequestRecord.tenant_id == tenant_id)
    if status:
        normalized = status.strip().upper()
        if normalized not in {"PENDING", "APPROVED", "DECLINED", "CANCELED"}:
            raise HTTPException(status_code=422, detail="Status de solicitação inválido.")
        query = query.where(CommercialChangeRequestRecord.status == normalized)
    requests = session.exec(query.order_by(CommercialChangeRequestRecord.requested_at.desc())).all()
    return _request_views(session, list(requests))


def _assert_request_applied(
    request: CommercialChangeRequestRecord, contract: TenantContract
) -> None:
    kind = CommercialChangeKind(request.kind)
    payload = request.payload
    if kind == CommercialChangeKind.ACTIVITY:
        applied = payload["activity_key"] in contract.activity_keys
    elif kind in {CommercialChangeKind.CAPABILITY, CommercialChangeKind.INTEGRATION}:
        applied = payload["capability_key"] in contract.capability_keys
    else:
        applied = int(contract.limits.get(payload["resource"]) or 0) >= int(payload["requested_limit"])
    if not applied:
        raise HTTPException(
            status_code=422,
            detail="A nova versão contratual não aplica integralmente a solicitação aprovada.",
        )


def _approval_contract_update(
    session: Session,
    request: CommercialChangeRequestRecord,
    reason: str,
) -> OwnerTenantContractUpdate:
    current = latest_contract(session, request.tenant_id)
    if current is None or current.id != request.source_contract_id:
        raise HTTPException(
            status_code=409,
            detail="O contrato mudou desde a solicitação. Recuse-a e peça uma nova solicitação sobre a versão atual.",
        )
    plan = session.get(ServicePlan, current.plan_id) if current.plan_id else None
    subscription = session.get(TenantSubscription, request.tenant_id)
    account = session.exec(
        select(SaasBillingAccount).where(SaasBillingAccount.tenant_id == request.tenant_id)
    ).first()
    if (
        not plan
        or not subscription
        or subscription.billing_day is None
        or not account
        or not account.contact_name
        or not account.contact_email
    ):
        raise HTTPException(
            status_code=409,
            detail="Plano, assinatura, vencimento persistido e conta de cobrança são obrigatórios para aprovar.",
        )

    activities = list(current.activity_keys)
    requested_keys = set(current.capability_keys)
    quotas = {
        "users": int(current.limits["users"]),
        "devices": int(current.limits["devices"]),
        "units": int(current.limits["units"]),
        "storage_mb": int(current.limits["storage_mb"]),
    }
    kind = CommercialChangeKind(request.kind)
    if kind == CommercialChangeKind.ACTIVITY:
        activities.append(str(request.payload["activity_key"]))
    elif kind in {CommercialChangeKind.CAPABILITY, CommercialChangeKind.INTEGRATION}:
        requested_keys.add(str(request.payload["capability_key"]))
    else:
        quotas[str(request.payload["resource"])] = int(request.payload["requested_limit"])

    base = _contract_offer(
        session,
        plan=plan,
        activity_keys=activities,
        capability_keys=[],
        selection_mode=CapabilitySelectionMode.OFFER_DEFAULT,
    )
    requested_keys.update(base["capability_keys"])
    resolved = _contract_offer(
        session,
        plan=plan,
        activity_keys=activities,
        capability_keys=sorted(requested_keys),
        selection_mode=CapabilitySelectionMode.EXPLICIT,
    )

    discount = None
    if subscription.discount_type and subscription.discount_value > 0:
        discount = OwnerContractDiscount(
            type=ContractDiscountType(subscription.discount_type),
            value=subscription.discount_value,
            reason_code=ContractDiscountReason(
                subscription.discount_reason_code or "COMMERCIAL_NEGOTIATION"
            ),
            reason=subscription.discount_reason or "Condição comercial vigente preservada.",
            starts_on=subscription.discount_starts_on,
            ends_on=subscription.discount_ends_on,
            review_on=subscription.discount_review_on,
        )
    return OwnerTenantContractUpdate(
        plan_id=plan.id,
        niches=activities,
        capability_keys=list(resolved["capability_keys"]),
        capability_selection_mode=CapabilitySelectionMode.EXPLICIT,
        quotas=OwnerQuotaCreate(**quotas),
        billing=OwnerBillingCreate(
            contact_name=account.contact_name,
            email=account.contact_email,
            phone=account.contact_phone,
            monthly_amount=subscription.gross_monthly_amount,
            billing_day=subscription.billing_day,
            discount=discount,
        ),
        subscription_status=SubscriptionStatusEnum(subscription.status),
        expected_contract_version=current.version,
        expected_billing_account_version=account.version,
        reason=reason,
    )


@router.post("/platform/{request_id}/decision", response_model=CommercialChangeRead)
def decide_platform_commercial_request(
    request_id: uuid.UUID,
    data: CommercialDecisionCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_permission(
        session, principal, FINANCE_MANAGE_BILLING, require_aal2=True
    )
    assert actor is not None
    request = session.exec(
        select(CommercialChangeRequestRecord)
        .where(CommercialChangeRequestRecord.id == request_id)
        .with_for_update()
    ).first()
    if request is None:
        raise HTTPException(status_code=404, detail="Solicitação comercial não encontrada.")
    if request.status != "PENDING":
        raise HTTPException(status_code=409, detail="A solicitação já possui uma decisão.")

    resulting_contract: Optional[TenantContract] = None
    if data.decision == OwnerDecisionKind.APPROVE:
        contract_update = _approval_contract_update(session, request, data.reason.strip())
        resulting_contract = _apply_owner_tenant_contract(
            session, request.tenant_id, contract_update, actor
        )
        _assert_request_applied(request, resulting_contract)
        request.status = "APPROVED"
    else:
        request.status = "DECLINED"

    now = datetime.utcnow()
    request.decided_at = now
    decision = CommercialChangeDecisionRecord(
        request_id=request.id,
        tenant_id=request.tenant_id,
        decision=data.decision.value,
        reason=data.reason.strip(),
        decided_by=actor.id,
        resulting_contract_id=resulting_contract.id if resulting_contract else None,
        decided_at=now,
    )
    session.add(request)
    session.add(decision)
    session.flush()
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=request.tenant_id,
        store_id=None,
        actor_id=actor.id,
        action="platform.commercial_change.decided",
        target=f"commercial_request:{request.id}",
        audit_payload={
            "request_id": str(request.id),
            "decision": decision.decision,
            "reason": decision.reason,
            "resulting_contract_id": str(resulting_contract.id) if resulting_contract else None,
        },
        aggregate_type="commercial_change_request",
        aggregate_id=str(request.id),
        event_type="platform.commercial_change.decided",
        outbox_payload={"request_id": str(request.id), "decision": decision.decision},
    )
    session.commit()
    session.refresh(request)
    session.refresh(decision)
    tenant = session.get(Tenant, request.tenant_id)
    return _view(request, tenant_name=tenant.name if tenant else None, decision=decision)

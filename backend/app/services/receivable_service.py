import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.context import TenantContext, scope_tenant_query
from app.models.negotiation import CheckoutNegotiation, CheckoutNegotiationStatusEnum
from app.models.receivable import (
    CreditPolicyStatusEnum, CustomerCreditPolicy, Receivable,
    ReceivableAllocation, ReceivableEntryTypeEnum, ReceivableLedgerEntry,
    ReceivableStatusEnum,
)
from app.models.sale import Customer
from app.services import negotiation_service, reliability_service


MONEY = Decimal("0.0001")
EXPOSURE_STATUSES = {
    ReceivableStatusEnum.OPEN,
    ReceivableStatusEnum.PARTIALLY_PAID,
    ReceivableStatusEnum.OVERDUE,
}


def _money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _actor(context: TenantContext, actor_id: Optional[uuid.UUID]) -> uuid.UUID:
    return actor_id or context.user_id or uuid.UUID("00000000-0000-0000-0000-000000000000")


def _write_event(
    session: Session, receivable: Receivable, actor_id: uuid.UUID,
    action: str, payload: dict,
) -> None:
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=receivable.tenant_id, store_id=receivable.store_id,
        actor_id=actor_id, action=action, target=f"RECEIVABLE-{receivable.id}",
        audit_payload=payload, aggregate_type="receivable", aggregate_id=str(receivable.id),
        event_type=action, outbox_payload={
            "tenant_id": str(receivable.tenant_id), "store_id": str(receivable.store_id),
            "receivable_id": str(receivable.id), **payload,
        },
    )


def credit_exposure(session: Session, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> Decimal:
    amount = session.exec(select(func.coalesce(func.sum(Receivable.balance), 0)).where(
        Receivable.tenant_id == tenant_id,
        Receivable.customer_id == customer_id,
        Receivable.status.in_(list(EXPOSURE_STATUSES)),
    )).one()
    return _money(amount)


def upsert_policy(
    session: Session, context: TenantContext, *, customer_id: uuid.UUID,
    credit_limit: Decimal, terms_days: int, allow_overdue: bool,
    status: CreditPolicyStatusEnum, actor_id: Optional[uuid.UUID], expected_version: Optional[int],
) -> CustomerCreditPolicy:
    customer = session.exec(scope_tenant_query(
        select(Customer).where(Customer.id == customer_id), Customer, context,
    )).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado neste tenant.")
    policy = session.exec(select(CustomerCreditPolicy).where(
        CustomerCreditPolicy.tenant_id == context.tenant_id,
        CustomerCreditPolicy.customer_id == customer_id,
    ).with_for_update()).first()
    actor = _actor(context, actor_id)
    if policy:
        if expected_version is None or policy.version != expected_version:
            raise HTTPException(status_code=409, detail="Política de crédito foi alterada por outra operação.")
        policy.credit_limit = _money(credit_limit)
        policy.terms_days = terms_days
        policy.allow_overdue = allow_overdue
        policy.status = status
        policy.version += 1
        policy.updated_by = actor
        policy.updated_at = datetime.utcnow()
    else:
        if expected_version not in (None, 0):
            raise HTTPException(status_code=409, detail="A política de crédito ainda não existe.")
        policy = CustomerCreditPolicy(
            tenant_id=context.tenant_id, customer_id=customer_id,
            credit_limit=_money(credit_limit), terms_days=terms_days,
            allow_overdue=allow_overdue, status=status, updated_by=actor,
        )
        session.add(policy)
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=context.store_id,
        actor_id=actor, action="credit.policy.updated", target=f"CUSTOMER-{customer_id}",
        audit_payload={"credit_limit": str(policy.credit_limit), "terms_days": terms_days,
                       "allow_overdue": allow_overdue, "status": status.value, "version": policy.version},
        aggregate_type="customer_credit_policy", aggregate_id=str(policy.id),
        event_type="credit.policy.updated", outbox_payload={"customer_id": str(customer_id), "version": policy.version},
    )
    session.commit()
    session.refresh(policy)
    return policy


def policy_projection(session: Session, context: TenantContext, customer_id: uuid.UUID) -> dict:
    policy = session.exec(select(CustomerCreditPolicy).where(
        CustomerCreditPolicy.tenant_id == context.tenant_id,
        CustomerCreditPolicy.customer_id == customer_id,
    )).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Política de crédito não configurada.")
    exposure = credit_exposure(session, context.tenant_id, customer_id)
    return {"policy": policy, "exposure": exposure, "available": max(Decimal("0"), _money(policy.credit_limit - exposure))}


def issue_and_finalize(
    session: Session, context: TenantContext, negotiation_id: uuid.UUID, *,
    customer_id: uuid.UUID, expected_version: int, due_at: Optional[datetime],
    reason: str, actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> Receivable:
    actor = _actor(context, actor_id)
    payload = {
        "negotiation_id": str(negotiation_id), "customer_id": str(customer_id),
        "expected_version": expected_version, "due_at": due_at.isoformat() if due_at else None,
        "reason": reason, "actor_id": str(actor),
    }
    request_hash = reliability_service.compute_request_hash(payload)
    existing = session.exec(select(Receivable).where(
        Receivable.tenant_id == context.tenant_id,
        Receivable.issue_idempotency_key == idempotency_key,
    )).first()
    if existing:
        if existing.issue_request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency-Key reutilizada com comando diferente.")
        return existing

    policy = session.exec(select(CustomerCreditPolicy).where(
        CustomerCreditPolicy.tenant_id == context.tenant_id,
        CustomerCreditPolicy.customer_id == customer_id,
    ).with_for_update()).first()
    if not policy or policy.status != CreditPolicyStatusEnum.ACTIVE:
        raise HTTPException(status_code=409, detail="Cliente sem política de crédito ativa.")
    customer = session.exec(scope_tenant_query(
        select(Customer).where(Customer.id == customer_id), Customer, context,
    )).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado neste tenant.")
    if not policy.allow_overdue:
        overdue = session.exec(select(Receivable.id).where(
            Receivable.tenant_id == context.tenant_id,
            Receivable.customer_id == customer_id,
            Receivable.balance > 0,
            Receivable.due_at < datetime.utcnow(),
            Receivable.status.in_(list(EXPOSURE_STATUSES)),
        ).limit(1)).first()
        if overdue:
            raise HTTPException(status_code=409, detail="Cliente possui título vencido e a política bloqueia novo crédito.")

    negotiation = session.exec(scope_tenant_query(select(CheckoutNegotiation).where(
        CheckoutNegotiation.id == negotiation_id,
    ).with_for_update(), CheckoutNegotiation, context)).first()
    if not negotiation:
        raise HTTPException(status_code=404, detail="Negociação não encontrada neste contexto.")
    if negotiation.version != expected_version:
        raise HTTPException(status_code=409, detail="Versão da negociação desatualizada.")
    if negotiation.status not in {
        CheckoutNegotiationStatusEnum.OPEN, CheckoutNegotiationStatusEnum.PARTIALLY_COVERED,
    }:
        raise HTTPException(status_code=409, detail="Negociação não aceita conversão em crediário.")
    negotiation_service._validate_source(session, negotiation)
    totals = negotiation_service._totals(session, negotiation)
    amount = _money(totals["remaining_amount"] - totals["processing_amount"])
    if amount <= 0:
        raise HTTPException(status_code=409, detail="Não há saldo disponível para crediário.")
    exposure = credit_exposure(session, context.tenant_id, customer_id)
    if _money(exposure + amount) > _money(policy.credit_limit):
        raise HTTPException(
            status_code=409,
            detail=f"Limite insuficiente. Exposição {exposure}; disponível {_money(policy.credit_limit - exposure)}.",
        )
    effective_due = due_at or datetime.utcnow() + timedelta(days=policy.terms_days)
    if effective_due < datetime.utcnow():
        raise HTTPException(status_code=422, detail="Vencimento não pode estar no passado.")
    receivable = Receivable(
        tenant_id=context.tenant_id, store_id=negotiation.store_id,
        customer_id=customer_id, negotiation_id=negotiation.id,
        principal_amount=amount, balance=amount, due_at=effective_due,
        issue_idempotency_key=idempotency_key, issue_request_hash=request_hash,
        created_by=actor,
    )
    session.add(receivable)
    session.flush()
    session.add(ReceivableAllocation(
        tenant_id=context.tenant_id, negotiation_id=negotiation.id,
        receivable_id=receivable.id, amount=amount,
    ))
    session.add(ReceivableLedgerEntry(
        tenant_id=context.tenant_id, store_id=negotiation.store_id,
        receivable_id=receivable.id, entry_type=ReceivableEntryTypeEnum.ISSUE,
        amount=amount, balance_after=amount, actor_id=actor, reason=reason,
        idempotency_key=f"{idempotency_key}:issue",
        metadata_payload={"negotiation_id": str(negotiation.id), "customer_id": str(customer_id)},
    ))
    negotiation.status = CheckoutNegotiationStatusEnum.COVERED
    negotiation.version += 1
    negotiation.updated_at = datetime.utcnow()
    _write_event(session, receivable, actor, "receivable.issued", {
        "customer_id": str(customer_id), "negotiation_id": str(negotiation.id),
        "principal_amount": str(amount), "due_at": effective_due.isoformat(),
        "credit_exposure_after": str(_money(exposure + amount)), "reason": reason,
    })
    try:
        negotiation_service.finalize_negotiation(
            session, context, negotiation.id, expected_version=negotiation.version,
            actor_id=actor, idempotency_key=f"{idempotency_key}:finalize", commit=False,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="O limite ou a negociação foram consumidos por outra operação.") from exc
    session.refresh(receivable)
    return receivable


def list_receivables(
    session: Session, context: TenantContext, *, customer_id: Optional[uuid.UUID] = None,
    status_filter: Optional[ReceivableStatusEnum] = None, limit: int = 100,
) -> list[Receivable]:
    query = select(Receivable).where(Receivable.tenant_id == context.tenant_id)
    if context.store_id:
        query = query.where(Receivable.store_id == context.store_id)
    if customer_id:
        query = query.where(Receivable.customer_id == customer_id)
    if status_filter:
        query = query.where(Receivable.status == status_filter)
    return list(session.exec(query.order_by(Receivable.due_at, Receivable.issued_at).limit(limit)).all())


def reverse(
    session: Session, context: TenantContext, receivable_id: uuid.UUID, *,
    reason: str, actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> Receivable:
    actor = _actor(context, actor_id)
    existing_entry = session.exec(select(ReceivableLedgerEntry).where(
        ReceivableLedgerEntry.tenant_id == context.tenant_id,
        ReceivableLedgerEntry.idempotency_key == idempotency_key,
    )).first()
    if existing_entry:
        existing = session.get(Receivable, existing_entry.receivable_id)
        if not existing or existing.id != receivable_id:
            raise HTTPException(status_code=409, detail="Idempotency-Key reutilizada em outro título.")
        return existing
    receivable = session.exec(scope_tenant_query(select(Receivable).where(
        Receivable.id == receivable_id,
    ).with_for_update(), Receivable, context)).first()
    if not receivable:
        raise HTTPException(status_code=404, detail="Título não encontrado neste contexto.")
    if receivable.status == ReceivableStatusEnum.REVERSED:
        raise HTTPException(status_code=409, detail="Título já estornado.")
    if receivable.paid_amount > 0:
        raise HTTPException(status_code=409, detail="Título com recebimentos deve ser tratado por estorno compensatório.")
    previous = _money(receivable.balance)
    receivable.balance = Decimal("0")
    receivable.status = ReceivableStatusEnum.REVERSED
    receivable.reversed_at = datetime.utcnow()
    receivable.updated_at = datetime.utcnow()
    receivable.version += 1
    session.add(ReceivableLedgerEntry(
        tenant_id=context.tenant_id, store_id=receivable.store_id,
        receivable_id=receivable.id, entry_type=ReceivableEntryTypeEnum.REVERSAL,
        amount=-previous, balance_after=Decimal("0"), actor_id=actor,
        reason=reason, idempotency_key=idempotency_key,
        metadata_payload={"principal_amount": str(receivable.principal_amount)},
    ))
    _write_event(session, receivable, actor, "receivable.reversed", {
        "reversed_amount": str(previous), "reason": reason, "version": receivable.version,
    })
    session.commit()
    session.refresh(receivable)
    return receivable

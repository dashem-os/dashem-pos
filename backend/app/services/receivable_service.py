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
    ReceivableStatusEnum, ReceivableReceipt, ReceivableReceiptAllocation,
    ReceivableReceiptStatusEnum, ReceivableAgreement, ReceivableAgreementItem,
    ReceivableAgreementStatusEnum, ReceivableCollectionEvent,
)
from app.models.payment import CashMovement, CashMovementTypeEnum, CashSession, CashSessionStatusEnum, PaymentMethodEnum
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


def settle(
    session: Session, context: TenantContext, *, allocations: list[dict],
    method: PaymentMethodEnum, cash_session_id: Optional[uuid.UUID], provider_reference: Optional[str],
    reason: str, actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> ReceivableReceipt:
    actor = _actor(context, actor_id)
    normalized = [{**item, "receivable_id": str(item["receivable_id"])} for item in allocations]
    payload = {"allocations": normalized, "method": method.value,
               "cash_session_id": str(cash_session_id) if cash_session_id else None,
               "provider_reference": provider_reference, "reason": reason, "actor_id": str(actor)}
    request_hash = reliability_service.compute_request_hash(payload)
    existing = session.exec(select(ReceivableReceipt).where(
        ReceivableReceipt.tenant_id == context.tenant_id,
        ReceivableReceipt.idempotency_key == idempotency_key,
    )).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency-Key reutilizada com recebimento diferente.")
        return existing
    if not allocations:
        raise HTTPException(status_code=422, detail="Selecione ao menos um título.")
    ids = sorted({uuid.UUID(str(item["receivable_id"])) for item in allocations}, key=str)
    if len(ids) != len(allocations):
        raise HTTPException(status_code=422, detail="Cada título deve possuir uma única allocation no recebimento.")
    titles = list(session.exec(select(Receivable).where(
        Receivable.tenant_id == context.tenant_id, Receivable.id.in_(ids),
    ).order_by(Receivable.id).with_for_update()).all())
    if len(titles) != len(ids) or (context.store_id and any(item.store_id != context.store_id for item in titles)):
        raise HTTPException(status_code=404, detail="Um ou mais títulos não pertencem ao contexto ativo.")
    customer_ids = {item.customer_id for item in titles}
    if len(customer_ids) != 1:
        raise HTTPException(status_code=422, detail="Um recebimento não pode misturar clientes.")
    by_id = {item.id: item for item in titles}
    prepared = []
    total = Decimal("0")
    for command in allocations:
        title = by_id[uuid.UUID(str(command["receivable_id"]))]
        if title.status not in EXPOSURE_STATUSES or title.balance <= 0:
            raise HTTPException(status_code=409, detail=f"Título {title.id} não aceita recebimento.")
        if int(command.get("expected_version", 0)) != title.version:
            raise HTTPException(status_code=409, detail=f"Título {title.id} foi alterado por outra operação.")
        principal = _money(command["principal_amount"])
        interest = _money(command.get("interest_amount", 0))
        fine = _money(command.get("fine_amount", 0))
        discount = _money(command.get("discount_amount", 0))
        abatement = _money(command.get("abatement_amount", 0))
        if principal <= 0 or principal > title.balance:
            raise HTTPException(status_code=422, detail=f"Principal inválido para o título {title.id}.")
        if discount + abatement > principal:
            raise HTTPException(status_code=422, detail="Desconto e abatimento não podem superar o principal liquidado.")
        net = _money(principal + interest + fine - discount - abatement)
        if net < 0:
            raise HTTPException(status_code=422, detail="Valor líquido do recebimento não pode ser negativo.")
        prepared.append((title, principal, interest, fine, discount, abatement, net))
        total += net
    total = _money(total)
    if total <= 0:
        raise HTTPException(status_code=422, detail="Recebimento precisa possuir valor financeiro positivo.")
    cash = None
    if method == PaymentMethodEnum.CASH:
        if not cash_session_id:
            raise HTTPException(status_code=422, detail="Recebimento em dinheiro exige sessão de caixa.")
        cash = session.exec(select(CashSession).where(
            CashSession.id == cash_session_id, CashSession.tenant_id == context.tenant_id,
            CashSession.store_id == titles[0].store_id,
        ).with_for_update()).first()
        if not cash or cash.status != CashSessionStatusEnum.OPEN:
            raise HTTPException(status_code=409, detail="Sessão de caixa aberta não encontrada.")
    receipt = ReceivableReceipt(
        tenant_id=context.tenant_id, store_id=titles[0].store_id,
        customer_id=titles[0].customer_id, status=ReceivableReceiptStatusEnum.CONFIRMED,
        method=method.value, amount=total, cash_session_id=cash_session_id,
        provider="MANUAL_OPERATOR", provider_reference=provider_reference,
        idempotency_key=idempotency_key, request_hash=request_hash,
        actor_id=actor, reason=reason, confirmed_at=datetime.utcnow(),
    )
    session.add(receipt)
    session.flush()
    if cash:
        movement = CashMovement(
            tenant_id=context.tenant_id, store_id=receipt.store_id,
            cash_session_id=cash.id, actor_id=actor,
            movement_type=CashMovementTypeEnum.RECEIVABLE_PAYMENT,
            amount=total, notes=f"Recebimento de crediário {receipt.id}",
            source_type="RECEIVABLE_RECEIPT", source_id=str(receipt.id),
            idempotency_key=f"receivable-receipt:{receipt.id}:cash",
        )
        session.add(movement); session.flush(); receipt.cash_movement_id = movement.id
    for title, principal, interest, fine, discount, abatement, net in prepared:
        title.balance = _money(title.balance - principal)
        title.paid_amount = _money(title.paid_amount + principal - discount - abatement)
        title.status = ReceivableStatusEnum.PAID if title.balance == 0 else ReceivableStatusEnum.PARTIALLY_PAID
        title.version += 1; title.updated_at = datetime.utcnow()
        session.add(ReceivableReceiptAllocation(
            tenant_id=context.tenant_id, receipt_id=receipt.id, receivable_id=title.id,
            principal_amount=principal, interest_amount=interest, fine_amount=fine,
            discount_amount=discount, abatement_amount=abatement, net_amount=net,
        ))
        session.add(ReceivableLedgerEntry(
            tenant_id=context.tenant_id, store_id=title.store_id, receivable_id=title.id,
            entry_type=ReceivableEntryTypeEnum.PAYMENT, amount=-principal,
            balance_after=title.balance, actor_id=actor, reason=reason,
            idempotency_key=f"{idempotency_key}:{title.id}",
            metadata_payload={"receipt_id": str(receipt.id), "net_amount": str(net),
                              "interest": str(interest), "fine": str(fine),
                              "discount": str(discount), "abatement": str(abatement)},
        ))
        _write_event(session, title, actor, "receivable.settled", {
            "receipt_id": str(receipt.id), "principal_amount": str(principal),
            "net_amount": str(net), "balance_after": str(title.balance), "reason": reason,
        })
    session.commit(); session.refresh(receipt)
    return receipt


def create_agreement(
    session: Session, context: TenantContext, *, receivable_ids: list[uuid.UUID],
    installment_count: int, first_due_at: datetime, interval_days: int,
    interest_amount: Decimal, fine_amount: Decimal, discount_amount: Decimal,
    reason: str, actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> ReceivableAgreement:
    actor = _actor(context, actor_id)
    ids = sorted(set(receivable_ids), key=str)
    payload = {"receivable_ids": [str(item) for item in ids], "installment_count": installment_count,
               "first_due_at": first_due_at.isoformat(), "interval_days": interval_days,
               "interest_amount": str(_money(interest_amount)), "fine_amount": str(_money(fine_amount)),
               "discount_amount": str(_money(discount_amount)), "reason": reason, "actor_id": str(actor)}
    request_hash = reliability_service.compute_request_hash(payload)
    existing = session.exec(select(ReceivableAgreement).where(
        ReceivableAgreement.tenant_id == context.tenant_id,
        ReceivableAgreement.idempotency_key == idempotency_key,
    )).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency-Key reutilizada com acordo diferente.")
        return existing
    titles = list(session.exec(select(Receivable).where(
        Receivable.tenant_id == context.tenant_id, Receivable.id.in_(ids),
    ).order_by(Receivable.id).with_for_update()).all())
    if not ids or len(titles) != len(ids) or (context.store_id and any(item.store_id != context.store_id for item in titles)):
        raise HTTPException(status_code=404, detail="Títulos do acordo não encontrados no contexto ativo.")
    if len({item.customer_id for item in titles}) != 1:
        raise HTTPException(status_code=422, detail="Um acordo não pode misturar clientes.")
    if any(item.status not in EXPOSURE_STATUSES or item.balance <= 0 for item in titles):
        raise HTTPException(status_code=409, detail="Todos os títulos precisam possuir saldo renegociável.")
    principal = _money(sum((item.balance for item in titles), Decimal("0")))
    interest = _money(interest_amount); fine = _money(fine_amount); discount = _money(discount_amount)
    total = _money(principal + interest + fine - discount)
    if total <= 0 or discount > principal:
        raise HTTPException(status_code=422, detail="Ajustes do acordo resultam em total inválido.")
    agreement = ReceivableAgreement(
        tenant_id=context.tenant_id, store_id=titles[0].store_id, customer_id=titles[0].customer_id,
        original_principal=principal, interest_amount=interest, fine_amount=fine,
        discount_amount=discount, agreement_total=total, installment_count=installment_count,
        idempotency_key=idempotency_key, request_hash=request_hash, actor_id=actor, reason=reason,
    )
    session.add(agreement); session.flush()
    for title in titles:
        selected = _money(title.balance)
        session.add(ReceivableAgreementItem(
            tenant_id=context.tenant_id, agreement_id=agreement.id,
            receivable_id=title.id, principal_selected=selected,
        ))
        title.balance = Decimal("0"); title.status = ReceivableStatusEnum.RENEGOTIATED
        title.version += 1; title.updated_at = datetime.utcnow()
        session.add(ReceivableLedgerEntry(
            tenant_id=context.tenant_id, store_id=title.store_id, receivable_id=title.id,
            entry_type=ReceivableEntryTypeEnum.AGREEMENT, amount=-selected,
            balance_after=Decimal("0"), actor_id=actor, reason=reason,
            idempotency_key=f"{idempotency_key}:origin:{title.id}",
            metadata_payload={"agreement_id": str(agreement.id)},
        ))
    base = (total / installment_count).quantize(MONEY, rounding=ROUND_HALF_UP)
    allocated = Decimal("0")
    for number in range(1, installment_count + 1):
        amount = _money(total - allocated) if number == installment_count else base
        allocated = _money(allocated + amount)
        child = Receivable(
            tenant_id=context.tenant_id, store_id=agreement.store_id,
            customer_id=agreement.customer_id, negotiation_id=None, sale_id=None,
            agreement_id=agreement.id, agreement_installment_number=number,
            origin_receivable_id=titles[0].id, principal_amount=amount, balance=amount,
            due_at=first_due_at + timedelta(days=interval_days * (number - 1)),
            issue_idempotency_key=f"{idempotency_key}:installment:{number}",
            issue_request_hash=request_hash, created_by=actor,
        )
        session.add(child); session.flush()
        session.add(ReceivableLedgerEntry(
            tenant_id=context.tenant_id, store_id=agreement.store_id, receivable_id=child.id,
            entry_type=ReceivableEntryTypeEnum.ISSUE, amount=amount,
            balance_after=amount, actor_id=actor, reason=reason,
            idempotency_key=f"{idempotency_key}:installment:{number}:issue",
            metadata_payload={"agreement_id": str(agreement.id), "installment_number": number},
        ))
    session.add(ReceivableCollectionEvent(
        tenant_id=context.tenant_id, store_id=agreement.store_id, customer_id=agreement.customer_id,
        agreement_id=agreement.id, event_type="AGREEMENT_CREATED", actor_id=actor, notes=reason,
    ))
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=agreement.store_id,
        actor_id=actor, action="receivable.agreement.created", target=f"AGREEMENT-{agreement.id}",
        audit_payload={**payload, "original_principal": str(principal), "agreement_total": str(total)},
        aggregate_type="receivable_agreement", aggregate_id=str(agreement.id),
        event_type="receivable.agreement.created", outbox_payload={"agreement_id": str(agreement.id), "customer_id": str(agreement.customer_id)},
    )
    session.commit(); session.refresh(agreement)
    return agreement


def list_agreements(session: Session, context: TenantContext, limit: int = 100) -> list[ReceivableAgreement]:
    query = select(ReceivableAgreement).where(ReceivableAgreement.tenant_id == context.tenant_id)
    if context.store_id:
        query = query.where(ReceivableAgreement.store_id == context.store_id)
    return list(session.exec(query.order_by(ReceivableAgreement.created_at.desc()).limit(limit)).all())


def record_collection_event(
    session: Session, context: TenantContext, *, customer_id: uuid.UUID,
    receivable_id: Optional[uuid.UUID], agreement_id: Optional[uuid.UUID], event_type: str,
    promised_for: Optional[datetime], notes: str, actor_id: Optional[uuid.UUID],
) -> ReceivableCollectionEvent:
    actor = _actor(context, actor_id)
    if receivable_id:
        title = session.exec(scope_tenant_query(select(Receivable).where(Receivable.id == receivable_id), Receivable, context)).first()
        if not title or title.customer_id != customer_id:
            raise HTTPException(status_code=404, detail="Título não encontrado para o cliente ativo.")
        store_id = title.store_id
    elif agreement_id:
        agreement = session.exec(scope_tenant_query(select(ReceivableAgreement).where(ReceivableAgreement.id == agreement_id), ReceivableAgreement, context)).first()
        if not agreement or agreement.customer_id != customer_id:
            raise HTTPException(status_code=404, detail="Acordo não encontrado para o cliente ativo.")
        store_id = agreement.store_id
    elif context.store_id:
        store_id = context.store_id
    else:
        raise HTTPException(status_code=422, detail="Informe título, acordo ou unidade ativa.")
    event = ReceivableCollectionEvent(
        tenant_id=context.tenant_id, store_id=store_id, customer_id=customer_id,
        receivable_id=receivable_id, agreement_id=agreement_id, event_type=event_type,
        promised_for=promised_for, actor_id=actor, notes=notes,
    )
    session.add(event)
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=store_id, actor_id=actor,
        action="receivable.collection.recorded", target=f"CUSTOMER-{customer_id}",
        audit_payload={"event_type": event_type, "promised_for": promised_for.isoformat() if promised_for else None, "notes": notes},
        aggregate_type="receivable_collection", aggregate_id=str(event.id),
        event_type="receivable.collection.recorded", outbox_payload={"customer_id": str(customer_id), "event_id": str(event.id)},
    )
    session.commit(); session.refresh(event)
    return event

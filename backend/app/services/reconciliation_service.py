import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.fiscal import FiscalDocument
from app.models.negotiation import CheckoutNegotiation, CheckoutNegotiationStatusEnum
from app.models.payment import Payment, PaymentStatusEnum
from app.models.receivable import Receivable
from app.models.reconciliation import FinancialReconciliation, ReconciliationEvent, ReconciliationStatusEnum
from app.models.sale import Sale
from app.services import reliability_service


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def reconcile_sale(
    session: Session, context: TenantContext, sale_id: uuid.UUID, *, actor_id: uuid.UUID,
    provider_reported_total: Optional[Decimal], provider: Optional[str],
    provider_reference: Optional[str], notes: Optional[str],
) -> FinancialReconciliation:
    actor_id = resolve_actor(context, actor_id)
    sale = session.exec(scope_tenant_query(select(Sale).where(
        Sale.id == sale_id,
    ), Sale, context).with_for_update()).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Venda não encontrada para este tenant.")
    payments = session.exec(scope_tenant_query(select(Payment).where(
        Payment.sale_id == sale.id, Payment.status == PaymentStatusEnum.CONFIRMED,
    ), Payment, context)).all()
    receivables = session.exec(scope_tenant_query(select(Receivable).where(
        Receivable.sale_id == sale.id,
    ), Receivable, context)).all()
    negotiation = session.exec(scope_tenant_query(select(CheckoutNegotiation).where(
        CheckoutNegotiation.sale_id == sale.id,
        CheckoutNegotiation.status == CheckoutNegotiationStatusEnum.FINALIZED,
    ), CheckoutNegotiation, context)).first()
    fiscal = session.exec(scope_tenant_query(select(FiscalDocument).where(
        FiscalDocument.sale_id == sale.id,
    ), FiscalDocument, context)).first()
    payment_total = _money(sum((item.amount for item in payments), Decimal("0")))
    receivable_total = _money(sum((item.principal_amount for item in receivables), Decimal("0")))
    expected = _money(sale.net_total)
    ledger_total = _money(payment_total + receivable_total)
    observed = _money(provider_reported_total) if provider_reported_total is not None else ledger_total
    difference = _money(observed - expected)
    result_status = ReconciliationStatusEnum.MATCHED if difference == 0 else ReconciliationStatusEnum.DIFFERENCE
    record = session.exec(scope_tenant_query(select(FinancialReconciliation).where(
        FinancialReconciliation.sale_id == sale.id,
    ), FinancialReconciliation, context).with_for_update()).first()
    if record is None:
        record = FinancialReconciliation(
            tenant_id=context.tenant_id, store_id=sale.store_id, sale_id=sale.id,
            expected_amount=expected, payment_total=payment_total, receivable_total=receivable_total,
            difference=difference, status=result_status, actor_id=actor_id,
        )
    else:
        record.version += 1
    record.negotiation_id = negotiation.id if negotiation else None
    record.fiscal_document_id = fiscal.id if fiscal else None
    record.cash_session_id = next((item.cash_session_id for item in payments if item.cash_session_id), None)
    record.expected_amount = expected
    record.payment_total = payment_total
    record.receivable_total = receivable_total
    record.provider_reported_total = _money(provider_reported_total) if provider_reported_total is not None else None
    record.difference = difference
    record.status = result_status
    record.provider = provider
    record.provider_reference = provider_reference
    record.actor_id = actor_id
    record.notes = notes
    record.checked_at = datetime.utcnow()
    session.add(record); session.flush()
    session.add(ReconciliationEvent(
        tenant_id=context.tenant_id, store_id=sale.store_id, reconciliation_id=record.id,
        actor_id=actor_id, status=result_status, expected_amount=expected,
        observed_amount=observed, difference=difference, provider=provider,
        provider_reference=provider_reference,
    ))
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=sale.store_id,
        actor_id=actor_id, action="financial_reconciliation.checked",
        target=f"RECONCILIATION-{record.id}",
        audit_payload={"sale_id": str(sale.id), "expected_amount": str(expected),
                       "observed_amount": str(observed), "difference": str(difference),
                       "status": result_status.value, "version": record.version},
        aggregate_type="financial_reconciliation", aggregate_id=str(record.id),
        event_type="financial_reconciliation.checked",
        outbox_payload={"reconciliation_id": str(record.id), "sale_id": str(sale.id),
                        "status": result_status.value, "difference": str(difference)},
    )
    session.commit(); session.refresh(record)
    return record


def list_reconciliations(
    session: Session, context: TenantContext, *, store_id: Optional[uuid.UUID],
    status_filter: Optional[ReconciliationStatusEnum],
) -> list[FinancialReconciliation]:
    query = select(FinancialReconciliation).where(FinancialReconciliation.tenant_id == context.tenant_id)
    if store_id:
        query = query.where(FinancialReconciliation.store_id == store_id)
    if status_filter:
        query = query.where(FinancialReconciliation.status == status_filter)
    return list(session.exec(query.order_by(FinancialReconciliation.checked_at.desc())).all())

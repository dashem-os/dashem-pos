import uuid
from decimal import Decimal
from datetime import datetime
from typing import List, Optional, Tuple
from sqlmodel import Session, select
from fastapi import HTTPException, status
from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.catalog import MovementTypeEnum
from app.models.sale import Sale, SaleStatusEnum, SaleItem
from app.models.payment import (
    Payment, CashSession, CashMovement, PaymentMethodEnum, PaymentStatusEnum, CashMovementTypeEnum, CashSessionStatusEnum
)
from app.models.reconciliation import PaymentRefund
from app.providers.payment_provider import payment_provider
from app.services import inventory_service, reliability_service


def refund_payment(
    session: Session, context: TenantContext, payment_id: uuid.UUID, *,
    actor_id: uuid.UUID, amount: Decimal, reason: str, idempotency_key: str,
    cash_session_id: Optional[uuid.UUID], provider_reference: Optional[str],
) -> PaymentRefund:
    actor_id = resolve_actor(context, actor_id)
    existing = session.exec(scope_tenant_query(select(PaymentRefund).where(
        PaymentRefund.idempotency_key == idempotency_key,
    ), PaymentRefund, context)).first()
    if existing:
        return existing
    payment = session.exec(scope_tenant_query(select(Payment).where(
        Payment.id == payment_id,
    ), Payment, context).with_for_update()).first()
    if not payment or payment.status != PaymentStatusEnum.CONFIRMED:
        raise HTTPException(status_code=409, detail="Somente pagamento confirmado admite estorno.")
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    previous = session.exec(scope_tenant_query(select(PaymentRefund).where(
        PaymentRefund.payment_id == payment.id,
    ), PaymentRefund, context)).all()
    if value <= 0 or sum((item.amount for item in previous), Decimal("0")) + value > payment.amount:
        raise HTTPException(status_code=422, detail="Valor do estorno excede o saldo confirmado.")
    cash = None
    if payment.method == PaymentMethodEnum.CASH:
        if not cash_session_id:
            raise HTTPException(status_code=422, detail="Estorno em dinheiro exige caixa aberto.")
        cash = session.exec(scope_tenant_query(select(CashSession).where(
            CashSession.id == cash_session_id, CashSession.store_id == payment.store_id,
        ), CashSession, context).with_for_update()).first()
        if not cash or cash.status != CashSessionStatusEnum.OPEN:
            raise HTTPException(status_code=409, detail="Caixa aberto não encontrado para o estorno.")
    refund = PaymentRefund(
        tenant_id=context.tenant_id, store_id=payment.store_id, payment_id=payment.id,
        cash_session_id=cash_session_id, amount=value, provider_reference=provider_reference,
        idempotency_key=idempotency_key, actor_id=actor_id, reason=reason,
    )
    session.add(refund); session.flush()
    if cash:
        movement = CashMovement(
            tenant_id=context.tenant_id, store_id=payment.store_id, cash_session_id=cash.id,
            actor_id=actor_id, movement_type=CashMovementTypeEnum.REFUND, amount=value,
            notes=f"Estorno do pagamento {payment.id}: {reason}", source_type="PAYMENT_REFUND",
            source_id=str(refund.id), idempotency_key=f"payment-refund:{refund.id}:cash",
        )
        session.add(movement); session.flush(); refund.cash_movement_id = movement.id
    sale = session.exec(scope_tenant_query(select(Sale).where(Sale.id == payment.sale_id), Sale, context).with_for_update()).first()
    sale_refunds = session.exec(scope_tenant_query(select(PaymentRefund).join(
        Payment, PaymentRefund.payment_id == Payment.id,
    ).where(Payment.sale_id == payment.sale_id), PaymentRefund, context)).all()
    refunded_total = sum((item.amount for item in sale_refunds), Decimal("0"))
    if sale:
        sale.status = SaleStatusEnum.REFUNDED if refunded_total >= sale.net_total else SaleStatusEnum.PARTIALLY_REFUNDED
        sale.updated_at = datetime.utcnow()
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=payment.store_id,
        actor_id=actor_id, action="payment.refunded", target=f"PAYMENT-REFUND-{refund.id}",
        audit_payload={"payment_id": str(payment.id), "amount": str(value), "reason": reason},
        aggregate_type="payment_refund", aggregate_id=str(refund.id), event_type="payment.refunded",
        outbox_payload={"payment_id": str(payment.id), "refund_id": str(refund.id), "amount": str(value)},
    )
    session.commit(); session.refresh(refund)
    return refund

def create_payment(
    session: Session,
    context: TenantContext,
    sale_id: uuid.UUID,
    method: PaymentMethodEnum,
    amount: Decimal,
    cash_session_id: Optional[uuid.UUID] = None,
    tendered_amount: Optional[Decimal] = None,
    provider: str = "MANUAL_OPERATOR",
    provider_event_id: Optional[str] = None
) -> Payment:
    # Verify Sale with pessimistic lock or scoped query
    sale_query = select(Sale).where(Sale.id == sale_id, Sale.tenant_id == context.tenant_id)
    sale = session.exec(sale_query).first()
    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found for this tenant.")

    if sale.status not in (SaleStatusEnum.AWAITING_PAYMENT, SaleStatusEnum.CHECKOUT, SaleStatusEnum.DRAFT):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot add payment to sale in status '{sale.status}'."
        )

    # Cash method requires an OPEN CashSession belonging to same tenant/store
    if method == PaymentMethodEnum.CASH:
        if not cash_session_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cash payments require an active cash_session_id."
            )
        cs_query = select(CashSession).where(
            CashSession.id == cash_session_id,
            CashSession.tenant_id == context.tenant_id,
            CashSession.store_id == sale.store_id
        )
        cash_session = session.exec(cs_query).first()
        if not cash_session or cash_session.status != CashSessionStatusEnum.OPEN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cash session is invalid, CLOSED, or belongs to another store."
            )

    amt_dec = Decimal(str(amount))

    # Calculate already confirmed/pending payments and remaining outstanding balance
    existing_payments_query = select(Payment).where(
        Payment.sale_id == sale_id,
        Payment.status.in_([PaymentStatusEnum.CONFIRMED, PaymentStatusEnum.PENDING])
    )
    existing_payments = session.exec(existing_payments_query).all()
    current_total = sum((p.amount for p in existing_payments), Decimal("0.00"))
    remaining_balance = sale.net_total - current_total

    # OVERPAYMENT PROTECTION FOR NON-CASH METHODS
    if method != PaymentMethodEnum.CASH and amt_dec > remaining_balance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PAYMENT_EXCEEDS_OUTSTANDING_AMOUNT: Payment amount R$ {amt_dec:.2f} exceeds remaining balance R$ {remaining_balance:.2f}."
        )

    # Handle CASH Tendered & Change Calculations
    change_dec = None
    tend_dec = None
    if method == PaymentMethodEnum.CASH and tendered_amount:
        tend_dec = Decimal(str(tendered_amount))
        if tend_dec < amt_dec:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tendered amount R$ {tend_dec:.2f} is less than payment amount R$ {amt_dec:.2f}."
            )
        change_dec = tend_dec - amt_dec

    payment = Payment(
        tenant_id=context.tenant_id,
        store_id=sale.store_id,
        sale_id=sale_id,
        cash_session_id=cash_session_id,
        method=method,
        status=PaymentStatusEnum.PENDING,
        amount=amt_dec,
        tendered_amount=tend_dec,
        change_amount=change_dec,
        provider=provider,
        provider_event_id=provider_event_id
    )
    session.add(payment)
    session.commit()
    session.refresh(payment)
    return payment

def confirm_payment(
    session: Session,
    context: TenantContext,
    payment_id: uuid.UUID,
    actor_id: uuid.UUID,
    correlation_id: Optional[str] = None
) -> Tuple[Payment, Sale, bool]:
    actor_id = resolve_actor(context, actor_id)
    # PESSIMISTIC LOCKING: Lock Payment record
    pay_query = select(Payment).where(
        Payment.id == payment_id,
        Payment.tenant_id == context.tenant_id
    ).with_for_update()
    payment = session.exec(pay_query).first()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment record not found.")

    # PESSIMISTIC LOCKING: Lock Sale record
    sale_query = select(Sale).where(
        Sale.id == payment.sale_id,
        Sale.tenant_id == context.tenant_id
    ).with_for_update()
    sale = session.exec(sale_query).first()
    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated Sale record not found.")

    # Idempotent re-execution check
    if payment.status == PaymentStatusEnum.CONFIRMED:
        return payment, sale, True

    # Process via Payment Provider
    success, tx_ref, msg = payment_provider.process_payment(
        tenant_id=context.tenant_id,
        store_id=payment.store_id,
        method=payment.method,
        amount=payment.amount
    )

    if not success:
        payment.status = PaymentStatusEnum.FAILED
        session.add(payment)
        session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Payment processing failed: {msg}")

    payment.status = PaymentStatusEnum.CONFIRMED
    payment.transaction_ref = tx_ref
    payment.confirmed_at = datetime.utcnow()
    session.add(payment)

    # Cash Movement if method is CASH
    if payment.method == PaymentMethodEnum.CASH and payment.cash_session_id:
        cash_mov = CashMovement(
            tenant_id=context.tenant_id,
            store_id=payment.store_id,
            cash_session_id=payment.cash_session_id,
            actor_id=actor_id,
            movement_type=CashMovementTypeEnum.SALE_PAYMENT,
            amount=payment.amount,
            notes=f"Pagamento Venda #{sale.id}",
            source_type="PAYMENT", source_id=str(payment.id),
            idempotency_key=f"payment:{payment.id}:cash",
        )
        session.add(cash_mov)

    # GRANULAR OUTBOX EVENT FOR THIS PAYMENT
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=payment.store_id,
        actor_id=actor_id,
        action="payment.confirm",
        target=f"PAYMENT-{payment.id}",
        audit_payload={"payment_id": str(payment.id), "amount": str(payment.amount), "method": payment.method.value},
        aggregate_type="payment",
        aggregate_id=str(payment.id),
        event_type="payment.confirmed",  # Granular Event
        outbox_payload={
            "tenant_id": str(context.tenant_id),
            "store_id": str(payment.store_id),
            "sale_id": str(payment.sale_id),
            "payment_id": str(payment.id),
            "amount": str(payment.amount),
            "method": payment.method.value
        },
        correlation_id=correlation_id
    )

    session.flush()

    # Calculate total confirmed payments for this Sale
    confirmed_payments_query = select(Payment).where(
        Payment.sale_id == sale.id,
        Payment.status == PaymentStatusEnum.CONFIRMED
    )
    confirmed_payments = session.exec(confirmed_payments_query).all()
    total_confirmed = sum((p.amount for p in confirmed_payments), Decimal("0.00"))

    # ATOMIC TRANSITION TO PAID WHEN TOTALLY QUITTED
    if total_confirmed >= sale.net_total:
        sale.status = SaleStatusEnum.PAID
        sale.updated_at = datetime.utcnow()
        session.add(sale)

        # ATOMIC STOCK DECREMENT FOR TRACKED ITEMS (EXACTLY ONCE WITH STRICT STOCK ENFORCEMENT)
        items_query = select(SaleItem).where(SaleItem.sale_id == sale.id)
        items = session.exec(items_query).all()

        for item in items:
            if item.tracks_inventory_snapshot:
                inventory_service.adjust_stock(
                    session=session,
                    context=context,
                    store_id=sale.store_id,
                    product_id=item.product_id,
                    actor_id=actor_id,
                    movement_type=MovementTypeEnum.SALE,
                    quantity=-item.quantity,
                    reason=f"Venda Consumada #{sale.id}",
                    correlation_id=correlation_id
                )

        # Atomic Audit + Outbox for Sale Paid
        reliability_service.write_audit_and_outbox(
            session=session,
            tenant_id=context.tenant_id,
            store_id=sale.store_id,
            actor_id=actor_id,
            action="sale.paid",
            target=f"SALE-{sale.id}",
            audit_payload={"sale_id": str(sale.id), "net_total": str(sale.net_total), "total_confirmed": str(total_confirmed)},
            aggregate_type="sale",
            aggregate_id=str(sale.id),
            event_type="sale.paid",
            outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(sale.store_id), "sale_id": str(sale.id)},
            correlation_id=correlation_id
        )

    session.commit()
    session.refresh(payment)
    session.refresh(sale)
    return payment, sale, False

def list_payments(
    session: Session,
    context: TenantContext,
    sale_id: Optional[uuid.UUID] = None
) -> List[Payment]:
    query = select(Payment).where(Payment.tenant_id == context.tenant_id)
    if sale_id:
        query = query.where(Payment.sale_id == sale_id)
    return session.exec(query.order_by(Payment.created_at.asc())).all()

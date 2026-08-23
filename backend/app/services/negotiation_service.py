import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.context import TenantContext, scope_tenant_query
from app.models.catalog import Product
from app.models.negotiation import (
    CheckoutNegotiation, CheckoutNegotiationStatusEnum, NegotiationEvent,
    NegotiationOrder, PaymentAllocation, PaymentIntent, PaymentIntentStatusEnum,
)
from app.models.order import Order, OrderItem, OrderItemStatusEnum, OrderStatusEnum
from app.models.payment import (
    CashMovement, CashMovementTypeEnum, CashSession, CashSessionStatusEnum,
    Payment, PaymentMethodEnum, PaymentStatusEnum,
)
from app.models.sale import (
    FulfillmentTypeEnum, Sale, SaleItem, SaleOperationModeEnum, SaleStatusEnum,
)
from app.models.table_service import (
    ServiceTable, ServiceTableStatusEnum, TableSession, TableSessionStatusEnum,
)
from app.services import reliability_service


MONEY = Decimal("0.0001")
ACTIVE_NEGOTIATIONS = {
    CheckoutNegotiationStatusEnum.OPEN,
    CheckoutNegotiationStatusEnum.PARTIALLY_COVERED,
    CheckoutNegotiationStatusEnum.COVERED,
}
ACTIVE_SESSIONS = {
    TableSessionStatusEnum.OPEN, TableSessionStatusEnum.IN_SERVICE,
    TableSessionStatusEnum.PARTIALLY_PAID, TableSessionStatusEnum.CLOSING,
}


def _money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _actor(context: TenantContext, actor_id: Optional[uuid.UUID]) -> uuid.UUID:
    return actor_id or context.user_id or uuid.UUID("00000000-0000-0000-0000-000000000000")


def _ensure_store(context: TenantContext, store_id: uuid.UUID) -> None:
    if context.store_id and context.store_id != store_id:
        raise HTTPException(status_code=403, detail="Operação fora da unidade ativa.")


def _event(
    session: Session, negotiation: CheckoutNegotiation, actor_id: uuid.UUID,
    event_type: str, payload: dict,
) -> None:
    session.add(NegotiationEvent(
        tenant_id=negotiation.tenant_id, negotiation_id=negotiation.id,
        event_type=event_type, actor_id=actor_id, payload=payload,
    ))
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=negotiation.tenant_id, store_id=negotiation.store_id,
        actor_id=actor_id, action=event_type, target=f"NEGOTIATION-{negotiation.id}",
        audit_payload=payload, aggregate_type="checkout_negotiation",
        aggregate_id=str(negotiation.id), event_type=event_type,
        outbox_payload={
            "tenant_id": str(negotiation.tenant_id), "store_id": str(negotiation.store_id),
            "negotiation_id": str(negotiation.id), **payload,
        },
    )


def _locked_negotiation(session: Session, context: TenantContext, negotiation_id: uuid.UUID) -> CheckoutNegotiation:
    query = select(CheckoutNegotiation).where(CheckoutNegotiation.id == negotiation_id).with_for_update()
    negotiation = session.exec(scope_tenant_query(query, CheckoutNegotiation, context)).first()
    if not negotiation:
        raise HTTPException(status_code=404, detail="Negociação não encontrada neste contexto.")
    return negotiation


def _orders_for_negotiation(session: Session, negotiation: CheckoutNegotiation, lock: bool = False) -> list[Order]:
    order_ids = list(session.exec(
        select(NegotiationOrder.order_id).where(
            NegotiationOrder.tenant_id == negotiation.tenant_id,
            NegotiationOrder.negotiation_id == negotiation.id,
        )
    ).all())
    if not order_ids:
        return []
    query = select(Order).where(
        Order.tenant_id == negotiation.tenant_id,
        Order.store_id == negotiation.store_id,
        Order.id.in_(order_ids),
    )
    if lock:
        query = query.with_for_update()
    return list(session.exec(query).all())


def _source_version(table_session: Optional[TableSession], orders: Iterable[Order]) -> int:
    if table_session:
        return table_session.version
    timestamps = [order.updated_at for order in orders]
    return max(1, int(max(timestamps).timestamp() * 1_000_000)) if timestamps else 1


def _order_amount(session: Session, order: Order) -> Decimal:
    items = session.exec(select(OrderItem).where(
        OrderItem.tenant_id == order.tenant_id,
        OrderItem.order_id == order.id,
        OrderItem.status == OrderItemStatusEnum.ACTIVE,
    )).all()
    return _money(sum((_money(item.unit_price) * _money(item.quantity) for item in items), Decimal("0")))


def _validate_source(session: Session, negotiation: CheckoutNegotiation) -> list[Order]:
    orders = _orders_for_negotiation(session, negotiation, lock=True)
    table_session = None
    if negotiation.table_session_id:
        table_session = session.exec(select(TableSession).where(
            TableSession.id == negotiation.table_session_id,
            TableSession.tenant_id == negotiation.tenant_id,
            TableSession.store_id == negotiation.store_id,
        ).with_for_update()).first()
        if not table_session or table_session.status not in ACTIVE_SESSIONS:
            raise HTTPException(status_code=409, detail="A sessão vinculada não está mais disponível.")
    current = _source_version(table_session, orders)
    if current != negotiation.source_version:
        if negotiation.status in ACTIVE_NEGOTIATIONS:
            negotiation.status = CheckoutNegotiationStatusEnum.INVALIDATED
            negotiation.version += 1
            negotiation.updated_at = datetime.utcnow()
            _event(session, negotiation, negotiation.opened_by, "checkout.negotiation.invalidated", {
                "expected_source_version": negotiation.source_version,
                "current_source_version": current,
            })
            session.commit()
        raise HTTPException(status_code=409, detail="O consumo mudou. Reabra a conta para obter um novo snapshot autoritativo.")
    return orders


def _totals(session: Session, negotiation: CheckoutNegotiation) -> dict:
    intents = list(session.exec(select(PaymentIntent).where(
        PaymentIntent.tenant_id == negotiation.tenant_id,
        PaymentIntent.negotiation_id == negotiation.id,
    ).order_by(PaymentIntent.created_at)).all())
    confirmed = _money(sum((item.amount for item in intents if item.status == PaymentIntentStatusEnum.CONFIRMED), Decimal("0")))
    processing = _money(sum((item.amount for item in intents if item.status in {
        PaymentIntentStatusEnum.PENDING, PaymentIntentStatusEnum.PROCESSING,
    }), Decimal("0")))
    failed = _money(sum((item.amount for item in intents if item.status == PaymentIntentStatusEnum.FAILED), Decimal("0")))
    remaining = max(Decimal("0"), _money(negotiation.total_due - confirmed))
    return {
        "confirmed_amount": confirmed, "processing_amount": processing,
        "failed_amount": failed, "remaining_amount": remaining, "intents": intents,
    }


def projection(session: Session, context: TenantContext, negotiation_id: uuid.UUID, validate: bool = True) -> dict:
    negotiation = session.exec(scope_tenant_query(
        select(CheckoutNegotiation).where(CheckoutNegotiation.id == negotiation_id),
        CheckoutNegotiation, context,
    )).first()
    if not negotiation:
        raise HTTPException(status_code=404, detail="Negociação não encontrada neste contexto.")
    if validate and negotiation.status in ACTIVE_NEGOTIATIONS:
        _validate_source(session, negotiation)
    totals = _totals(session, negotiation)
    orders = list(session.exec(select(NegotiationOrder).where(
        NegotiationOrder.tenant_id == context.tenant_id,
        NegotiationOrder.negotiation_id == negotiation.id,
    )).all())
    allocations = list(session.exec(select(PaymentAllocation).where(
        PaymentAllocation.tenant_id == context.tenant_id,
        PaymentAllocation.negotiation_id == negotiation.id,
    )).all())
    return {
        "id": negotiation.id, "tenant_id": negotiation.tenant_id,
        "store_id": negotiation.store_id, "table_session_id": negotiation.table_session_id,
        "sale_id": negotiation.sale_id, "status": negotiation.status,
        "subtotal": negotiation.subtotal, "discount_total": negotiation.discount_total,
        "surcharge_total": negotiation.surcharge_total, "tax_total": negotiation.tax_total,
        "total_due": negotiation.total_due, "source_version": negotiation.source_version,
        "version": negotiation.version, "created_at": negotiation.created_at,
        "updated_at": negotiation.updated_at, "finalized_at": negotiation.finalized_at,
        "orders": orders, "allocations": allocations, **totals,
    }


def open_negotiation(
    session: Session, context: TenantContext, *, store_id: uuid.UUID,
    table_session_id: Optional[uuid.UUID], order_ids: list[uuid.UUID],
    actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> dict:
    _ensure_store(context, store_id)
    actor = _actor(context, actor_id)
    payload = {
        "store_id": str(store_id), "table_session_id": str(table_session_id) if table_session_id else None,
        "order_ids": sorted(str(item) for item in order_ids), "actor_id": str(actor),
    }
    request_hash = reliability_service.compute_request_hash(payload)
    existing = session.exec(select(CheckoutNegotiation).where(
        CheckoutNegotiation.tenant_id == context.tenant_id,
        CheckoutNegotiation.open_idempotency_key == idempotency_key,
    )).first()
    if existing:
        if existing.open_request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency-Key reutilizada com payload diferente.")
        return projection(session, context, existing.id, validate=False)

    table_session = None
    if table_session_id:
        table_session = session.exec(scope_tenant_query(select(TableSession).where(
            TableSession.id == table_session_id,
            TableSession.store_id == store_id,
        ).with_for_update(), TableSession, context)).first()
        if not table_session or table_session.status not in ACTIVE_SESSIONS:
            raise HTTPException(status_code=404, detail="Sessão ativa não encontrada.")
        orders = list(session.exec(select(Order).where(
            Order.tenant_id == context.tenant_id,
            Order.store_id == store_id,
            Order.table_session_id == table_session_id,
            Order.status.in_([OrderStatusEnum.OPEN, OrderStatusEnum.SUBMITTED]),
        ).with_for_update()).all())
        scope_key = f"table-session:{table_session_id}"
    else:
        unique_ids = sorted(set(order_ids), key=str)
        if not unique_ids:
            raise HTTPException(status_code=422, detail="Informe uma sessão de mesa ou ao menos um Order.")
        orders = list(session.exec(scope_tenant_query(select(Order).where(
            Order.id.in_(unique_ids), Order.store_id == store_id,
            Order.status.in_([OrderStatusEnum.OPEN, OrderStatusEnum.SUBMITTED]),
        ).with_for_update(), Order, context)).all())
        if len(orders) != len(unique_ids):
            raise HTTPException(status_code=404, detail="Um ou mais Orders não pertencem ao contexto ativo.")
        scope_key = "orders:" + ":".join(str(item) for item in unique_ids)
    if not orders:
        raise HTTPException(status_code=409, detail="Não há Orders ativos para fechar.")
    active = session.exec(select(CheckoutNegotiation).where(
        CheckoutNegotiation.tenant_id == context.tenant_id,
        CheckoutNegotiation.store_id == store_id,
        CheckoutNegotiation.scope_key == scope_key,
        CheckoutNegotiation.status.in_(list(ACTIVE_NEGOTIATIONS)),
    )).first()
    if active:
        return projection(session, context, active.id)
    snapshots = [(order, _order_amount(session, order)) for order in orders]
    subtotal = _money(sum((amount for _, amount in snapshots), Decimal("0")))
    if subtotal <= 0:
        raise HTTPException(status_code=409, detail="A conta não possui consumo ativo.")
    negotiation = CheckoutNegotiation(
        tenant_id=context.tenant_id, store_id=store_id,
        table_session_id=table_session_id, scope_key=scope_key,
        subtotal=subtotal, total_due=subtotal,
        source_version=_source_version(table_session, orders), opened_by=actor,
        open_idempotency_key=idempotency_key, open_request_hash=request_hash,
    )
    session.add(negotiation)
    session.flush()
    for order, amount in snapshots:
        session.add(NegotiationOrder(
            tenant_id=context.tenant_id, negotiation_id=negotiation.id,
            order_id=order.id, amount_snapshot=amount,
        ))
    _event(session, negotiation, actor, "checkout.negotiation.opened", {
        "total_due": str(subtotal), "order_ids": [str(order.id) for order, _ in snapshots],
        "source_version": negotiation.source_version,
    })
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="A conta já está sendo negociada por outra operação.") from exc
    return projection(session, context, negotiation.id)


def create_intent(
    session: Session, context: TenantContext, negotiation_id: uuid.UUID, *,
    method: PaymentMethodEnum, amount: Decimal, cash_session_id: Optional[uuid.UUID],
    tendered_amount: Optional[Decimal], allocations: list[dict],
    actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> dict:
    actor = _actor(context, actor_id)
    normalized_amount = _money(amount)
    payload = {
        "negotiation_id": str(negotiation_id), "method": method.value,
        "amount": str(normalized_amount), "cash_session_id": str(cash_session_id) if cash_session_id else None,
        "tendered_amount": str(tendered_amount) if tendered_amount is not None else None,
        "allocations": allocations, "actor_id": str(actor),
    }
    request_hash = reliability_service.compute_request_hash(payload)
    existing = session.exec(select(PaymentIntent).where(
        PaymentIntent.tenant_id == context.tenant_id,
        PaymentIntent.idempotency_key == idempotency_key,
    )).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency-Key reutilizada com payload diferente.")
        return projection(session, context, existing.negotiation_id)
    negotiation = _locked_negotiation(session, context, negotiation_id)
    if negotiation.status not in ACTIVE_NEGOTIATIONS:
        raise HTTPException(status_code=409, detail="A negociação não aceita novas parcelas.")
    _validate_source(session, negotiation)
    totals = _totals(session, negotiation)
    available = _money(totals["remaining_amount"] - totals["processing_amount"])
    if normalized_amount <= 0 or normalized_amount > available:
        raise HTTPException(status_code=409, detail=f"Parcela excede o saldo reservável de {available}.")
    if method == PaymentMethodEnum.CASH:
        if not cash_session_id:
            raise HTTPException(status_code=422, detail="Pagamento em dinheiro exige sessão de caixa.")
        cash = session.exec(select(CashSession).where(
            CashSession.id == cash_session_id,
            CashSession.tenant_id == context.tenant_id,
            CashSession.store_id == negotiation.store_id,
        ).with_for_update()).first()
        if not cash or cash.status != CashSessionStatusEnum.OPEN:
            raise HTTPException(status_code=409, detail="Sessão de caixa aberta não encontrada.")
        tendered = _money(tendered_amount or normalized_amount)
        if tendered < normalized_amount:
            raise HTTPException(status_code=422, detail="Valor recebido é menor que a parcela.")
        change = _money(tendered - normalized_amount)
    else:
        tendered, change = None, Decimal("0")
    if allocations:
        allocation_total = _money(sum((_money(item["amount"]) for item in allocations), Decimal("0")))
        if allocation_total != normalized_amount:
            raise HTTPException(status_code=422, detail="A soma das allocations deve ser igual à parcela.")
    intent = PaymentIntent(
        tenant_id=context.tenant_id, store_id=negotiation.store_id,
        negotiation_id=negotiation.id, cash_session_id=cash_session_id,
        method=method, amount=normalized_amount, tendered_amount=tendered,
        change_amount=change, provider="MANUAL_OPERATOR",
        idempotency_key=idempotency_key, request_hash=request_hash, created_by=actor,
    )
    session.add(intent)
    session.flush()
    linked_orders = {item.order_id for item in session.exec(select(NegotiationOrder).where(
        NegotiationOrder.negotiation_id == negotiation.id,
    )).all()}
    for allocation in allocations or [{"amount": normalized_amount}]:
        order_id = uuid.UUID(str(allocation["order_id"])) if allocation.get("order_id") else None
        item_id = uuid.UUID(str(allocation["order_item_id"])) if allocation.get("order_item_id") else None
        if order_id and order_id not in linked_orders:
            raise HTTPException(status_code=422, detail="Allocation aponta para Order fora da negociação.")
        if item_id:
            item = session.exec(select(OrderItem).where(
                OrderItem.id == item_id, OrderItem.tenant_id == context.tenant_id,
                OrderItem.order_id.in_(list(linked_orders)),
            )).first()
            if not item:
                raise HTTPException(status_code=422, detail="Allocation aponta para item fora da negociação.")
            order_id = item.order_id
        session.add(PaymentAllocation(
            tenant_id=context.tenant_id, negotiation_id=negotiation.id,
            payment_intent_id=intent.id, order_id=order_id, order_item_id=item_id,
            amount=_money(allocation["amount"]),
        ))
    negotiation.version += 1
    negotiation.updated_at = datetime.utcnow()
    _event(session, negotiation, actor, "payment.intent.created", {
        "payment_intent_id": str(intent.id), "method": method.value,
        "amount": str(normalized_amount), "remaining_reserved": str(available - normalized_amount),
    })
    session.commit()
    return projection(session, context, negotiation.id)


def confirm_intent(
    session: Session, context: TenantContext, intent_id: uuid.UUID, *,
    actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> dict:
    actor = _actor(context, actor_id)
    request_hash = reliability_service.compute_request_hash({"intent_id": str(intent_id), "actor_id": str(actor)})
    intent = session.exec(scope_tenant_query(select(PaymentIntent).where(
        PaymentIntent.id == intent_id,
    ).with_for_update(), PaymentIntent, context)).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Parcela não encontrada.")
    if intent.confirm_idempotency_key:
        if intent.confirm_idempotency_key != idempotency_key or intent.confirm_request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Confirmação já registrada com outro comando.")
        return projection(session, context, intent.negotiation_id, validate=False)
    if intent.status not in {PaymentIntentStatusEnum.PENDING, PaymentIntentStatusEnum.PROCESSING}:
        raise HTTPException(status_code=409, detail="A parcela não está pendente para confirmação.")
    negotiation = _locked_negotiation(session, context, intent.negotiation_id)
    if negotiation.status not in ACTIVE_NEGOTIATIONS:
        raise HTTPException(status_code=409, detail="Negociação indisponível para confirmação.")
    _validate_source(session, negotiation)
    if intent.method == PaymentMethodEnum.CASH:
        cash = session.exec(select(CashSession).where(
            CashSession.id == intent.cash_session_id,
            CashSession.tenant_id == context.tenant_id,
            CashSession.store_id == negotiation.store_id,
        ).with_for_update()).first()
        if not cash or cash.status != CashSessionStatusEnum.OPEN:
            raise HTTPException(status_code=409, detail="A sessão de caixa foi encerrada.")
        movement = CashMovement(
            tenant_id=context.tenant_id, store_id=negotiation.store_id,
            cash_session_id=cash.id, actor_id=actor,
            movement_type=CashMovementTypeEnum.SALE_PAYMENT, amount=intent.amount,
            notes=f"Parcela da negociação {negotiation.id}",
        )
        session.add(movement)
        session.flush()
        intent.cash_movement_id = movement.id
    intent.status = PaymentIntentStatusEnum.CONFIRMED
    intent.confirmed_by = actor
    intent.confirmed_at = datetime.utcnow()
    intent.updated_at = datetime.utcnow()
    intent.confirm_idempotency_key = idempotency_key
    intent.confirm_request_hash = request_hash
    session.flush()
    totals = _totals(session, negotiation)
    negotiation.status = (
        CheckoutNegotiationStatusEnum.COVERED
        if totals["remaining_amount"] == 0
        else CheckoutNegotiationStatusEnum.PARTIALLY_COVERED
    )
    negotiation.version += 1
    negotiation.updated_at = datetime.utcnow()
    if negotiation.table_session_id:
        table_session = session.exec(select(TableSession).where(
            TableSession.id == negotiation.table_session_id,
            TableSession.tenant_id == context.tenant_id,
        ).with_for_update()).first()
        if table_session and table_session.status in ACTIVE_SESSIONS:
            table_session.status = TableSessionStatusEnum.PARTIALLY_PAID
            table_session.version += 1
            table_session.updated_at = datetime.utcnow()
            negotiation.source_version = table_session.version
    _event(session, negotiation, actor, "payment.intent.confirmed", {
        "payment_intent_id": str(intent.id), "amount": str(intent.amount),
        "confirmed_amount": str(totals["confirmed_amount"]),
        "remaining_amount": str(totals["remaining_amount"]),
    })
    session.commit()
    return projection(session, context, negotiation.id)


def fail_intent(
    session: Session, context: TenantContext, intent_id: uuid.UUID, *,
    failure_code: str, reason: str, actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> dict:
    actor = _actor(context, actor_id)
    payload = {"intent_id": str(intent_id), "failure_code": failure_code, "reason": reason, "actor_id": str(actor)}
    request_hash = reliability_service.compute_request_hash(payload)
    intent = session.exec(scope_tenant_query(select(PaymentIntent).where(
        PaymentIntent.id == intent_id,
    ).with_for_update(), PaymentIntent, context)).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Parcela não encontrada.")
    if intent.failure_idempotency_key:
        if intent.failure_idempotency_key != idempotency_key or intent.failure_request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Falha já registrada com outro comando.")
        return projection(session, context, intent.negotiation_id, validate=False)
    if intent.status not in {PaymentIntentStatusEnum.PENDING, PaymentIntentStatusEnum.PROCESSING}:
        raise HTTPException(status_code=409, detail="Somente parcelas pendentes podem falhar.")
    negotiation = _locked_negotiation(session, context, intent.negotiation_id)
    intent.status = PaymentIntentStatusEnum.FAILED
    intent.failure_code = failure_code
    intent.failure_reason = reason
    intent.failure_idempotency_key = idempotency_key
    intent.failure_request_hash = request_hash
    intent.failed_at = datetime.utcnow()
    intent.updated_at = datetime.utcnow()
    negotiation.version += 1
    negotiation.updated_at = datetime.utcnow()
    _event(session, negotiation, actor, "payment.intent.failed", {
        "payment_intent_id": str(intent.id), "amount": str(intent.amount),
        "failure_code": failure_code, "reason": reason,
    })
    session.commit()
    return projection(session, context, negotiation.id)


def finalize_negotiation(
    session: Session, context: TenantContext, negotiation_id: uuid.UUID, *,
    expected_version: int, actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> dict:
    actor = _actor(context, actor_id)
    payload = {"negotiation_id": str(negotiation_id), "expected_version": expected_version, "actor_id": str(actor)}
    request_hash = reliability_service.compute_request_hash(payload)
    negotiation = _locked_negotiation(session, context, negotiation_id)
    if negotiation.finalize_idempotency_key:
        if negotiation.finalize_idempotency_key != idempotency_key or negotiation.finalize_request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Finalização já registrada com outro comando.")
        return projection(session, context, negotiation.id, validate=False)
    if negotiation.version != expected_version:
        raise HTTPException(status_code=409, detail="Versão da negociação desatualizada.")
    if negotiation.status != CheckoutNegotiationStatusEnum.COVERED:
        raise HTTPException(status_code=409, detail="A conta ainda não possui cobertura financeira integral.")
    orders = _validate_source(session, negotiation)
    totals = _totals(session, negotiation)
    if totals["remaining_amount"] != 0:
        raise HTTPException(status_code=409, detail="Saldo restante impede a finalização.")
    sale = Sale(
        tenant_id=context.tenant_id, store_id=negotiation.store_id,
        source_type="ORDER_CHECKOUT", idempotency_key=f"negotiation:{negotiation.id}",
        fulfillment_type=FulfillmentTypeEnum.DINE_IN if negotiation.table_session_id else FulfillmentTypeEnum.COUNTER,
        operation_mode=SaleOperationModeEnum.COUNTER, seller_id=actor,
        status=SaleStatusEnum.PAID, gross_total=negotiation.subtotal,
        discount_total=negotiation.discount_total, approved_discount=negotiation.discount_total,
        net_total=negotiation.total_due, occurred_at=datetime.utcnow(),
        notes=f"Finalizada pela negociação {negotiation.id}",
    )
    session.add(sale)
    session.flush()
    for order in orders:
        items = session.exec(select(OrderItem).where(
            OrderItem.tenant_id == context.tenant_id,
            OrderItem.order_id == order.id,
            OrderItem.status == OrderItemStatusEnum.ACTIVE,
        )).all()
        for item in items:
            product = session.exec(select(Product).where(
                Product.id == item.product_id, Product.tenant_id == context.tenant_id,
            )).first()
            gross = _money(item.unit_price * item.quantity)
            session.add(SaleItem(
                tenant_id=context.tenant_id, sale_id=sale.id, product_id=item.product_id,
                product_name=item.product_name, sku=item.sku,
                item_type_snapshot=getattr(getattr(product, "item_type", None), "value", "PRODUCT"),
                tracks_inventory_snapshot=bool(getattr(product, "tracks_inventory", False)),
                requires_fulfillment_snapshot=bool(getattr(product, "requires_fulfillment", False)),
                unit_price=item.unit_price, quantity=item.quantity,
                gross_total=gross, net_total=gross,
            ))
        order.sale_id = sale.id
        order.status = OrderStatusEnum.CLOSED
        order.updated_at = datetime.utcnow()
    confirmed_intents = session.exec(select(PaymentIntent).where(
        PaymentIntent.tenant_id == context.tenant_id,
        PaymentIntent.negotiation_id == negotiation.id,
        PaymentIntent.status == PaymentIntentStatusEnum.CONFIRMED,
    )).all()
    for intent in confirmed_intents:
        session.add(Payment(
            tenant_id=context.tenant_id, store_id=negotiation.store_id, sale_id=sale.id,
            cash_session_id=intent.cash_session_id, method=intent.method,
            status=PaymentStatusEnum.CONFIRMED, amount=intent.amount,
            tendered_amount=intent.tendered_amount, change_amount=intent.change_amount,
            provider="CHECKOUT_ORCHESTRATOR", provider_event_id=f"intent:{intent.id}",
            transaction_ref=str(intent.id), confirmed_at=intent.confirmed_at,
        ))
    if negotiation.table_session_id:
        table_session = session.exec(select(TableSession).where(
            TableSession.id == negotiation.table_session_id,
            TableSession.tenant_id == context.tenant_id,
        ).with_for_update()).first()
        if not table_session or table_session.status not in ACTIVE_SESSIONS:
            raise HTTPException(status_code=409, detail="A sessão não pode ser liberada neste estado.")
        table_session.status = TableSessionStatusEnum.CLOSED
        table_session.closed_by = actor
        table_session.close_reason = "Conta coberta e negociação finalizada"
        table_session.closed_at = datetime.utcnow()
        table_session.updated_at = datetime.utcnow()
        table_session.version += 1
        if table_session.service_table_id:
            service_table = session.exec(select(ServiceTable).where(
                ServiceTable.id == table_session.service_table_id,
                ServiceTable.tenant_id == context.tenant_id,
            ).with_for_update()).first()
            if service_table:
                service_table.status = ServiceTableStatusEnum.AVAILABLE
                service_table.version += 1
                service_table.updated_at = datetime.utcnow()
    negotiation.sale_id = sale.id
    negotiation.status = CheckoutNegotiationStatusEnum.FINALIZED
    negotiation.finalized_by = actor
    negotiation.finalized_at = datetime.utcnow()
    negotiation.updated_at = datetime.utcnow()
    negotiation.version += 1
    negotiation.finalize_idempotency_key = idempotency_key
    negotiation.finalize_request_hash = request_hash
    _event(session, negotiation, actor, "checkout.negotiation.finalized", {
        "sale_id": str(sale.id), "total_due": str(negotiation.total_due),
        "payment_intent_ids": [str(item.id) for item in confirmed_intents],
    })
    session.commit()
    return projection(session, context, negotiation.id, validate=False)

import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.context import TenantContext, resolve_actor, scope_tenant_query
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
    Customer, FulfillmentTypeEnum, Sale, SaleItem, SaleOperationModeEnum, SaleStatusEnum,
)
from app.models.receivable import Receivable, ReceivableAllocation
from app.models.table_service import (
    ServiceTable, ServiceTableStatusEnum, TableSession, TableSessionStatusEnum,
)
from app.modules.settlement import contracts as settlement_contracts
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
    return resolve_actor(context, actor_id)


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


# An allocation held by an intent in one of these states is money already taken
# from the item: settled if the intent confirmed, reserved while it is still in
# flight. A failed or cancelled intent releases what it held.
SETTLED_INTENTS = {PaymentIntentStatusEnum.CONFIRMED}
RESERVED_INTENTS = {PaymentIntentStatusEnum.PENDING, PaymentIntentStatusEnum.PROCESSING}


def item_settlement(
    session: Session, negotiation: CheckoutNegotiation, *,
    item_ids: Optional[Iterable[uuid.UUID]] = None, lock: bool = False,
) -> dict[uuid.UUID, dict]:
    """How much of each item of this account is owed, settled and reserved.

    Money is the only financial truth here. An allocation carries an amount and
    never a quantity, because two canonical sources can disagree and half a
    pizza has no whole number of units; "one of four beers" is a reading the
    screen derives from ``amount / unit_price``, not a second fact in the ledger.

    The sums deliberately span *every* negotiation that touched the item, not
    only this one. What an item owes is a property of the item: while a bill
    scoped to the table and a bill scoped to one of its comandas can both exist,
    neither may spend the same whisky twice.

    ``lock`` takes the item rows FOR UPDATE, so a caller that is about to
    allocate decides against a state no concurrent transaction can move under it.
    """
    orders = _orders_for_negotiation(session, negotiation)
    if not orders:
        return {}
    query = select(OrderItem).where(
        OrderItem.tenant_id == negotiation.tenant_id,
        OrderItem.order_id.in_([order.id for order in orders]),
        OrderItem.status == OrderItemStatusEnum.ACTIVE,
    )
    if item_ids is not None:
        wanted = list(item_ids)
        if not wanted:
            return {}
        query = query.where(OrderItem.id.in_(wanted))
    if lock:
        query = query.with_for_update()
    items = list(session.exec(query.order_by(OrderItem.created_at)).all())
    if not items:
        return {}
    taken: dict[uuid.UUID, dict] = {}
    rows = session.exec(
        select(
            PaymentAllocation.order_item_id, PaymentIntent.status,
            PaymentIntent.payer_label, func.sum(PaymentAllocation.amount),
        )
        .join(PaymentIntent, PaymentIntent.id == PaymentAllocation.payment_intent_id)
        .where(
            PaymentAllocation.tenant_id == negotiation.tenant_id,
            PaymentAllocation.order_item_id.in_([item.id for item in items]),
        )
        .group_by(PaymentAllocation.order_item_id, PaymentIntent.status, PaymentIntent.payer_label)
    ).all()
    for item_id, intent_status, payer, total in rows:
        bucket = taken.setdefault(
            item_id, {"settled": Decimal("0"), "reserved": Decimal("0"), "settled_by": [], "reserved_by": []},
        )
        if intent_status in SETTLED_INTENTS:
            bucket["settled"] += _money(total or 0)
            if payer and payer not in bucket["settled_by"]:
                bucket["settled_by"].append(payer)
        elif intent_status in RESERVED_INTENTS:
            bucket["reserved"] += _money(total or 0)
            if payer and payer not in bucket["reserved_by"]:
                bucket["reserved_by"].append(payer)
    settlement = {}
    for item in items:
        bucket = taken.get(
            item.id, {"settled": Decimal("0"), "reserved": Decimal("0"), "settled_by": [], "reserved_by": []},
        )
        item_total = _money(_money(item.unit_price) * _money(item.quantity))
        settled, reserved = _money(bucket["settled"]), _money(bucket["reserved"])
        settlement[item.id] = {
            "order_item_id": item.id, "order_id": item.order_id,
            "product_name": item.product_name, "quantity": item.quantity,
            "unit_price": item.unit_price, "item_total": item_total,
            "settled_amount": settled, "reserved_amount": reserved,
            "available_amount": max(Decimal("0"), _money(item_total - settled - reserved)),
            "is_paid": item_total > 0 and settled >= item_total,
            # Who paid, when they said so. A parcel with no declared payer adds
            # nothing here rather than a guess.
            "settled_by": list(bucket["settled_by"]),
            "reserved_by": list(bucket["reserved_by"]),
        }
    return settlement


def coverage_breaches(session: Session, negotiation: CheckoutNegotiation) -> list[dict]:
    """Items whose value fell below the money already resting on them.

    The boundary is economic and per item — ``item_total >= settled + reserved``
    — and not "any item carrying an allocation is frozen". Cancelling a pizza
    nobody paid for is ordinary work and lowers what the table owes; reducing a
    whisky below what somebody already settled on it is a financial conflict and
    is refused. A pizza of R$80 with R$20 settled still accepts any change that
    leaves it at R$20 or more.
    """
    rows = session.exec(
        select(PaymentAllocation.order_item_id, func.sum(PaymentAllocation.amount))
        .join(PaymentIntent, PaymentIntent.id == PaymentAllocation.payment_intent_id)
        .where(
            PaymentAllocation.tenant_id == negotiation.tenant_id,
            PaymentAllocation.negotiation_id == negotiation.id,
            PaymentAllocation.order_item_id.is_not(None),
            PaymentIntent.status.in_(list(SETTLED_INTENTS | RESERVED_INTENTS)),
        )
        .group_by(PaymentAllocation.order_item_id)
    ).all()
    breaches = []
    for item_id, taken in rows:
        held = _money(taken or 0)
        item = session.get(OrderItem, item_id)
        worth = (
            _money(_money(item.unit_price) * _money(item.quantity))
            if item is not None and item.status == OrderItemStatusEnum.ACTIVE
            else Decimal("0")
        )
        if worth < held:
            breaches.append({
                "order_item_id": str(item_id),
                "product_name": item.product_name if item is not None else None,
                "item_total": str(worth), "covered": str(held),
            })
    return breaches


def reconcile_source(session: Session, negotiation: CheckoutNegotiation) -> list[Order]:
    """The bill follows the table instead of freezing away from it.

    A negotiation used to be the snapshot of an account that was closing: any
    change in consumption sent it to ``INVALIDATED`` and the operator had to
    reopen. That is wrong for the room this product serves. Marcelo settles his
    hamburger, someone orders another beer, and Astra must still be able to pay
    her whisky — the bill is a living thing while people are at the table.

    So consumption that *grows* is absorbed: the totals are recomputed, comandas
    opened after the bill join it, and every confirmed parcel and item
    allocation stays exactly where it was. Consumption that would fall below
    money already settled or reserved is refused — on the item by
    ``coverage_breaches``, and on the whole account by comparing against what is
    covered. That is a refund, not a reconciliation.

    A consequence worth naming: ``COVERED`` stops being terminal. Two beers
    arriving after the bill was fully paid return it to ``PARTIALLY_COVERED``
    with the new balance. The irreversible point is ``FINALIZED``.

    Nothing here commits. The caller owns the transaction, because a commit in
    the middle of ``confirm_intent`` would drop the row locks it depends on.
    """
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
        # A bill scoped to the table takes in the comandas the table gained. A
        # bill scoped to named Orders does not: whoever chose those Orders chose
        # them, and a group that sat down later is not part of that choice.
        if negotiation.scope_key.startswith("table-session:"):
            known = {order.id for order in orders}
            query = select(Order).where(
                Order.tenant_id == negotiation.tenant_id,
                Order.store_id == negotiation.store_id,
                Order.table_session_id == table_session.id,
                Order.status.in_([OrderStatusEnum.OPEN, OrderStatusEnum.SUBMITTED]),
            )
            if known:
                query = query.where(Order.id.notin_(list(known)))
            # A comanda already being paid in its own bill is not absorbed: it
            # belongs to whoever opened that bill, and taking it here would let
            # the same item be spent twice.
            taken = {row for row in session.exec(
                select(NegotiationOrder.order_id)
                .join(CheckoutNegotiation, CheckoutNegotiation.id == NegotiationOrder.negotiation_id)
                .where(
                    CheckoutNegotiation.tenant_id == negotiation.tenant_id,
                    CheckoutNegotiation.id != negotiation.id,
                    CheckoutNegotiation.status.in_(list(ACTIVE_NEGOTIATIONS)),
                )
            ).all()}
            for order in session.exec(query.with_for_update()).all():
                if order.id in taken:
                    continue
                session.add(NegotiationOrder(
                    tenant_id=negotiation.tenant_id, negotiation_id=negotiation.id,
                    order_id=order.id, amount_snapshot=_order_amount(session, order),
                ))
                orders.append(order)
    current = _source_version(table_session, orders)
    if current == negotiation.source_version:
        return orders
    breaches = coverage_breaches(session, negotiation)
    if breaches:
        raise HTTPException(status_code=409, detail={
            "code": "ITEM_BELOW_SETTLEMENT",
            "message": "Um item ficou abaixo do valor já liquidado ou reservado nele.",
            "items": breaches,
        })
    snapshots = {order.id: _order_amount(session, order) for order in orders}
    subtotal = _money(sum(snapshots.values(), Decimal("0")))
    total_due = _money(
        subtotal - negotiation.discount_total + negotiation.surcharge_total + negotiation.tax_total
    )
    previous = _totals(session, negotiation)
    covered = _money(previous["confirmed_amount"] + previous["receivable_amount"])
    if total_due < covered:
        raise HTTPException(status_code=409, detail={
            "code": "SETTLEMENT_ABOVE_CONSUMPTION",
            "message": "O consumo ficou abaixo do que já foi pago. Trate por estorno, não por reabertura.",
            "total_due": str(total_due), "covered": str(covered),
        })
    for row in session.exec(select(NegotiationOrder).where(
        NegotiationOrder.tenant_id == negotiation.tenant_id,
        NegotiationOrder.negotiation_id == negotiation.id,
    )).all():
        if row.order_id in snapshots:
            row.amount_snapshot = snapshots[row.order_id]
    previous_subtotal, previous_status = negotiation.subtotal, negotiation.status
    negotiation.subtotal = subtotal
    negotiation.total_due = total_due
    negotiation.source_version = current
    negotiation.version += 1
    negotiation.updated_at = datetime.utcnow()
    session.flush()
    totals = _totals(session, negotiation)
    if negotiation.status in ACTIVE_NEGOTIATIONS:
        if totals["remaining_amount"] == 0:
            negotiation.status = CheckoutNegotiationStatusEnum.COVERED
        elif totals["confirmed_amount"] > 0 or totals["receivable_amount"] > 0:
            negotiation.status = CheckoutNegotiationStatusEnum.PARTIALLY_COVERED
        else:
            negotiation.status = CheckoutNegotiationStatusEnum.OPEN
    _event(session, negotiation, negotiation.opened_by, "checkout.negotiation.reconciled", {
        "previous_subtotal": str(previous_subtotal), "subtotal": str(subtotal),
        "total_due": str(total_due), "remaining_amount": str(totals["remaining_amount"]),
        "previous_status": previous_status.value, "status": negotiation.status.value,
        "source_version": current,
    })
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
    receivable_covered = _money(session.exec(select(
        func.coalesce(func.sum(ReceivableAllocation.amount), 0)
    ).where(
        ReceivableAllocation.tenant_id == negotiation.tenant_id,
        ReceivableAllocation.negotiation_id == negotiation.id,
    )).one())
    remaining = max(Decimal("0"), _money(negotiation.total_due - confirmed - receivable_covered))
    return {
        "confirmed_amount": confirmed, "processing_amount": processing,
        "failed_amount": failed, "receivable_amount": receivable_covered,
        "remaining_amount": remaining, "intents": intents,
    }


def projection(session: Session, context: TenantContext, negotiation_id: uuid.UUID, validate: bool = True) -> dict:
    negotiation = session.exec(scope_tenant_query(
        select(CheckoutNegotiation).where(CheckoutNegotiation.id == negotiation_id),
        CheckoutNegotiation, context,
    )).first()
    if not negotiation:
        raise HTTPException(status_code=404, detail="Negociação não encontrada neste contexto.")
    if validate and negotiation.status in ACTIVE_NEGOTIATIONS:
        reconcile_source(session, negotiation)
        # A read is where the table's movement usually surfaces: someone opens
        # the bill and two beers have arrived since. Persisting it here is what
        # makes the next payer see the new balance instead of a stale one.
        if session.new or session.dirty:
            session.commit()
            session.refresh(negotiation)
    totals = _totals(session, negotiation)
    orders = list(session.exec(select(NegotiationOrder).where(
        NegotiationOrder.tenant_id == context.tenant_id,
        NegotiationOrder.negotiation_id == negotiation.id,
    )).all())
    allocations = list(session.exec(select(PaymentAllocation).where(
        PaymentAllocation.tenant_id == context.tenant_id,
        PaymentAllocation.negotiation_id == negotiation.id,
    )).all())
    # What each item still owes, so the screen can offer "pay these" and grey out
    # what someone else is already paying, without arithmetic in the browser.
    settlement = item_settlement(session, negotiation)
    assigned_settled = _money(sum((row["settled_amount"] for row in settlement.values()), Decimal("0")))
    assigned_reserved = _money(sum((row["reserved_amount"] for row in settlement.values()), Decimal("0")))
    return {
        "item_settlements": list(settlement.values()),
        # Money paid against the account without naming an item: whoever settled
        # the whole bill rather than their own share.
        "unassigned_settled_amount": max(Decimal("0"), _money(totals["confirmed_amount"] - assigned_settled)),
        "unassigned_reserved_amount": max(Decimal("0"), _money(totals["processing_amount"] - assigned_reserved)),
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
    # One live bill per comanda, whatever shape the scope has. The unique index
    # only guards an identical `scope_key`, and `table-session:<id>` and
    # `orders:<id>` are different strings — so the table's bill and a bill for
    # one of its comandas could both exist and spend the same whisky. The Orders
    # above are already locked FOR UPDATE, so two terminals opening at the same
    # instant serialise here rather than both winning.
    held = session.exec(
        select(NegotiationOrder.order_id, CheckoutNegotiation.scope_key)
        .join(CheckoutNegotiation, CheckoutNegotiation.id == NegotiationOrder.negotiation_id)
        .where(
            CheckoutNegotiation.tenant_id == context.tenant_id,
            CheckoutNegotiation.store_id == store_id,
            CheckoutNegotiation.status.in_(list(ACTIVE_NEGOTIATIONS)),
            NegotiationOrder.order_id.in_([order.id for order in orders]),
        )
    ).first()
    if held:
        raise HTTPException(status_code=409, detail={
            "code": "ORDER_ALREADY_IN_NEGOTIATION",
            "message": "Uma comanda desta conta já está sendo paga em outra conta aberta.",
            "order_id": str(held[0]), "held_by_scope": held[1],
        })
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
    payer_label: Optional[str] = None, payer_customer_id: Optional[uuid.UUID] = None,
) -> dict:
    actor = _actor(context, actor_id)
    normalized_amount = _money(amount)
    payload = {
        "negotiation_id": str(negotiation_id), "method": method.value,
        "amount": str(normalized_amount), "cash_session_id": str(cash_session_id) if cash_session_id else None,
        "tendered_amount": str(tendered_amount) if tendered_amount is not None else None,
        "allocations": allocations, "actor_id": str(actor),
        "payer_label": (payer_label or "").strip() or None,
        "payer_customer_id": str(payer_customer_id) if payer_customer_id else None,
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
    reconcile_source(session, negotiation)
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
    # A named customer must be this tenant's. An unnamed payer is fine: dividing
    # a bill between friends never requires registering anybody.
    if payer_customer_id and not session.exec(scope_tenant_query(
        select(Customer).where(Customer.id == payer_customer_id), Customer, context,
    )).first():
        raise HTTPException(status_code=404, detail="Cliente informado como pagador não existe neste contexto.")
    # The item invariant, decided here and not after the intent exists: nothing
    # may settle or reserve above what the item still has available. The read is
    # FOR UPDATE inside the transaction that already holds the negotiation, so
    # two terminals cannot both see the whisky as free and both take it.
    requested_by_item: dict[uuid.UUID, Decimal] = {}
    for allocation in allocations:
        if not allocation.get("order_item_id"):
            continue
        item_id = uuid.UUID(str(allocation["order_item_id"]))
        requested_by_item[item_id] = _money(requested_by_item.get(item_id, Decimal("0")) + _money(allocation["amount"]))
    item_state = item_settlement(session, negotiation, item_ids=requested_by_item, lock=True) if requested_by_item else {}
    for item_id, requested in requested_by_item.items():
        state = item_state.get(item_id)
        if not state:
            raise HTTPException(status_code=422, detail="Allocation aponta para item fora da negociação.")
        if requested > state["available_amount"]:
            raise HTTPException(status_code=409, detail={
                "code": "ITEM_SETTLEMENT_UNAVAILABLE",
                "order_item_id": str(item_id),
                "requested": str(requested),
                "available": str(state["available_amount"]),
                "settled": str(state["settled_amount"]),
                "reserved": str(state["reserved_amount"]),
            })
    intent = PaymentIntent(
        tenant_id=context.tenant_id, store_id=negotiation.store_id,
        negotiation_id=negotiation.id, cash_session_id=cash_session_id,
        method=method, amount=normalized_amount, tendered_amount=tendered,
        change_amount=change, provider="MANUAL_OPERATOR",
        payer_label=payload["payer_label"], payer_customer_id=payer_customer_id,
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
            # Already resolved, locked and checked above; the item carries its
            # own Order so an allocation cannot be filed under the wrong one.
            order_id = item_state[item_id]["order_id"]
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
    reconcile_source(session, negotiation)
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
            source_type="PAYMENT_INTENT", source_id=str(intent.id),
            idempotency_key=f"payment-intent:{intent.id}:cash",
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
    commit: bool = True,
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
    orders = reconcile_source(session, negotiation)
    totals = _totals(session, negotiation)
    if totals["remaining_amount"] != 0:
        raise HTTPException(status_code=409, detail="Saldo restante impede a finalização.")
    receivable_allocation = session.exec(select(ReceivableAllocation).where(
        ReceivableAllocation.tenant_id == context.tenant_id,
        ReceivableAllocation.negotiation_id == negotiation.id,
    )).first()
    receivable = None
    if receivable_allocation:
        receivable = session.exec(select(Receivable).where(
            Receivable.id == receivable_allocation.receivable_id,
            Receivable.tenant_id == context.tenant_id,
        ).with_for_update()).first()
    sale = Sale(
        tenant_id=context.tenant_id, store_id=negotiation.store_id,
        source_type="ORDER_CHECKOUT", idempotency_key=f"negotiation:{negotiation.id}",
        fulfillment_type=FulfillmentTypeEnum.DINE_IN if negotiation.table_session_id else FulfillmentTypeEnum.COUNTER,
        operation_mode=SaleOperationModeEnum.COUNTER, seller_id=actor,
        customer_id=receivable.customer_id if receivable else None,
        status=SaleStatusEnum.COMPLETED if receivable else SaleStatusEnum.PAID,
        gross_total=negotiation.subtotal,
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
                service_table.status = (ServiceTableStatusEnum.BLOCKED if service_table.blocking_reason
                                        else ServiceTableStatusEnum.AVAILABLE)
                service_table.version += 1
                service_table.updated_at = datetime.utcnow()
    negotiation.sale_id = sale.id
    if receivable:
        receivable.sale_id = sale.id
        receivable.updated_at = datetime.utcnow()
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
        "receivable_id": str(receivable.id) if receivable else None,
    })
    if commit:
        session.commit()
    else:
        session.flush()
    return projection(session, context, negotiation.id, validate=False)


def _hold_on_items(session: Session, order_item_ids) -> dict[uuid.UUID, Decimal]:
    """Finance answering the operation side, through the settlement port.

    Deliberately not scoped to one negotiation: what rests on an item rests on
    it whoever is paying, and a cancellation must see all of it.
    """
    wanted = list(order_item_ids)
    if not wanted:
        return {}
    rows = session.exec(
        select(PaymentAllocation.order_item_id, func.sum(PaymentAllocation.amount))
        .join(PaymentIntent, PaymentIntent.id == PaymentAllocation.payment_intent_id)
        .where(
            PaymentAllocation.order_item_id.in_(wanted),
            PaymentIntent.status.in_(list(SETTLED_INTENTS | RESERVED_INTENTS)),
        )
        .group_by(PaymentAllocation.order_item_id)
    ).all()
    return {item_id: _money(total or 0) for item_id, total in rows}


def _hold_on_orders(session: Session, order_ids) -> dict[uuid.UUID, Decimal]:
    """The same answer one step up, for a comanda about to change hands."""
    wanted = list(order_ids)
    if not wanted:
        return {}
    rows = session.exec(
        select(PaymentAllocation.order_id, func.sum(PaymentAllocation.amount))
        .join(PaymentIntent, PaymentIntent.id == PaymentAllocation.payment_intent_id)
        .where(
            PaymentAllocation.order_id.in_(wanted),
            PaymentIntent.status.in_(list(SETTLED_INTENTS | RESERVED_INTENTS)),
        )
        .group_by(PaymentAllocation.order_id)
    ).all()
    return {order_id: _money(total or 0) for order_id, total in rows}


settlement_contracts.register(_hold_on_items, _hold_on_orders)

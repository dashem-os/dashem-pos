import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.catalog import Product
from app.models.negotiation import (
    CheckoutNegotiation, CheckoutNegotiationStatusEnum, NegotiationEvent,
    NegotiationOrder, PaymentAllocation, PaymentIntent, PaymentIntentStatusEnum,
    PaymentIntentRefund, PaymentIntentRefundAllocation, PaymentIntentRefundRouteEnum,
    PaymentIntentRefundStatusEnum, PaymentSettlementDivergence, SettlementDivergenceKindEnum,
)
from app.models.provider import ProviderTransaction, ProviderTransactionStatusEnum
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
# Um estorno pedido nao move saldo; so o comprovadamente revertido move (ADR-030).
PROVEN_REFUNDS = {PaymentIntentRefundStatusEnum.CONFIRMED}
# E um estorno em curso nao pode ser pedido duas vezes sobre o mesmo dinheiro.
HOLDING_REFUNDS = {PaymentIntentRefundStatusEnum.PENDING, PaymentIntentRefundStatusEnum.CONFIRMED}


def reverted_by_item(
    session: Session, negotiation: CheckoutNegotiation, item_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, Decimal]:
    """Quanto ja voltou para o cliente, por linha da conta.

    Le apenas estorno **confirmado**: o que foi pedido e ainda espera prova nao
    devolve saldo nenhum, senao a linha ficaria pagavel duas vezes enquanto o
    adquirente ainda nem respondeu.
    """
    wanted = list(item_ids)
    if not wanted:
        return {}
    rows = session.exec(
        select(PaymentIntentRefundAllocation.order_item_id, func.sum(PaymentIntentRefundAllocation.amount))
        .join(PaymentIntentRefund, PaymentIntentRefund.id == PaymentIntentRefundAllocation.payment_intent_refund_id)
        .where(
            PaymentIntentRefundAllocation.tenant_id == negotiation.tenant_id,
            PaymentIntentRefund.status.in_(list(PROVEN_REFUNDS)),
            PaymentIntentRefundAllocation.order_item_id.in_(wanted),
        )
        .group_by(PaymentIntentRefundAllocation.order_item_id)
    ).all()
    return {item_id: _money(total or 0) for item_id, total in rows}


def refunds_for_intent(session: Session, intent: PaymentIntent) -> list[PaymentIntentRefund]:
    return list(session.exec(select(PaymentIntentRefund).where(
        PaymentIntentRefund.tenant_id == intent.tenant_id,
        PaymentIntentRefund.payment_intent_id == intent.id,
    ).order_by(PaymentIntentRefund.created_at)).all())


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
    # O que voltou para o cliente deixa de quitar a linha. Sem esta subtracao o
    # item seguiria pago por um dinheiro que ja saiu de volta (ADR-030).
    reverted = reverted_by_item(session, negotiation, [item.id for item in items])
    settlement = {}
    for item in items:
        bucket = taken.get(
            item.id, {"settled": Decimal("0"), "reserved": Decimal("0"), "settled_by": [], "reserved_by": []},
        )
        item_total = _money(_money(item.unit_price) * _money(item.quantity))
        settled = max(Decimal("0"), _money(bucket["settled"] - reverted.get(item.id, Decimal("0"))))
        reserved = _money(bucket["reserved"])
        settlement[item.id] = {
            "order_item_id": item.id, "order_id": item.order_id,
            "product_name": item.product_name, "quantity": item.quantity,
            "unit_price": item.unit_price, "item_total": item_total,
            "settled_amount": settled, "reserved_amount": reserved,
            "refunded_amount": _money(reverted.get(item.id, Decimal("0"))),
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
    gross_confirmed = _money(sum((item.amount for item in intents if item.status == PaymentIntentStatusEnum.CONFIRMED), Decimal("0")))
    # O dinheiro que voltou nao cobre mais a conta. Uma conta estornada ate zero
    # volta a dever o que devia, e e assim que `finalize_negotiation` a le.
    reverted = _money(session.exec(select(
        func.coalesce(func.sum(PaymentIntentRefund.reverted_amount), 0)
    ).where(
        PaymentIntentRefund.tenant_id == negotiation.tenant_id,
        PaymentIntentRefund.negotiation_id == negotiation.id,
        PaymentIntentRefund.status.in_(list(PROVEN_REFUNDS)),
    )).one())
    confirmed = max(Decimal("0"), _money(gross_confirmed - reverted))
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
        "gross_confirmed_amount": gross_confirmed, "refunded_amount": reverted,
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
    # Each parcel says what can still be done with it, so the screen never has
    # to guess whether cancelling would be refused. The answer is the server's.
    refunds = list(session.exec(select(PaymentIntentRefund).where(
        PaymentIntentRefund.tenant_id == context.tenant_id,
        PaymentIntentRefund.negotiation_id == negotiation.id,
    ).order_by(PaymentIntentRefund.created_at)).all())
    by_intent: dict[uuid.UUID, list[PaymentIntentRefund]] = {}
    for refund in refunds:
        by_intent.setdefault(refund.payment_intent_id, []).append(refund)
    parcels = []
    for row in totals["intents"]:
        charge = unresolved_charge(session, row) if row.status in OPEN_INTENTS else None
        mine = by_intent.get(row.id, [])
        reverted = _money(sum((item.reverted_amount for item in mine
                               if item.status in PROVEN_REFUNDS), Decimal("0")))
        held = _money(sum((item.amount for item in mine
                           if item.status == PaymentIntentRefundStatusEnum.PENDING), Decimal("0")))
        parcels.append({
            **row.model_dump(),
            "awaiting_provider": charge is not None,
            "provider_status": charge.status.value if charge is not None else None,
            "can_cancel": row.status in OPEN_INTENTS and charge is None,
            "can_query_provider": charge is not None,
            # Quanto ja voltou, quanto esta pedido a espera de prova, e quanto
            # ainda pode ser estornado. A tela nao deduz autoridade sozinha.
            "refunded_amount": reverted,
            "refund_pending_amount": held,
            "refundable_amount": max(Decimal("0"), _money(row.amount - reverted - held)),
            "can_refund": (
                row.status == PaymentIntentStatusEnum.CONFIRMED
                and _money(row.amount - reverted - held) > 0
            ),
            "awaiting_refund": held > 0,
        })
    divergences = list(session.exec(scope_tenant_query(
        select(PaymentSettlementDivergence).where(
            PaymentSettlementDivergence.payment_intent_id.in_([row.id for row in totals["intents"]] or [uuid.uuid4()]),
            PaymentSettlementDivergence.resolved_at.is_(None),
        ).order_by(PaymentSettlementDivergence.created_at),
        PaymentSettlementDivergence, context,
    )).all()) if totals["intents"] else []
    return {
        "item_settlements": list(settlement.values()),
        "divergences": divergences,
        "refunds": refunds,
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
        "orders": orders, "allocations": allocations, **{**totals, "intents": parcels},
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
    payment_device_binding_id: Optional[uuid.UUID] = None,
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
        "payment_device_binding_id": str(payment_device_binding_id) if payment_device_binding_id else None,
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
    # If this parcel is going out through a device, the chain is proved before
    # the reserve exists. The screen used to create the parcel and only then
    # discover the bridge was offline, leaving a line of the bill held by an
    # attempt that never happened.
    if payment_device_binding_id is not None:
        from app.services import provider_service  # local: provider imports this module
        provider_service.assert_executable_binding(
            session, context, payment_device_binding_id=payment_device_binding_id,
            store_id=negotiation.store_id, method=method,
        )
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
        payment_device_binding_id=payment_device_binding_id,
        # Only a reserve that declared a device carries a clock. For that one,
        # "no provider transaction" proves it was never sent. For cash or a
        # manual PIX nothing was ever going to be sent, so the same absence
        # proves nothing about the money and the server must not act on it —
        # that reserve waits for a person, who has an explicit cancellation.
        reserve_expires_at=(
            datetime.utcnow() + timedelta(seconds=settings.PAYMENT_RESERVE_TTL_SECONDS)
            if payment_device_binding_id is not None else None
        ),
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
    actor_id: Optional[uuid.UUID], idempotency_key: str, external: bool = False,
) -> dict:
    """Take the money in, and only when nothing outside contradicts it.

    Hand-confirming a card whose transaction is still unresolved would write a
    receipt the acquirer never issued, so it is refused the same way cancelling
    is. The provider's own result passes with ``external=True``.
    """
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
    if not external:
        _refuse_over_external_charge(session, intent, "confirm")
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
    intent.reserve_expires_at = None
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
    external: bool = False,
) -> dict:
    """Record that an attempt did not go through.

    Saying a payment failed is the provider's word. Until S25.1 this command
    took anyone's: it released the reserve after checking only that the parcel
    was open, so a card still authorising could be declared failed and its line
    handed to somebody else. It now refuses over a charge in flight unless the
    caller *is* the provider result (``external=True``).
    """
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
    if not external:
        _refuse_over_external_charge(session, intent, "fail")
    negotiation = _locked_negotiation(session, context, intent.negotiation_id)
    intent.reserve_expires_at = None
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


# ---------------------------------------------------------------------------
# S25.1 — recovering a reserve that was abandoned, or whose answer never came.
#
# Four operations, and the whole sprint is in keeping them apart:
#
#   cancel   the reserve was never sent; give the line back
#   fail     something was attempted and did not go through
#   expire   the server cancels an untouched reserve, and only that
#   refund   money left and came back; it is a reversal, never a release
#
# The rule that decides all of them, in the owner's words: never release money
# merely because the clock passed.
# ---------------------------------------------------------------------------

UNRESOLVED_PROVIDER = {
    ProviderTransactionStatusEnum.CREATED,
    ProviderTransactionStatusEnum.PROCESSING,
    ProviderTransactionStatusEnum.UNKNOWN,
}
OPEN_INTENTS = {PaymentIntentStatusEnum.PENDING, PaymentIntentStatusEnum.PROCESSING}
# A transaction that already has an answer. Reaching one of these is the end of
# the provider's side of the story; only REFUNDED may still follow CONFIRMED.
TERMINAL_PROVIDER = {
    ProviderTransactionStatusEnum.CONFIRMED,
    ProviderTransactionStatusEnum.FAILED,
    ProviderTransactionStatusEnum.CANCELED,
    ProviderTransactionStatusEnum.REFUNDED,
}


def provider_transactions_for(session: Session, intent: PaymentIntent) -> list[ProviderTransaction]:
    return list(session.exec(select(ProviderTransaction).where(
        ProviderTransaction.tenant_id == intent.tenant_id,
        ProviderTransaction.payment_intent_id == intent.id,
    ).order_by(ProviderTransaction.created_at)).all())


def unresolved_charge(session: Session, intent: PaymentIntent) -> Optional[ProviderTransaction]:
    """A charge whose answer has not reached this parcel.

    Two shapes, and the second is the one the review found. The obvious one is a
    transaction still in flight. The dangerous one is a transaction that *did*
    answer — CONFIRMED, say — while the parcel stayed open, which happens when
    the process dies between persisting the provider's result and applying it.
    Reading only the first shape let an operator cancel a parcel whose card had
    been approved.

    Either way the answer is the same: this parcel is not free to be released by
    hand. Absence of an answer here is not absence of a charge out there.
    """
    for transaction in provider_transactions_for(session, intent):
        if transaction.status in UNRESOLVED_PROVIDER:
            return transaction
        if transaction.status in TERMINAL_PROVIDER and intent.status in OPEN_INTENTS:
            # Answered outside, unapplied here: recoverable, never releasable.
            return transaction
    return None


def unapplied_results(session: Session, limit: int = 200) -> list[ProviderTransaction]:
    """Provider answers that were persisted and never reached their parcel.

    The window is real: `_apply_result` commits the transaction before touching
    the parcel, so a crash in between leaves the two disagreeing. This is what
    the worker sweeps, and what a query on the bill resolves on the spot.
    """
    # The filter belongs in the query, not after it. Taking the newest terminal
    # transactions and *then* keeping the unapplied ones meant a backlog older
    # than the page was never reached — the oldest stuck parcel, which is
    # exactly the one that has been holding a line the longest, was the first
    # to be ignored. Oldest first, so the backlog drains instead of growing.
    return list(session.exec(
        select(ProviderTransaction)
        .join(PaymentIntent, PaymentIntent.id == ProviderTransaction.payment_intent_id)
        .where(
            ProviderTransaction.status.in_(list(TERMINAL_PROVIDER)),
            PaymentIntent.status.in_(list(OPEN_INTENTS)),
        )
        .order_by(ProviderTransaction.updated_at)
        .limit(limit)
    ).all())


def _refuse_over_external_charge(session: Session, intent: PaymentIntent, action: str) -> None:
    charge = unresolved_charge(session, intent)
    if charge is None:
        return
    raise HTTPException(status_code=409, detail={
        "code": "EXTERNAL_CHARGE_IN_FLIGHT",
        "message": (
            "Existe cobrança externa sem resultado conhecido. "
            "Consulte o pagamento antes de decidir sobre esta parcela."
        ),
        "action": action,
        "payment_intent_id": str(intent.id),
        "provider_transaction_id": str(charge.id),
        "provider_status": charge.status.value,
    })


def record_divergence(
    session: Session, intent: PaymentIntent, *, kind: SettlementDivergenceKindEnum,
    provider_status: str, transaction_id: Optional[uuid.UUID], detail: str,
) -> Optional[PaymentSettlementDivergence]:
    """Write down what the provider said when the parcel could not hear it.

    Never applied, never discarded. The unique key makes a repeated or
    out-of-order event land on the same fact instead of a second one.
    """
    existing = session.exec(select(PaymentSettlementDivergence).where(
        PaymentSettlementDivergence.tenant_id == intent.tenant_id,
        PaymentSettlementDivergence.payment_intent_id == intent.id,
        PaymentSettlementDivergence.kind == kind,
        PaymentSettlementDivergence.provider_status == provider_status,
    )).first()
    if existing:
        return existing
    row = PaymentSettlementDivergence(
        tenant_id=intent.tenant_id, store_id=intent.store_id, payment_intent_id=intent.id,
        provider_transaction_id=transaction_id, kind=kind,
        intent_status=intent.status.value, provider_status=provider_status,
        amount=intent.amount, detail=detail,
    )
    session.add(row)
    session.flush()
    return row


def cancel_intent(
    session: Session, context: TenantContext, intent_id: uuid.UUID, *,
    reason: str, actor_id: Optional[uuid.UUID], idempotency_key: str,
    external: bool = False, external_status: Optional[str] = None,
) -> dict:
    """Give the line back because nothing was ever charged for it.

    This is deliberately not `fail_intent`. Failing says an attempt did not go
    through, and it is the provider's word to say so; cancelling says there was
    no attempt, and it is a person's decision. A parcel with a charge in flight
    is refused here, and the operator is sent to consult the payment instead.
    """
    actor = _actor(context, actor_id)
    payload = {"intent_id": str(intent_id), "reason": reason, "actor_id": str(actor)}
    request_hash = reliability_service.compute_request_hash(payload)
    intent = session.exec(scope_tenant_query(select(PaymentIntent).where(
        PaymentIntent.id == intent_id,
    ).with_for_update(), PaymentIntent, context)).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Parcela não encontrada.")
    if intent.cancel_idempotency_key:
        if intent.cancel_idempotency_key != idempotency_key or intent.cancel_request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Cancelamento já registrado com outro comando.")
        return projection(session, context, intent.negotiation_id, validate=False)
    if intent.status == PaymentIntentStatusEnum.CONFIRMED:
        raise HTTPException(status_code=409, detail={
            "code": "CONFIRMED_PAYMENT_NEEDS_REVERSAL",
            "message": "Pagamento confirmado não se cancela para liberar saldo; use o fluxo de estorno.",
            "payment_intent_id": str(intent.id),
        })
    if intent.status not in OPEN_INTENTS:
        raise HTTPException(status_code=409, detail="Somente parcela pendente ou em processamento pode ser cancelada.")
    if not external:
        _refuse_over_external_charge(session, intent, "cancel")
    negotiation = _locked_negotiation(session, context, intent.negotiation_id)
    now = datetime.utcnow()
    intent.status = PaymentIntentStatusEnum.CANCELED
    intent.cancel_reason = reason
    intent.canceled_by = actor
    intent.canceled_at = now
    intent.cancel_idempotency_key = idempotency_key
    intent.cancel_request_hash = request_hash
    intent.reserve_expires_at = None
    intent.updated_at = now
    negotiation.version += 1
    negotiation.updated_at = now
    _event(session, negotiation, actor, "payment.intent.canceled", {
        "payment_intent_id": str(intent.id), "amount": str(intent.amount),
        "reason": reason, "origin": "PROVIDER" if external else "OPERATOR",
        "provider_status": external_status,
    })
    reliability_service.write_audit_and_outbox(
        session, context.tenant_id, intent.store_id, actor,
        "checkout.payment.canceled", f"INTENT-{intent.id}",
        {"amount": str(intent.amount), "reason": reason, "origin": "PROVIDER" if external else "OPERATOR"},
        "payment_intent", str(intent.id), "checkout.payment.canceled",
        {"negotiation_id": str(negotiation.id), "amount": str(intent.amount)},
    )
    session.commit()
    return projection(session, context, negotiation.id)


def _refund_holdings(session: Session, intent: PaymentIntent) -> Decimal:
    """Quanto do valor da parcela ja esta comprometido por estornos.

    Confirmado conta pelo que foi provado; pendente conta pelo que foi pedido,
    porque dois pedidos nao podem disputar o mesmo dinheiro enquanto o
    adquirente ainda nem respondeu ao primeiro.
    """
    total = Decimal("0")
    for refund in refunds_for_intent(session, intent):
        if refund.status == PaymentIntentRefundStatusEnum.CONFIRMED:
            total += _money(refund.reverted_amount)
        elif refund.status == PaymentIntentRefundStatusEnum.PENDING:
            total += _money(refund.amount)
    return _money(total)


def _held_by_item(session: Session, intent: PaymentIntent) -> dict[uuid.UUID, Decimal]:
    rows = session.exec(
        select(PaymentIntentRefundAllocation.order_item_id, func.sum(PaymentIntentRefundAllocation.amount))
        .join(PaymentIntentRefund, PaymentIntentRefund.id == PaymentIntentRefundAllocation.payment_intent_refund_id)
        .where(
            PaymentIntentRefund.tenant_id == intent.tenant_id,
            PaymentIntentRefund.payment_intent_id == intent.id,
            PaymentIntentRefund.status.in_(list(HOLDING_REFUNDS)),
        )
        .group_by(PaymentIntentRefundAllocation.order_item_id)
    ).all()
    return {item_id: _money(total or 0) for item_id, total in rows if item_id is not None}


def _resolve_refund_allocations(
    session: Session, intent: PaymentIntent, amount: Decimal,
    requested: Optional[list[dict]],
) -> list[dict]:
    """Onde o dinheiro devolvido pousa, item a item.

    Por item, o revertido nunca passa do que **esta parcela** alocou nele. Quem
    pagou a conta toda sem nomear item estorna sem alocacao, e o valor sai do
    montante nao atribuido.
    """
    parcel = list(session.exec(select(PaymentAllocation).where(
        PaymentAllocation.tenant_id == intent.tenant_id,
        PaymentAllocation.payment_intent_id == intent.id,
    ).order_by(PaymentAllocation.created_at)).all())
    if not parcel:
        if requested:
            raise HTTPException(status_code=422, detail=(
                "Esta parcela nao foi alocada a itens; o estorno tambem nao pode ser."
            ))
        return []
    held = _held_by_item(session, intent)
    room = {}
    for allocation in parcel:
        if allocation.order_item_id is None:
            continue
        left = _money(allocation.amount - held.get(allocation.order_item_id, Decimal("0")))
        if left > 0:
            room[allocation.order_item_id] = {"amount": left, "order_id": allocation.order_id}
    if requested:
        resolved, total = [], Decimal("0")
        for line in requested:
            item_id = line.get("order_item_id")
            value = _money(line.get("amount") or 0)
            if item_id is None or value <= 0:
                raise HTTPException(status_code=422, detail="Alocacao de estorno invalida.")
            available = room.get(item_id)
            if available is None or value > available["amount"]:
                raise HTTPException(status_code=409, detail={
                    "code": "REFUND_EXCEEDS_ITEM",
                    "message": "O estorno de um item nao pode passar do que esta parcela pagou nele.",
                    "order_item_id": str(item_id),
                })
            resolved.append({"order_item_id": item_id, "order_id": available["order_id"], "amount": value})
            total += value
        if _money(total) != amount:
            raise HTTPException(status_code=422, detail=(
                "A soma das alocacoes do estorno precisa ser igual ao valor estornado."
            ))
        return resolved
    # Sem alocacao declarada, o estorno preenche as linhas da propria parcela na
    # ordem em que foram pagas. Para estorno integral isso reproduz exatamente as
    # alocacoes da parcela; para parcial, e deterministico e sem arredondamento.
    resolved, left = [], amount
    for allocation in parcel:
        if left <= 0:
            break
        available = room.get(allocation.order_item_id)
        if not available:
            continue
        take = min(available["amount"], left)
        resolved.append({
            "order_item_id": allocation.order_item_id,
            "order_id": available["order_id"], "amount": _money(take),
        })
        left = _money(left - take)
    return resolved


def _open_register(session: Session, context: TenantContext, store_id: uuid.UUID) -> CashSession:
    """O caixa aberto desta unidade, porque o dinheiro sai de uma gaveta real."""
    cash = session.exec(select(CashSession).where(
        CashSession.tenant_id == context.tenant_id,
        CashSession.store_id == store_id,
        CashSession.status == CashSessionStatusEnum.OPEN,
    ).order_by(CashSession.opened_at.desc()).with_for_update()).first()
    if not cash:
        raise HTTPException(status_code=409, detail={
            "code": "REFUND_NEEDS_OPEN_REGISTER",
            "message": (
                "Estorno em dinheiro exige caixa aberto nesta unidade: o valor sai "
                "da gaveta e precisa aparecer no fechamento."
            ),
        })
    return cash


def mark_refund_reverted(
    session: Session, refund: PaymentIntentRefund, *, reverted: Decimal, actor: uuid.UUID,
) -> None:
    """Marcar o que o mundo devolveu. Chamado so quando existe prova.

    Publica de proposito: quem recebe a resposta do adquirente e o
    provider_service, e a prova nasce la.
    """
    refund.reverted_amount = _money(reverted)
    refund.status = PaymentIntentRefundStatusEnum.CONFIRMED
    refund.confirmed_by = actor
    refund.confirmed_at = datetime.utcnow()
    refund.updated_at = datetime.utcnow()


def _restate_coverage(session: Session, negotiation: CheckoutNegotiation) -> dict:
    totals = _totals(session, negotiation)
    if totals["remaining_amount"] == 0:
        negotiation.status = CheckoutNegotiationStatusEnum.COVERED
    elif totals["confirmed_amount"] > 0 or totals["receivable_amount"] > 0:
        negotiation.status = CheckoutNegotiationStatusEnum.PARTIALLY_COVERED
    else:
        # Uma conta estornada ate zero volta a dever o que devia.
        negotiation.status = CheckoutNegotiationStatusEnum.OPEN
    negotiation.version += 1
    negotiation.updated_at = datetime.utcnow()
    return totals


def refund_intent(
    session: Session, context: TenantContext, intent_id: uuid.UUID, *,
    amount: Decimal, reason: str, allocations: Optional[list[dict]],
    actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> dict:
    """Devolver dinheiro de uma parcela confirmada, com a conta ainda aberta.

    ADR-030. A parcela confirmada continua confirmada: o estorno e escrito ao
    lado, e o saldo passa a ser lido como confirmado menos revertido. Um estorno
    *pedido* nao move saldo nenhum; so o comprovadamente revertido move, e o que
    conta como prova depende da rota pela qual o dinheiro entrou.
    """
    actor = _actor(context, actor_id)
    amount = _money(amount)
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Estorno exige motivo.")
    if amount <= 0:
        raise HTTPException(status_code=422, detail="Valor de estorno precisa ser positivo.")
    request_hash = reliability_service.compute_request_hash({
        "intent_id": str(intent_id), "amount": str(amount), "reason": reason,
        "actor_id": str(actor),
        "allocations": sorted(
            [f"{line.get('order_item_id')}:{_money(line.get('amount') or 0)}"
             for line in (allocations or [])]
        ),
    })
    existing = session.exec(scope_tenant_query(select(PaymentIntentRefund).where(
        PaymentIntentRefund.idempotency_key == idempotency_key,
    ), PaymentIntentRefund, context)).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Estorno ja registrado com outro comando.")
        return projection(session, context, existing.negotiation_id, validate=False)

    intent = session.exec(scope_tenant_query(select(PaymentIntent).where(
        PaymentIntent.id == intent_id,
    ).with_for_update(), PaymentIntent, context)).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Parcela nao encontrada.")
    if intent.status in OPEN_INTENTS:
        raise HTTPException(status_code=409, detail={
            "code": "PARCEL_NOT_SETTLED",
            "message": (
                "Esta parcela ainda nao foi confirmada; nao ha o que estornar. "
                "Cancele a reserva ou consulte a cobranca."
            ),
        })
    if intent.status != PaymentIntentStatusEnum.CONFIRMED:
        raise HTTPException(status_code=409, detail={
            "code": "PARCEL_NOT_SETTLED",
            "message": "Somente parcela confirmada pode ser estornada.",
        })
    negotiation = _locked_negotiation(session, context, intent.negotiation_id)
    if negotiation.status not in ACTIVE_NEGOTIATIONS:
        raise HTTPException(status_code=409, detail={
            "code": "NEGOTIATION_CLOSED",
            "message": (
                "A conta ja foi encerrada; o estorno da venda finalizada tem fluxo proprio."
            ),
        })
    taken = _refund_holdings(session, intent)
    if _money(amount + taken) > _money(intent.amount):
        raise HTTPException(status_code=409, detail={
            "code": "REFUND_EXCEEDS_PARCEL",
            "message": "O estorno passa do que esta parcela recebeu.",
            "already_refunded": str(taken), "parcel_amount": str(intent.amount),
        })
    resolved = _resolve_refund_allocations(session, intent, amount, allocations)

    charge = None
    if intent.method != PaymentMethodEnum.CASH:
        charge = session.exec(select(ProviderTransaction).where(
            ProviderTransaction.tenant_id == intent.tenant_id,
            ProviderTransaction.payment_intent_id == intent.id,
            ProviderTransaction.status == ProviderTransactionStatusEnum.CONFIRMED,
        ).order_by(ProviderTransaction.created_at.desc()).with_for_update()).first()
    if intent.method == PaymentMethodEnum.CASH:
        route = PaymentIntentRefundRouteEnum.CASH
    elif charge is not None:
        route = PaymentIntentRefundRouteEnum.PROVIDER
    else:
        route = PaymentIntentRefundRouteEnum.MANUAL

    # Caixa fechado nao e um estorno esperando: e uma condicao a satisfazer.
    # Conferir antes de escrever evita deixar um pedido pendente que nao pode
    # avancar e que ainda por cima segura saldo da parcela.
    cash = _open_register(session, context, negotiation.store_id) if route == PaymentIntentRefundRouteEnum.CASH else None

    refund = PaymentIntentRefund(
        tenant_id=context.tenant_id, store_id=negotiation.store_id,
        negotiation_id=negotiation.id, payment_intent_id=intent.id,
        amount=amount, reverted_amount=Decimal("0"),
        status=PaymentIntentRefundStatusEnum.PENDING, route=route, reason=reason,
        requested_by=actor, provider_transaction_id=charge.id if charge else None,
        idempotency_key=idempotency_key, request_hash=request_hash,
    )
    session.add(refund)
    session.flush()
    for line in resolved:
        session.add(PaymentIntentRefundAllocation(
            tenant_id=context.tenant_id, negotiation_id=negotiation.id,
            payment_intent_refund_id=refund.id, order_id=line["order_id"],
            order_item_id=line["order_item_id"], amount=line["amount"],
        ))

    if route == PaymentIntentRefundRouteEnum.CASH:
        movement = CashMovement(
            tenant_id=context.tenant_id, store_id=negotiation.store_id,
            cash_session_id=cash.id, actor_id=actor,
            movement_type=CashMovementTypeEnum.REFUND, amount=amount,
            notes=f"Estorno de parcela da negociacao {negotiation.id}: {reason}",
            source_type="PAYMENT_REFUND", source_id=str(refund.id),
            idempotency_key=f"payment-refund:{refund.id}:cash",
        )
        session.add(movement)
        session.flush()
        refund.cash_movement_id = movement.id
        # O dinheiro saiu da gaveta; a prova e o proprio movimento.
        mark_refund_reverted(session, refund, reverted=amount, actor=actor)
    elif route == PaymentIntentRefundRouteEnum.MANUAL:
        # Entrou pela palavra de uma pessoa, sai pela palavra de uma pessoa —
        # com nome, motivo e auditoria.
        mark_refund_reverted(session, refund, reverted=amount, actor=actor)
    else:
        # Cartao so volta pela resposta do adquirente, e so com valor declarado.
        # Ate la o estorno espera e nada e liberado.
        from app.services import provider_service

        provider_service.request_reversal(session, context, charge, refund, actor_id=actor)

    session.flush()
    totals = _restate_coverage(session, negotiation)
    _event(session, negotiation, actor, "payment.intent.refunded", {
        "payment_intent_id": str(intent.id), "payment_intent_refund_id": str(refund.id),
        "amount": str(amount), "route": route.value, "status": refund.status.value,
        "reverted_amount": str(refund.reverted_amount), "reason": reason,
        "confirmed_amount": str(totals["confirmed_amount"]),
        "remaining_amount": str(totals["remaining_amount"]),
    })
    reliability_service.write_audit_and_outbox(
        session, context.tenant_id, negotiation.store_id, actor,
        "checkout.payment.refunded", f"REFUND-{refund.id}",
        {
            "amount": str(amount), "reason": reason, "route": route.value,
            "status": refund.status.value, "payment_intent_id": str(intent.id),
        },
        "payment_intent_refund", str(refund.id), "checkout.payment.refunded",
        {
            "negotiation_id": str(negotiation.id), "payment_intent_id": str(intent.id),
            "amount": str(amount), "reverted_amount": str(refund.reverted_amount),
        },
    )
    session.commit()
    return projection(session, context, negotiation.id)


def settle_provider_reversal(
    session: Session, context: TenantContext, intent: PaymentIntent, *,
    transaction: ProviderTransaction, declared: Optional[Decimal], actor_id: uuid.UUID,
) -> bool:
    """Aplicar um estorno que o provider declarou com valor.

    Sem quantia nao ha prova, e o chamador segue para a divergencia. Com quantia,
    o estorno pendente que a pediu e confirmado; se ninguem pediu, o fato externo
    vira um estorno proprio, porque o dinheiro voltou de qualquer forma.
    """
    if declared is None or _money(declared) <= 0:
        return False
    declared = _money(declared)
    transaction.refunded_amount = declared
    pending = [row for row in refunds_for_intent(session, intent)
               if row.status == PaymentIntentRefundStatusEnum.PENDING]
    negotiation = session.exec(select(CheckoutNegotiation).where(
        CheckoutNegotiation.id == intent.negotiation_id,
        CheckoutNegotiation.tenant_id == intent.tenant_id,
    ).with_for_update()).first()
    if negotiation is None:
        return False
    if pending:
        refund = pending[0]
        # O adquirente pode reverter menos do que se pediu, e quem manda e ele.
        mark_refund_reverted(session, refund, reverted=min(declared, _money(refund.amount)), actor=actor_id)
    else:
        taken = _refund_holdings(session, intent)
        room = _money(intent.amount - taken)
        if room <= 0:
            return False
        value = min(declared, room)
        refund = PaymentIntentRefund(
            tenant_id=intent.tenant_id, store_id=intent.store_id,
            negotiation_id=intent.negotiation_id, payment_intent_id=intent.id,
            amount=value, reverted_amount=Decimal("0"),
            status=PaymentIntentRefundStatusEnum.PENDING,
            route=PaymentIntentRefundRouteEnum.PROVIDER,
            reason="Estorno informado pelo provider.",
            requested_by=actor_id, provider_transaction_id=transaction.id,
            idempotency_key=f"provider-refund:{transaction.id}",
            request_hash=reliability_service.compute_request_hash({
                "transaction_id": str(transaction.id), "amount": str(value),
            }),
        )
        session.add(refund)
        session.flush()
        for line in _resolve_refund_allocations(session, intent, value, None):
            session.add(PaymentIntentRefundAllocation(
                tenant_id=intent.tenant_id, negotiation_id=intent.negotiation_id,
                payment_intent_refund_id=refund.id, order_id=line["order_id"],
                order_item_id=line["order_item_id"], amount=line["amount"],
            ))
        mark_refund_reverted(session, refund, reverted=value, actor=actor_id)
    session.flush()
    totals = _restate_coverage(session, negotiation)
    _event(session, negotiation, actor_id, "payment.intent.refunded", {
        "payment_intent_id": str(intent.id), "payment_intent_refund_id": str(refund.id),
        "amount": str(refund.amount), "route": refund.route.value,
        "status": refund.status.value, "reverted_amount": str(refund.reverted_amount),
        "origin": "PROVIDER", "confirmed_amount": str(totals["confirmed_amount"]),
    })
    session.commit()
    return True


def expire_abandoned_reserves(session: Session, *, now: Optional[datetime] = None) -> list[uuid.UUID]:
    """Take back reserves the server can prove were never sent.

    Three conditions, and none of them is time alone: the clock ran out, the
    parcel declared a device it never used, and it has no provider transaction.

    The middle one is what the second review added, and it matters. A reserve
    with no transaction is only *provably* unsent when a transaction was due in
    the first place. Cash and manual PIX never produce one, so their absence
    says nothing — the money may be in the drawer with the parcel unconfirmed.
    Those wait for a person.
    """
    moment = now or datetime.utcnow()
    candidates = list(session.exec(select(PaymentIntent).where(
        PaymentIntent.status == PaymentIntentStatusEnum.PENDING,
        PaymentIntent.reserve_expires_at.is_not(None),
        PaymentIntent.reserve_expires_at <= moment,
        # Belt and braces: the clock is only ever set for a declared route, and
        # the sweep refuses to touch anything else even if one appeared.
        PaymentIntent.payment_device_binding_id.is_not(None),
    ).with_for_update(skip_locked=True)).all())
    expired = []
    for intent in candidates:
        if provider_transactions_for(session, intent):
            # It reached a provider at some point: this belongs to reconciliation.
            intent.reserve_expires_at = None
            intent.updated_at = moment
            continue
        negotiation = session.exec(select(CheckoutNegotiation).where(
            CheckoutNegotiation.id == intent.negotiation_id,
        ).with_for_update()).first()
        if not negotiation:
            continue
        intent.status = PaymentIntentStatusEnum.CANCELED
        # Deliberately narrow wording. Expiring says this registration was
        # never charged by the system; it does not claim nobody handed money
        # over the counter, and a manual receipt still has to be entered.
        intent.cancel_reason = (
            "Reserva expirada: o pagamento por dispositivo foi declarado e nunca "
            "enviado ao provider. Nenhuma cobrança externa existiu para esta parcela."
        )
        intent.canceled_by = intent.created_by
        intent.canceled_at = moment
        intent.reserve_expires_at = None
        intent.updated_at = moment
        negotiation.version += 1
        negotiation.updated_at = moment
        _event(session, negotiation, intent.created_by, "payment.intent.expired", {
            "payment_intent_id": str(intent.id), "amount": str(intent.amount),
        })
        expired.append(intent.id)
    session.commit()
    return expired


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


def locked_intent_for_query(
    session: Session, context: TenantContext, intent_id: uuid.UUID,
) -> PaymentIntent:
    """The parcel, in this tenant, ready to be asked about."""
    intent = session.exec(scope_tenant_query(select(PaymentIntent).where(
        PaymentIntent.id == intent_id,
    ), PaymentIntent, context)).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Parcela não encontrada.")
    return intent

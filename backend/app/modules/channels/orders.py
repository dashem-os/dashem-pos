"""Applying one stored channel event to the Order Engine.

S10.1, §3.4. Everything here runs inside the caller's transaction and commits
nothing: the order, its items, the mapping, the external lines, the contact and
the event status land together or not at all (H2, H3).

The outcome is either a return — `APPLIED` or `SUPERSEDED` — or one of two
exceptions that carry a **code**, never content: `Quarantine`, for what cannot be
applied until something is fixed, and `NeedsReview`, for what a person has to
decide. The caller rolls back on either and records the code.

Identity is external: an order is its external order id on its connection, and a
line is its external line id. Repeating or reordering events never duplicates an
item, and an update is a comparison of lines, not an append.
"""

from dataclasses import dataclass
import secrets
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.context import TenantContext
from app.models.channel_catalog import CatalogEntityTypeEnum, ChannelCatalogMapping
from app.models.channel_hub import (
    ChannelInboxEvent, ChannelInboxStatusEnum, ChannelOrderContact, ChannelOrderLine,
    ChannelOrderLineStatusEnum, ChannelRetentionBasisEnum, ExternalOrderMapping,
    ExternalOrderTerminalStateEnum, MerchantConnection,
)
from app.models.order import Order, OrderFulfillmentEnum, OrderItem, OrderItemStatusEnum
from app.modules.channels import retention
from app.modules.channels.contracts import (
    ExternalContact, ExternalEvent, ExternalEventKind, ExternalOrder, ExternalOrderLine,
    ExternalPaymentOrigin, IngressEnvelope, PayloadRejected,
)
from app.modules.settlement import contracts as settlement
from app.services import order_service

MONEY = Decimal("0.0001")
MAX_MONEY = Decimal("9999999999.9999")


class Quarantine(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code[:80]


class NeedsReview(Exception):
    def __init__(self, code: str, order_id: Optional[uuid.UUID] = None) -> None:
        super().__init__(code)
        self.code = code[:80]
        self.order_id = order_id


@dataclass(frozen=True)
class _ResolvedLine:
    line: ExternalOrderLine
    product_id: uuid.UUID
    modifier_ids: list[uuid.UUID]
    quantity: Decimal
    unit_amount: Decimal
    discount_amount: Optional[Decimal]
    effective_unit_amount: Decimal
    net_line_amount: Decimal
    local_unit_amount: Decimal
    local_line_amount: Decimal
    difference_amount: Decimal
    preparation_notes: Optional[str]


@dataclass(frozen=True)
class _ValidatedOrderAmounts:
    delivery_fee: Optional[Decimal]
    channel_discount: Optional[Decimal]
    channel_subsidy: Optional[Decimal]
    declared_total: Optional[Decimal]
    local_items_amount: Decimal
    difference_amount: Decimal
    effective_merchandise_amount: Decimal
    expected_total: Decimal


def _exact_money(
    value: object, code: str = "CHANNEL_AMOUNT_INVALID",
    order_id: Optional[uuid.UUID] = None, *, allow_zero: bool = True,
) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise NeedsReview("CHANNEL_AMOUNT_INVALID", order_id) from None
    if not amount.is_finite():
        raise NeedsReview("CHANNEL_AMOUNT_INVALID", order_id)
    if amount < Decimal("0") or (not allow_zero and amount == Decimal("0")):
        raise NeedsReview("CHANNEL_AMOUNT_INVALID", order_id)
    if amount > MAX_MONEY:
        raise NeedsReview("CHANNEL_AMOUNT_INVALID", order_id)
    try:
        quantized = amount.quantize(MONEY)
    except InvalidOperation:
        raise NeedsReview("CHANNEL_AMOUNT_INVALID", order_id) from None
    if amount != quantized:
        raise NeedsReview("CHANNEL_AMOUNT_INVALID", order_id)
    return quantized


def _exact_signed_money(
    value: object, order_id: Optional[uuid.UUID] = None,
) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise NeedsReview("CHANNEL_AMOUNT_INVALID", order_id) from None
    if not amount.is_finite() or abs(amount) > MAX_MONEY:
        raise NeedsReview("CHANNEL_AMOUNT_INVALID", order_id)
    try:
        quantized = amount.quantize(MONEY)
    except InvalidOperation:
        raise NeedsReview("CHANNEL_AMOUNT_INVALID", order_id) from None
    if amount != quantized:
        raise NeedsReview("CHANNEL_AMOUNT_INVALID", order_id)
    return quantized


def normalize(adapter, connection: MerchantConnection, row: ChannelInboxEvent) -> ExternalEvent:
    if row.raw_payload is None:
        raise Quarantine("PAYLOAD_PURGED")
    envelope = IngressEnvelope(
        provider_event_id=row.provider_event_id, merchant_external_id=connection.merchant_external_id,
        event_type=row.event_type, payload=row.raw_payload, external_order_id=row.external_order_id,
    )
    try:
        return adapter.normalize(envelope)
    except PayloadRejected as rejection:
        raise Quarantine(f"PAYLOAD_{rejection.code}") from None


def apply(
    session: Session, context: TenantContext, connection: MerchantConnection,
    row: ChannelInboxEvent, event: ExternalEvent, now: datetime,
) -> tuple[ChannelInboxStatusEnum, Optional[ExternalOrderMapping]]:
    row.parser_version = event.parser_version
    row.order_key = event.order_key
    row.external_order_id = event.external_order_id

    mapping = session.exec(select(ExternalOrderMapping).where(
        ExternalOrderMapping.merchant_connection_id == connection.id,
        ExternalOrderMapping.external_order_id == event.external_order_id,
    )).first()

    if mapping is None:
        if event.kind != ExternalEventKind.ORDER_PLACED:
            # A change for an order that has not arrived. Kept on its reception
            # clock and retaken as soon as the order is applied.
            raise Quarantine("ORDER_NOT_YET_RECEIVED")
        mapping = _open(session, context, connection, event, now)
        return ChannelInboxStatusEnum.APPLIED, mapping

    order = session.exec(select(Order).where(Order.id == mapping.order_id)).first()
    if not order:
        raise Quarantine("ORDER_NOT_YET_RECEIVED")
    if _stale(mapping, event) or mapping.terminal_at is not None or order.status in order_service.TERMINAL_ORDER_STATES:
        # Older than what was applied, or after the order ended: recorded, never
        # applied, and the order does not move backwards (H5).
        return ChannelInboxStatusEnum.SUPERSEDED, mapping

    actor = connection.service_actor_id
    if event.kind in {ExternalEventKind.ORDER_PLACED, ExternalEventKind.ORDER_UPDATED}:
        if not _update(session, context, connection, mapping, order, event, actor, now):
            return ChannelInboxStatusEnum.SUPERSEDED, mapping
    elif event.kind == ExternalEventKind.ORDER_CANCELLED:
        coverage = settlement.coverage_on_orders(session, [order.id]).get(
            order.id, settlement.OrderCoverage(order_id=order.id)
        )
        mapping = session.exec(
            select(ExternalOrderMapping)
            .where(ExternalOrderMapping.id == mapping.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        order = session.get(Order, mapping.order_id)
        if _stale(mapping, event) or mapping.terminal_at is not None or order.status in order_service.TERMINAL_ORDER_STATES:
            return ChannelInboxStatusEnum.SUPERSEDED, mapping
        _refuse_if_preparing(session, context, order)
        items = list(session.exec(select(OrderItem).where(
            OrderItem.tenant_id == context.tenant_id, OrderItem.order_id == order.id,
            OrderItem.status == OrderItemStatusEnum.ACTIVE,
        ).order_by(OrderItem.id).with_for_update().execution_options(populate_existing=True)).all())
        items_held = sum(
            settlement.hold_on_items(session, [item.id for item in items]).values(),
            Decimal("0.0000"),
        )
        order_held = settlement.hold_on_orders(session, [order.id]).get(order.id, Decimal("0.0000"))
        order_covered = max(order_held, coverage.order_covered, items_held)
        if items_held > Decimal("0.0000") or order_covered > Decimal("0.0000"):
            raise NeedsReview("ITEM_BELOW_SETTLEMENT", order.id)
        if coverage.joint_covered > Decimal("0.0000") and (
            coverage.joint_total_with(Decimal("0.0000")) < coverage.joint_covered
        ):
            raise NeedsReview("ITEM_BELOW_SETTLEMENT", order.id)
        _map_http(lambda: order_service.cancel_external_order(
            session, context, order, reason="Cancelado pelo canal", actor_id=actor,
            coverage=coverage,
        ), order.id)
        for line in _lines(session, mapping):
            line.status = ChannelOrderLineStatusEnum.CANCELED
            line.updated_at = now
            session.add(line)
        retention.anchor_terminal(session, mapping, ExternalOrderTerminalStateEnum.CANCELED, now)
    elif event.kind == ExternalEventKind.ORDER_CONCLUDED:
        settlement.coverage_on_orders(session, [order.id])
        mapping = session.exec(
            select(ExternalOrderMapping)
            .where(ExternalOrderMapping.id == mapping.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        order = session.get(Order, mapping.order_id)
        if _stale(mapping, event) or mapping.terminal_at is not None or order.status in order_service.TERMINAL_ORDER_STATES:
            return ChannelInboxStatusEnum.SUPERSEDED, mapping
        _map_http(lambda: order_service.conclude_external_order(session, context, order, actor_id=actor), order.id)
        retention.anchor_terminal(session, mapping, ExternalOrderTerminalStateEnum.CONCLUDED, now)
    _upsert_contact(session, mapping, event.contact, now)
    _advance(mapping, event)
    return ChannelInboxStatusEnum.APPLIED, mapping


def _stale(mapping: ExternalOrderMapping, event: ExternalEvent) -> bool:
    return bool(event.order_key and mapping.last_order_key and event.order_key <= mapping.last_order_key)


def _advance(mapping: ExternalOrderMapping, event: ExternalEvent) -> None:
    if event.order_key and (mapping.last_order_key is None or event.order_key > mapping.last_order_key):
        mapping.last_order_key = event.order_key


def _map_http(action, order_id: Optional[uuid.UUID] = None):
    try:
        return action()
    except HTTPException as exc:
        if isinstance(exc.detail, dict) and exc.detail.get("code") == "ITEM_BELOW_SETTLEMENT":
            raise NeedsReview("ITEM_BELOW_SETTLEMENT", order_id) from None
        # The Order Engine refused: product unavailable, no price, journey not
        # contracted. Its message is not kept — only that it refused.
        raise Quarantine("ORDER_ENGINE_REFUSED") from None


def _mapped(session: Session, connection: MerchantConnection, entity: CatalogEntityTypeEnum, code: str, missing: str) -> uuid.UUID:
    mapping = session.exec(select(ChannelCatalogMapping).where(
        ChannelCatalogMapping.merchant_connection_id == connection.id,
        ChannelCatalogMapping.entity_type == entity,
        ChannelCatalogMapping.external_id == code,
    )).first()
    if mapping is None:
        raise Quarantine(missing)
    return mapping.internal_id


def _resolve_line(
    session: Session, context: TenantContext, connection: MerchantConnection,
    line: ExternalOrderLine, *, order_id: Optional[uuid.UUID] = None,
    stored_local_unit_amount: Optional[Decimal] = None,
) -> _ResolvedLine:
    product_id = _mapped(session, connection, CatalogEntityTypeEnum.PRODUCT, line.external_item_code, "ITEM_NOT_MAPPED")
    modifier_ids = [
        _mapped(session, connection, CatalogEntityTypeEnum.MODIFIER, code, "MODIFIER_NOT_MAPPED")
        for code in line.modifier_codes
    ]
    if stored_local_unit_amount is not None:
        local_unit_amount = _exact_money(stored_local_unit_amount, order_id=order_id)
    else:
        raw_local_unit = _map_http(
            lambda: order_service.local_offer_unit_price(
                session, context, store_id=connection.store_id,
                product_id=product_id, modifier_ids=modifier_ids,
            ),
            order_id,
        )
        local_unit_amount = _exact_money(raw_local_unit, order_id=order_id)
    # D1/H7: the channel's declared unit price governs the order item; missing or
    # unsafe channel values never fall back silently to `local_unit_amount`.
    if line.unit_amount is None:
        raise NeedsReview("CHANNEL_PRICE_MISSING", order_id)
    quantity = _exact_money(line.quantity, order_id=order_id, allow_zero=False)
    unit_amount = _exact_money(line.unit_amount, order_id=order_id)
    gross_line_amount = _exact_money(unit_amount * quantity, order_id=order_id)
    discount_amount = (
        _exact_money(line.discount_amount, order_id=order_id)
        if line.discount_amount is not None else None
    )
    line_discount = discount_amount if discount_amount is not None else Decimal("0.0000")
    if line_discount > gross_line_amount:
        raise NeedsReview("CHANNEL_DISCOUNT_EXCEEDS_AMOUNT", order_id)
    net_line_amount = gross_line_amount - line_discount
    effective_unit_amount = (net_line_amount / quantity).quantize(MONEY)
    if effective_unit_amount * quantity != net_line_amount:
        raise NeedsReview("CHANNEL_LINE_TOTAL_INEXACT", order_id)
    local_line_amount = _exact_money(local_unit_amount * quantity, order_id=order_id)
    difference_amount = _exact_signed_money(net_line_amount - local_line_amount, order_id=order_id)
    return _ResolvedLine(
        line=line, product_id=product_id, modifier_ids=modifier_ids,
        quantity=quantity, unit_amount=unit_amount, discount_amount=discount_amount,
        effective_unit_amount=effective_unit_amount, net_line_amount=net_line_amount,
        local_unit_amount=local_unit_amount, local_line_amount=local_line_amount,
        difference_amount=difference_amount, preparation_notes=line.preparation_notes,
    )


def _validate_order_amounts(
    external: ExternalOrder, resolved_lines: list[_ResolvedLine],
    order_id: Optional[uuid.UUID] = None,
) -> _ValidatedOrderAmounts:
    """Validate order-level channel figures against resolved lines without double-counting discounts."""
    net_items_amount = _exact_money(
        sum((row.net_line_amount for row in resolved_lines), Decimal("0.0000")),
        order_id=order_id,
    )
    line_discounts_amount = _exact_money(
        sum(
            ((row.discount_amount or Decimal("0.0000")) for row in resolved_lines),
            Decimal("0.0000"),
        ),
        order_id=order_id,
    )
    local_items_amount = _exact_money(
        sum((row.local_line_amount for row in resolved_lines), Decimal("0.0000")),
        order_id=order_id,
    )
    delivery_fee = (
        _exact_money(external.delivery_fee, order_id=order_id)
        if external.delivery_fee is not None else None
    )
    order_discount = (
        _exact_money(external.channel_discount, order_id=order_id)
        if external.channel_discount is not None else None
    )
    subsidy = (
        _exact_money(external.channel_subsidy, order_id=order_id)
        if external.channel_subsidy is not None else None
    )
    declared_total = (
        _exact_money(external.declared_total, order_id=order_id)
        if external.declared_total is not None else None
    )
    discount_val = order_discount if order_discount is not None else Decimal("0.0000")
    delivery_val = delivery_fee if delivery_fee is not None else Decimal("0.0000")
    if discount_val > net_items_amount:
        raise NeedsReview("CHANNEL_DISCOUNT_EXCEEDS_AMOUNT", order_id)
    total_discounts = _exact_money(line_discounts_amount + discount_val, order_id=order_id)
    if subsidy is not None and subsidy > total_discounts:
        raise NeedsReview("CHANNEL_SUBSIDY_INCONSISTENT", order_id)
    effective_merchandise_amount = _exact_money(net_items_amount - discount_val, order_id=order_id)
    expected_total = _exact_money(effective_merchandise_amount + delivery_val, order_id=order_id)
    if declared_total is not None and declared_total != expected_total:
        raise NeedsReview("CHANNEL_TOTAL_MISMATCH", order_id)
    difference_amount = _exact_signed_money(
        effective_merchandise_amount - local_items_amount, order_id=order_id,
    )
    return _ValidatedOrderAmounts(
        delivery_fee=delivery_fee,
        channel_discount=order_discount,
        channel_subsidy=subsidy,
        declared_total=declared_total,
        local_items_amount=local_items_amount,
        difference_amount=difference_amount,
        effective_merchandise_amount=effective_merchandise_amount,
        expected_total=expected_total,
    )


def _normalize_payment_origin(value: Optional[str]) -> ExternalPaymentOrigin:
    if isinstance(value, ExternalPaymentOrigin):
        return value
    raw = str(value or "").strip().upper()
    if raw in {item.value for item in ExternalPaymentOrigin}:
        return ExternalPaymentOrigin(raw)
    return ExternalPaymentOrigin.UNKNOWN


def _open(
    session: Session, context: TenantContext, connection: MerchantConnection,
    event: ExternalEvent, now: datetime,
) -> ExternalOrderMapping:
    external = event.order
    resolved = [_resolve_line(session, context, connection, line) for line in external.lines]
    amounts = _validate_order_amounts(external, resolved)
    order, items = _map_http(lambda: order_service.open_external_order(
        session, context, store_id=connection.store_id, channel_id=connection.channel_id,
        idempotency_key=f"channel:{connection.id}:{external.external_order_id}",
        external_reference=external.external_order_id,
        fulfillment=OrderFulfillmentEnum(external.fulfillment),
        lines=[
            (row.product_id, row.quantity, row.modifier_ids, row.preparation_notes, row.effective_unit_amount)
            for row in resolved
        ],
        actor_id=connection.service_actor_id,
    ))
    mapping = ExternalOrderMapping(
        tenant_id=connection.tenant_id, store_id=connection.store_id,
        merchant_connection_id=connection.id, external_order_id=external.external_order_id,
        order_id=order.id, payment_origin=_normalize_payment_origin(external.payment_origin).value,
    )
    _declared_amounts(mapping, external, amounts)
    _advance(mapping, event)
    session.add(mapping)
    session.flush()
    for row, item in zip(resolved, items):
        session.add(ChannelOrderLine(
            tenant_id=connection.tenant_id, store_id=connection.store_id,
            external_order_mapping_id=mapping.id, external_line_id=row.line.external_line_id,
            external_item_code=row.line.external_item_code, order_item_id=item.id,
            quantity=row.quantity, unit_amount=row.unit_amount, discount_amount=row.discount_amount,
            local_unit_amount=row.local_unit_amount, difference_amount=row.difference_amount,
            modifier_codes=list(row.line.modifier_codes), created_at=now, updated_at=now,
        ))
    _upsert_contact(session, mapping, event.contact, now)
    return mapping


def _declared_amounts(
    mapping: ExternalOrderMapping, external: ExternalOrder, amounts: _ValidatedOrderAmounts,
) -> bool:
    next_payment_origin = _normalize_payment_origin(external.payment_origin).value
    changed = (
        mapping.delivery_fee != amounts.delivery_fee
        or mapping.channel_discount != amounts.channel_discount
        or mapping.channel_subsidy != amounts.channel_subsidy
        or mapping.declared_total != amounts.declared_total
        or mapping.local_items_amount != amounts.local_items_amount
        or mapping.difference_amount != amounts.difference_amount
        or mapping.payment_origin != next_payment_origin
    )
    mapping.delivery_fee = amounts.delivery_fee
    mapping.channel_discount = amounts.channel_discount
    mapping.channel_subsidy = amounts.channel_subsidy
    mapping.declared_total = amounts.declared_total
    mapping.local_items_amount = amounts.local_items_amount
    mapping.difference_amount = amounts.difference_amount
    mapping.payment_origin = next_payment_origin
    return changed


def _lines(session: Session, mapping: ExternalOrderMapping) -> list[ChannelOrderLine]:
    return list(session.exec(select(ChannelOrderLine).where(
        ChannelOrderLine.external_order_mapping_id == mapping.id,
        ChannelOrderLine.status == ChannelOrderLineStatusEnum.ACTIVE,
    ).execution_options(populate_existing=True)).all())


def _preparing(item: Optional[OrderItem]) -> bool:
    return item is not None and item.production_state in order_service.PREPARATION_STARTED


def _refuse_if_preparing(session: Session, context: TenantContext, order: Order) -> None:
    items = session.exec(select(OrderItem).where(
        OrderItem.tenant_id == context.tenant_id, OrderItem.order_id == order.id,
        OrderItem.status == OrderItemStatusEnum.ACTIVE,
    ).execution_options(populate_existing=True)).all()
    if any(_preparing(item) for item in items):
        # D2, conservative until decided: the kitchen started, a person decides.
        raise NeedsReview("PREPARATION_STARTED", order.id)


def _line_changed(stored: ChannelOrderLine, item: Optional[OrderItem], resolved: _ResolvedLine) -> bool:
    return (
        stored.external_item_code != resolved.line.external_item_code
        or stored.modifier_codes != list(resolved.line.modifier_codes)
        or stored.quantity != resolved.quantity
        or stored.unit_amount != resolved.unit_amount
        or stored.discount_amount != resolved.discount_amount
        or (item is not None and item.unit_price != resolved.effective_unit_amount)
        or (item is not None and item.notes != resolved.preparation_notes)
    )


def _update(
    session: Session, context: TenantContext, connection: MerchantConnection,
    mapping: ExternalOrderMapping, order: Order, event: ExternalEvent,
    actor: uuid.UUID, now: datetime,
) -> bool:
    """Compare lines, decide everything, and only then change anything.

    If any change touches an item already being prepared, nothing is applied:
    a half-applied update would leave the order matching neither the channel nor
    the kitchen.
    """
    external = event.order
    current = {line.external_line_id: line for line in _lines(session, mapping)}
    incoming = {line.external_line_id: line for line in external.lines}
    resolved_all: list[_ResolvedLine] = []
    for line in external.lines:
        stored = current.get(line.external_line_id)
        same_offer = (
            stored is not None
            and stored.external_item_code == line.external_item_code
            and stored.modifier_codes == list(line.modifier_codes)
            and stored.local_unit_amount is not None
        )
        resolved_all.append(_resolve_line(
            session, context, connection, line, order_id=order.id,
            stored_local_unit_amount=stored.local_unit_amount if same_offer else None,
        ))
    amounts = _validate_order_amounts(external, resolved_all, order_id=order.id)

    coverage = settlement.coverage_on_orders(session, [order.id]).get(
        order.id,
        settlement.OrderCoverage(order_id=order.id),
    )
    mapping = session.exec(
        select(ExternalOrderMapping)
        .where(ExternalOrderMapping.id == mapping.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    order = session.get(Order, mapping.order_id)
    if _stale(mapping, event) or mapping.terminal_at is not None or order.status in order_service.TERMINAL_ORDER_STATES:
        return False

    current = {line.external_line_id: line for line in _lines(session, mapping)}
    items = {
        item.id: item for item in session.exec(select(OrderItem).where(
            OrderItem.tenant_id == context.tenant_id, OrderItem.order_id == order.id,
        ).order_by(OrderItem.id).with_for_update().execution_options(populate_existing=True)).all()
    }
    active_item_ids = [
        item.id for item in items.values()
        if item.status == OrderItemStatusEnum.ACTIVE
    ]
    items_held = sum(
        settlement.hold_on_items(session, active_item_ids).values(),
        Decimal("0.0000"),
    )
    order_held = settlement.hold_on_orders(session, [order.id]).get(order.id, Decimal("0.0000"))
    order_covered = max(order_held, coverage.order_covered, items_held)
    has_local_coverage = order_covered > Decimal("0.0000") or coverage.has_any_coverage
    next_payment_origin = _normalize_payment_origin(external.payment_origin)
    if (
        has_local_coverage
        and next_payment_origin != ExternalPaymentOrigin.LOCAL
        and (
            mapping.payment_origin == ExternalPaymentOrigin.LOCAL.value
            or mapping.payment_origin != next_payment_origin.value
        )
    ):
        raise NeedsReview("CHANNEL_PAYMENT_ORIGIN_CONFLICT", order.id)

    if items_held > Decimal("0.0000") and amounts.effective_merchandise_amount < items_held:
        raise NeedsReview("ITEM_BELOW_SETTLEMENT", order.id)
    if order_covered > Decimal("0.0000") and amounts.expected_total < order_covered:
        raise NeedsReview("ITEM_BELOW_SETTLEMENT", order.id)
    if coverage.joint_covered > Decimal("0.0000") and (
        coverage.joint_total_with(amounts.expected_total) < coverage.joint_covered
    ):
        raise NeedsReview("ITEM_BELOW_SETTLEMENT", order.id)

    added = [row for row in resolved_all if row.line.external_line_id not in current]
    changed = [
        (current[row.line.external_line_id], row) for row in resolved_all
        if row.line.external_line_id in current
        and _line_changed(current[row.line.external_line_id], items.get(current[row.line.external_line_id].order_item_id), row)
    ]
    removed = [line for key, line in current.items() if key not in incoming]
    if any(_preparing(items.get(stored.order_item_id)) for stored, _ in changed) or any(
        _preparing(items.get(stored.order_item_id)) for stored in removed
    ):
        raise NeedsReview("PREPARATION_STARTED", order.id)

    for stored, row in changed:
        item = items.get(stored.order_item_id)
        if stored.external_item_code != row.line.external_item_code or stored.modifier_codes != list(row.line.modifier_codes):
            if item is not None and item.status == OrderItemStatusEnum.ACTIVE:
                _map_http(lambda: order_service.cancel_external_item(
                    session, context, order, item, reason="Substituído por atualização do canal", actor_id=actor,
                ), order.id)
            replacement = _map_http(lambda: order_service.add_external_item(
                session, context, order, product_id=row.product_id, quantity=row.quantity,
                modifier_ids=row.modifier_ids, notes=row.preparation_notes,
                unit_price=row.effective_unit_amount, actor_id=actor,
            ), order.id)
            stored.order_item_id = replacement.id
            stored.external_item_code = row.line.external_item_code
            stored.modifier_codes = list(row.line.modifier_codes)
        else:
            _map_http(lambda: order_service.change_external_item(
                session, context, order, item, quantity=row.quantity,
                notes=row.preparation_notes, unit_price=row.effective_unit_amount, actor_id=actor,
            ), order.id)
        stored.quantity = row.quantity
        stored.unit_amount = row.unit_amount
        stored.discount_amount = row.discount_amount
        stored.local_unit_amount = row.local_unit_amount
        stored.difference_amount = row.difference_amount
        stored.updated_at = now
        session.add(stored)
    for stored in removed:
        item = items.get(stored.order_item_id)
        if item is not None and item.status == OrderItemStatusEnum.ACTIVE:
            _map_http(lambda: order_service.cancel_external_item(
                session, context, order, item, reason="Removido pelo canal", actor_id=actor,
            ), order.id)
        stored.status = ChannelOrderLineStatusEnum.CANCELED
        stored.updated_at = now
        session.add(stored)
    for row in added:
        item = _map_http(lambda: order_service.add_external_item(
            session, context, order, product_id=row.product_id, quantity=row.quantity,
            modifier_ids=row.modifier_ids, notes=row.preparation_notes,
            unit_price=row.effective_unit_amount, actor_id=actor,
        ), order.id)
        session.add(ChannelOrderLine(
            tenant_id=connection.tenant_id, store_id=connection.store_id,
            external_order_mapping_id=mapping.id, external_line_id=row.line.external_line_id,
            external_item_code=row.line.external_item_code, order_item_id=item.id,
            quantity=row.quantity, unit_amount=row.unit_amount, discount_amount=row.discount_amount,
            local_unit_amount=row.local_unit_amount, difference_amount=row.difference_amount,
            modifier_codes=list(row.line.modifier_codes), created_at=now, updated_at=now,
        ))
    header_changed = _declared_amounts(mapping, external, amounts)
    if header_changed or added or changed or removed:
        order.updated_at = max(datetime.utcnow(), now, (order.updated_at or now) + timedelta(microseconds=1))
        session.add(order)
    session.add(mapping)
    return True


def _upsert_contact(session: Session, mapping: ExternalOrderMapping, contact: ExternalContact, now: datetime) -> None:
    """The person goes here and nowhere else (H13). A redacted contact is never refilled."""
    if contact.is_empty():
        return
    row = session.exec(select(ChannelOrderContact).where(
        ChannelOrderContact.external_order_mapping_id == mapping.id,
    )).first()
    if row is None:
        row = ChannelOrderContact(
            tenant_id=mapping.tenant_id, store_id=mapping.store_id,
            external_order_mapping_id=mapping.id,
            # Random, not derived from anything the person gave.
            pseudonym=f"Cliente {secrets.token_hex(3).upper()}",
            retention_basis=ChannelRetentionBasisEnum.ESTADO_TERMINAL,
            retention_until=retention.contact_deadline(mapping),
            created_at=now,
        )
    if row.redacted_at is not None:
        return
    row.display_name = (contact.display_name or "")[:160] or None
    row.phone = (contact.phone or "")[:40] or None
    row.delivery_address = dict(contact.delivery_address) if contact.delivery_address else None
    row.delivery_instructions = (contact.delivery_instructions or "")[:500] or None
    row.updated_at = now
    session.add(row)


def _channel_order_terms(
    session: Session, order_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, settlement.ChannelOrderTerms]:
    wanted = list(order_ids)
    if not wanted:
        return {}
    rows = session.exec(
        select(ExternalOrderMapping)
        .where(ExternalOrderMapping.order_id.in_(wanted))
        .execution_options(populate_existing=True)
    ).all()
    return {
        row.order_id: settlement.ChannelOrderTerms(
            order_id=row.order_id,
            payment_origin=row.payment_origin,
            delivery_fee=row.delivery_fee,
            channel_discount=row.channel_discount,
            channel_subsidy=row.channel_subsidy,
            declared_total=row.declared_total,
        )
        for row in rows
    }


settlement.register_channel_orders(_channel_order_terms)

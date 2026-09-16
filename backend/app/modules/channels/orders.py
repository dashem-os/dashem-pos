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

import secrets
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

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
    ExternalContact, ExternalEvent, ExternalEventKind, ExternalOrder, IngressEnvelope, PayloadRejected,
)
from app.services import order_service


class Quarantine(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code[:80]


class NeedsReview(Exception):
    def __init__(self, code: str, order_id: Optional[uuid.UUID] = None) -> None:
        super().__init__(code)
        self.code = code[:80]
        self.order_id = order_id


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
    ).with_for_update()).first()

    if mapping is None:
        if event.kind != ExternalEventKind.ORDER_PLACED:
            # A change for an order that has not arrived. Kept on its reception
            # clock and retaken as soon as the order is applied.
            raise Quarantine("ORDER_NOT_YET_RECEIVED")
        mapping = _open(session, context, connection, event, now)
        return ChannelInboxStatusEnum.APPLIED, mapping

    order = session.exec(select(Order).where(Order.id == mapping.order_id).with_for_update()).first()
    if _stale(mapping, event) or mapping.terminal_at is not None or order.status in order_service.TERMINAL_ORDER_STATES:
        # Older than what was applied, or after the order ended: recorded, never
        # applied, and the order does not move backwards (H5).
        return ChannelInboxStatusEnum.SUPERSEDED, mapping

    actor = connection.service_actor_id
    if event.kind in {ExternalEventKind.ORDER_PLACED, ExternalEventKind.ORDER_UPDATED}:
        _update(session, context, connection, mapping, order, event, actor, now)
    elif event.kind == ExternalEventKind.ORDER_CANCELLED:
        _refuse_if_preparing(session, context, order)
        _map_http(lambda: order_service.cancel_external_order(
            session, context, order, reason="Cancelado pelo canal", actor_id=actor,
        ))
        for line in _lines(session, mapping):
            line.status = ChannelOrderLineStatusEnum.CANCELED
            line.updated_at = now
            session.add(line)
        retention.anchor_terminal(session, mapping, ExternalOrderTerminalStateEnum.CANCELED, now)
    elif event.kind == ExternalEventKind.ORDER_CONCLUDED:
        _map_http(lambda: order_service.conclude_external_order(session, context, order, actor_id=actor))
        retention.anchor_terminal(session, mapping, ExternalOrderTerminalStateEnum.CONCLUDED, now)
    _upsert_contact(session, mapping, event.contact, now)
    _advance(mapping, event)
    return ChannelInboxStatusEnum.APPLIED, mapping


def _stale(mapping: ExternalOrderMapping, event: ExternalEvent) -> bool:
    return bool(event.order_key and mapping.last_order_key and event.order_key <= mapping.last_order_key)


def _advance(mapping: ExternalOrderMapping, event: ExternalEvent) -> None:
    if event.order_key and (mapping.last_order_key is None or event.order_key > mapping.last_order_key):
        mapping.last_order_key = event.order_key


def _map_http(action):
    try:
        return action()
    except HTTPException:
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


def _resolve_line(session: Session, connection: MerchantConnection, line):
    product_id = _mapped(session, connection, CatalogEntityTypeEnum.PRODUCT, line.external_item_code, "ITEM_NOT_MAPPED")
    modifier_ids = [
        _mapped(session, connection, CatalogEntityTypeEnum.MODIFIER, code, "MODIFIER_NOT_MAPPED")
        for code in line.modifier_codes
    ]
    return product_id, line.quantity, modifier_ids, line.preparation_notes


def _open(
    session: Session, context: TenantContext, connection: MerchantConnection,
    event: ExternalEvent, now: datetime,
) -> ExternalOrderMapping:
    external = event.order
    resolved = [_resolve_line(session, connection, line) for line in external.lines]
    order, items = _map_http(lambda: order_service.open_external_order(
        session, context, store_id=connection.store_id, channel_id=connection.channel_id,
        idempotency_key=f"channel:{connection.id}:{external.external_order_id}",
        external_reference=external.external_order_id,
        fulfillment=OrderFulfillmentEnum(external.fulfillment),
        lines=resolved, actor_id=connection.service_actor_id,
    ))
    mapping = ExternalOrderMapping(
        tenant_id=connection.tenant_id, store_id=connection.store_id,
        merchant_connection_id=connection.id, external_order_id=external.external_order_id,
        order_id=order.id, payment_origin=external.payment_origin,
    )
    _declared_amounts(mapping, external)
    _advance(mapping, event)
    session.add(mapping)
    session.flush()
    for line, item in zip(external.lines, items):
        session.add(ChannelOrderLine(
            tenant_id=connection.tenant_id, store_id=connection.store_id,
            external_order_mapping_id=mapping.id, external_line_id=line.external_line_id,
            external_item_code=line.external_item_code, order_item_id=item.id,
            quantity=line.quantity, unit_amount=line.unit_amount, discount_amount=line.discount_amount,
            modifier_codes=list(line.modifier_codes), created_at=now, updated_at=now,
        ))
    _upsert_contact(session, mapping, event.contact, now)
    return mapping


def _declared_amounts(mapping: ExternalOrderMapping, external: ExternalOrder) -> None:
    mapping.delivery_fee = external.delivery_fee
    mapping.channel_discount = external.channel_discount
    mapping.channel_subsidy = external.channel_subsidy
    mapping.declared_total = external.declared_total
    mapping.payment_origin = external.payment_origin or mapping.payment_origin


def _lines(session: Session, mapping: ExternalOrderMapping) -> list[ChannelOrderLine]:
    return list(session.exec(select(ChannelOrderLine).where(
        ChannelOrderLine.external_order_mapping_id == mapping.id,
        ChannelOrderLine.status == ChannelOrderLineStatusEnum.ACTIVE,
    )).all())


def _preparing(item: Optional[OrderItem]) -> bool:
    return item is not None and item.production_state in order_service.PREPARATION_STARTED


def _refuse_if_preparing(session: Session, context: TenantContext, order: Order) -> None:
    items = session.exec(select(OrderItem).where(
        OrderItem.tenant_id == context.tenant_id, OrderItem.order_id == order.id,
        OrderItem.status == OrderItemStatusEnum.ACTIVE,
    )).all()
    if any(_preparing(item) for item in items):
        # D2, conservative until decided: the kitchen started, a person decides.
        raise NeedsReview("PREPARATION_STARTED", order.id)


def _update(
    session: Session, context: TenantContext, connection: MerchantConnection,
    mapping: ExternalOrderMapping, order: Order, event: ExternalEvent,
    actor: uuid.UUID, now: datetime,
) -> None:
    """Compare lines, decide everything, and only then change anything.

    If any change touches an item already being prepared, nothing is applied:
    a half-applied update would leave the order matching neither the channel nor
    the kitchen.
    """
    external = event.order
    current = {line.external_line_id: line for line in _lines(session, mapping)}
    items = {
        item.id: item for item in session.exec(select(OrderItem).where(
            OrderItem.tenant_id == context.tenant_id, OrderItem.order_id == order.id,
        )).all()
    }
    incoming = {line.external_line_id: line for line in external.lines}

    added = [line for key, line in incoming.items() if key not in current]
    changed = [
        (current[key], line) for key, line in incoming.items()
        if key in current and (
            current[key].quantity != line.quantity
            or (items.get(current[key].order_item_id) and items[current[key].order_item_id].notes != line.preparation_notes)
        )
    ]
    removed = [line for key, line in current.items() if key not in incoming]
    if any(_preparing(items.get(stored.order_item_id)) for stored, _ in changed) or any(
        _preparing(items.get(stored.order_item_id)) for stored in removed
    ):
        raise NeedsReview("PREPARATION_STARTED", order.id)

    resolved_added = [(line, _resolve_line(session, connection, line)) for line in added]
    for stored, line in changed:
        item = items.get(stored.order_item_id)
        _map_http(lambda: order_service.change_external_item(
            session, context, order, item, quantity=line.quantity, notes=line.preparation_notes, actor_id=actor,
        ))
        stored.quantity, stored.unit_amount, stored.discount_amount = line.quantity, line.unit_amount, line.discount_amount
        stored.updated_at = now
        session.add(stored)
    for stored in removed:
        item = items.get(stored.order_item_id)
        if item is not None and item.status == OrderItemStatusEnum.ACTIVE:
            _map_http(lambda: order_service.cancel_external_item(
                session, context, order, item, reason="Removido pelo canal", actor_id=actor,
            ))
        stored.status = ChannelOrderLineStatusEnum.CANCELED
        stored.updated_at = now
        session.add(stored)
    for line, (product_id, quantity, modifier_ids, notes) in resolved_added:
        item = _map_http(lambda: order_service.add_external_item(
            session, context, order, product_id=product_id, quantity=quantity,
            modifier_ids=modifier_ids, notes=notes, actor_id=actor,
        ))
        session.add(ChannelOrderLine(
            tenant_id=connection.tenant_id, store_id=connection.store_id,
            external_order_mapping_id=mapping.id, external_line_id=line.external_line_id,
            external_item_code=line.external_item_code, order_item_id=item.id,
            quantity=line.quantity, unit_amount=line.unit_amount, discount_amount=line.discount_amount,
            modifier_codes=list(line.modifier_codes), created_at=now, updated_at=now,
        ))
    _declared_amounts(mapping, external)


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

import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.catalog import (
    SalesChannel, Modifier, ModifierGroup, Product, ProductModifierGroup, ProductPrice,
)
from app.models.identity import Register, Store
from app.models.order import (
    Order, OrderCommand, OrderFulfillmentEnum, OrderItem, OrderItemStatusEnum,
    OrderOriginEnum, OrderStatusEnum, ProductionStateEnum,
)
from app.models.sale import Customer, Sale
from app.models.table_service import ServiceTable, TableSession, TableSessionStatusEnum
from app.models.assortment import Assortment, SalesContextEnum
from app.services.assortment_service import resolve_effective_product_ids
from app.services import reliability_service, table_service
from app.modules.capabilities.service import capability_allowed_by_activity
from app.modules.settlement import contracts as settlement


def _hash(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _actor(context: TenantContext, actor_id: Optional[uuid.UUID]) -> uuid.UUID:
    return resolve_actor(context, actor_id)


def _event(session: Session, context: TenantContext, order: Order, actor_id: uuid.UUID, event_type: str, payload: dict[str, Any]) -> None:
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=order.store_id,
        actor_id=actor_id, action=event_type, target=f"ORDER-{order.id}",
        audit_payload=payload, aggregate_type="order", aggregate_id=str(order.id),
        event_type=event_type,
        outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(order.store_id), "order_id": str(order.id), **payload},
    )


def _command_result(
    session: Session, context: TenantContext, order_id: uuid.UUID,
    key: str, command_type: str, payload: dict[str, Any],
) -> Optional[uuid.UUID]:
    command = session.exec(select(OrderCommand).where(
        OrderCommand.tenant_id == context.tenant_id,
        OrderCommand.idempotency_key == key,
    )).first()
    if not command:
        return None
    if command.order_id != order_id or command.command_type != command_type or command.request_hash != _hash(payload):
        raise HTTPException(status_code=409, detail="Idempotency-Key já utilizada com outro comando ou conteúdo.")
    return command.result_entity_id


def _record_command(
    session: Session, context: TenantContext, order_id: uuid.UUID,
    key: str, command_type: str, payload: dict[str, Any],
    result_entity_id: uuid.UUID, actor_id: uuid.UUID,
) -> None:
    session.add(OrderCommand(
        tenant_id=context.tenant_id, order_id=order_id, idempotency_key=key,
        command_type=command_type, request_hash=_hash(payload),
        result_entity_id=result_entity_id, actor_id=actor_id,
    ))


def _commit_item_command(
    session: Session, context: TenantContext, order_id: uuid.UUID,
    item: OrderItem, key: str, command_type: str, payload: dict[str, Any],
) -> OrderItem:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        result = _command_result(session, context, order_id, key, command_type, payload)
        if result:
            existing = session.get(OrderItem, result)
            if existing:
                return existing
        raise HTTPException(status_code=409, detail="Conflito durante comando idempotente do pedido.") from exc
    session.refresh(item)
    return item


def get_order(session: Session, context: TenantContext, order_id: uuid.UUID) -> Order:
    query = select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
    order = session.exec(scope_tenant_query(query, Order, context)).first()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado no contexto ativo.")
    return order


def list_orders(session: Session, context: TenantContext, status_filter: Optional[OrderStatusEnum] = None) -> list[Order]:
    query = scope_tenant_query(select(Order).options(selectinload(Order.items)), Order, context)
    if status_filter:
        query = query.where(Order.status == status_filter)
    return list(session.exec(query.order_by(Order.updated_at.desc()).limit(100)).all())


def _fulfillment_to_context(fulfillment: OrderFulfillmentEnum) -> Optional[SalesContextEnum]:
    mapping = {
        OrderFulfillmentEnum.COUNTER: SalesContextEnum.COUNTER,
        OrderFulfillmentEnum.TAKEAWAY: SalesContextEnum.TAKEAWAY,
        OrderFulfillmentEnum.DINE_IN: SalesContextEnum.TABLE,
        OrderFulfillmentEnum.DELIVERY: SalesContextEnum.DELIVERY,
    }
    return mapping.get(fulfillment)


def _enforce_journey_capability(session: Session, context: TenantContext, sales_context: SalesContextEnum) -> None:
    caps = set(context.capabilities or ())
    if sales_context == SalesContextEnum.TABLE:
        if "table_service" not in caps:
            if not capability_allowed_by_activity(session, context.tenant_id, "table_service"):
                raise HTTPException(status_code=403, detail="Jornada de mesa indisponível: a atividade FOOD_SERVICE não está contratada e ativa nesta unidade.")
            raise HTTPException(status_code=403, detail="Capacidade 'table_service' não contratada ou inativa para esta unidade.")
    elif sales_context == SalesContextEnum.DELIVERY:
        if "delivery_orders" not in caps:
            raise HTTPException(status_code=403, detail="Capacidade 'delivery_orders' não contratada ou inativa para esta unidade.")
    elif sales_context in {SalesContextEnum.COUNTER, SalesContextEnum.TAKEAWAY}:
        if "counter_order" not in caps:
            raise HTTPException(status_code=403, detail="Capacidade 'counter_order' não contratada ou inativa para esta unidade.")
    elif sales_context == SalesContextEnum.ECOMMERCE:
        if "ecommerce" not in caps:
            raise HTTPException(status_code=403, detail="Jornada de e-commerce não contratada ou habilitada para esta unidade.")


def create_order(
    session: Session, context: TenantContext, *, store_id: uuid.UUID,
    idempotency_key: str, actor_id: Optional[uuid.UUID],
    register_id: Optional[uuid.UUID], customer_id: Optional[uuid.UUID],
    table_id: Optional[uuid.UUID], table_session_id: Optional[uuid.UUID], sale_id: Optional[uuid.UUID],
    channel_id: Optional[uuid.UUID], origin: OrderOriginEnum,
    fulfillment: OrderFulfillmentEnum, external_reference: Optional[str], notes: Optional[str],
) -> Order:
    key = idempotency_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Idempotency-Key é obrigatória.")
    actor = _actor(context, actor_id)
    existing = session.exec(select(Order).options(selectinload(Order.items)).where(
        Order.tenant_id == context.tenant_id, Order.idempotency_key == key,
    )).first()
    if existing:
        same_request = (
            existing.store_id == store_id and existing.register_id == register_id
            and existing.customer_id == customer_id and existing.table_id == table_id
            and existing.table_session_id == table_session_id
            and existing.sale_id == sale_id and existing.channel_id == channel_id
            and existing.origin == origin and existing.fulfillment == fulfillment
            and existing.external_reference == external_reference and existing.notes == notes
            and existing.opened_by == actor
        )
        if not same_request:
            raise HTTPException(status_code=409, detail="Idempotency-Key do pedido já utilizada com outro conteúdo.")
        return existing
    if context.store_id and context.store_id != store_id:
        raise HTTPException(status_code=403, detail="Pedido fora da unidade ativa.")
    store = session.get(Store, store_id)
    if not store or store.tenant_id != context.tenant_id or not store.is_active:
        raise HTTPException(status_code=404, detail="Unidade não encontrada.")
    order_context = _fulfillment_to_context(fulfillment)
    if order_context:
        _enforce_journey_capability(session, context, order_context)
    if register_id:
        register = session.get(Register, register_id)
        if not register or register.tenant_id != context.tenant_id or register.store_id != store_id or not register.is_active:
            raise HTTPException(status_code=403, detail="Terminal não pertence à unidade ativa.")
    if customer_id and not session.exec(scope_tenant_query(select(Customer).where(Customer.id == customer_id), Customer, context)).first():
        raise HTTPException(status_code=404, detail="Cliente não encontrado.")
    if table_id:
        table = session.exec(scope_tenant_query(select(ServiceTable).where(ServiceTable.id == table_id), ServiceTable, context)).first()
        if not table:
            raise HTTPException(status_code=404, detail="Mesa não encontrada.")
    if table_session_id:
        table_session = session.exec(scope_tenant_query(select(TableSession).where(TableSession.id == table_session_id), TableSession, context)).first()
        if not table_session or table_session.status in {TableSessionStatusEnum.CLOSED, TableSessionStatusEnum.CANCELED}:
            raise HTTPException(status_code=404, detail="Sessão de atendimento ativa não encontrada.")
        if table_session.service_table_id != table_id:
            raise HTTPException(status_code=409, detail="Mesa e sessão de atendimento não correspondem.")
    if sale_id:
        sale = session.exec(scope_tenant_query(select(Sale).where(Sale.id == sale_id), Sale, context)).first()
        if not sale:
            raise HTTPException(status_code=404, detail="Venda vinculada não encontrada.")
    if channel_id:
        channel = session.exec(scope_tenant_query(select(SalesChannel).where(SalesChannel.id == channel_id), SalesChannel, context)).first()
        if not channel:
            raise HTTPException(status_code=404, detail="Canal não encontrado.")
    if origin == OrderOriginEnum.SALES_CHANNEL and not channel_id:
        raise HTTPException(status_code=400, detail="Pedidos de canal exigem channel_id.")
    order = Order(
        tenant_id=context.tenant_id, store_id=store_id, register_id=register_id,
        customer_id=customer_id, table_id=table_id, table_session_id=table_session_id, sale_id=sale_id,
        channel_id=channel_id, origin=origin, fulfillment=fulfillment,
        status=OrderStatusEnum.OPEN, idempotency_key=key,
        external_reference=external_reference, opened_by=actor, notes=notes,
    )
    session.add(order)
    _event(session, context, order, actor, "order.created", {
        "origin": origin.value, "fulfillment": fulfillment.value,
        "register_id": str(register_id) if register_id else None,
        "customer_id": str(customer_id) if customer_id else None,
        "table_id": str(table_id) if table_id else None,
        "table_session_id": str(table_session_id) if table_session_id else None,
        "sale_id": str(sale_id) if sale_id else None,
        "channel_id": str(channel_id) if channel_id else None,
    })
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = session.exec(select(Order).options(selectinload(Order.items)).where(
            Order.tenant_id == context.tenant_id, Order.idempotency_key == key,
        )).first()
        if existing:
            return existing
        raise HTTPException(status_code=409, detail="Conflito ao abrir pedido.") from exc
    session.refresh(order)
    return order


def _modifiers(
    session: Session, context: TenantContext, product_id: uuid.UUID, modifier_ids: list[uuid.UUID],
) -> tuple[list[dict[str, Any]], Decimal]:
    group_rows = session.exec(
        select(ProductModifierGroup, ModifierGroup)
        .join(ModifierGroup, ModifierGroup.id == ProductModifierGroup.modifier_group_id)
        .where(
            ProductModifierGroup.tenant_id == context.tenant_id,
            ProductModifierGroup.product_id == product_id,
            ModifierGroup.is_active.is_(True),
        )
    ).all()
    groups = {group.id: group for _link, group in group_rows}
    selected: list[Modifier] = []
    if modifier_ids:
        selected = list(session.exec(select(Modifier).where(
            Modifier.tenant_id == context.tenant_id,
            Modifier.id.in_(modifier_ids),
            Modifier.is_active.is_(True),
        )).all())
        if len(selected) != len(set(modifier_ids)) or any(modifier.group_id not in groups for modifier in selected):
            raise HTTPException(status_code=400, detail="Modificador inválido ou não vinculado ao produto.")
    by_group: dict[uuid.UUID, int] = {}
    for modifier in selected:
        by_group[modifier.group_id] = by_group.get(modifier.group_id, 0) + 1
    for group_id, group in groups.items():
        count = by_group.get(group_id, 0)
        if count < group.minimum_choices or count > group.maximum_choices:
            raise HTTPException(status_code=400, detail=f"Seleções do grupo '{group.name}' fora dos limites {group.minimum_choices}..{group.maximum_choices}.")
    snapshot = [{
        "group_id": str(modifier.group_id), "group_name": groups[modifier.group_id].name,
        "modifier_id": str(modifier.id), "modifier_name": modifier.name,
        "price_delta": str(modifier.price_delta),
    } for modifier in selected]
    return snapshot, sum((Decimal(str(modifier.price_delta)) for modifier in selected), Decimal("0"))


def add_item(
    session: Session, context: TenantContext, order_id: uuid.UUID, *,
    product_id: uuid.UUID, quantity: Decimal, modifier_ids: list[uuid.UUID],
    notes: Optional[str], idempotency_key: str, actor_id: Optional[uuid.UUID],
) -> OrderItem:
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser positiva.")
    payload = {"product_id": str(product_id), "quantity": str(quantity), "modifier_ids": sorted(map(str, modifier_ids)), "notes": notes}
    result = _command_result(session, context, order_id, idempotency_key, "ADD_ITEM", payload)
    if result:
        item = session.get(OrderItem, result)
        if not item: raise HTTPException(status_code=409, detail="Resultado idempotente indisponível.")
        return item
    order = get_order(session, context, order_id)
    if order.status != OrderStatusEnum.OPEN:
        raise HTTPException(status_code=409, detail="Pedido não está aberto para novos lançamentos.")
    product = session.exec(scope_tenant_query(select(Product).where(
        Product.id == product_id, Product.is_active.is_(True), Product.available_for_sale.is_(True),
    ), Product, context)).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto indisponível no tenant.")

    order_context = _fulfillment_to_context(order.fulfillment)
    if not order_context:
        raise HTTPException(status_code=400, detail=f"Contexto de fulfillment '{order.fulfillment}' inválido.")
    _enforce_journey_capability(session, context, order_context)

    authorized_ids = resolve_effective_product_ids(
        session, context.tenant_id, order.store_id, order_context, order.channel_id
    )
    if product.id not in authorized_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Produto '{product.name}' não pertence ao sortimento autorizado para o contexto {order_context.value}.",
        )
    price = session.exec(scope_tenant_query(select(ProductPrice).where(
        ProductPrice.product_id == product_id, ProductPrice.store_id == order.store_id,
    ), ProductPrice, context)).first()
    if not price:
        price = session.exec(scope_tenant_query(select(ProductPrice).where(
            ProductPrice.product_id == product_id, ProductPrice.store_id.is_(None),
        ), ProductPrice, context)).first()
    if not price:
        raise HTTPException(status_code=400, detail="Produto sem preço efetivo na unidade.")
    snapshot, modifier_total = _modifiers(session, context, product_id, modifier_ids)
    actor = _actor(context, actor_id)
    item = OrderItem(
        tenant_id=context.tenant_id, order_id=order.id, product_id=product.id,
        product_name=product.name, sku=product.sku, unit_snapshot=product.unit,
        unit_price=Decimal(str(price.sale_price)) + modifier_total,
        quantity=quantity, modifier_snapshot=snapshot, notes=notes,
        production_destination=product.production_destination,
        production_state=ProductionStateEnum.PENDING if product.requires_fulfillment or product.production_destination else ProductionStateEnum.NOT_REQUIRED,
        added_by=actor,
    )
    session.add(item)
    _record_command(session, context, order.id, idempotency_key, "ADD_ITEM", payload, item.id, actor)
    order.updated_at = datetime.utcnow()
    table_service.touch_session_activity(session, context, order, actor, item.id)
    _event(session, context, order, actor, "order.item.added", {
        "order_item_id": str(item.id), "product_id": str(product.id),
        "quantity": str(quantity), "unit_price": str(item.unit_price),
        "production_state": item.production_state.value,
    })
    return _commit_item_command(session, context, order.id, item, idempotency_key, "ADD_ITEM", payload)


def _refuse_below_settlement(session: Session, item: OrderItem, new_total: Decimal) -> None:
    """An item may change, as long as it stays worth what was paid on it.

    The boundary is economic, not a freeze: a pizza nobody paid for can be
    cancelled and the table owes less; a pizza of R$80 carrying R$20 accepts any
    change that leaves it at R$20 or more; a whisky already settled cannot be
    reduced below what settled on it. Finance is asked through the settlement
    port — operation does not read the allocation table (ADR-029).
    """
    held = settlement.hold_on_items(session, [item.id]).get(item.id, Decimal("0"))
    if held > 0 and new_total < held:
        raise HTTPException(status_code=409, detail={
            "code": "ITEM_BELOW_SETTLEMENT",
            "message": "O item já possui pagamento liquidado ou reservado e não pode valer menos que ele.",
            "order_item_id": str(item.id), "product_name": item.product_name,
            "requested_total": str(new_total), "covered": str(held),
        })


def update_item(
    session: Session, context: TenantContext, order_id: uuid.UUID, item_id: uuid.UUID, *,
    quantity: Decimal, notes: Optional[str], idempotency_key: str, actor_id: Optional[uuid.UUID],
) -> OrderItem:
    if quantity <= 0: raise HTTPException(status_code=400, detail="Quantidade deve ser positiva.")
    payload = {"item_id": str(item_id), "quantity": str(quantity), "notes": notes}
    result = _command_result(session, context, order_id, idempotency_key, "UPDATE_ITEM", payload)
    if result:
        item = session.get(OrderItem, result)
        if not item: raise HTTPException(status_code=409, detail="Resultado idempotente indisponível.")
        return item
    order = get_order(session, context, order_id)
    if order.status != OrderStatusEnum.OPEN: raise HTTPException(status_code=409, detail="Pedido não está aberto.")
    item = session.exec(select(OrderItem).where(OrderItem.tenant_id == context.tenant_id, OrderItem.order_id == order_id, OrderItem.id == item_id)).first()
    if not item or item.status != OrderItemStatusEnum.ACTIVE: raise HTTPException(status_code=404, detail="Item ativo não encontrado.")
    _refuse_below_settlement(session, item, Decimal(str(item.unit_price)) * Decimal(str(quantity)))
    actor = _actor(context, actor_id)
    item.quantity = quantity; item.notes = notes; item.production_version += 1; item.updated_at = datetime.utcnow()
    _record_command(session, context, order.id, idempotency_key, "UPDATE_ITEM", payload, item.id, actor)
    order.updated_at = item.updated_at
    table_service.touch_session_activity(session, context, order, actor, item.id, "table_session.item_changed")
    _event(session, context, order, actor, "order.item.updated", {"order_item_id": str(item.id), "quantity": str(quantity)})
    return _commit_item_command(session, context, order.id, item, idempotency_key, "UPDATE_ITEM", payload)


def cancel_item(
    session: Session, context: TenantContext, order_id: uuid.UUID, item_id: uuid.UUID, *,
    reason: str, idempotency_key: str, actor_id: Optional[uuid.UUID],
) -> OrderItem:
    payload = {"item_id": str(item_id), "reason": reason}
    result = _command_result(session, context, order_id, idempotency_key, "CANCEL_ITEM", payload)
    if result:
        item = session.get(OrderItem, result)
        if not item: raise HTTPException(status_code=409, detail="Resultado idempotente indisponível.")
        return item
    order = get_order(session, context, order_id)
    if order.status != OrderStatusEnum.OPEN: raise HTTPException(status_code=409, detail="Pedido não está aberto.")
    item = session.exec(select(OrderItem).where(OrderItem.tenant_id == context.tenant_id, OrderItem.order_id == order_id, OrderItem.id == item_id)).first()
    if not item: raise HTTPException(status_code=404, detail="Item não encontrado.")
    _refuse_below_settlement(session, item, Decimal("0"))
    actor = _actor(context, actor_id)
    item.status = OrderItemStatusEnum.CANCELED
    item.production_state = ProductionStateEnum.CANCELED
    item.production_version += 1
    item.canceled_by = actor; item.cancellation_reason = reason.strip(); item.canceled_at = datetime.utcnow(); item.updated_at = item.canceled_at
    _record_command(session, context, order.id, idempotency_key, "CANCEL_ITEM", payload, item.id, actor)
    order.updated_at = item.updated_at
    table_service.touch_session_activity(session, context, order, actor, item.id, "table_session.item_canceled")
    _event(session, context, order, actor, "order.item.canceled", {"order_item_id": str(item.id), "reason": reason})
    return _commit_item_command(session, context, order.id, item, idempotency_key, "CANCEL_ITEM", payload)

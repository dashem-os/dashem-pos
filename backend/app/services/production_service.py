import uuid
from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.context import TenantContext, scope_tenant_query
from app.models.catalog import Modifier, Product
from app.models.order import Order, OrderItem, OrderItemStatusEnum, ProductionStateEnum
from app.models.production import (
    ProductionDispatch, ProductionOperationEnum, ProductionPoint,
    ProductionPointTypeEnum, ProductionRoutingRule, ProductionTicket,
    ProductionTicketItem, ProductionTicketStatusEnum, ProductionTransition,
)
from app.services import reliability_service


def _actor(context: TenantContext, actor_id: Optional[uuid.UUID]) -> uuid.UUID:
    actor = actor_id or context.user_id
    if not actor:
        raise HTTPException(status_code=400, detail="actor_id é obrigatório.")
    if context.user_id and actor != context.user_id:
        raise HTTPException(status_code=403, detail="Ator não corresponde à identidade autenticada.")
    return actor


def _point(session: Session, context: TenantContext, point_id: uuid.UUID) -> ProductionPoint:
    point = session.exec(scope_tenant_query(select(ProductionPoint).where(
        ProductionPoint.id == point_id,
    ), ProductionPoint, context)).first()
    if not point:
        raise HTTPException(status_code=404, detail="Ponto de produção não encontrado.")
    return point


def create_point(session: Session, context: TenantContext, *, store_id: uuid.UUID, code: str, name: str,
                 point_type: ProductionPointTypeEnum, printer_configuration_ref: Optional[str],
                 actor_id: Optional[uuid.UUID], idempotency_key: str) -> ProductionPoint:
    if context.store_id and context.store_id != store_id:
        raise HTTPException(status_code=403, detail="Ponto fora da unidade ativa.")
    if point_type == ProductionPointTypeEnum.PRINTER and not printer_configuration_ref:
        raise HTTPException(status_code=422, detail="Impressora exige configuração persistida.")
    actor = _actor(context, actor_id)
    payload = {"store_id": str(store_id), "code": code.strip().upper(), "name": name.strip(),
               "point_type": point_type.value, "printer_configuration_ref": printer_configuration_ref}
    cached, _, body = reliability_service.check_idempotency(
        session, context.tenant_id, actor, "production.point.create", idempotency_key, payload,
    )
    if cached and body:
        return _point(session, context, uuid.UUID(body["point_id"]))
    point = ProductionPoint(tenant_id=context.tenant_id, store_id=store_id, code=payload["code"],
                            name=payload["name"], point_type=point_type,
                            printer_configuration_ref=printer_configuration_ref)
    session.add(point)
    reliability_service.write_audit_and_outbox(
        session, context.tenant_id, store_id, actor, "production.point.created",
        f"PRODUCTION-POINT-{point.id}", payload, "production_point", str(point.id),
        "production.point.created", payload,
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(status_code=409, detail="Código de produção já existe na unidade.") from exc
    session.refresh(point)
    reliability_service.save_idempotency_record(session, context.tenant_id, actor, "production.point.create",
                                                idempotency_key, payload, 200, {"point_id": str(point.id)})
    session.commit()
    return point


def list_points(session: Session, context: TenantContext) -> list[ProductionPoint]:
    return list(session.exec(scope_tenant_query(select(ProductionPoint).order_by(ProductionPoint.name), ProductionPoint, context)).all())


def update_point(session: Session, context: TenantContext, point_id: uuid.UUID, *, name: Optional[str],
                 is_active: Optional[bool], printer_configuration_ref: Optional[str],
                 actor_id: Optional[uuid.UUID], reason: str) -> ProductionPoint:
    point = _point(session, context, point_id); actor = _actor(context, actor_id)
    if name is not None: point.name = name.strip()
    if is_active is not None: point.is_active = is_active
    if printer_configuration_ref is not None: point.printer_configuration_ref = printer_configuration_ref.strip() or None
    if point.point_type == ProductionPointTypeEnum.PRINTER and not point.printer_configuration_ref:
        raise HTTPException(status_code=422, detail="Impressora exige uma referência de configuração.")
    point.updated_at = datetime.utcnow()
    reliability_service.write_audit_and_outbox(
        session, context.tenant_id, point.store_id, actor, "production.point.updated",
        f"PRODUCTION-POINT-{point.id}", {"name": point.name, "is_active": point.is_active, "reason": reason},
        "production_point", str(point.id), "production.point.updated",
        {"point_id": str(point.id), "is_active": point.is_active},
    )
    session.add(point); session.commit(); session.refresh(point)
    return point


def list_rules(session: Session, context: TenantContext) -> list[ProductionRoutingRule]:
    return list(session.exec(scope_tenant_query(select(ProductionRoutingRule).order_by(
        ProductionRoutingRule.priority, ProductionRoutingRule.created_at,
    ), ProductionRoutingRule, context)).all())


def create_rule(session: Session, context: TenantContext, *, point_id: uuid.UUID,
                product_id: Optional[uuid.UUID], modifier_id: Optional[uuid.UUID], fulfillment,
                priority: int, actor_id: Optional[uuid.UUID], idempotency_key: str) -> ProductionRoutingRule:
    if bool(product_id) == bool(modifier_id):
        raise HTTPException(status_code=422, detail="Regra deve apontar exatamente produto ou modifier.")
    point = _point(session, context, point_id); actor = _actor(context, actor_id)
    if product_id:
        product = session.exec(scope_tenant_query(select(Product).where(Product.id == product_id), Product, context)).first()
        if not product: raise HTTPException(status_code=404, detail="Produto não encontrado.")
    if modifier_id:
        modifier = session.exec(scope_tenant_query(select(Modifier).where(Modifier.id == modifier_id), Modifier, context)).first()
        if not modifier: raise HTTPException(status_code=404, detail="Modifier não encontrado.")
    payload = {"point_id": str(point_id), "product_id": str(product_id) if product_id else None,
               "modifier_id": str(modifier_id) if modifier_id else None,
               "fulfillment": fulfillment.value if fulfillment else None, "priority": priority}
    cached, _, body = reliability_service.check_idempotency(
        session, context.tenant_id, actor, "production.rule.create", idempotency_key, payload,
    )
    if cached and body:
        rule = session.get(ProductionRoutingRule, uuid.UUID(body["rule_id"]))
        if rule and rule.tenant_id == context.tenant_id: return rule
        raise HTTPException(status_code=409, detail="Resultado idempotente não disponível.")
    rule = ProductionRoutingRule(tenant_id=context.tenant_id, store_id=point.store_id,
                                 production_point_id=point.id, product_id=product_id,
                                 modifier_id=modifier_id, fulfillment=fulfillment, priority=priority)
    session.add(rule)
    reliability_service.write_audit_and_outbox(
        session, context.tenant_id, point.store_id, actor, "production.rule.created",
        f"PRODUCTION-RULE-{rule.id}", payload, "production_rule", str(rule.id),
        "production.rule.created", payload,
    )
    session.commit(); session.refresh(rule)
    reliability_service.save_idempotency_record(session, context.tenant_id, actor, "production.rule.create",
                                                idempotency_key, payload, 200, {"rule_id": str(rule.id)})
    session.commit(); return rule


def _routes(session: Session, context: TenantContext, order: Order, item: OrderItem) -> list[ProductionPoint]:
    modifier_ids = [uuid.UUID(row["modifier_id"]) for row in item.modifier_snapshot if row.get("modifier_id")]
    rules = list(session.exec(select(ProductionRoutingRule).where(
        ProductionRoutingRule.tenant_id == context.tenant_id,
        ProductionRoutingRule.store_id == order.store_id,
        ProductionRoutingRule.is_active.is_(True),
    )).all())
    applicable = [rule for rule in rules if rule.fulfillment is None or rule.fulfillment == order.fulfillment]
    chosen = [rule for rule in applicable if rule.modifier_id in modifier_ids] if modifier_ids else []
    if not chosen:
        chosen = [rule for rule in applicable if rule.product_id == item.product_id]
    point_ids = sorted({rule.production_point_id for rule in chosen}, key=str)
    if not point_ids and item.production_destination:
        legacy = session.exec(select(ProductionPoint).where(
            ProductionPoint.tenant_id == context.tenant_id, ProductionPoint.store_id == order.store_id,
            ProductionPoint.code == item.production_destination.upper(),
        )).first()
        if legacy: point_ids = [legacy.id]
    return list(session.exec(select(ProductionPoint).where(ProductionPoint.id.in_(point_ids))).all()) if point_ids else []


def _ticket_projection(session: Session, ticket: ProductionTicket) -> dict:
    point = session.get(ProductionPoint, ticket.production_point_id)
    items = list(session.exec(select(ProductionTicketItem).where(ProductionTicketItem.ticket_id == ticket.id).order_by(ProductionTicketItem.created_at)).all())
    return {"ticket": ticket, "point": point, "items": items}


def dispatch_order(session: Session, context: TenantContext, order_id: uuid.UUID, *, actor_id: Optional[uuid.UUID],
                   idempotency_key: str) -> list[dict]:
    actor = _actor(context, actor_id); payload = {"order_id": str(order_id)}
    request_hash = reliability_service.compute_request_hash(payload)
    existing = session.exec(select(ProductionDispatch).where(
        ProductionDispatch.tenant_id == context.tenant_id,
        ProductionDispatch.idempotency_key == idempotency_key,
    )).first()
    if existing:
        if existing.request_hash != request_hash: raise HTTPException(status_code=409, detail="Idempotency-Key reutilizada com outro pedido.")
        tickets = session.exec(select(ProductionTicket).where(ProductionTicket.dispatch_id == existing.id)).all()
        return [_ticket_projection(session, item) for item in tickets]
    order = session.exec(scope_tenant_query(select(Order).where(Order.id == order_id).with_for_update(), Order, context)).first()
    if not order: raise HTTPException(status_code=404, detail="Pedido não encontrado.")
    items = list(session.exec(select(OrderItem).where(OrderItem.order_id == order.id)).all())
    dispatch = ProductionDispatch(tenant_id=context.tenant_id, store_id=order.store_id, order_id=order.id,
                                  idempotency_key=idempotency_key, request_hash=request_hash, actor_id=actor)
    session.add(dispatch); session.flush()
    grouped: dict[uuid.UUID, list[tuple[OrderItem, ProductionOperationEnum]]] = defaultdict(list)
    for item in items:
        operation = ProductionOperationEnum.CANCEL if item.status == OrderItemStatusEnum.CANCELED else (
            ProductionOperationEnum.UPDATE if item.production_version > 1 else ProductionOperationEnum.CREATE)
        if operation == ProductionOperationEnum.CANCEL:
            previous = session.exec(select(ProductionTicket.production_point_id).join(
                ProductionTicketItem, ProductionTicketItem.ticket_id == ProductionTicket.id,
            ).where(ProductionTicketItem.order_item_id == item.id)).all()
            points = [session.get(ProductionPoint, point_id) for point_id in set(previous)]
            points = [point for point in points if point]
        else:
            points = _routes(session, context, order, item)
        for point in points:
            duplicate = session.exec(select(ProductionTicketItem).join(
                ProductionTicket, ProductionTicket.id == ProductionTicketItem.ticket_id,
            ).where(ProductionTicketItem.order_item_id == item.id,
                    ProductionTicketItem.item_version == item.production_version,
                    ProductionTicketItem.operation == operation,
                    ProductionTicket.production_point_id == point.id)).first()
            if not duplicate: grouped[point.id].append((item, operation))
    created: list[ProductionTicket] = []
    for point_id, allocations in grouped.items():
        rules_priority = [r.priority for r in session.exec(select(ProductionRoutingRule).where(
            ProductionRoutingRule.production_point_id == point_id, ProductionRoutingRule.is_active.is_(True))).all()]
        ticket = ProductionTicket(tenant_id=context.tenant_id, store_id=order.store_id, order_id=order.id,
                                  dispatch_id=dispatch.id, production_point_id=point_id,
                                  priority=min(rules_priority or [100]))
        session.add(ticket); session.flush(); created.append(ticket)
        for item, operation in allocations:
            session.add(ProductionTicketItem(
                tenant_id=context.tenant_id, ticket_id=ticket.id, order_item_id=item.id,
                item_version=item.production_version, operation=operation, quantity=item.quantity,
                product_name_snapshot=item.product_name, modifier_snapshot=item.modifier_snapshot,
                notes_snapshot=item.notes,
            ))
    reliability_service.write_audit_and_outbox(
        session, context.tenant_id, order.store_id, actor, "production.order.dispatched",
        f"ORDER-{order.id}", {"ticket_count": len(created)}, "order", str(order.id),
        "production.order.dispatched", {"ticket_ids": [str(ticket.id) for ticket in created]},
    )
    try: session.commit()
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(status_code=409, detail="Conflito no dispatch de produção.") from exc
    return [_ticket_projection(session, ticket) for ticket in created]


def list_tickets(session: Session, context: TenantContext, point_id: Optional[uuid.UUID] = None,
                 include_terminal: bool = False) -> list[dict]:
    query = scope_tenant_query(select(ProductionTicket), ProductionTicket, context)
    if point_id: query = query.where(ProductionTicket.production_point_id == point_id)
    if not include_terminal: query = query.where(ProductionTicket.status.notin_([
        ProductionTicketStatusEnum.DELIVERED, ProductionTicketStatusEnum.CANCELED]))
    tickets = session.exec(query.order_by(ProductionTicket.priority, ProductionTicket.created_at)).all()
    return [_ticket_projection(session, ticket) for ticket in tickets]


_NEXT = {
    ProductionTicketStatusEnum.NEW: {ProductionTicketStatusEnum.ACCEPTED, ProductionTicketStatusEnum.CANCELED},
    ProductionTicketStatusEnum.ACCEPTED: {ProductionTicketStatusEnum.PREPARING, ProductionTicketStatusEnum.CANCELED},
    ProductionTicketStatusEnum.PREPARING: {ProductionTicketStatusEnum.READY, ProductionTicketStatusEnum.CANCELED},
    ProductionTicketStatusEnum.READY: {ProductionTicketStatusEnum.DELIVERED, ProductionTicketStatusEnum.CANCELED},
}


def transition_ticket(session: Session, context: TenantContext, ticket_id: uuid.UUID, *,
                      target: ProductionTicketStatusEnum, expected_version: int, actor_id: Optional[uuid.UUID],
                      device_id: str, idempotency_key: str) -> dict:
    actor = _actor(context, actor_id)
    existing = session.exec(select(ProductionTransition).where(
        ProductionTransition.tenant_id == context.tenant_id,
        ProductionTransition.idempotency_key == idempotency_key,
    )).first()
    if existing:
        if existing.ticket_id != ticket_id or existing.to_status != target or existing.expected_version != expected_version:
            raise HTTPException(status_code=409, detail="Idempotency-Key reutilizada com outra transição.")
        ticket = session.get(ProductionTicket, ticket_id); return _ticket_projection(session, ticket)
    ticket = session.exec(scope_tenant_query(select(ProductionTicket).where(
        ProductionTicket.id == ticket_id,
    ).with_for_update(), ProductionTicket, context)).first()
    if not ticket: raise HTTPException(status_code=404, detail="Ticket não encontrado.")
    if ticket.version != expected_version:
        raise HTTPException(status_code=409, detail={"code": "PRODUCTION_VERSION_CONFLICT", "current_version": ticket.version})
    if target not in _NEXT.get(ticket.status, set()):
        raise HTTPException(status_code=409, detail="Transição de produção inválida.")
    previous = ticket.status; now = datetime.utcnow(); ticket.status = target; ticket.version += 1; ticket.updated_at = now
    setattr(ticket, {ProductionTicketStatusEnum.ACCEPTED: "accepted_at", ProductionTicketStatusEnum.PREPARING: "preparing_at",
                     ProductionTicketStatusEnum.READY: "ready_at", ProductionTicketStatusEnum.DELIVERED: "delivered_at",
                     ProductionTicketStatusEnum.CANCELED: "canceled_at"}[target], now)
    transition = ProductionTransition(tenant_id=context.tenant_id, store_id=ticket.store_id, ticket_id=ticket.id,
                                      from_status=previous, to_status=target, expected_version=expected_version,
                                      resulting_version=ticket.version, actor_id=actor, device_id=device_id,
                                      idempotency_key=idempotency_key)
    session.add(transition)
    reliability_service.write_audit_and_outbox(
        session, context.tenant_id, ticket.store_id, actor, "production.ticket.transitioned",
        f"PRODUCTION-TICKET-{ticket.id}", {"from": previous.value, "to": target.value, "device_id": device_id,
        "version": ticket.version}, "production_ticket", str(ticket.id), "production.ticket.transitioned",
        {"from": previous.value, "to": target.value, "version": ticket.version},
    )
    session.commit(); session.refresh(ticket)
    ticket_items = session.exec(select(ProductionTicketItem).where(ProductionTicketItem.ticket_id == ticket.id)).all()
    for allocation in ticket_items:
        item = session.get(OrderItem, allocation.order_item_id)
        if not item or allocation.item_version != item.production_version or allocation.operation == ProductionOperationEnum.CANCEL: continue
        related_statuses = session.exec(select(ProductionTicket.status).join(
            ProductionTicketItem, ProductionTicketItem.ticket_id == ProductionTicket.id,
        ).where(ProductionTicketItem.order_item_id == item.id,
                ProductionTicketItem.item_version == item.production_version,
                ProductionTicketItem.operation != ProductionOperationEnum.CANCEL)).all()
        if related_statuses and all(status == ProductionTicketStatusEnum.DELIVERED for status in related_statuses):
            item.production_state = ProductionStateEnum.DELIVERED
        elif related_statuses and all(status in {ProductionTicketStatusEnum.READY, ProductionTicketStatusEnum.DELIVERED} for status in related_statuses):
            item.production_state = ProductionStateEnum.READY
        elif any(status in {ProductionTicketStatusEnum.ACCEPTED, ProductionTicketStatusEnum.PREPARING} for status in related_statuses):
            item.production_state = ProductionStateEnum.IN_PREPARATION
    session.commit(); return _ticket_projection(session, ticket)

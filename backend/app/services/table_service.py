import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.context import TenantContext, scope_tenant_query
from app.models.identity import Store
from app.models.order import (
    Order, OrderFulfillmentEnum, OrderItem, OrderItemStatusEnum, OrderOriginEnum,
    OrderStatusEnum,
)
from app.models.sale import Customer
from app.models.table_service import (
    ServiceTable, ServiceTableStatusEnum, TableSession, TableSessionCommand,
    TableSessionEvent, TableSessionKindEnum, TableSessionStatusEnum,
)
from app.services import reliability_service


ACTIVE_SESSION_STATUSES = (
    TableSessionStatusEnum.OPEN,
    TableSessionStatusEnum.IN_SERVICE,
    TableSessionStatusEnum.PARTIALLY_PAID,
    TableSessionStatusEnum.CLOSING,
)


def _hash(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _actor(context: TenantContext, actor_id: Optional[uuid.UUID]) -> uuid.UUID:
    effective = actor_id or context.user_id
    if not effective:
        raise HTTPException(status_code=400, detail="actor_id é obrigatório.")
    if context.user_id and effective != context.user_id:
        raise HTTPException(status_code=403, detail="Ator não corresponde à identidade autenticada.")
    return effective


def _store(session: Session, context: TenantContext, store_id: uuid.UUID) -> Store:
    if context.store_id and context.store_id != store_id:
        raise HTTPException(status_code=403, detail="Unidade fora do contexto ativo.")
    store = session.get(Store, store_id)
    if not store or store.tenant_id != context.tenant_id or not store.is_active:
        raise HTTPException(status_code=404, detail="Unidade não encontrada.")
    return store


def _write_event(
    session: Session,
    context: TenantContext,
    table_session: TableSession,
    actor_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    *,
    from_status: Optional[TableSessionStatusEnum] = None,
    to_status: Optional[TableSessionStatusEnum] = None,
    reason: Optional[str] = None,
) -> None:
    session.add(TableSessionEvent(
        tenant_id=context.tenant_id,
        table_session_id=table_session.id,
        event_type=event_type,
        actor_id=actor_id,
        from_status=from_status.value if from_status else None,
        to_status=to_status.value if to_status else None,
        reason=reason,
        payload=payload,
    ))
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=table_session.store_id,
        actor_id=actor_id,
        action=event_type,
        target=f"TABLE-SESSION-{table_session.id}",
        audit_payload=payload,
        aggregate_type="table_session",
        aggregate_id=str(table_session.id),
        event_type=event_type,
        outbox_payload={
            "tenant_id": str(context.tenant_id),
            "store_id": str(table_session.store_id),
            "table_session_id": str(table_session.id),
            **payload,
        },
    )


def create_service_table(
    session: Session,
    context: TenantContext,
    *,
    store_id: uuid.UUID,
    code: str,
    name: str,
    capacity: int,
    area: Optional[str],
    actor_id: Optional[uuid.UUID],
    idempotency_key: str,
) -> ServiceTable:
    _store(session, context, store_id)
    actor = _actor(context, actor_id)
    normalized_code = code.strip().upper()
    normalized_name = name.strip()
    if not normalized_code or not normalized_name:
        raise HTTPException(status_code=400, detail="Código e nome da mesa são obrigatórios.")
    if capacity < 1:
        raise HTTPException(status_code=400, detail="Capacidade deve ser positiva.")
    payload = {
        "store_id": str(store_id), "code": normalized_code, "name": normalized_name,
        "capacity": capacity, "area": area.strip() if area else None,
    }
    request_hash = _hash(payload)
    by_key = session.exec(select(ServiceTable).where(
        ServiceTable.tenant_id == context.tenant_id,
        ServiceTable.creation_idempotency_key == idempotency_key,
    )).first()
    if by_key:
        if by_key.creation_request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency-Key já utilizada com outro cadastro de mesa.")
        return by_key
    existing = session.exec(select(ServiceTable).where(
        ServiceTable.tenant_id == context.tenant_id,
        ServiceTable.store_id == store_id,
        ServiceTable.code == normalized_code,
    )).first()
    if existing:
        if existing.name == normalized_name and existing.capacity == capacity and existing.area == (area.strip() if area else None):
            return existing
        raise HTTPException(status_code=409, detail="Já existe uma mesa com este código na unidade.")
    table = ServiceTable(
        tenant_id=context.tenant_id,
        store_id=store_id,
        code=normalized_code,
        name=normalized_name,
        capacity=capacity,
        area=area.strip() if area else None,
        creation_idempotency_key=idempotency_key.strip(),
        creation_request_hash=request_hash,
    )
    session.add(table)
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=store_id,
        actor_id=actor,
        action="service_table.created",
        target=f"SERVICE-TABLE-{table.id}",
        audit_payload={"code": table.code, "name": table.name, "capacity": capacity, "area": table.area},
        aggregate_type="service_table",
        aggregate_id=str(table.id),
        event_type="service_table.created",
        outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(store_id), "service_table_id": str(table.id)},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = session.exec(select(ServiceTable).where(
            ServiceTable.tenant_id == context.tenant_id,
            ServiceTable.creation_idempotency_key == idempotency_key,
        )).first()
        if existing and existing.creation_request_hash == request_hash:
            return existing
        raise HTTPException(status_code=409, detail="Conflito ao cadastrar mesa.") from exc
    session.refresh(table)
    return table


def list_service_tables(session: Session, context: TenantContext) -> list[dict[str, Any]]:
    table_query = scope_tenant_query(select(ServiceTable), ServiceTable, context).where(ServiceTable.is_active.is_(True))
    tables = list(session.exec(table_query.order_by(ServiceTable.area, ServiceTable.code)).all())
    if not tables:
        return []
    table_ids = [table.id for table in tables]
    sessions = list(session.exec(scope_tenant_query(select(TableSession).where(
        TableSession.service_table_id.in_(table_ids),
        TableSession.status.in_(ACTIVE_SESSION_STATUSES),
    ), TableSession, context)).all())
    sessions_by_table = {item.service_table_id: item for item in sessions}
    session_ids = [item.id for item in sessions]
    orders = list(session.exec(scope_tenant_query(select(Order).where(
        Order.table_session_id.in_(session_ids),
    ), Order, context)).all()) if session_ids else []
    order_ids = [order.id for order in orders]
    items = list(session.exec(select(OrderItem).where(
        OrderItem.tenant_id == context.tenant_id,
        OrderItem.order_id.in_(order_ids),
        OrderItem.status == OrderItemStatusEnum.ACTIVE,
    )).all()) if order_ids else []
    orders_by_session: dict[uuid.UUID, list[Order]] = {}
    for order in orders:
        orders_by_session.setdefault(order.table_session_id, []).append(order)
    items_by_order: dict[uuid.UUID, list[OrderItem]] = {}
    for item in items:
        items_by_order.setdefault(item.order_id, []).append(item)
    result: list[dict[str, Any]] = []
    for table in tables:
        active = sessions_by_table.get(table.id)
        session_orders = orders_by_session.get(active.id, []) if active else []
        session_items = [item for order in session_orders for item in items_by_order.get(order.id, [])]
        total = sum((Decimal(str(item.unit_price)) * Decimal(str(item.quantity)) for item in session_items), Decimal("0"))
        result.append({
            **table.model_dump(),
            "active_session_id": active.id if active else None,
            "active_session_status": active.status if active else None,
            "active_session_label": active.display_label if active else None,
            "order_count": len(session_orders),
            "item_count": len(session_items),
            "consolidated_total": total,
        })
    return result


def _get_session(
    session: Session,
    context: TenantContext,
    table_session_id: uuid.UUID,
    *,
    lock: bool = False,
) -> TableSession:
    query = scope_tenant_query(select(TableSession).where(TableSession.id == table_session_id), TableSession, context)
    if lock:
        query = query.with_for_update()
    table_session = session.exec(query).first()
    if not table_session:
        raise HTTPException(status_code=404, detail="Sessão de atendimento não encontrada no contexto ativo.")
    return table_session


def session_projection(session: Session, context: TenantContext, table_session_id: uuid.UUID) -> dict[str, Any]:
    table_session = _get_session(session, context, table_session_id)
    table = session.get(ServiceTable, table_session.service_table_id) if table_session.service_table_id else None
    orders = list(session.exec(scope_tenant_query(select(Order).where(
        Order.table_session_id == table_session.id,
    ), Order, context).order_by(Order.created_at)).all())
    order_ids = [order.id for order in orders]
    items = list(session.exec(select(OrderItem).where(
        OrderItem.tenant_id == context.tenant_id,
        OrderItem.order_id.in_(order_ids),
    ).order_by(OrderItem.created_at)).all()) if order_ids else []
    items_by_order: dict[uuid.UUID, list[OrderItem]] = {}
    for item in items:
        items_by_order.setdefault(item.order_id, []).append(item)
    order_payloads: list[dict[str, Any]] = []
    consolidated_total = Decimal("0")
    active_item_count = 0
    for order in orders:
        order_items = items_by_order.get(order.id, [])
        for item in order_items:
            if item.status == OrderItemStatusEnum.ACTIVE:
                consolidated_total += Decimal(str(item.unit_price)) * Decimal(str(item.quantity))
                active_item_count += 1
        order_payloads.append({**order.model_dump(), "items": [item.model_dump() for item in order_items]})
    events = list(session.exec(select(TableSessionEvent).where(
        TableSessionEvent.tenant_id == context.tenant_id,
        TableSessionEvent.table_session_id == table_session.id,
    ).order_by(TableSessionEvent.created_at)).all())
    return {
        **table_session.model_dump(),
        "service_table": table.model_dump() if table else None,
        "orders": order_payloads,
        "events": [event.model_dump() for event in events],
        "order_count": len(orders),
        "active_item_count": active_item_count,
        "consolidated_total": consolidated_total,
    }


def list_active_sessions(session: Session, context: TenantContext) -> list[dict[str, Any]]:
    sessions = list(session.exec(scope_tenant_query(select(TableSession).where(
        TableSession.status.in_(ACTIVE_SESSION_STATUSES),
    ), TableSession, context).order_by(TableSession.updated_at.desc()).limit(200)).all())
    if not sessions:
        return []
    session_ids = [item.id for item in sessions]
    orders = list(session.exec(scope_tenant_query(select(Order).where(
        Order.table_session_id.in_(session_ids),
    ), Order, context)).all())
    order_ids = [order.id for order in orders]
    items = list(session.exec(select(OrderItem).where(
        OrderItem.tenant_id == context.tenant_id,
        OrderItem.order_id.in_(order_ids),
        OrderItem.status == OrderItemStatusEnum.ACTIVE,
    )).all()) if order_ids else []
    orders_by_session: dict[uuid.UUID, list[Order]] = {}
    for order in orders:
        orders_by_session.setdefault(order.table_session_id, []).append(order)
    items_by_order: dict[uuid.UUID, list[OrderItem]] = {}
    for item in items:
        items_by_order.setdefault(item.order_id, []).append(item)
    result: list[dict[str, Any]] = []
    for table_session in sessions:
        session_orders = orders_by_session.get(table_session.id, [])
        session_items = [item for order in session_orders for item in items_by_order.get(order.id, [])]
        total = sum((Decimal(str(item.unit_price)) * Decimal(str(item.quantity)) for item in session_items), Decimal("0"))
        result.append({
            "id": table_session.id,
            "service_table_id": table_session.service_table_id,
            "kind": table_session.kind,
            "status": table_session.status,
            "display_label": table_session.display_label,
            "version": table_session.version,
            "opened_at": table_session.opened_at,
            "updated_at": table_session.updated_at,
            "order_count": len(session_orders),
            "item_count": len(session_items),
            "consolidated_total": total,
        })
    return result


def open_table_session(
    session: Session,
    context: TenantContext,
    *,
    store_id: uuid.UUID,
    service_table_id: Optional[uuid.UUID],
    display_label: Optional[str],
    customer_id: Optional[uuid.UUID],
    attendant_id: Optional[uuid.UUID],
    actor_id: Optional[uuid.UUID],
    idempotency_key: str,
) -> dict[str, Any]:
    _store(session, context, store_id)
    actor = _actor(context, actor_id)
    attendant = attendant_id or actor
    payload = {
        "store_id": str(store_id),
        "service_table_id": str(service_table_id) if service_table_id else None,
        "display_label": display_label.strip() if display_label else None,
        "customer_id": str(customer_id) if customer_id else None,
        "attendant_id": str(attendant),
    }
    request_hash = _hash(payload)
    existing = session.exec(select(TableSession).where(
        TableSession.tenant_id == context.tenant_id,
        TableSession.open_idempotency_key == idempotency_key,
    )).first()
    if existing:
        if existing.open_request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency-Key já utilizada com outra abertura.")
        return session_projection(session, context, existing.id)
    if customer_id and not session.exec(scope_tenant_query(select(Customer).where(Customer.id == customer_id), Customer, context)).first():
        raise HTTPException(status_code=404, detail="Cliente não encontrado.")
    table: Optional[ServiceTable] = None
    kind = TableSessionKindEnum.INDIVIDUAL_TAB
    label = display_label.strip() if display_label else ""
    if service_table_id:
        table_query = scope_tenant_query(select(ServiceTable).where(
            ServiceTable.id == service_table_id,
            ServiceTable.is_active.is_(True),
        ), ServiceTable, context).with_for_update()
        table = session.exec(table_query).first()
        if not table:
            raise HTTPException(status_code=404, detail="Mesa não encontrada.")
        if table.status != ServiceTableStatusEnum.AVAILABLE:
            concurrent_retry = session.exec(select(TableSession).where(
                TableSession.tenant_id == context.tenant_id,
                TableSession.open_idempotency_key == idempotency_key,
            )).first()
            if concurrent_retry and concurrent_retry.open_request_hash == request_hash:
                return session_projection(session, context, concurrent_retry.id)
            raise HTTPException(status_code=409, detail="Mesa não está disponível para abertura.")
        kind = TableSessionKindEnum.TABLE
        label = label or table.name
    elif not label:
        raise HTTPException(status_code=400, detail="Informe uma identificação para a comanda individual.")
    table_session = TableSession(
        tenant_id=context.tenant_id,
        store_id=store_id,
        service_table_id=service_table_id,
        kind=kind,
        status=TableSessionStatusEnum.OPEN,
        display_label=label,
        customer_id=customer_id,
        attendant_id=attendant,
        opened_by=actor,
        open_idempotency_key=idempotency_key.strip(),
        open_request_hash=request_hash,
    )
    order = Order(
        tenant_id=context.tenant_id,
        store_id=store_id,
        customer_id=customer_id,
        table_id=service_table_id,
        table_session_id=table_session.id,
        origin=OrderOriginEnum.POS,
        fulfillment=OrderFulfillmentEnum.DINE_IN,
        status=OrderStatusEnum.OPEN,
        idempotency_key=f"table-session:{table_session.id}:order:1",
        external_reference=None,
        opened_by=actor,
        notes=None,
    )
    session.add(table_session)
    try:
        # The initial order references the new session.  Flush the aggregate
        # root first so PostgreSQL can enforce the FK without depending on
        # SQLAlchemy's insert ordering across models that have no ORM
        # relationship configured.  This remains inside the same transaction.
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        existing = session.exec(select(TableSession).where(
            TableSession.tenant_id == context.tenant_id,
            TableSession.open_idempotency_key == idempotency_key,
        )).first()
        if existing and existing.open_request_hash == request_hash:
            return session_projection(session, context, existing.id)
        raise HTTPException(
            status_code=409,
            detail="Mesa já possui uma sessão ativa ou houve abertura concorrente.",
        ) from exc
    session.add(order)
    if table:
        table.status = ServiceTableStatusEnum.OCCUPIED
        table.version += 1
        table.updated_at = datetime.utcnow()
    _write_event(session, context, table_session, actor, "table_session.opened", {
        "service_table_id": str(service_table_id) if service_table_id else None,
        "kind": kind.value,
        "display_label": label,
        "customer_id": str(customer_id) if customer_id else None,
        "attendant_id": str(attendant),
        "initial_order_id": str(order.id),
    }, to_status=TableSessionStatusEnum.OPEN)
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=store_id,
        actor_id=actor,
        action="order.created",
        target=f"ORDER-{order.id}",
        audit_payload={"table_session_id": str(table_session.id), "table_id": str(service_table_id) if service_table_id else None},
        aggregate_type="order",
        aggregate_id=str(order.id),
        event_type="order.created",
        outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(store_id), "order_id": str(order.id), "table_session_id": str(table_session.id)},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = session.exec(select(TableSession).where(
            TableSession.tenant_id == context.tenant_id,
            TableSession.open_idempotency_key == idempotency_key,
        )).first()
        if existing and existing.open_request_hash == request_hash:
            return session_projection(session, context, existing.id)
        raise HTTPException(status_code=409, detail="Mesa já possui uma sessão ativa ou houve abertura concorrente.") from exc
    return session_projection(session, context, table_session.id)


def add_session_order(
    session: Session,
    context: TenantContext,
    table_session_id: uuid.UUID,
    *,
    display_reference: Optional[str],
    customer_id: Optional[uuid.UUID],
    actor_id: Optional[uuid.UUID],
    idempotency_key: str,
) -> Order:
    actor = _actor(context, actor_id)
    table_session = _get_session(session, context, table_session_id, lock=True)
    if table_session.status not in ACTIVE_SESSION_STATUSES[:3]:
        raise HTTPException(status_code=409, detail="Sessão não aceita novas comandas.")
    effective_customer = customer_id or table_session.customer_id
    if effective_customer and not session.exec(scope_tenant_query(select(Customer).where(Customer.id == effective_customer), Customer, context)).first():
        raise HTTPException(status_code=404, detail="Cliente não encontrado.")
    existing = session.exec(select(Order).where(
        Order.tenant_id == context.tenant_id,
        Order.idempotency_key == idempotency_key,
    )).first()
    if existing:
        if existing.table_session_id != table_session.id or existing.customer_id != effective_customer or existing.notes != display_reference:
            raise HTTPException(status_code=409, detail="Idempotency-Key já utilizada com outra comanda.")
        return existing
    order = Order(
        tenant_id=context.tenant_id,
        store_id=table_session.store_id,
        customer_id=effective_customer,
        table_id=table_session.service_table_id,
        table_session_id=table_session.id,
        origin=OrderOriginEnum.POS,
        fulfillment=OrderFulfillmentEnum.DINE_IN,
        status=OrderStatusEnum.OPEN,
        idempotency_key=idempotency_key,
        opened_by=actor,
        notes=display_reference.strip() if display_reference else None,
    )
    session.add(order)
    previous = table_session.status
    if table_session.status == TableSessionStatusEnum.OPEN:
        table_session.status = TableSessionStatusEnum.IN_SERVICE
    table_session.version += 1
    table_session.updated_at = datetime.utcnow()
    _write_event(session, context, table_session, actor, "table_session.order_added", {
        "order_id": str(order.id), "customer_id": str(effective_customer) if effective_customer else None,
        "reference": order.notes,
    }, from_status=previous, to_status=table_session.status)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = session.exec(select(Order).where(
            Order.tenant_id == context.tenant_id,
            Order.idempotency_key == idempotency_key,
        )).first()
        if existing:
            return existing
        raise HTTPException(status_code=409, detail="Conflito ao criar comanda.") from exc
    session.refresh(order)
    return order


def close_empty_session(
    session: Session,
    context: TenantContext,
    table_session_id: uuid.UUID,
    *,
    expected_version: int,
    reason: str,
    actor_id: Optional[uuid.UUID],
    idempotency_key: str,
) -> dict[str, Any]:
    actor = _actor(context, actor_id)
    payload = {"expected_version": expected_version, "reason": reason.strip()}
    existing_command = session.exec(select(TableSessionCommand).where(
        TableSessionCommand.tenant_id == context.tenant_id,
        TableSessionCommand.idempotency_key == idempotency_key,
    )).first()
    if existing_command:
        if existing_command.table_session_id != table_session_id or existing_command.command_type != "CLOSE_EMPTY" or existing_command.request_hash != _hash(payload):
            raise HTTPException(status_code=409, detail="Idempotency-Key já utilizada com outro encerramento.")
        return session_projection(session, context, table_session_id)
    table_session = _get_session(session, context, table_session_id, lock=True)
    concurrent_command = session.exec(select(TableSessionCommand).where(
        TableSessionCommand.tenant_id == context.tenant_id,
        TableSessionCommand.idempotency_key == idempotency_key,
    )).first()
    if concurrent_command:
        if concurrent_command.table_session_id == table_session_id and concurrent_command.command_type == "CLOSE_EMPTY" and concurrent_command.request_hash == _hash(payload):
            return session_projection(session, context, table_session_id)
        raise HTTPException(status_code=409, detail="Idempotency-Key já utilizada com outro encerramento.")
    if table_session.status in {TableSessionStatusEnum.CLOSED, TableSessionStatusEnum.CANCELED}:
        raise HTTPException(status_code=409, detail="Sessão já encerrada.")
    if table_session.version != expected_version:
        raise HTTPException(status_code=409, detail={"code": "STALE_VERSION", "current_version": table_session.version})
    order_ids = list(session.exec(select(Order.id).where(
        Order.tenant_id == context.tenant_id,
        Order.table_session_id == table_session.id,
    )).all())
    active_items = session.exec(select(OrderItem.id).where(
        OrderItem.tenant_id == context.tenant_id,
        OrderItem.order_id.in_(order_ids),
        OrderItem.status == OrderItemStatusEnum.ACTIVE,
    )).first() if order_ids else None
    if active_items:
        raise HTTPException(status_code=409, detail="Sessão possui consumo ativo; o fechamento financeiro será realizado pelo Payment Engine.")
    previous = table_session.status
    table_session.status = TableSessionStatusEnum.CLOSED
    table_session.closed_by = actor
    table_session.close_reason = reason.strip()
    table_session.closed_at = datetime.utcnow()
    table_session.updated_at = table_session.closed_at
    table_session.version += 1
    for order in session.exec(select(Order).where(
        Order.tenant_id == context.tenant_id,
        Order.table_session_id == table_session.id,
        Order.status == OrderStatusEnum.OPEN,
    )).all():
        order.status = OrderStatusEnum.CLOSED
        order.updated_at = table_session.updated_at
    if table_session.service_table_id:
        table = session.exec(scope_tenant_query(select(ServiceTable).where(
            ServiceTable.id == table_session.service_table_id,
        ), ServiceTable, context).with_for_update()).first()
        if table:
            table.status = ServiceTableStatusEnum.AVAILABLE
            table.version += 1
            table.updated_at = table_session.updated_at
    session.add(TableSessionCommand(
        tenant_id=context.tenant_id,
        table_session_id=table_session.id,
        idempotency_key=idempotency_key,
        command_type="CLOSE_EMPTY",
        request_hash=_hash(payload),
        result_entity_id=table_session.id,
        actor_id=actor,
    ))
    _write_event(session, context, table_session, actor, "table_session.closed", {
        "reason": reason.strip(), "service_table_id": str(table_session.service_table_id) if table_session.service_table_id else None,
    }, from_status=previous, to_status=TableSessionStatusEnum.CLOSED, reason=reason.strip())
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Conflito ao encerrar sessão.") from exc
    return session_projection(session, context, table_session.id)


def touch_session_activity(
    session: Session,
    context: TenantContext,
    order: Order,
    actor_id: uuid.UUID,
    order_item_id: uuid.UUID,
) -> None:
    if not order.table_session_id:
        return
    table_session = session.exec(scope_tenant_query(select(TableSession).where(
        TableSession.id == order.table_session_id,
    ), TableSession, context).with_for_update()).first()
    if not table_session or table_session.status not in ACTIVE_SESSION_STATUSES[:3]:
        raise HTTPException(status_code=409, detail="Sessão de atendimento não aceita lançamentos.")
    previous = table_session.status
    if table_session.status == TableSessionStatusEnum.OPEN:
        table_session.status = TableSessionStatusEnum.IN_SERVICE
    table_session.version += 1
    table_session.updated_at = datetime.utcnow()
    _write_event(session, context, table_session, actor_id, "table_session.item_added", {
        "order_id": str(order.id), "order_item_id": str(order_item_id), "version": table_session.version,
    }, from_status=previous, to_status=table_session.status)

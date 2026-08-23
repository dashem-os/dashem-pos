import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from fastapi import HTTPException
from sqlmodel import Session, select
from app.core.context import TenantContext, scope_tenant_query
from app.models.negotiation import PaymentAllocation
from app.models.order import Order, OrderFulfillmentEnum, OrderItem, OrderItemStatusEnum, OrderOriginEnum, OrderStatusEnum, ProductionStateEnum
from app.models.production import ProductionTicket, ProductionTicketItem, ProductionTicketStatusEnum
from app.models.table_service import ServiceTable, ServiceTableStatusEnum, TableSession, TableSessionEvent, TableSessionStatusEnum
from app.models.transfer import TransferRecord, TransferTypeEnum
from app.services import reliability_service

ACTIVE={TableSessionStatusEnum.OPEN,TableSessionStatusEnum.IN_SERVICE}

def _actor(context: TenantContext, actor_id: Optional[uuid.UUID])->uuid.UUID:
    actor=actor_id or context.user_id
    if not actor: raise HTTPException(400,"actor_id é obrigatório.")
    if context.user_id and actor!=context.user_id: raise HTTPException(403,"Ator inválido.")
    return actor

def _sessions(session: Session, context: TenantContext, source_id: uuid.UUID, destination_id: uuid.UUID):
    if source_id==destination_id: raise HTTPException(422,"Origem e destino devem ser diferentes.")
    rows=list(session.exec(scope_tenant_query(select(TableSession).where(TableSession.id.in_([source_id,destination_id])).order_by(TableSession.id).with_for_update(),TableSession,context)).all())
    if len(rows)!=2: raise HTTPException(404,"Sessão de origem ou destino não encontrada.")
    by_id={row.id:row for row in rows}; source=by_id[source_id]; destination=by_id[destination_id]
    if source.store_id!=destination.store_id: raise HTTPException(403,"Transferência entre unidades não é permitida.")
    if source.status not in ACTIVE or destination.status not in ACTIVE: raise HTTPException(409,"Sessões em pagamento, fechamento ou encerradas não aceitam transferência.")
    return source,destination

def _destination_order(session: Session, context: TenantContext, target: TableSession, actor: uuid.UUID)->Order:
    order=session.exec(select(Order).where(Order.tenant_id==context.tenant_id,Order.table_session_id==target.id,Order.status==OrderStatusEnum.OPEN).order_by(Order.created_at)).first()
    if order:return order
    order=Order(tenant_id=context.tenant_id,store_id=target.store_id,table_id=target.service_table_id,table_session_id=target.id,
        origin=OrderOriginEnum.POS,fulfillment=OrderFulfillmentEnum.DINE_IN,status=OrderStatusEnum.OPEN,
        idempotency_key=f"transfer-destination-{uuid.uuid4()}",opened_by=actor,notes="Comanda de transferência")
    session.add(order);session.flush();return order

def _production_state(session: Session,item_id:uuid.UUID):
    tickets=list(session.exec(select(ProductionTicket).join(ProductionTicketItem,ProductionTicketItem.ticket_id==ProductionTicket.id).where(ProductionTicketItem.order_item_id==item_id)).all())
    if any(ticket.status in {ProductionTicketStatusEnum.READY,ProductionTicketStatusEnum.DELIVERED} for ticket in tickets):
        raise HTTPException(409,"Item pronto ou entregue não pode ser transferido sem estorno operacional.")
    return bool(tickets)

def transfer_item(session:Session,context:TenantContext,*,source_session_id:uuid.UUID,destination_session_id:uuid.UUID,
    order_item_id:uuid.UUID,quantity:Decimal,expected_source_version:int,expected_destination_version:int,
    reason:str,actor_id:Optional[uuid.UUID],idempotency_key:str)->TransferRecord:
    actor=_actor(context,actor_id);payload={"source_session_id":str(source_session_id),"destination_session_id":str(destination_session_id),"order_item_id":str(order_item_id),"quantity":str(quantity),"expected_source_version":expected_source_version,"expected_destination_version":expected_destination_version,"reason":reason.strip()};request_hash=reliability_service.compute_request_hash(payload)
    existing=session.exec(select(TransferRecord).where(TransferRecord.tenant_id==context.tenant_id,TransferRecord.idempotency_key==idempotency_key)).first()
    if existing:
        if existing.request_hash!=request_hash:raise HTTPException(409,"Idempotency-Key reutilizada com outra transferência.")
        return existing
    source,destination=_sessions(session,context,source_session_id,destination_session_id)
    if source.version!=expected_source_version or destination.version!=expected_destination_version:
        raise HTTPException(409,detail={"code":"TRANSFER_VERSION_CONFLICT","source_version":source.version,"destination_version":destination.version})
    item=session.exec(select(OrderItem).join(Order,Order.id==OrderItem.order_id).where(OrderItem.id==order_item_id,OrderItem.tenant_id==context.tenant_id,Order.table_session_id==source.id).with_for_update()).first()
    if not item or item.status!=OrderItemStatusEnum.ACTIVE:raise HTTPException(404,"Item ativo não encontrado na origem.")
    if quantity<=0 or quantity>item.quantity:raise HTTPException(422,"Quantidade de transferência inválida.")
    if session.exec(select(PaymentAllocation).where(PaymentAllocation.order_item_id==item.id)).first():raise HTTPException(409,"Item com cobertura financeira não pode mudar de obrigação.")
    source_order=session.get(Order,item.order_id)
    if source_order.sale_id:raise HTTPException(409,"Item já materializado em venda não pode ser transferido.")
    compensation=_production_state(session,item.id);destination_order=_destination_order(session,context,destination,actor)
    derived=OrderItem(tenant_id=context.tenant_id,order_id=destination_order.id,product_id=item.product_id,product_name=item.product_name,
        sku=item.sku,unit_snapshot=item.unit_snapshot,unit_price=item.unit_price,quantity=quantity,modifier_snapshot=item.modifier_snapshot,
        notes=item.notes,production_destination=item.production_destination,production_state=ProductionStateEnum.PENDING if item.production_state!=ProductionStateEnum.NOT_REQUIRED else ProductionStateEnum.NOT_REQUIRED,
        production_version=1,status=OrderItemStatusEnum.ACTIVE,added_by=actor)
    session.add(derived);session.flush()
    if quantity==item.quantity:
        item.status=OrderItemStatusEnum.CANCELED;item.canceled_by=actor;item.cancellation_reason=f"Transferido: {reason.strip()}";item.canceled_at=datetime.utcnow();item.production_state=ProductionStateEnum.CANCELED
    else:item.quantity-=quantity
    item.production_version+=1;item.updated_at=datetime.utcnow();source.version+=1;destination.version+=1;source.updated_at=item.updated_at;destination.updated_at=item.updated_at
    record=TransferRecord(tenant_id=context.tenant_id,store_id=source.store_id,transfer_type=TransferTypeEnum.ITEM,
        source_session_id=source.id,destination_session_id=destination.id,source_order_id=source_order.id,destination_order_id=destination_order.id,
        source_order_item_id=item.id,derived_order_item_id=derived.id,quantity=quantity,unit_price_snapshot=item.unit_price,
        source_version_before=expected_source_version,destination_version_before=expected_destination_version,actor_id=actor,reason=reason.strip(),
        production_compensation_required=compensation,idempotency_key=idempotency_key,request_hash=request_hash)
    session.add(record)
    for target,event in ((source,"table_session.item.transferred_out"),(destination,"table_session.item.transferred_in")):
        session.add(TableSessionEvent(tenant_id=context.tenant_id,table_session_id=target.id,event_type=event,actor_id=actor,reason=reason.strip(),payload={"transfer_id":str(record.id),"quantity":str(quantity),"source_item_id":str(item.id),"derived_item_id":str(derived.id)}))
    reliability_service.write_audit_and_outbox(session,context.tenant_id,source.store_id,actor,"table.transfer.item",f"TRANSFER-{record.id}",payload,"transfer",str(record.id),"table.transfer.item",{"source_item_id":str(item.id),"derived_item_id":str(derived.id),"compensation_required":compensation})
    session.commit();session.refresh(record);return record

def merge_sessions(session:Session,context:TenantContext,*,source_session_id:uuid.UUID,destination_session_id:uuid.UUID,
    expected_source_version:int,expected_destination_version:int,reason:str,actor_id:Optional[uuid.UUID],idempotency_key:str)->TransferRecord:
    actor=_actor(context,actor_id);payload={"source_session_id":str(source_session_id),"destination_session_id":str(destination_session_id),"expected_source_version":expected_source_version,"expected_destination_version":expected_destination_version,"reason":reason.strip()};digest=reliability_service.compute_request_hash(payload)
    existing=session.exec(select(TransferRecord).where(TransferRecord.tenant_id==context.tenant_id,TransferRecord.idempotency_key==idempotency_key)).first()
    if existing:
        if existing.request_hash!=digest:raise HTTPException(409,"Idempotency-Key reutilizada.")
        return existing
    source,destination=_sessions(session,context,source_session_id,destination_session_id)
    if source.version!=expected_source_version or destination.version!=expected_destination_version:raise HTTPException(409,detail={"code":"TRANSFER_VERSION_CONFLICT","source_version":source.version,"destination_version":destination.version})
    orders=list(session.exec(select(Order).where(Order.tenant_id==context.tenant_id,Order.table_session_id==source.id)).all())
    item_ids=list(session.exec(select(OrderItem.id).where(OrderItem.order_id.in_([o.id for o in orders]))).all()) if orders else []
    if item_ids and session.exec(select(PaymentAllocation).where(PaymentAllocation.order_item_id.in_(item_ids))).first():raise HTTPException(409,"Sessão possui itens cobertos por pagamento.")
    for item_id in item_ids:_production_state(session,item_id)
    for order in orders:order.table_session_id=destination.id;order.table_id=destination.service_table_id;order.updated_at=datetime.utcnow()
    source.status=TableSessionStatusEnum.CLOSED;source.closed_by=actor;source.close_reason=f"Unida à sessão {destination.id}: {reason.strip()}";source.closed_at=datetime.utcnow();source.version+=1;destination.version+=1
    if source.service_table_id:
        table=session.get(ServiceTable,source.service_table_id)
        if table:table.status=ServiceTableStatusEnum.AVAILABLE;table.version+=1;table.updated_at=datetime.utcnow()
    record=TransferRecord(tenant_id=context.tenant_id,store_id=source.store_id,transfer_type=TransferTypeEnum.SESSION_MERGE,
        source_session_id=source.id,destination_session_id=destination.id,source_version_before=expected_source_version,destination_version_before=expected_destination_version,
        actor_id=actor,reason=reason.strip(),idempotency_key=idempotency_key,request_hash=digest)
    session.add(record);reliability_service.write_audit_and_outbox(session,context.tenant_id,source.store_id,actor,"table.transfer.merge",f"TRANSFER-{record.id}",payload,"transfer",str(record.id),"table.transfer.merge",{"order_ids":[str(o.id) for o in orders]})
    session.commit();session.refresh(record);return record

def list_transfers(session:Session,context:TenantContext,table_session_id:Optional[uuid.UUID]=None)->list[TransferRecord]:
    query=scope_tenant_query(select(TransferRecord),TransferRecord,context)
    if table_session_id:query=query.where((TransferRecord.source_session_id==table_session_id)|(TransferRecord.destination_session_id==table_session_id))
    return list(session.exec(query.order_by(TransferRecord.created_at.desc()).limit(200)).all())

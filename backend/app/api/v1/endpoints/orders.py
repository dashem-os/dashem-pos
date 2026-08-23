import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.order import (
    OrderFulfillmentEnum, OrderItemStatusEnum, OrderOriginEnum,
    OrderStatusEnum, ProductionStateEnum,
)
from app.services import order_service


router = APIRouter()


class OrderItemReadDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    order_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    sku: str
    unit_snapshot: str
    unit_price: Decimal
    quantity: Decimal
    modifier_snapshot: list[dict[str, Any]]
    notes: Optional[str]
    production_destination: Optional[str]
    production_state: ProductionStateEnum
    status: OrderItemStatusEnum
    added_by: uuid.UUID
    canceled_by: Optional[uuid.UUID]
    cancellation_reason: Optional[str]
    canceled_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class OrderReadDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    register_id: Optional[uuid.UUID]
    customer_id: Optional[uuid.UUID]
    table_id: Optional[uuid.UUID]
    table_session_id: Optional[uuid.UUID]
    sale_id: Optional[uuid.UUID]
    channel_id: Optional[uuid.UUID]
    origin: OrderOriginEnum
    fulfillment: OrderFulfillmentEnum
    status: OrderStatusEnum
    idempotency_key: str
    external_reference: Optional[str]
    opened_by: uuid.UUID
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemReadDTO] = []


class OrderCreateDTO(BaseModel):
    store_id: uuid.UUID
    register_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    table_id: Optional[uuid.UUID] = None
    table_session_id: Optional[uuid.UUID] = None
    sale_id: Optional[uuid.UUID] = None
    channel_id: Optional[uuid.UUID] = None
    origin: OrderOriginEnum = OrderOriginEnum.POS
    fulfillment: OrderFulfillmentEnum = OrderFulfillmentEnum.COUNTER
    external_reference: Optional[str] = Field(default=None, max_length=160)
    actor_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None


class OrderItemAddDTO(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    modifier_ids: list[uuid.UUID] = Field(default_factory=list)
    notes: Optional[str] = None
    actor_id: Optional[uuid.UUID] = None


class OrderItemUpdateDTO(BaseModel):
    quantity: Decimal = Field(gt=0)
    notes: Optional[str] = None
    actor_id: Optional[uuid.UUID] = None


class OrderItemCancelDTO(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    actor_id: Optional[uuid.UUID] = None


@router.post("", response_model=OrderReadDTO)
def create_order_endpoint(
    data: OrderCreateDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return order_service.create_order(
        session, context, store_id=data.store_id, idempotency_key=idempotency_key,
        actor_id=data.actor_id, register_id=data.register_id, customer_id=data.customer_id,
        table_id=data.table_id, table_session_id=data.table_session_id,
        sale_id=data.sale_id, channel_id=data.channel_id,
        origin=data.origin, fulfillment=data.fulfillment,
        external_reference=data.external_reference, notes=data.notes,
    )


@router.get("", response_model=List[OrderReadDTO])
def list_orders_endpoint(
    status: Optional[OrderStatusEnum] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return order_service.list_orders(session, context, status)


@router.get("/{order_id}", response_model=OrderReadDTO)
def get_order_endpoint(
    order_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return order_service.get_order(session, context, order_id)


@router.post("/{order_id}/items", response_model=OrderItemReadDTO)
def add_order_item_endpoint(
    order_id: uuid.UUID, data: OrderItemAddDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return order_service.add_item(
        session, context, order_id, product_id=data.product_id, quantity=data.quantity,
        modifier_ids=data.modifier_ids, notes=data.notes,
        idempotency_key=idempotency_key, actor_id=data.actor_id,
    )


@router.patch("/{order_id}/items/{item_id}", response_model=OrderItemReadDTO)
def update_order_item_endpoint(
    order_id: uuid.UUID, item_id: uuid.UUID, data: OrderItemUpdateDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return order_service.update_item(
        session, context, order_id, item_id, quantity=data.quantity, notes=data.notes,
        idempotency_key=idempotency_key, actor_id=data.actor_id,
    )


@router.post("/{order_id}/items/{item_id}/cancel", response_model=OrderItemReadDTO)
def cancel_order_item_endpoint(
    order_id: uuid.UUID, item_id: uuid.UUID, data: OrderItemCancelDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return order_service.cancel_item(
        session, context, order_id, item_id, reason=data.reason,
        idempotency_key=idempotency_key, actor_id=data.actor_id,
    )

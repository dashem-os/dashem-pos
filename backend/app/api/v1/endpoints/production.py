import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.order import OrderFulfillmentEnum
from app.models.production import ProductionOperationEnum, ProductionPointTypeEnum, ProductionTicketStatusEnum
from app.services import production_service

router = APIRouter()

class PointCreateDTO(BaseModel):
    store_id: uuid.UUID; code: str = Field(min_length=2, max_length=80); name: str = Field(min_length=2, max_length=160)
    point_type: ProductionPointTypeEnum; printer_configuration_ref: Optional[str] = Field(default=None, max_length=255)
    actor_id: Optional[uuid.UUID] = None

class PointDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID; tenant_id: uuid.UUID; store_id: uuid.UUID; code: str; name: str
    point_type: ProductionPointTypeEnum; is_active: bool; printer_configuration_ref: Optional[str]
    created_at: datetime; updated_at: datetime

class PointUpdateDTO(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    is_active: Optional[bool] = None
    printer_configuration_ref: Optional[str] = Field(default=None, max_length=255)
    actor_id: Optional[uuid.UUID] = None
    reason: str = Field(min_length=3, max_length=500)

class RuleCreateDTO(BaseModel):
    production_point_id: uuid.UUID; product_id: Optional[uuid.UUID] = None; modifier_id: Optional[uuid.UUID] = None
    fulfillment: Optional[OrderFulfillmentEnum] = None; priority: int = Field(default=100, ge=1, le=999)
    actor_id: Optional[uuid.UUID] = None

class RuleDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID; tenant_id: uuid.UUID; store_id: uuid.UUID; production_point_id: uuid.UUID
    product_id: Optional[uuid.UUID]; modifier_id: Optional[uuid.UUID]; fulfillment: Optional[OrderFulfillmentEnum]
    priority: int; is_active: bool; created_at: datetime; updated_at: datetime

class DispatchDTO(BaseModel): actor_id: Optional[uuid.UUID] = None

class TicketItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID; order_item_id: uuid.UUID; item_version: int; operation: ProductionOperationEnum
    quantity: Decimal; product_name_snapshot: str; modifier_snapshot: list[dict]
    notes_snapshot: Optional[str]; created_at: datetime

class TicketCoreDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID; tenant_id: uuid.UUID; store_id: uuid.UUID; order_id: uuid.UUID
    dispatch_id: uuid.UUID; production_point_id: uuid.UUID; status: ProductionTicketStatusEnum
    priority: int; version: int; created_at: datetime; updated_at: datetime

class TicketProjectionDTO(BaseModel):
    ticket: TicketCoreDTO; point: PointDTO; items: list[TicketItemDTO]

class TransitionDTO(BaseModel):
    target: ProductionTicketStatusEnum; expected_version: int = Field(ge=1)
    actor_id: Optional[uuid.UUID] = None; device_id: str = Field(min_length=2, max_length=160)

@router.post("/points", response_model=PointDTO)
def create_point_endpoint(data: PointCreateDTO, idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160), context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return production_service.create_point(session, context, store_id=data.store_id, code=data.code, name=data.name, point_type=data.point_type, printer_configuration_ref=data.printer_configuration_ref, actor_id=data.actor_id, idempotency_key=idempotency_key)

@router.get("/points", response_model=list[PointDTO])
def list_points_endpoint(context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return production_service.list_points(session, context)

@router.patch("/points/{point_id}", response_model=PointDTO)
def update_point_endpoint(point_id: uuid.UUID, data: PointUpdateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return production_service.update_point(session, context, point_id, name=data.name, is_active=data.is_active,
        printer_configuration_ref=data.printer_configuration_ref, actor_id=data.actor_id, reason=data.reason)

@router.post("/rules", response_model=RuleDTO)
def create_rule_endpoint(data: RuleCreateDTO, idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160), context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return production_service.create_rule(session, context, point_id=data.production_point_id, product_id=data.product_id, modifier_id=data.modifier_id, fulfillment=data.fulfillment, priority=data.priority, actor_id=data.actor_id, idempotency_key=idempotency_key)

@router.get("/rules", response_model=list[RuleDTO])
def list_rules_endpoint(context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return production_service.list_rules(session, context)

@router.post("/orders/{order_id}/dispatch", response_model=list[TicketProjectionDTO])
def dispatch_order_endpoint(order_id: uuid.UUID, data: DispatchDTO, idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160), context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return production_service.dispatch_order(session, context, order_id, actor_id=data.actor_id, idempotency_key=idempotency_key)

@router.get("/tickets", response_model=list[TicketProjectionDTO])
def list_tickets_endpoint(point_id: Optional[uuid.UUID] = None, include_terminal: bool = False, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return production_service.list_tickets(session, context, point_id, include_terminal)

@router.post("/tickets/{ticket_id}/transition", response_model=TicketProjectionDTO)
def transition_ticket_endpoint(ticket_id: uuid.UUID, data: TransitionDTO, idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160), context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return production_service.transition_ticket(session, context, ticket_id, target=data.target, expected_version=data.expected_version, actor_id=data.actor_id, device_id=data.device_id, idempotency_key=idempotency_key)

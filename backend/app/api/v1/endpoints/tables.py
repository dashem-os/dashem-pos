import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.v1.endpoints.orders import OrderReadDTO
from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.table_service import (
    ServiceTableStatusEnum, TableSessionKindEnum, TableSessionStatusEnum,
)
from app.services import table_service


router = APIRouter()


class ServiceTableCreateDTO(BaseModel):
    store_id: uuid.UUID
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    capacity: int = Field(default=1, ge=1, le=100)
    area: Optional[str] = Field(default=None, max_length=80)
    actor_id: Optional[uuid.UUID] = None


class ServiceTableReadDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    code: str
    name: str
    capacity: int
    area: Optional[str]
    status: ServiceTableStatusEnum
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ServiceTableProjectionDTO(ServiceTableReadDTO):
    active_session_id: Optional[uuid.UUID]
    active_session_status: Optional[TableSessionStatusEnum]
    active_session_label: Optional[str]
    order_count: int
    item_count: int
    consolidated_total: Decimal


class TableSessionOpenDTO(BaseModel):
    store_id: uuid.UUID
    service_table_id: Optional[uuid.UUID] = None
    display_label: Optional[str] = Field(default=None, max_length=120)
    customer_id: Optional[uuid.UUID] = None
    attendant_id: Optional[uuid.UUID] = None
    actor_id: Optional[uuid.UUID] = None


class TableSessionOrderCreateDTO(BaseModel):
    display_reference: Optional[str] = Field(default=None, max_length=200)
    customer_id: Optional[uuid.UUID] = None
    actor_id: Optional[uuid.UUID] = None


class TableSessionCloseDTO(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)
    actor_id: Optional[uuid.UUID] = None


class TableSessionEventDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    table_session_id: uuid.UUID
    event_type: str
    actor_id: uuid.UUID
    from_status: Optional[str]
    to_status: Optional[str]
    reason: Optional[str]
    payload: dict[str, Any]
    created_at: datetime


class TableSessionDetailDTO(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    service_table_id: Optional[uuid.UUID]
    kind: TableSessionKindEnum
    status: TableSessionStatusEnum
    display_label: str
    customer_id: Optional[uuid.UUID]
    attendant_id: uuid.UUID
    opened_by: uuid.UUID
    closed_by: Optional[uuid.UUID]
    close_reason: Optional[str]
    version: int
    opened_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime]
    service_table: Optional[ServiceTableReadDTO]
    orders: List[OrderReadDTO]
    events: List[TableSessionEventDTO]
    order_count: int
    active_item_count: int
    consolidated_total: Decimal


class TableSessionSummaryDTO(BaseModel):
    id: uuid.UUID
    service_table_id: Optional[uuid.UUID]
    kind: TableSessionKindEnum
    status: TableSessionStatusEnum
    display_label: str
    version: int
    opened_at: datetime
    updated_at: datetime
    order_count: int
    item_count: int
    consolidated_total: Decimal


@router.post("", response_model=ServiceTableReadDTO)
def create_service_table_endpoint(
    data: ServiceTableCreateDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return table_service.create_service_table(
        session, context, store_id=data.store_id, code=data.code, name=data.name,
        capacity=data.capacity, area=data.area, actor_id=data.actor_id,
        idempotency_key=idempotency_key,
    )


@router.get("", response_model=List[ServiceTableProjectionDTO])
def list_service_tables_endpoint(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return table_service.list_service_tables(session, context)


@router.post("/sessions", response_model=TableSessionDetailDTO)
def open_table_session_endpoint(
    data: TableSessionOpenDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return table_service.open_table_session(
        session, context, store_id=data.store_id, service_table_id=data.service_table_id,
        display_label=data.display_label, customer_id=data.customer_id,
        attendant_id=data.attendant_id, actor_id=data.actor_id,
        idempotency_key=idempotency_key,
    )


@router.get("/sessions", response_model=List[TableSessionSummaryDTO])
def list_active_table_sessions_endpoint(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return table_service.list_active_sessions(session, context)


@router.get("/sessions/{table_session_id}", response_model=TableSessionDetailDTO)
def get_table_session_endpoint(
    table_session_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return table_service.session_projection(session, context, table_session_id)


@router.post("/sessions/{table_session_id}/orders", response_model=OrderReadDTO)
def add_table_session_order_endpoint(
    table_session_id: uuid.UUID,
    data: TableSessionOrderCreateDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return table_service.add_session_order(
        session, context, table_session_id,
        display_reference=data.display_reference, customer_id=data.customer_id,
        actor_id=data.actor_id, idempotency_key=idempotency_key,
    )


@router.post("/sessions/{table_session_id}/close", response_model=TableSessionDetailDTO)
def close_table_session_endpoint(
    table_session_id: uuid.UUID,
    data: TableSessionCloseDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return table_service.close_empty_session(
        session, context, table_session_id, expected_version=data.expected_version,
        reason=data.reason, actor_id=data.actor_id, idempotency_key=idempotency_key,
    )

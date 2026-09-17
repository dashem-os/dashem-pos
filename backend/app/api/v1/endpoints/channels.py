import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.channel_hub import (
    ChannelInboxStatusEnum, ChannelOutboundStatusEnum, MerchantConnectionStatusEnum,
)
from app.modules.channels import outbound as channel_outbound
from app.modules.channels import registry as channel_registry
from app.services import channel_hub_service


router = APIRouter()


class MerchantConnectionCreateDTO(BaseModel):
    # A channel credential is never typed by the shopkeeper (H12): the channel
    # signs with the platform's application credential. A body that still sends
    # one is refused, not silently dropped.
    model_config = ConfigDict(extra="forbid")
    store_id: uuid.UUID
    provider_code: str = Field(min_length=2, max_length=80)
    merchant_external_id: str = Field(min_length=2, max_length=160)
    channel_name: str = Field(min_length=2, max_length=160)
    actor_id: Optional[uuid.UUID] = None


class MerchantConnectionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    channel_id: uuid.UUID
    provider_code: str
    adapter_version: str
    merchant_external_id: str
    status: MerchantConnectionStatusEnum
    last_validated_at: Optional[datetime]
    last_event_at: Optional[datetime]
    last_error_code: Optional[str]
    last_error_message: Optional[str]
    # What the connector for this provider can do in this environment. Empty
    # means no connector here: the connection receives nothing (H11).
    capabilities: list[str] = []
    created_at: datetime
    updated_at: datetime


def _connection_view(connection) -> MerchantConnectionDTO:
    view = MerchantConnectionDTO.model_validate(connection)
    view.capabilities = sorted(
        capability.value for capability in channel_registry.adapter_for(connection.provider_code).capabilities
    )
    return view


class MerchantConnectionCreateResponseDTO(BaseModel):
    connection: MerchantConnectionDTO


class ValidateConnectionDTO(BaseModel):
    actor_id: Optional[uuid.UUID] = None


class ChannelInboxEventDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    merchant_connection_id: uuid.UUID
    provider_event_id: str
    external_order_id: str
    event_type: str
    status: ChannelInboxStatusEnum
    order_id: Optional[uuid.UUID]
    # The local order's state, so the screen names the order without its UUID.
    order_status: Optional[str] = None
    quarantine_code: Optional[str]
    quarantine_reason: Optional[str]
    received_at: datetime
    acknowledged_at: Optional[datetime]
    processed_at: Optional[datetime]
    # Prazo do payload e se ele já passou por quarentena (D6). Nada pessoal.
    retention_until: Optional[datetime] = None
    first_quarantined_at: Optional[datetime] = None
    last_error_code: Optional[str] = None


class OutboundCreateDTO(BaseModel):
    message_type: str = Field(min_length=2, max_length=80)
    payload: dict = Field(default_factory=dict)
    actor_id: Optional[uuid.UUID] = None


class OutboundDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    order_id: uuid.UUID
    merchant_connection_id: uuid.UUID
    message_type: str
    payload: dict
    status: ChannelOutboundStatusEnum
    attempt_count: int
    last_error_code: Optional[str] = None
    next_retry_at: Optional[datetime]
    delivered_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


@router.post("/connections", response_model=MerchantConnectionCreateResponseDTO)
def create_connection_endpoint(
    data: MerchantConnectionCreateDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session),
):
    connection = channel_hub_service.create_connection(
        session, context, store_id=data.store_id, provider_code=data.provider_code,
        merchant_external_id=data.merchant_external_id, channel_name=data.channel_name,
        actor_id=data.actor_id, idempotency_key=idempotency_key,
    )
    return {"connection": _connection_view(connection)}


@router.get("/connections", response_model=list[MerchantConnectionDTO])
def list_connections_endpoint(context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return [_connection_view(connection) for connection in channel_hub_service.list_connections(session, context)]


@router.post("/connections/{connection_id}/validate", response_model=MerchantConnectionDTO)
def validate_connection_endpoint(
    connection_id: uuid.UUID,
    data: ValidateConnectionDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return _connection_view(channel_hub_service.validate_connection(
        session, context, connection_id, data.actor_id, idempotency_key,
    ))


@router.get("/inbox", response_model=list[ChannelInboxEventDTO])
def list_channel_inbox_endpoint(limit: int = 100, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return channel_hub_service.list_inbox(session, context, min(max(limit, 1), 500))


@router.post("/orders/{order_id}/outbound", response_model=OutboundDTO)
def queue_channel_outbound_endpoint(
    order_id: uuid.UUID, data: OutboundCreateDTO, background: BackgroundTasks,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session),
):
    message = channel_outbound.enqueue(
        session, context, order_id, message_type=data.message_type,
        payload=data.payload, actor_id=data.actor_id, idempotency_key=idempotency_key,
    )
    background.add_task(channel_outbound.deliver_now, [message.id])
    return message

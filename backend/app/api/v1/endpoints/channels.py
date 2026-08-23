import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.channel_hub import (
    ChannelInboxStatusEnum, ChannelOutboundStatusEnum, MerchantConnectionStatusEnum,
)
from app.services import channel_hub_service


router = APIRouter()


class MerchantConnectionCreateDTO(BaseModel):
    store_id: uuid.UUID
    provider_code: str = Field(min_length=2, max_length=80)
    merchant_external_id: str = Field(min_length=2, max_length=160)
    channel_name: str = Field(min_length=2, max_length=160)
    credentials_ref: Optional[str] = Field(default=None, max_length=255)
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
    created_at: datetime
    updated_at: datetime


class MerchantConnectionCreateResponseDTO(BaseModel):
    connection: MerchantConnectionDTO
    webhook_secret: str


class ValidateConnectionDTO(BaseModel):
    actor_id: Optional[uuid.UUID] = None


class ChannelWebhookDTO(BaseModel):
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    connection_id: uuid.UUID
    provider_event_id: str = Field(min_length=1, max_length=160)
    event_type: str = Field(default="ORDER_CREATED", max_length=80)
    payload: dict
    signature: str = Field(min_length=64, max_length=128)


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
    quarantine_code: Optional[str]
    quarantine_reason: Optional[str]
    received_at: datetime
    acknowledged_at: Optional[datetime]
    processed_at: Optional[datetime]


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
    last_error: Optional[str]
    next_retry_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


@router.post("/connections", response_model=MerchantConnectionCreateResponseDTO)
def create_connection_endpoint(
    data: MerchantConnectionCreateDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session),
):
    connection, secret = channel_hub_service.create_connection(
        session, context, store_id=data.store_id, provider_code=data.provider_code,
        merchant_external_id=data.merchant_external_id, channel_name=data.channel_name,
        credentials_ref=data.credentials_ref, actor_id=data.actor_id,
        idempotency_key=idempotency_key,
    )
    return {"connection": connection, "webhook_secret": secret}


@router.get("/connections", response_model=list[MerchantConnectionDTO])
def list_connections_endpoint(context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return channel_hub_service.list_connections(session, context)


@router.post("/connections/{connection_id}/validate", response_model=MerchantConnectionDTO)
def validate_connection_endpoint(
    connection_id: uuid.UUID,
    data: ValidateConnectionDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return channel_hub_service.validate_connection(
        session, context, connection_id, data.actor_id, idempotency_key,
    )


@router.post("/webhooks", response_model=ChannelInboxEventDTO)
def receive_channel_webhook_endpoint(data: ChannelWebhookDTO, session: Session = Depends(get_session)):
    return channel_hub_service.receive_event(
        session, tenant_id=data.tenant_id, store_id=data.store_id,
        connection_id=data.connection_id, provider_event_id=data.provider_event_id,
        event_type=data.event_type, payload=data.payload, signature=data.signature,
    )


@router.get("/inbox", response_model=list[ChannelInboxEventDTO])
def list_channel_inbox_endpoint(limit: int = 100, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return channel_hub_service.list_inbox(session, context, min(max(limit, 1), 500))


@router.post("/orders/{order_id}/outbound", response_model=OutboundDTO)
def queue_channel_outbound_endpoint(
    order_id: uuid.UUID, data: OutboundCreateDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session),
):
    return channel_hub_service.queue_outbound(
        session, context, order_id, message_type=data.message_type,
        payload=data.payload, actor_id=data.actor_id, idempotency_key=idempotency_key,
    )

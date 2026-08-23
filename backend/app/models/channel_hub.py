import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, Text
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


class MerchantConnectionStatusEnum(str, Enum):
    NOT_CONNECTED = "NOT_CONNECTED"
    VALIDATING = "VALIDATING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    SUSPENDED = "SUSPENDED"


class ChannelInboxStatusEnum(str, Enum):
    RECEIVED = "RECEIVED"
    NORMALIZED = "NORMALIZED"
    PROCESSED = "PROCESSED"
    QUARANTINED = "QUARANTINED"
    DUPLICATE = "DUPLICATE"


class ChannelOutboundStatusEnum(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RETRY = "RETRY"
    DEAD_LETTER = "DEAD_LETTER"


class MerchantConnection(SQLModel, table=True):
    __tablename__ = "merchant_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_code", "merchant_external_id", name="uq_provider_merchant_connection"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_merchant_connection_key"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    channel_id: uuid.UUID = Field(foreign_key="sales_channels.id", index=True)
    provider_code: str = Field(max_length=80, index=True)
    adapter_version: str = Field(default="1.0.0", max_length=40)
    merchant_external_id: str = Field(max_length=160, index=True)
    status: MerchantConnectionStatusEnum = Field(default=MerchantConnectionStatusEnum.NOT_CONNECTED, sa_column=Column(EnumString(MerchantConnectionStatusEnum), nullable=False, index=True))
    credentials_ref: Optional[str] = Field(default=None, max_length=255)
    webhook_secret_hash: str = Field(max_length=64)
    service_actor_id: uuid.UUID = Field(index=True)
    idempotency_key: str = Field(max_length=160, index=True)
    request_hash: str = Field(max_length=64)
    configured_by: uuid.UUID = Field(index=True)
    last_validated_at: Optional[datetime] = Field(default=None, index=True)
    last_event_at: Optional[datetime] = Field(default=None, index=True)
    last_error_code: Optional[str] = Field(default=None, max_length=80)
    last_error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChannelInboxEvent(SQLModel, table=True):
    __tablename__ = "channel_inbox_events"
    __table_args__ = (
        UniqueConstraint("merchant_connection_id", "provider_event_id", name="uq_connection_provider_event"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    merchant_connection_id: uuid.UUID = Field(foreign_key="merchant_connections.id", index=True)
    provider_event_id: str = Field(max_length=160, index=True)
    external_order_id: str = Field(max_length=160, index=True)
    event_type: str = Field(max_length=80, index=True)
    payload_hash: str = Field(max_length=64)
    raw_payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: ChannelInboxStatusEnum = Field(default=ChannelInboxStatusEnum.RECEIVED, sa_column=Column(EnumString(ChannelInboxStatusEnum), nullable=False, index=True))
    order_id: Optional[uuid.UUID] = Field(default=None, foreign_key="orders.id", index=True)
    quarantine_code: Optional[str] = Field(default=None, max_length=80)
    quarantine_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    received_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    acknowledged_at: Optional[datetime] = Field(default=None, index=True)
    processed_at: Optional[datetime] = Field(default=None, index=True)


class ExternalOrderMapping(SQLModel, table=True):
    __tablename__ = "external_order_mappings"
    __table_args__ = (
        UniqueConstraint("merchant_connection_id", "external_order_id", name="uq_connection_external_order"),
        UniqueConstraint("tenant_id", "order_id", name="uq_tenant_external_order_mapping"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    merchant_connection_id: uuid.UUID = Field(foreign_key="merchant_connections.id", index=True)
    external_order_id: str = Field(max_length=160, index=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", index=True)
    payment_origin: Optional[str] = Field(default=None, max_length=80, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class ChannelOutboundMessage(SQLModel, table=True):
    __tablename__ = "channel_outbound_messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_channel_outbound_key"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    merchant_connection_id: uuid.UUID = Field(foreign_key="merchant_connections.id", index=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", index=True)
    message_type: str = Field(max_length=80, index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: ChannelOutboundStatusEnum = Field(default=ChannelOutboundStatusEnum.PENDING, sa_column=Column(EnumString(ChannelOutboundStatusEnum), nullable=False, index=True))
    attempt_count: int = Field(default=0, ge=0)
    idempotency_key: str = Field(max_length=160, index=True)
    request_hash: str = Field(max_length=64)
    last_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    next_retry_at: Optional[datetime] = Field(default=None, index=True)
    created_by: uuid.UUID = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

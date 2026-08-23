import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional

from sqlalchemy import JSON, Column, Numeric, Text
from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


class OrderStatusEnum(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    CLOSED = "CLOSED"
    CANCELED = "CANCELED"


class OrderOriginEnum(str, Enum):
    POS = "POS"
    API = "API"
    SALES_CHANNEL = "SALES_CHANNEL"


class OrderFulfillmentEnum(str, Enum):
    COUNTER = "COUNTER"
    TAKEAWAY = "TAKEAWAY"
    DINE_IN = "DINE_IN"
    DELIVERY = "DELIVERY"


class OrderItemStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELED = "CANCELED"


class ProductionStateEnum(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    IN_PREPARATION = "IN_PREPARATION"
    READY = "READY"
    DELIVERED = "DELIVERED"
    CANCELED = "CANCELED"


class Order(SQLModel, table=True):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_order_idempotency"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    register_id: Optional[uuid.UUID] = Field(default=None, foreign_key="registers.id", index=True)
    customer_id: Optional[uuid.UUID] = Field(default=None, foreign_key="customers.id", index=True)
    table_id: Optional[uuid.UUID] = Field(default=None, index=True)
    sale_id: Optional[uuid.UUID] = Field(default=None, foreign_key="sales.id", index=True)
    channel_id: Optional[uuid.UUID] = Field(default=None, foreign_key="sales_channels.id", index=True)
    origin: OrderOriginEnum = Field(sa_column=Column(EnumString(OrderOriginEnum), nullable=False, index=True))
    fulfillment: OrderFulfillmentEnum = Field(sa_column=Column(EnumString(OrderFulfillmentEnum), nullable=False, index=True))
    status: OrderStatusEnum = Field(default=OrderStatusEnum.OPEN, sa_column=Column(EnumString(OrderStatusEnum), nullable=False, index=True))
    idempotency_key: str = Field(max_length=160, index=True)
    external_reference: Optional[str] = Field(default=None, max_length=160, index=True)
    opened_by: uuid.UUID = Field(index=True)
    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    items: List["OrderItem"] = Relationship(back_populates="order")


class OrderItem(SQLModel, table=True):
    __tablename__ = "order_items"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", ondelete="CASCADE", index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", index=True)
    product_name: str = Field(max_length=200)
    sku: str = Field(max_length=100)
    unit_snapshot: str = Field(max_length=16)
    unit_price: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    quantity: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    modifier_snapshot: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    production_destination: Optional[str] = Field(default=None, max_length=80)
    production_state: ProductionStateEnum = Field(sa_column=Column(EnumString(ProductionStateEnum), nullable=False, index=True))
    status: OrderItemStatusEnum = Field(default=OrderItemStatusEnum.ACTIVE, sa_column=Column(EnumString(OrderItemStatusEnum), nullable=False, index=True))
    added_by: uuid.UUID = Field(index=True)
    canceled_by: Optional[uuid.UUID] = Field(default=None, index=True)
    cancellation_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    canceled_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    order: Optional[Order] = Relationship(back_populates="items")


class OrderCommand(SQLModel, table=True):
    __tablename__ = "order_commands"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_order_command_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", ondelete="CASCADE", index=True)
    idempotency_key: str = Field(max_length=160, index=True)
    command_type: str = Field(max_length=80, index=True)
    request_hash: str = Field(max_length=64)
    result_entity_id: uuid.UUID = Field(index=True)
    actor_id: uuid.UUID = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

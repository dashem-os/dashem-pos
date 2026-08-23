import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, CheckConstraint, Column, Numeric, Text
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString
from app.models.order import OrderFulfillmentEnum


class ProductionPointTypeEnum(str, Enum):
    KITCHEN = "KITCHEN"
    BAR = "BAR"
    PANTRY = "PANTRY"
    EXPEDITION = "EXPEDITION"
    PRINTER = "PRINTER"


class ProductionTicketStatusEnum(str, Enum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    DELIVERED = "DELIVERED"
    CANCELED = "CANCELED"


class ProductionOperationEnum(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    CANCEL = "CANCEL"


class ProductionPoint(SQLModel, table=True):
    __tablename__ = "production_points"
    __table_args__ = (UniqueConstraint("tenant_id", "store_id", "code", name="uq_store_production_point_code"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    code: str = Field(max_length=80, index=True)
    name: str = Field(max_length=160)
    point_type: ProductionPointTypeEnum = Field(sa_column=Column(EnumString(ProductionPointTypeEnum), nullable=False, index=True))
    is_active: bool = Field(default=True, index=True)
    printer_configuration_ref: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProductionRoutingRule(SQLModel, table=True):
    __tablename__ = "production_routing_rules"
    __table_args__ = (CheckConstraint("(product_id IS NOT NULL) <> (modifier_id IS NOT NULL)", name="ck_production_rule_one_subject"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    production_point_id: uuid.UUID = Field(foreign_key="production_points.id", index=True)
    product_id: Optional[uuid.UUID] = Field(default=None, foreign_key="products.id", index=True)
    modifier_id: Optional[uuid.UUID] = Field(default=None, foreign_key="modifiers.id", index=True)
    fulfillment: Optional[OrderFulfillmentEnum] = Field(default=None, sa_column=Column(EnumString(OrderFulfillmentEnum), nullable=True, index=True))
    priority: int = Field(default=100, ge=1, le=999, index=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProductionDispatch(SQLModel, table=True):
    __tablename__ = "production_dispatches"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_production_dispatch_key"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", index=True)
    idempotency_key: str = Field(max_length=160, index=True)
    request_hash: str = Field(max_length=64)
    actor_id: uuid.UUID = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class ProductionTicket(SQLModel, table=True):
    __tablename__ = "production_tickets"
    __table_args__ = (UniqueConstraint("dispatch_id", "production_point_id", name="uq_dispatch_production_point"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", index=True)
    dispatch_id: uuid.UUID = Field(foreign_key="production_dispatches.id", index=True)
    production_point_id: uuid.UUID = Field(foreign_key="production_points.id", index=True)
    status: ProductionTicketStatusEnum = Field(default=ProductionTicketStatusEnum.NEW, sa_column=Column(EnumString(ProductionTicketStatusEnum), nullable=False, index=True))
    priority: int = Field(default=100, ge=1, le=999, index=True)
    version: int = Field(default=1, ge=1)
    accepted_at: Optional[datetime] = None
    preparing_at: Optional[datetime] = None
    ready_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProductionTicketItem(SQLModel, table=True):
    __tablename__ = "production_ticket_items"
    __table_args__ = (UniqueConstraint("ticket_id", "order_item_id", "item_version", "operation", name="uq_ticket_item_version_operation"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    ticket_id: uuid.UUID = Field(foreign_key="production_tickets.id", ondelete="CASCADE", index=True)
    order_item_id: uuid.UUID = Field(foreign_key="order_items.id", index=True)
    item_version: int = Field(ge=1)
    operation: ProductionOperationEnum = Field(sa_column=Column(EnumString(ProductionOperationEnum), nullable=False, index=True))
    quantity: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    product_name_snapshot: str = Field(max_length=200)
    modifier_snapshot: list[dict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    notes_snapshot: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class ProductionTransition(SQLModel, table=True):
    __tablename__ = "production_transitions"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_production_transition_key"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    ticket_id: uuid.UUID = Field(foreign_key="production_tickets.id", ondelete="CASCADE", index=True)
    from_status: ProductionTicketStatusEnum = Field(sa_column=Column(EnumString(ProductionTicketStatusEnum), nullable=False))
    to_status: ProductionTicketStatusEnum = Field(sa_column=Column(EnumString(ProductionTicketStatusEnum), nullable=False, index=True))
    expected_version: int
    resulting_version: int
    actor_id: uuid.UUID = Field(index=True)
    device_id: str = Field(max_length=160, index=True)
    idempotency_key: str = Field(max_length=160, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

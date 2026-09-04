import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from sqlalchemy import Column, Numeric, Text
from sqlmodel import Field, SQLModel, UniqueConstraint
from app.core.db_types import EnumString

class TransferTypeEnum(str, Enum):
    ITEM = "ITEM"
    ORDER = "ORDER"
    SESSION_MOVE = "SESSION_MOVE"
    SESSION_MERGE = "SESSION_MERGE"

class TransferRecord(SQLModel, table=True):
    __tablename__ = "transfer_records"
    __table_args__ = (UniqueConstraint("tenant_id","idempotency_key",name="uq_tenant_transfer_key"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    transfer_type: TransferTypeEnum = Field(sa_column=Column(EnumString(TransferTypeEnum),nullable=False,index=True))
    source_session_id: uuid.UUID = Field(foreign_key="table_sessions.id", index=True)
    destination_session_id: uuid.UUID = Field(foreign_key="table_sessions.id", index=True)
    source_order_id: Optional[uuid.UUID] = Field(default=None, foreign_key="orders.id", index=True)
    destination_order_id: Optional[uuid.UUID] = Field(default=None, foreign_key="orders.id", index=True)
    source_order_item_id: Optional[uuid.UUID] = Field(default=None, foreign_key="order_items.id", index=True)
    derived_order_item_id: Optional[uuid.UUID] = Field(default=None, foreign_key="order_items.id", index=True)
    quantity: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14,4),nullable=True))
    unit_price_snapshot: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14,4),nullable=True))
    source_version_before: int; destination_version_before: int
    actor_id: uuid.UUID = Field(index=True)
    reason: str = Field(sa_column=Column(Text,nullable=False))
    production_compensation_required: bool = Field(default=False,index=True)
    idempotency_key: str = Field(max_length=160,index=True); request_hash: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow,index=True)

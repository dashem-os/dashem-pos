import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, JSON, String
from sqlmodel import Field, SQLModel, UniqueConstraint


class SalesChannelTypeEnum(str, Enum):
    POS = "POS"
    WHATSAPP = "WHATSAPP"
    MARKETPLACE = "MARKETPLACE"
    ECOMMERCE = "ECOMMERCE"
    API = "API"
    IMPORT = "IMPORT"
    ASSISTED = "ASSISTED"
    OTHER = "OTHER"


class SalesChannel(SQLModel, table=True):
    __tablename__ = "sales_channels"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tenant_sales_channel_code"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: Optional[uuid.UUID] = Field(default=None, foreign_key="stores.id", index=True)
    code: str = Field(index=True)
    name: str = Field(index=True)
    channel_type: SalesChannelTypeEnum = Field(
        sa_column=Column(String, nullable=False, index=True)
    )
    external_account_id: Optional[str] = Field(default=None, index=True)
    is_active: bool = Field(default=True, index=True)
    configuration: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

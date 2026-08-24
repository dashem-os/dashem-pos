import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


class OperationalDeviceTypeEnum(str, Enum):
    POS = "POS"
    KDS = "KDS"
    PRINTER = "PRINTER"


class OperationalDeviceStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REVOKED = "REVOKED"


class OperationalDevice(SQLModel, table=True):
    __tablename__ = "operational_devices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", "code", name="uq_operational_device_store_code"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    code: str = Field(max_length=80, index=True)
    name: str = Field(max_length=160, index=True)
    device_type: OperationalDeviceTypeEnum = Field(
        sa_column=Column(EnumString(OperationalDeviceTypeEnum), nullable=False, index=True),
    )
    status: OperationalDeviceStatusEnum = Field(
        default=OperationalDeviceStatusEnum.ACTIVE,
        sa_column=Column(EnumString(OperationalDeviceStatusEnum), nullable=False, index=True),
    )
    register_id: Optional[uuid.UUID] = Field(default=None, foreign_key="registers.id", index=True)
    production_point_id: Optional[uuid.UUID] = Field(default=None, foreign_key="production_points.id", index=True)
    configuration_ref: Optional[str] = Field(default=None, max_length=255)
    authorization_version: int = Field(default=0)
    authorized_at: Optional[datetime] = Field(default=None, index=True)
    authorized_by: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    authorization_expires_at: Optional[datetime] = Field(default=None, index=True)
    last_seen_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

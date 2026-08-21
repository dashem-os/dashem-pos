import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, JSON, String
from sqlmodel import Field, SQLModel, UniqueConstraint


class LeadStatusEnum(str, Enum):
    NEW = "NEW"
    QUALIFIED = "QUALIFIED"
    ONBOARDING = "ONBOARDING"
    CONVERTED = "CONVERTED"
    LOST = "LOST"


class PlatformRoleEnum(str, Enum):
    PLATFORM_OWNER = "PLATFORM_OWNER"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    SALES = "SALES"
    SUPPORT = "SUPPORT"
    OPERATIONS = "OPERATIONS"
    AUDITOR = "AUDITOR"


class PlatformMembership(SQLModel, table=True):
    __tablename__ = "platform_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_platform_membership_user"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    role: PlatformRoleEnum = Field(sa_column=Column(String, nullable=False, index=True))
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Lead(SQLModel, table=True):
    __tablename__ = "platform_leads"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_name: str = Field(index=True)
    contact_name: str
    email: Optional[str] = Field(default=None, index=True)
    phone: Optional[str] = Field(default=None, index=True)
    source: Optional[str] = Field(default=None, index=True)
    status: LeadStatusEnum = Field(
        default=LeadStatusEnum.NEW,
        sa_column=Column(String, nullable=False, index=True),
    )
    notes: Optional[str] = None
    owner_user_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    converted_tenant_id: Optional[uuid.UUID] = Field(default=None, foreign_key="tenants.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    converted_at: Optional[datetime] = None


class TenantCapability(SQLModel, table=True):
    __tablename__ = "tenant_capabilities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tenant_capability_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    key: str = Field(index=True)
    enabled: bool = Field(default=True, index=True)
    configuration: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

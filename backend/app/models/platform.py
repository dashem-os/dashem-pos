import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, JSON, String
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


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


class CapabilityScopeEnum(str, Enum):
    TENANT = "TENANT"
    STORE = "STORE"
    TERMINAL = "TERMINAL"


class CapabilityStatusEnum(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class EntitlementStatusEnum(str, Enum):
    CONTRACTED = "CONTRACTED"
    CONFIGURED = "CONFIGURED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


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


class CapabilityDefinition(SQLModel, table=True):
    __tablename__ = "capability_definitions"

    key: str = Field(primary_key=True, max_length=80)
    name: str = Field(max_length=160)
    version: str = Field(default="1.0.0", max_length=32)
    description: str
    scope: CapabilityScopeEnum = Field(sa_column=Column(EnumString(CapabilityScopeEnum), nullable=False, index=True))
    status: CapabilityStatusEnum = Field(
        default=CapabilityStatusEnum.ACTIVE,
        sa_column=Column(EnumString(CapabilityStatusEnum), nullable=False, index=True),
    )
    configuration_schema: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CapabilityDependency(SQLModel, table=True):
    __tablename__ = "capability_dependencies"
    __table_args__ = (
        UniqueConstraint("capability_key", "requires_key", name="uq_capability_dependency"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    capability_key: str = Field(foreign_key="capability_definitions.key", index=True)
    requires_key: str = Field(foreign_key="capability_definitions.key", index=True)
    minimum_version: Optional[str] = Field(default=None, max_length=32)


class CapabilityProfile(SQLModel, table=True):
    __tablename__ = "capability_profiles"

    key: str = Field(primary_key=True, max_length=80)
    name: str = Field(max_length=160)
    description: str
    version: str = Field(default="1.0.0", max_length=32)
    is_active: bool = Field(default=True, index=True)


class CapabilityProfileItem(SQLModel, table=True):
    __tablename__ = "capability_profile_items"
    __table_args__ = (
        UniqueConstraint("profile_key", "capability_key", name="uq_capability_profile_item"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    profile_key: str = Field(foreign_key="capability_profiles.key", index=True)
    capability_key: str = Field(foreign_key="capability_definitions.key", index=True)
    required: bool = Field(default=True)
    default_configuration: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )


class TenantCapability(SQLModel, table=True):
    __tablename__ = "tenant_capabilities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tenant_capability_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    key: str = Field(foreign_key="capability_definitions.key", index=True)
    enabled: bool = Field(default=True, index=True)
    status: EntitlementStatusEnum = Field(
        default=EntitlementStatusEnum.ACTIVE,
        sa_column=Column(EnumString(EntitlementStatusEnum), nullable=False, index=True),
    )
    contract_limits: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    configuration: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StoreCapabilityOverride(SQLModel, table=True):
    __tablename__ = "store_capability_overrides"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", "key", name="uq_store_capability_override"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    key: str = Field(foreign_key="capability_definitions.key", index=True)
    enabled: bool = Field(default=True, index=True)
    configuration: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )
    updated_at: datetime = Field(default_factory=datetime.utcnow)

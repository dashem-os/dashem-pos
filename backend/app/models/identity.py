import uuid
from datetime import date, datetime
from enum import Enum
from typing import Optional, List
from decimal import Decimal
from sqlalchemy import Column, Index, Numeric, String, Text, text
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint

class RoleEnum(str, Enum):
    OWNER = "OWNER"
    TENANT_OWNER = "TENANT_OWNER"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    SUPERVISOR = "SUPERVISOR"
    CASHIER = "CASHIER"
    OPERATOR = "OPERATOR"

class TenantStatusEnum(str, Enum):
    PROVISIONING = "PROVISIONING"
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    SUSPENDED = "SUSPENDED"
    CANCELED = "CANCELED"
    ARCHIVED = "ARCHIVED"


class TenantCustomerTypeEnum(str, Enum):
    TEST = "TEST"
    PILOT = "PILOT"
    CUSTOMER = "CUSTOMER"
    INTERNAL = "INTERNAL"


class TenantTypeEnum(str, Enum):
    CUSTOMER = "CUSTOMER"
    INTERNAL = "INTERNAL"


class TenantPhaseEnum(str, Enum):
    TEST = "TEST"
    PILOT = "PILOT"
    PRODUCTION = "PRODUCTION"


class SubscriptionStatusEnum(str, Enum):
    PENDING = "PENDING"
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELED = "CANCELED"

class MembershipStatusEnum(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class EmployeeStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"
    TERMINATED = "TERMINATED"


class OperationalSessionStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PermissionGrantEffectEnum(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"

class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(unique=True, index=True)
    status: TenantStatusEnum = Field(
        default=TenantStatusEnum.PROVISIONING,
        sa_column=Column(String, nullable=False, index=True),
    )
    legal_name: Optional[str] = None
    timezone: str = Field(default="America/Sao_Paulo")
    default_locale: str = Field(default="pt-BR")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    stores: List["Store"] = Relationship(back_populates="tenant")
    memberships: List["Membership"] = Relationship(back_populates="tenant")


class TenantProfile(SQLModel, table=True):
    """Commercial and legal master data for one platform customer."""

    __tablename__ = "tenant_profiles"
    __table_args__ = (
        UniqueConstraint("tax_id", name="uq_tenant_profiles_tax_id"),
    )

    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", primary_key=True)
    customer_type: TenantCustomerTypeEnum = Field(
        default=TenantCustomerTypeEnum.TEST,
        sa_column=Column(String, nullable=False, index=True),
    )
    tenant_type: TenantTypeEnum = Field(
        default=TenantTypeEnum.CUSTOMER,
        sa_column=Column(String, nullable=False, index=True),
    )
    lifecycle_phase: TenantPhaseEnum = Field(
        default=TenantPhaseEnum.TEST,
        sa_column=Column(String, nullable=False, index=True),
    )
    trade_name: str = Field(index=True, max_length=160)
    legal_name: Optional[str] = Field(default=None, index=True, max_length=200)
    tax_id: Optional[str] = Field(default=None, index=True, max_length=14)
    state_registration: Optional[str] = Field(default=None, max_length=32)
    municipal_registration: Optional[str] = Field(default=None, max_length=32)
    industry: Optional[str] = Field(default=None, index=True, max_length=120)
    company_email: Optional[str] = Field(default=None, index=True, max_length=254)
    company_phone: Optional[str] = Field(default=None, index=True, max_length=32)
    website: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TenantContact(SQLModel, table=True):
    __tablename__ = "tenant_contacts"
    __table_args__ = (
        Index(
            "uq_tenant_primary_contact",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_primary = true AND is_active = true"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    full_name: str = Field(index=True, max_length=160)
    job_title: Optional[str] = Field(default=None, max_length=120)
    email: Optional[str] = Field(default=None, index=True, max_length=254)
    phone: Optional[str] = Field(default=None, index=True, max_length=32)
    is_primary: bool = Field(default=False, index=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ServicePlan(SQLModel, table=True):
    """Owner-managed commercial plan; plans are data, not code constants."""

    __tablename__ = "service_plans"
    __table_args__ = (
        UniqueConstraint("code", name="uq_service_plans_code"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(index=True, max_length=60)
    name: str = Field(index=True, max_length=120)
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    is_active: bool = Field(default=True, index=True)
    store_limit: Optional[int] = None
    user_limit: Optional[int] = None
    terminal_limit: Optional[int] = None
    storage_limit_mb: Optional[int] = None
    monthly_price: Decimal = Field(
        default=Decimal("0.00"),
        sa_column=Column(Numeric(14, 2), nullable=False, default=0),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TenantSubscription(SQLModel, table=True):
    __tablename__ = "tenant_subscriptions"

    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", primary_key=True)
    plan_id: Optional[uuid.UUID] = Field(default=None, foreign_key="service_plans.id", index=True)
    status: SubscriptionStatusEnum = Field(
        default=SubscriptionStatusEnum.PENDING,
        sa_column=Column(String, nullable=False, index=True),
    )
    starts_at: Optional[datetime] = None
    trial_ends_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    monthly_amount: Decimal = Field(
        default=Decimal("0.00"),
        sa_column=Column(Numeric(14, 2), nullable=False, default=0),
    )
    billing_day: int = Field(default=1)
    billing_status: str = Field(default="PENDING", max_length=32)
    next_due_date: Optional[date] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Store(SQLModel, table=True):
    __tablename__ = "stores"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tenant_store_code"),
        Index(
            "uq_tenant_headquarters",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_headquarters = true"),
        ),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    name: str = Field(index=True)
    code: str = Field(index=True)
    site_type: str = Field(default="STORE", index=True)
    is_headquarters: bool = Field(default=False, index=True)
    legal_name: Optional[str] = Field(default=None, max_length=200)
    tax_id: Optional[str] = Field(default=None, index=True, max_length=14)
    state_registration: Optional[str] = Field(default=None, max_length=32)
    email: Optional[str] = Field(default=None, max_length=254)
    phone: Optional[str] = Field(default=None, max_length=32)
    postal_code: Optional[str] = Field(default=None, max_length=8)
    street: Optional[str] = Field(default=None, max_length=200)
    street_number: Optional[str] = Field(default=None, max_length=32)
    address_complement: Optional[str] = Field(default=None, max_length=120)
    district: Optional[str] = Field(default=None, max_length=120)
    city: Optional[str] = Field(default=None, max_length=120)
    state: Optional[str] = Field(default=None, max_length=2)
    country_code: str = Field(default="BR", max_length=2)
    timezone: str = Field(default="America/Sao_Paulo")
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    tenant: Optional[Tenant] = Relationship(back_populates="stores")
    memberships: List["Membership"] = Relationship(back_populates="store")

class User(SQLModel, table=True):
    __tablename__ = "users"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: Optional[str] = Field(default=None, unique=True, index=True)
    full_name: str
    # Credentials are owned by the identity provider. Kept nullable only for
    # migration compatibility with the pre-Supabase prototype.
    password_hash: Optional[str] = Field(default=None, exclude=True)
    is_active: bool = Field(default=True)
    password_setup_completed_at: Optional[datetime] = None
    onboarding_completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    memberships: List["Membership"] = Relationship(back_populates="user")


class AuthIdentity(SQLModel, table=True):
    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_auth_provider_subject"),
        UniqueConstraint("user_id", "provider", name="uq_user_auth_provider"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    provider: str = Field(default="supabase", index=True)
    provider_subject: str = Field(index=True)
    provider_email: Optional[str] = Field(default=None, index=True)
    email_verified: bool = Field(default=False)
    last_login_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Membership(SQLModel, table=True):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", "store_id", name="uq_user_tenant_store"),
        Index(
            "uq_user_tenant_membership_all_sites",
            "user_id",
            "tenant_id",
            unique=True,
            postgresql_where=text("store_id IS NULL"),
        ),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: Optional[uuid.UUID] = Field(default=None, foreign_key="stores.id", index=True)
    role: RoleEnum = Field(
        default=RoleEnum.CASHIER,
        sa_column=Column(String, nullable=False),
    )
    status: MembershipStatusEnum = Field(
        default=MembershipStatusEnum.ACTIVE,
        sa_column=Column(String, nullable=False, index=True),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    user: Optional[User] = Relationship(back_populates="memberships")
    tenant: Optional[Tenant] = Relationship(back_populates="memberships")
    store: Optional[Store] = Relationship(back_populates="memberships")


class Employee(SQLModel, table=True):
    """Tenant-owned personnel record, independent from authentication."""

    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_number", name="uq_tenant_employee_number"),
        UniqueConstraint("tenant_id", "tax_id", name="uq_tenant_employee_tax_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    user_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", unique=True, index=True)
    home_store_id: Optional[uuid.UUID] = Field(default=None, foreign_key="stores.id", index=True)
    employee_number: str = Field(index=True, max_length=30)
    full_name: str = Field(index=True, max_length=160)
    preferred_name: Optional[str] = Field(default=None, max_length=100)
    tax_id: Optional[str] = Field(default=None, index=True, max_length=11)
    email: Optional[str] = Field(default=None, index=True, max_length=254)
    phone: Optional[str] = Field(default=None, index=True, max_length=32)
    job_title: Optional[str] = Field(default=None, index=True, max_length=120)
    department: Optional[str] = Field(default=None, index=True, max_length=120)
    hire_date: Optional[date] = Field(default=None, index=True)
    postal_code: Optional[str] = Field(default=None, max_length=8)
    street: Optional[str] = Field(default=None, max_length=200)
    street_number: Optional[str] = Field(default=None, max_length=32)
    address_complement: Optional[str] = Field(default=None, max_length=120)
    district: Optional[str] = Field(default=None, max_length=120)
    city: Optional[str] = Field(default=None, max_length=120)
    state: Optional[str] = Field(default=None, max_length=2)
    emergency_contact_name: Optional[str] = Field(default=None, max_length=160)
    emergency_contact_phone: Optional[str] = Field(default=None, max_length=32)
    status: EmployeeStatusEnum = Field(
        default=EmployeeStatusEnum.ACTIVE,
        sa_column=Column(String, nullable=False, index=True),
    )
    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class OperationalCredential(SQLModel, table=True):
    """Store-scoped identity whose personal PIN is activated by the employee."""

    __tablename__ = "operational_credentials"
    __table_args__ = (
        UniqueConstraint("membership_id", name="uq_operational_credential_membership"),
        UniqueConstraint("tenant_id", "store_id", "employee_code", name="uq_operational_employee_code"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    membership_id: uuid.UUID = Field(foreign_key="memberships.id", ondelete="CASCADE", index=True)
    employee_id: uuid.UUID = Field(foreign_key="employees.id", ondelete="RESTRICT", index=True)
    employee_code: str = Field(index=True, max_length=20)
    pin_salt: Optional[str] = Field(default=None, max_length=64, exclude=True)
    pin_hash: Optional[str] = Field(default=None, max_length=128, exclude=True)
    pin_iterations: int = Field(default=210_000)
    activation_secret_hash: Optional[str] = Field(default=None, max_length=64, exclude=True)
    activation_expires_at: Optional[datetime] = Field(default=None, index=True)
    activation_failed_attempts: int = Field(default=0)
    pin_activated_at: Optional[datetime] = Field(default=None, index=True)
    session_version: int = Field(default=1)
    failed_attempts: int = Field(default=0)
    locked_until: Optional[datetime] = Field(default=None, index=True)
    last_used_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class OperationalSession(SQLModel, table=True):
    """Server-side authority for one collaborator shift on one authorized POS."""

    __tablename__ = "operational_sessions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    register_id: uuid.UUID = Field(foreign_key="registers.id", index=True)
    device_id: uuid.UUID = Field(foreign_key="operational_devices.id", index=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    membership_id: uuid.UUID = Field(foreign_key="memberships.id", ondelete="CASCADE", index=True)
    credential_id: uuid.UUID = Field(foreign_key="operational_credentials.id", ondelete="CASCADE", index=True)
    terminal_authorization_version: int
    credential_version: int
    status: OperationalSessionStatusEnum = Field(
        default=OperationalSessionStatusEnum.ACTIVE,
        sa_column=Column(String, nullable=False, index=True),
    )
    started_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    expires_at: datetime = Field(index=True)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    ended_at: Optional[datetime] = Field(default=None, index=True)
    end_reason: Optional[str] = Field(default=None, max_length=500)


class Permission(SQLModel, table=True):
    """Canonical action contract evaluated by the backend."""

    __tablename__ = "permissions"

    key: str = Field(primary_key=True, max_length=100)
    name: str = Field(max_length=160)
    description: str = Field(sa_column=Column(Text, nullable=False))
    capability_key: Optional[str] = Field(
        default=None, foreign_key="capability_definitions.key", index=True, max_length=80
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RoleProfile(SQLModel, table=True):
    __tablename__ = "role_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tenant_role_profile_code"),
        Index(
            "uq_system_role_profile_code",
            "code",
            unique=True,
            postgresql_where=text("tenant_id IS NULL AND is_system = true"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: Optional[uuid.UUID] = Field(default=None, foreign_key="tenants.id", index=True)
    code: str = Field(index=True, max_length=80)
    name: str = Field(max_length=160)
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    is_system: bool = Field(default=False, index=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RoleProfilePermission(SQLModel, table=True):
    __tablename__ = "role_profile_permissions"
    __table_args__ = (
        UniqueConstraint("role_profile_id", "permission_key", name="uq_role_profile_permission"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    role_profile_id: uuid.UUID = Field(foreign_key="role_profiles.id", ondelete="CASCADE", index=True)
    permission_key: str = Field(foreign_key="permissions.key", index=True, max_length=100)


class MembershipRoleProfile(SQLModel, table=True):
    __tablename__ = "membership_role_profiles"
    __table_args__ = (
        UniqueConstraint("membership_id", "role_profile_id", name="uq_membership_role_profile"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    membership_id: uuid.UUID = Field(foreign_key="memberships.id", ondelete="CASCADE", index=True)
    role_profile_id: uuid.UUID = Field(foreign_key="role_profiles.id", ondelete="CASCADE", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PermissionGrant(SQLModel, table=True):
    __tablename__ = "permission_grants"
    __table_args__ = (
        UniqueConstraint(
            "membership_id", "permission_key", "store_id",
            name="uq_membership_permission_store_grant",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: Optional[uuid.UUID] = Field(default=None, foreign_key="stores.id", index=True)
    membership_id: uuid.UUID = Field(foreign_key="memberships.id", ondelete="CASCADE", index=True)
    permission_key: str = Field(foreign_key="permissions.key", index=True, max_length=100)
    effect: PermissionGrantEffectEnum = Field(
        default=PermissionGrantEffectEnum.ALLOW,
        sa_column=Column(String, nullable=False, index=True),
    )
    reason: str = Field(sa_column=Column(Text, nullable=False))
    granted_by: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

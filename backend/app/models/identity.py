import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, List
from sqlalchemy import Column, Index, String, text
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint

class RoleEnum(str, Enum):
    OWNER = "OWNER"
    TENANT_OWNER = "TENANT_OWNER"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    CASHIER = "CASHIER"
    OPERATOR = "OPERATOR"
    AUDITOR = "AUDITOR"

class TenantStatusEnum(str, Enum):
    PROVISIONING = "PROVISIONING"
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELED = "CANCELED"

class MembershipStatusEnum(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"

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

class Store(SQLModel, table=True):
    __tablename__ = "stores"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tenant_store_code"),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    name: str = Field(index=True)
    code: str = Field(index=True)
    site_type: str = Field(default="STORE", index=True)
    timezone: str = Field(default="America/Sao_Paulo")
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    tenant: Optional[Tenant] = Relationship(back_populates="stores")
    memberships: List["Membership"] = Relationship(back_populates="store")

class User(SQLModel, table=True):
    __tablename__ = "users"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True)
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

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint

class RoleEnum(str, Enum):
    OWNER = "OWNER"
    MANAGER = "MANAGER"
    CASHIER = "CASHIER"
    OPERATOR = "OPERATOR"

class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    stores: List["Store"] = Relationship(back_populates="tenant")
    memberships: List["Membership"] = Relationship(back_populates="tenant")

class Store(SQLModel, table=True):
    __tablename__ = "stores"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    name: str = Field(index=True)
    code: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    tenant: Optional[Tenant] = Relationship(back_populates="stores")
    memberships: List["Membership"] = Relationship(back_populates="store")

class User(SQLModel, table=True):
    __tablename__ = "users"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True)
    full_name: str
    password_hash: str
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    memberships: List["Membership"] = Relationship(back_populates="user")

class Membership(SQLModel, table=True):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", "store_id", name="uq_user_tenant_store"),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    role: RoleEnum = Field(default=RoleEnum.CASHIER)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    user: Optional[User] = Relationship(back_populates="memberships")
    tenant: Optional[Tenant] = Relationship(back_populates="memberships")
    store: Optional[Store] = Relationship(back_populates="memberships")

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, List
from sqlalchemy import Column, Index, Text, text
from sqlmodel import CheckConstraint, Field, Relationship, SQLModel, UniqueConstraint
from app.core.db_types import EnumString


class AssortmentStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SalesContextEnum(str, Enum):
    COUNTER = "COUNTER"
    TAKEAWAY = "TAKEAWAY"
    TABLE = "TABLE"
    DELIVERY = "DELIVERY"
    ECOMMERCE = "ECOMMERCE"


class Assortment(SQLModel, table=True):
    __tablename__ = "assortments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tenant_assortment_code"),
        CheckConstraint("version > 0", name="ck_assortment_version_positive"),
        CheckConstraint(
            "business_activity IS NULL OR business_activity IN "
            "('FOOD_SERVICE', 'RETAIL', 'BEAUTY_RESELLER')",
            name="ck_assortment_business_activity",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    code: str = Field(max_length=40, index=True)
    name: str = Field(max_length=160, index=True)
    # Contracted business activity this curated set belongs to. NULL keeps the
    # assortment valid for every activity, which is what pre-existing rows need.
    # The activity is a property of the curated set, not of the product: the same
    # product may be sold by operations of different niches.
    business_activity: Optional[str] = Field(default=None, max_length=40, index=True, nullable=True)
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    status: AssortmentStatusEnum = Field(
        default=AssortmentStatusEnum.ACTIVE,
        sa_column=Column(EnumString(AssortmentStatusEnum), nullable=False, index=True),
    )
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    scopes: List["AssortmentScope"] = Relationship(
        back_populates="assortment",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    products: List["AssortmentProduct"] = Relationship(
        back_populates="assortment",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class AssortmentScope(SQLModel, table=True):
    __tablename__ = "assortment_scopes"
    __table_args__ = (
        Index(
            "uq_assortment_scope_channel",
            "tenant_id", "assortment_id", "store_id", "sales_context", "channel_id",
            unique=True,
            postgresql_where=text("channel_id IS NOT NULL"),
        ),
        Index(
            "uq_assortment_scope_no_channel",
            "tenant_id", "assortment_id", "store_id", "sales_context",
            unique=True,
            postgresql_where=text("channel_id IS NULL"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    assortment_id: uuid.UUID = Field(foreign_key="assortments.id", ondelete="CASCADE", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", ondelete="CASCADE", index=True)
    channel_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="sales_channels.id",
        ondelete="CASCADE",
        index=True,
        nullable=True,
    )
    sales_context: SalesContextEnum = Field(
        sa_column=Column(EnumString(SalesContextEnum), nullable=False, index=True),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    assortment: Optional[Assortment] = Relationship(back_populates="scopes")


class AssortmentProduct(SQLModel, table=True):
    __tablename__ = "assortment_products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "assortment_id", "product_id", name="uq_tenant_assortment_product"),
        CheckConstraint("sort_order >= 0", name="ck_assortment_product_sort_order"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    assortment_id: uuid.UUID = Field(foreign_key="assortments.id", ondelete="CASCADE", index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", ondelete="CASCADE", index=True)
    sort_order: int = Field(default=100, ge=0, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    assortment: Optional[Assortment] = Relationship(back_populates="products")

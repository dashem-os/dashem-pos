import uuid
from decimal import Decimal
from datetime import datetime
from enum import Enum
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint, Column, Numeric
from sqlalchemy import String

class SaleStatusEnum(str, Enum):
    DRAFT = "DRAFT"
    CHECKOUT = "CHECKOUT"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAID = "PAID"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"

class DiscountTypeEnum(str, Enum):
    PERCENTAGE = "PERCENTAGE"
    FIXED = "FIXED"

class FulfillmentTypeEnum(str, Enum):
    COUNTER = "COUNTER"
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"
    DINE_IN = "DINE_IN"
    SHIPPING = "SHIPPING"
    DIGITAL = "DIGITAL"

class SyncStatusEnum(str, Enum):
    LOCAL = "LOCAL"
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    CONFLICT = "CONFLICT"
    FAILED = "FAILED"

class Customer(SQLModel, table=True):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "cpf_cnpj", name="uq_tenant_customer_cpf_cnpj"),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    name: str = Field(index=True)
    cpf_cnpj: Optional[str] = Field(default=None, index=True)
    phone: Optional[str] = None
    email: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    sales: List["Sale"] = Relationship(back_populates="customer")

class Sale(SQLModel, table=True):
    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "channel_id", "external_order_id",
            name="uq_tenant_channel_external_order"
        ),
        UniqueConstraint(
            "tenant_id", "idempotency_key",
            name="uq_tenant_sale_idempotency_key"
        ),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: uuid.UUID = Field(index=True)
    channel_id: Optional[uuid.UUID] = Field(default=None, foreign_key="sales_channels.id", index=True)
    source_type: str = Field(default="POS", index=True)
    external_order_id: Optional[str] = Field(default=None, index=True)
    idempotency_key: Optional[str] = Field(default=None, index=True)
    fulfillment_type: FulfillmentTypeEnum = Field(
        default=FulfillmentTypeEnum.COUNTER,
        sa_column=Column(String, nullable=False, index=True),
    )
    sync_status: SyncStatusEnum = Field(
        default=SyncStatusEnum.SYNCED,
        sa_column=Column(String, nullable=False, index=True),
    )
    occurred_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    customer_id: Optional[uuid.UUID] = Field(default=None, foreign_key="customers.id", index=True)
    seller_id: Optional[uuid.UUID] = Field(default=None, index=True)
    status: SaleStatusEnum = Field(default=SaleStatusEnum.DRAFT, index=True)
    discount_type: Optional[DiscountTypeEnum] = Field(default=None)
    requested_discount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    approved_discount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    gross_total: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    discount_total: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    net_total: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    customer: Optional["Customer"] = Relationship(back_populates="sales")
    items: List["SaleItem"] = Relationship(back_populates="sale")

class SaleItem(SQLModel, table=True):
    __tablename__ = "sale_items"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    sale_id: uuid.UUID = Field(foreign_key="sales.id", index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", index=True)
    
    # Historical & Operational Snapshot Fields
    product_name: str = Field(index=True)
    sku: str = Field(index=True)
    item_type_snapshot: str = Field(default="PRODUCT")
    tracks_inventory_snapshot: bool = Field(default=True)
    requires_fulfillment_snapshot: bool = Field(default=False)
    unit_price: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    quantity: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    discount_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    gross_total: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    net_total: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    sale: Optional["Sale"] = Relationship(back_populates="items")

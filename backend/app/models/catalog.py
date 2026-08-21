import uuid
from decimal import Decimal
from datetime import datetime
from enum import Enum
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint, Column, Numeric

class ItemTypeEnum(str, Enum):
    PRODUCT = "PRODUCT"
    SERVICE = "SERVICE"

class MovementTypeEnum(str, Enum):
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    LOSS = "LOSS"
    RETURN = "RETURN"
    ADJUSTMENT = "ADJUSTMENT"

class Category(SQLModel, table=True):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_tenant_category_slug"),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    name: str = Field(index=True)
    slug: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    products: List["Product"] = Relationship(back_populates="category")

class Product(SQLModel, table=True):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_tenant_product_sku"),
        UniqueConstraint("tenant_id", "barcode", name="uq_tenant_product_barcode"),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    category_id: Optional[uuid.UUID] = Field(default=None, foreign_key="categories.id", index=True)
    name: str = Field(index=True)
    sku: str = Field(index=True)
    barcode: Optional[str] = Field(default=None, index=True)
    description: Optional[str] = None
    item_type: ItemTypeEnum = Field(default=ItemTypeEnum.PRODUCT)
    tracks_inventory: bool = Field(default=True)
    requires_fulfillment: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    category: Optional[Category] = Relationship(back_populates="products")
    prices: List["ProductPrice"] = Relationship(back_populates="product")
    balances: List["InventoryBalance"] = Relationship(back_populates="product")

class ProductPrice(SQLModel, table=True):
    __tablename__ = "product_prices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", "product_id", name="uq_tenant_store_product_price"),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: Optional[uuid.UUID] = Field(default=None, index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", index=True)
    cost_price: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    sale_price: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    product: Optional[Product] = Relationship(back_populates="prices")

class InventoryMovement(SQLModel, table=True):
    __tablename__ = "inventory_movements"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: uuid.UUID = Field(index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", index=True)
    actor_id: uuid.UUID = Field(index=True)
    movement_type: MovementTypeEnum = Field(default=MovementTypeEnum.ADJUSTMENT, index=True)
    quantity: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    previous_balance: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    new_balance: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    reason: Optional[str] = None
    correlation_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

class InventoryBalance(SQLModel, table=True):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", "product_id", name="uq_tenant_store_product_balance"),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: uuid.UUID = Field(index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", index=True)
    quantity: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    minimum_stock: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    product: Optional[Product] = Relationship(back_populates="balances")

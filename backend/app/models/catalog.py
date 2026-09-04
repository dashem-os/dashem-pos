import uuid
from decimal import Decimal
from datetime import datetime
from enum import Enum
from typing import Any, Optional, List
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint, Column, Numeric
from sqlalchemy import CheckConstraint, Index, JSON, String, text
from app.core.db_types import EnumString

class ItemTypeEnum(str, Enum):
    PRODUCT = "PRODUCT"
    SERVICE = "SERVICE"

class MovementTypeEnum(str, Enum):
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    LOSS = "LOSS"
    RETURN = "RETURN"
    ADJUSTMENT = "ADJUSTMENT"

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

class Category(SQLModel, table=True):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_tenant_category_slug"),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    parent_id: Optional[uuid.UUID] = Field(default=None, foreign_key="categories.id", index=True)
    name: str = Field(index=True)
    slug: str = Field(index=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

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
    image_url: Optional[str] = Field(default=None, max_length=500)
    unit: str = Field(default="UN", max_length=16)
    item_type: ItemTypeEnum = Field(
        default=ItemTypeEnum.PRODUCT,
        sa_column=Column(EnumString(ItemTypeEnum), nullable=False),
    )
    tracks_inventory: bool = Field(default=True)
    requires_fulfillment: bool = Field(default=False)
    is_active: bool = Field(default=True, index=True)
    available_for_sale: bool = Field(default=True, index=True)
    allows_multi_flavor: bool = Field(default=False)
    production_destination: Optional[str] = Field(default=None, max_length=80)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    category: Optional[Category] = Relationship(back_populates="products")
    prices: List["ProductPrice"] = Relationship(back_populates="product")
    balances: List["InventoryBalance"] = Relationship(back_populates="product")

class ProductPrice(SQLModel, table=True):
    __tablename__ = "product_prices"
    __table_args__ = (
        Index(
            "uq_product_prices_store", "tenant_id", "store_id", "product_id",
            unique=True, postgresql_where=text("store_id IS NOT NULL"),
        ),
        Index(
            "uq_product_prices_global", "tenant_id", "product_id",
            unique=True, postgresql_where=text("store_id IS NULL"),
        ),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: Optional[uuid.UUID] = Field(default=None, index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", index=True)
    cost_price: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    sale_price: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    product: Optional[Product] = Relationship(back_populates="prices")

class InventoryMovement(SQLModel, table=True):
    __tablename__ = "inventory_movements"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: uuid.UUID = Field(index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", index=True)
    actor_id: uuid.UUID = Field(index=True)
    movement_type: MovementTypeEnum = Field(
        default=MovementTypeEnum.ADJUSTMENT,
        sa_column=Column(EnumString(MovementTypeEnum), nullable=False, index=True),
    )
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


class QuickAccessProduct(SQLModel, table=True):
    __tablename__ = "quick_access_products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", "membership_id", "product_id", name="uq_quick_access_product"),
        UniqueConstraint("tenant_id", "store_id", "membership_id", "position", name="uq_quick_access_position"),
        CheckConstraint("position BETWEEN 1 AND 99", name="ck_quick_access_position"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    membership_id: uuid.UUID = Field(foreign_key="memberships.id", ondelete="CASCADE", index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", ondelete="CASCADE", index=True)
    position: int = Field(ge=1, le=99)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ModifierGroup(SQLModel, table=True):
    __tablename__ = "modifier_groups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_modifier_group_name"),
        CheckConstraint("minimum_choices >= 0 AND maximum_choices >= 1 AND minimum_choices <= maximum_choices", name="ck_modifier_group_choices"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    name: str = Field(max_length=160)
    minimum_choices: int = Field(default=0, ge=0)
    maximum_choices: int = Field(default=1, ge=1)
    is_required: bool = Field(default=False)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Modifier(SQLModel, table=True):
    __tablename__ = "modifiers"
    __table_args__ = (UniqueConstraint("tenant_id", "group_id", "name", name="uq_modifier_group_name"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    group_id: uuid.UUID = Field(foreign_key="modifier_groups.id", ondelete="CASCADE", index=True)
    name: str = Field(max_length=160)
    price_delta: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    production_destination: Optional[str] = Field(default=None, max_length=80)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProductModifierGroup(SQLModel, table=True):
    __tablename__ = "product_modifier_groups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "modifier_group_id", name="uq_product_modifier_group"),
        CheckConstraint("position >= 1", name="ck_product_modifier_position"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", ondelete="CASCADE", index=True)
    modifier_group_id: uuid.UUID = Field(foreign_key="modifier_groups.id", ondelete="CASCADE", index=True)
    position: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Combo(SQLModel, table=True):
    __tablename__ = "combos"
    __table_args__ = (UniqueConstraint("product_id", name="uq_combos_product_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", ondelete="CASCADE", index=True)
    name: str = Field(max_length=160)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ComboItem(SQLModel, table=True):
    __tablename__ = "combo_items"
    __table_args__ = (
        UniqueConstraint("combo_id", "product_id", name="uq_combo_item_product"),
        CheckConstraint("quantity > 0", name="ck_combo_item_quantity"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    combo_id: uuid.UUID = Field(foreign_key="combos.id", ondelete="CASCADE", index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", index=True)
    quantity: Decimal = Field(default=Decimal("1.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=1.0))
    created_at: datetime = Field(default_factory=datetime.utcnow)

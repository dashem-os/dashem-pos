import uuid
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.catalog import (
    Category, Combo, ItemTypeEnum, Modifier, ModifierGroup, Product,
    ProductModifierGroup, ProductPrice, QuickAccessProduct,
)
from app.services import catalog_service

router = APIRouter()


class CategoryCreateDTO(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    parent_id: Optional[uuid.UUID] = None


class CategoryUpdateDTO(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    slug: Optional[str] = Field(default=None, min_length=2, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    parent_id: Optional[uuid.UUID] = None
    is_active: Optional[bool] = None


class ProductCreateDTO(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    sku: str = Field(min_length=1, max_length=100)
    barcode: Optional[str] = Field(default=None, max_length=80)
    description: Optional[str] = None
    image_url: Optional[str] = Field(default=None, max_length=500)
    unit: str = Field(default="UN", min_length=1, max_length=16)
    category_id: Optional[uuid.UUID] = None
    item_type: ItemTypeEnum = ItemTypeEnum.PRODUCT
    tracks_inventory: Optional[bool] = None
    requires_fulfillment: Optional[bool] = None
    available_for_sale: bool = True
    allows_multi_flavor: bool = False
    production_destination: Optional[str] = Field(default=None, max_length=80)


class ProductUpdateDTO(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    sku: Optional[str] = Field(default=None, min_length=1, max_length=100)
    barcode: Optional[str] = Field(default=None, max_length=80)
    description: Optional[str] = None
    image_url: Optional[str] = Field(default=None, max_length=500)
    unit: Optional[str] = Field(default=None, min_length=1, max_length=16)
    category_id: Optional[uuid.UUID] = None
    item_type: Optional[ItemTypeEnum] = None
    tracks_inventory: Optional[bool] = None
    requires_fulfillment: Optional[bool] = None
    is_active: Optional[bool] = None
    available_for_sale: Optional[bool] = None
    allows_multi_flavor: Optional[bool] = None
    production_destination: Optional[str] = Field(default=None, max_length=80)


class ProductPriceCreateDTO(BaseModel):
    product_id: uuid.UUID
    cost_price: Decimal = Field(ge=0)
    sale_price: Decimal = Field(ge=0)
    store_id: Optional[uuid.UUID] = None


class SellableProductDTO(BaseModel):
    id: uuid.UUID
    name: str
    sku: str
    barcode: Optional[str]
    description: Optional[str]
    image_url: Optional[str]
    unit: str
    item_type: ItemTypeEnum
    category_id: Optional[uuid.UUID]
    category_name: Optional[str]
    tracks_inventory: bool
    requires_fulfillment: bool
    available_for_sale: bool
    allows_multi_flavor: bool
    production_destination: Optional[str]
    sale_price: Decimal
    cost_price: Decimal
    margin_percent: Decimal
    quantity: Decimal
    minimum_stock: Decimal
    is_low_stock: bool
    quick_position: Optional[int]


class SellableProductPageDTO(BaseModel):
    items: List[SellableProductDTO]
    total: int
    page: int
    page_size: int


class QuickAccessDTO(BaseModel):
    position: int = Field(ge=1, le=99)


class ModifierGroupCreateDTO(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    minimum_choices: int = Field(default=0, ge=0)
    maximum_choices: int = Field(default=1, ge=1)
    is_required: bool = False


class ModifierCreateDTO(BaseModel):
    group_id: uuid.UUID
    name: str = Field(min_length=1, max_length=160)
    price_delta: Decimal = Decimal("0")


class ProductModifierGroupDTO(BaseModel):
    group_id: uuid.UUID
    position: int = Field(default=1, ge=1)


class ComboItemDTO(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(default=Decimal("1"), gt=0)


class ComboCreateDTO(BaseModel):
    product_id: uuid.UUID
    name: str = Field(min_length=2, max_length=160)
    items: List[ComboItemDTO] = Field(min_length=1)


@router.post("/categories", response_model=Category)
def create_category_endpoint(data: CategoryCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.create_category(session, context, data.name, data.slug, data.parent_id)


@router.get("/categories", response_model=List[Category])
def list_categories_endpoint(include_inactive: bool = False, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.list_categories(session, context, include_inactive)


@router.patch("/categories/{category_id}", response_model=Category)
def update_category_endpoint(category_id: uuid.UUID, data: CategoryUpdateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.update_category(session, context, category_id, data.model_dump(exclude_unset=True))


@router.delete("/categories/{category_id}", response_model=Category)
def archive_category_endpoint(category_id: uuid.UUID, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.archive_category(session, context, category_id)


@router.post("/products", response_model=Product)
def create_product_endpoint(data: ProductCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.create_product(session, context, **data.model_dump())


@router.get("/products", response_model=List[Product])
def list_products_endpoint(category_id: Optional[uuid.UUID] = None, search: Optional[str] = None, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.list_products(session, context, category_id, search)


@router.patch("/products/{product_id}", response_model=Product)
def update_product_endpoint(product_id: uuid.UUID, data: ProductUpdateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.update_product(session, context, product_id, data.model_dump(exclude_unset=True))


@router.delete("/products/{product_id}", response_model=Product)
def archive_product_endpoint(product_id: uuid.UUID, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.archive_product(session, context, product_id)


@router.get("/sellable-products", response_model=SellableProductPageDTO)
def sellable_products_endpoint(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=160), category_id: Optional[uuid.UUID] = None,
    quick_access: bool = False, context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return catalog_service.list_sellable_products(session, context, page, page_size, search, category_id, quick_access)


@router.post("/prices", response_model=ProductPrice)
def upsert_product_price_endpoint(data: ProductPriceCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.create_product_price(session, context, data.product_id, float(data.cost_price), float(data.sale_price), data.store_id)


@router.get("/prices", response_model=List[ProductPrice])
def list_product_prices_endpoint(store_id: Optional[uuid.UUID] = None, product_id: Optional[uuid.UUID] = None, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.list_prices(session, context, store_id, product_id)


@router.put("/quick-access/{product_id}", response_model=QuickAccessProduct)
def set_quick_access_endpoint(product_id: uuid.UUID, data: QuickAccessDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.set_quick_access(session, context, product_id, data.position)


@router.delete("/quick-access/{product_id}", status_code=204)
def remove_quick_access_endpoint(product_id: uuid.UUID, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    catalog_service.remove_quick_access(session, context, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/modifier-groups", response_model=ModifierGroup, status_code=201)
def create_modifier_group_endpoint(data: ModifierGroupCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.create_modifier_group(session, context, data.name, data.minimum_choices, data.maximum_choices, data.is_required)


@router.post("/modifiers", response_model=Modifier, status_code=201)
def create_modifier_endpoint(data: ModifierCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.create_modifier(session, context, data.group_id, data.name, float(data.price_delta))


@router.post("/products/{product_id}/modifier-groups", response_model=ProductModifierGroup, status_code=201)
def link_modifier_group_endpoint(product_id: uuid.UUID, data: ProductModifierGroupDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.link_modifier_group(session, context, product_id, data.group_id, data.position)


@router.post("/combos", response_model=Combo, status_code=201)
def create_combo_endpoint(data: ComboCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.create_combo(session, context, data.product_id, data.name, [(item.product_id, item.quantity) for item in data.items])

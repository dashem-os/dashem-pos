import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlmodel import Session
from app.core.database import get_session
from app.core.context import TenantContext, get_tenant_context
from app.models.catalog import Category, Product, ProductPrice, ItemTypeEnum
from app.services import catalog_service

router = APIRouter()

class CategoryCreateDTO(BaseModel):
    name: str
    slug: str

class ProductCreateDTO(BaseModel):
    name: str
    sku: str
    barcode: Optional[str] = None
    description: Optional[str] = None
    category_id: Optional[uuid.UUID] = None
    item_type: ItemTypeEnum = ItemTypeEnum.PRODUCT
    tracks_inventory: Optional[bool] = None
    requires_fulfillment: Optional[bool] = None

class ProductPriceCreateDTO(BaseModel):
    product_id: uuid.UUID
    cost_price: float
    sale_price: float
    store_id: Optional[uuid.UUID] = None

@router.post("/categories", response_model=Category)
def create_category_endpoint(
    data: CategoryCreateDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return catalog_service.create_category(session, context, name=data.name, slug=data.slug)

@router.get("/categories", response_model=List[Category])
def list_categories_endpoint(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return catalog_service.list_categories(session, context)

@router.post("/products", response_model=Product)
def create_product_endpoint(
    data: ProductCreateDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return catalog_service.create_product(
        session,
        context,
        name=data.name,
        sku=data.sku,
        barcode=data.barcode,
        description=data.description,
        category_id=data.category_id,
        item_type=data.item_type,
        tracks_inventory=data.tracks_inventory,
        requires_fulfillment=data.requires_fulfillment
    )

@router.get("/products", response_model=List[Product])
def list_products_endpoint(
    category_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return catalog_service.list_products(session, context, category_id=category_id, search=search)


@router.post("/prices", response_model=ProductPrice)
def create_product_price_endpoint(
    data: ProductPriceCreateDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return catalog_service.create_product_price(
        session,
        context,
        product_id=data.product_id,
        cost_price=data.cost_price,
        sale_price=data.sale_price,
        store_id=data.store_id
    )

@router.get("/prices", response_model=List[ProductPrice])
def list_product_prices_endpoint(
    store_id: Optional[uuid.UUID] = None,
    product_id: Optional[uuid.UUID] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return catalog_service.list_prices(session, context, store_id=store_id, product_id=product_id)


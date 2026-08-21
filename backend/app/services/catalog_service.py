import uuid
from typing import List, Optional
from sqlmodel import Session, select, or_
from fastapi import HTTPException, status
from app.core.context import TenantContext, scope_tenant_query
from app.models.catalog import Category, Product, ProductPrice, ItemTypeEnum

def create_category(session: Session, context: TenantContext, name: str, slug: str) -> Category:
    existing_query = select(Category).where(Category.slug == slug)
    existing_query = scope_tenant_query(existing_query, Category, context)
    if session.exec(existing_query).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category with slug '{slug}' already exists for this tenant."
        )
    category = Category(tenant_id=context.tenant_id, name=name, slug=slug)
    session.add(category)
    session.commit()
    session.refresh(category)
    return category

def list_categories(session: Session, context: TenantContext) -> List[Category]:
    query = select(Category)
    query = scope_tenant_query(query, Category, context)
    return session.exec(query).all()

def create_product(
    session: Session,
    context: TenantContext,
    name: str,
    sku: str,
    barcode: Optional[str] = None,
    description: Optional[str] = None,
    category_id: Optional[uuid.UUID] = None,
    item_type: ItemTypeEnum = ItemTypeEnum.PRODUCT,
    tracks_inventory: Optional[bool] = None,
    requires_fulfillment: Optional[bool] = None
) -> Product:
    # Check SKU uniqueness per tenant
    existing_query = select(Product).where(Product.sku == sku)
    existing_query = scope_tenant_query(existing_query, Product, context)
    if session.exec(existing_query).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product with SKU '{sku}' already exists for this tenant."
        )
    
    # Enforce Domain Invariants
    if item_type == ItemTypeEnum.PRODUCT:
        final_tracks_inventory = True if tracks_inventory is None else tracks_inventory
        final_requires_fulfillment = False if requires_fulfillment is None else requires_fulfillment
    else:  # ItemTypeEnum.SERVICE
        final_tracks_inventory = False  # Absolute invariant for SERVICE
        final_requires_fulfillment = True if requires_fulfillment is None else requires_fulfillment

    product = Product(
        tenant_id=context.tenant_id,
        category_id=category_id,
        name=name,
        sku=sku,
        barcode=barcode,
        description=description,
        item_type=item_type,
        tracks_inventory=final_tracks_inventory,
        requires_fulfillment=final_requires_fulfillment
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return product

def list_products(
    session: Session,
    context: TenantContext,
    category_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None
) -> List[Product]:
    query = select(Product)
    query = scope_tenant_query(query, Product, context)
    if category_id:
        query = query.where(Product.category_id == category_id)
    if search:
        search_term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Product.name.ilike(search_term),
                Product.sku.ilike(search_term),
                Product.barcode == search.strip()
            )
        )
    return session.exec(query).all()


def create_product_price(
    session: Session,
    context: TenantContext,
    product_id: uuid.UUID,
    cost_price: float,
    sale_price: float,
    store_id: Optional[uuid.UUID] = None
) -> ProductPrice:
    # Verify product belongs to tenant
    product_query = select(Product).where(Product.id == product_id)
    product_query = scope_tenant_query(product_query, Product, context)
    product = session.exec(product_query).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{product_id}' not found for this tenant."
        )
    
    price = ProductPrice(
        tenant_id=context.tenant_id,
        store_id=store_id or context.store_id,
        product_id=product_id,
        cost_price=cost_price,
        sale_price=sale_price
    )
    session.add(price)
    session.commit()
    session.refresh(price)
    return price

def list_prices(
    session: Session,
    context: TenantContext,
    store_id: Optional[uuid.UUID] = None,
    product_id: Optional[uuid.UUID] = None
) -> List[ProductPrice]:
    query = select(ProductPrice)
    query = scope_tenant_query(query, ProductPrice, context)
    if store_id:
        query = query.where(ProductPrice.store_id == store_id)
    if product_id:
        query = query.where(ProductPrice.product_id == product_id)
    return session.exec(query).all()


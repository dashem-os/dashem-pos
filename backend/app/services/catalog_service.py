import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.catalog import (
    Category, Combo, ComboItem, InventoryBalance, ItemTypeEnum, Modifier,
    ModifierGroup, Product, ProductModifierGroup, ProductPrice,
    QuickAccessProduct,
)
from app.services import reliability_service


def _actor(context: TenantContext) -> uuid.UUID:
    return resolve_actor(context)


def _event(session: Session, context: TenantContext, action: str, aggregate: str, aggregate_id: uuid.UUID, payload: dict[str, Any]) -> None:
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=context.store_id,
        actor_id=_actor(context), action=action,
        target=f"{aggregate.upper()}-{aggregate_id}", audit_payload=payload,
        aggregate_type=aggregate, aggregate_id=str(aggregate_id),
        event_type=action, outbox_payload={"tenant_id": str(context.tenant_id), **payload},
    )


def _tenant_record(session: Session, context: TenantContext, model: Any, record_id: uuid.UUID, label: str) -> Any:
    record = session.exec(scope_tenant_query(select(model).where(model.id == record_id), model, context)).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"{label} não encontrado neste tenant.")
    return record


def create_category(session: Session, context: TenantContext, name: str, slug: str, parent_id: Optional[uuid.UUID] = None) -> Category:
    existing = session.exec(scope_tenant_query(select(Category).where(Category.slug == slug), Category, context)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Category with slug '{slug}' already exists for this tenant.")
    if parent_id:
        _tenant_record(session, context, Category, parent_id, "Categoria pai")
    category = Category(tenant_id=context.tenant_id, name=name.strip(), slug=slug.strip(), parent_id=parent_id)
    session.add(category)
    _event(session, context, "catalog.category.created", "category", category.id, {"name": category.name, "slug": category.slug})
    session.commit(); session.refresh(category)
    return category


def update_category(session: Session, context: TenantContext, category_id: uuid.UUID, changes: dict[str, Any]) -> Category:
    category = _tenant_record(session, context, Category, category_id, "Categoria")
    if changes.get("parent_id") == category_id:
        raise HTTPException(status_code=400, detail="Uma categoria não pode ser sua própria categoria pai.")
    if changes.get("parent_id"):
        _tenant_record(session, context, Category, changes["parent_id"], "Categoria pai")
    for key, value in changes.items():
        setattr(category, key, value.strip() if isinstance(value, str) else value)
    category.updated_at = datetime.utcnow()
    _event(session, context, "catalog.category.updated", "category", category.id, changes)
    session.commit(); session.refresh(category)
    return category


def archive_category(session: Session, context: TenantContext, category_id: uuid.UUID) -> Category:
    return update_category(session, context, category_id, {"is_active": False})


def list_categories(session: Session, context: TenantContext, include_inactive: bool = False) -> List[Category]:
    query = scope_tenant_query(select(Category), Category, context)
    if not include_inactive:
        query = query.where(Category.is_active.is_(True))
    return list(session.exec(query.order_by(Category.name)).all())


def create_product(session: Session, context: TenantContext, **data: Any) -> Product:
    sku = str(data.pop("sku")).strip()
    existing = session.exec(scope_tenant_query(select(Product).where(Product.sku == sku), Product, context)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Product with SKU '{sku}' already exists for this tenant.")
    category_id = data.get("category_id")
    if category_id:
        _tenant_record(session, context, Category, category_id, "Categoria")
    item_type = data.get("item_type", ItemTypeEnum.PRODUCT)
    if item_type == ItemTypeEnum.SERVICE:
        data["tracks_inventory"] = False
    elif data.get("tracks_inventory") is None:
        data["tracks_inventory"] = True
    if data.get("requires_fulfillment") is None:
        data["requires_fulfillment"] = item_type == ItemTypeEnum.SERVICE
    product = Product(tenant_id=context.tenant_id, sku=sku, **data)
    session.add(product)
    _event(session, context, "catalog.product.created", "product", product.id, {"name": product.name, "sku": product.sku})
    session.commit(); session.refresh(product)
    return product


def update_product(session: Session, context: TenantContext, product_id: uuid.UUID, changes: dict[str, Any]) -> Product:
    product = _tenant_record(session, context, Product, product_id, "Produto")
    if changes.get("category_id"):
        _tenant_record(session, context, Category, changes["category_id"], "Categoria")
    if changes.get("item_type", product.item_type) == ItemTypeEnum.SERVICE:
        changes["tracks_inventory"] = False
    for key, value in changes.items():
        setattr(product, key, value.strip() if isinstance(value, str) else value)
    product.updated_at = datetime.utcnow()
    _event(session, context, "catalog.product.updated", "product", product.id, changes)
    session.commit(); session.refresh(product)
    return product


def archive_product(session: Session, context: TenantContext, product_id: uuid.UUID) -> Product:
    return update_product(session, context, product_id, {"is_active": False, "available_for_sale": False})


def list_products(session: Session, context: TenantContext, category_id: Optional[uuid.UUID] = None, search: Optional[str] = None) -> List[Product]:
    query = scope_tenant_query(select(Product).where(Product.is_active.is_(True)), Product, context)
    if category_id:
        query = query.where(Product.category_id == category_id)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Product.name.ilike(term), Product.sku.ilike(term), Product.barcode.ilike(term)))
    return list(session.exec(query.order_by(Product.name).limit(200)).all())


def create_product_price(session: Session, context: TenantContext, product_id: uuid.UUID, cost_price: float, sale_price: float, store_id: Optional[uuid.UUID] = None) -> ProductPrice:
    _tenant_record(session, context, Product, product_id, "Produto")
    effective_store = store_id or context.store_id
    if context.store_id and effective_store != context.store_id:
        raise HTTPException(status_code=403, detail="Preço fora da unidade ativa.")
    query = scope_tenant_query(select(ProductPrice).where(ProductPrice.product_id == product_id), ProductPrice, context)
    query = query.where(ProductPrice.store_id == effective_store) if effective_store else query.where(ProductPrice.store_id.is_(None))
    price = session.exec(query).first()
    if price:
        price.cost_price = Decimal(str(cost_price)); price.sale_price = Decimal(str(sale_price)); price.updated_at = datetime.utcnow()
    else:
        price = ProductPrice(tenant_id=context.tenant_id, store_id=effective_store, product_id=product_id, cost_price=Decimal(str(cost_price)), sale_price=Decimal(str(sale_price)))
        session.add(price)
    _event(session, context, "catalog.price.upserted", "product", product_id, {"store_id": str(effective_store) if effective_store else None, "cost_price": str(cost_price), "sale_price": str(sale_price)})
    session.commit(); session.refresh(price)
    return price


def list_prices(session: Session, context: TenantContext, store_id: Optional[uuid.UUID] = None, product_id: Optional[uuid.UUID] = None) -> List[ProductPrice]:
    query = scope_tenant_query(select(ProductPrice), ProductPrice, context)
    if store_id: query = query.where(ProductPrice.store_id == store_id)
    if product_id: query = query.where(ProductPrice.product_id == product_id)
    return list(session.exec(query).all())


def list_sellable_products(session: Session, context: TenantContext, page: int, page_size: int, search: Optional[str], category_id: Optional[uuid.UUID], quick_access: bool) -> dict[str, Any]:
    if not context.store_id:
        raise HTTPException(status_code=400, detail="X-Store-ID é obrigatório para o catálogo operacional.")
    StorePrice, GlobalPrice = aliased(ProductPrice), aliased(ProductPrice)
    Balance, Quick = aliased(InventoryBalance), aliased(QuickAccessProduct)
    sale_price = func.coalesce(StorePrice.sale_price, GlobalPrice.sale_price, 0)
    cost_price = func.coalesce(StorePrice.cost_price, GlobalPrice.cost_price, 0)
    quantity, minimum = func.coalesce(Balance.quantity, 0), func.coalesce(Balance.minimum_stock, 0)
    query = (
        select(
            Product.id, Product.name, Product.sku, Product.barcode, Product.description,
            Product.image_url, Product.unit, Product.item_type, Product.category_id,
            Category.name.label("category_name"), Product.tracks_inventory,
            Product.requires_fulfillment, Product.available_for_sale,
            Product.allows_multi_flavor, Product.production_destination,
            sale_price.label("sale_price"), cost_price.label("cost_price"),
            quantity.label("quantity"), minimum.label("minimum_stock"),
            Quick.position.label("quick_position"), func.count().over().label("total_count"),
        )
        .outerjoin(Category, and_(Category.id == Product.category_id, Category.tenant_id == Product.tenant_id))
        .outerjoin(StorePrice, and_(StorePrice.product_id == Product.id, StorePrice.tenant_id == Product.tenant_id, StorePrice.store_id == context.store_id))
        .outerjoin(GlobalPrice, and_(GlobalPrice.product_id == Product.id, GlobalPrice.tenant_id == Product.tenant_id, GlobalPrice.store_id.is_(None)))
        .outerjoin(Balance, and_(Balance.product_id == Product.id, Balance.tenant_id == Product.tenant_id, Balance.store_id == context.store_id))
        .outerjoin(Quick, and_(Quick.product_id == Product.id, Quick.tenant_id == Product.tenant_id, Quick.store_id == context.store_id, Quick.membership_id == context.membership_id))
        .where(Product.tenant_id == context.tenant_id, Product.is_active.is_(True), Product.available_for_sale.is_(True))
    )
    if category_id: query = query.where(Product.category_id == category_id)
    if quick_access: query = query.where(Quick.id.is_not(None))
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Product.name.ilike(term), Product.sku.ilike(term), Product.barcode.ilike(term)))
    query = query.order_by(case((Quick.position.is_(None), 1), else_=0), Quick.position, Product.name).offset((page - 1) * page_size).limit(page_size)
    rows = session.exec(query).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        values = row._mapping
        sale, cost = Decimal(str(values["sale_price"])), Decimal(str(values["cost_price"]))
        margin = ((sale - cost) / sale * 100) if sale else Decimal("0")
        item = {key: values[key] for key in (
            "id", "name", "sku", "barcode", "description", "image_url", "unit", "item_type",
            "category_id", "category_name", "tracks_inventory", "requires_fulfillment",
            "available_for_sale", "allows_multi_flavor", "production_destination",
            "sale_price", "cost_price", "quantity", "minimum_stock", "quick_position",
        )}
        item.update(margin_percent=margin.quantize(Decimal("0.01")), is_low_stock=bool(values["tracks_inventory"] and Decimal(str(values["quantity"])) <= Decimal(str(values["minimum_stock"]))))
        items.append(item)
    return {"items": items, "total": int(rows[0]._mapping["total_count"]) if rows else 0, "page": page, "page_size": page_size}


def set_quick_access(session: Session, context: TenantContext, product_id: uuid.UUID, position: int) -> QuickAccessProduct:
    if not context.store_id or not context.membership_id:
        raise HTTPException(status_code=400, detail="Contexto de unidade e membro obrigatório.")
    _tenant_record(session, context, Product, product_id, "Produto")
    occupied = session.exec(select(QuickAccessProduct).where(QuickAccessProduct.tenant_id == context.tenant_id, QuickAccessProduct.store_id == context.store_id, QuickAccessProduct.membership_id == context.membership_id, QuickAccessProduct.position == position, QuickAccessProduct.product_id != product_id)).first()
    if occupied: raise HTTPException(status_code=409, detail=f"A posição {position} já está ocupada.")
    quick = session.exec(select(QuickAccessProduct).where(QuickAccessProduct.tenant_id == context.tenant_id, QuickAccessProduct.store_id == context.store_id, QuickAccessProduct.membership_id == context.membership_id, QuickAccessProduct.product_id == product_id)).first()
    if quick:
        quick.position = position; quick.updated_at = datetime.utcnow()
    else:
        quick = QuickAccessProduct(tenant_id=context.tenant_id, store_id=context.store_id, membership_id=context.membership_id, product_id=product_id, position=position); session.add(quick)
    _event(session, context, "catalog.quick_access.upserted", "product", product_id, {"position": position})
    session.commit(); session.refresh(quick)
    return quick


def remove_quick_access(session: Session, context: TenantContext, product_id: uuid.UUID) -> None:
    if not context.store_id or not context.membership_id: raise HTTPException(status_code=400, detail="Contexto de unidade e membro obrigatório.")
    quick = session.exec(select(QuickAccessProduct).where(QuickAccessProduct.tenant_id == context.tenant_id, QuickAccessProduct.store_id == context.store_id, QuickAccessProduct.membership_id == context.membership_id, QuickAccessProduct.product_id == product_id)).first()
    if quick:
        session.delete(quick); _event(session, context, "catalog.quick_access.removed", "product", product_id, {}); session.commit()


def create_modifier_group(session: Session, context: TenantContext, name: str, minimum_choices: int, maximum_choices: int, is_required: bool) -> ModifierGroup:
    if minimum_choices > maximum_choices: raise HTTPException(status_code=400, detail="minimum_choices não pode exceder maximum_choices.")
    group = ModifierGroup(tenant_id=context.tenant_id, name=name.strip(), minimum_choices=minimum_choices, maximum_choices=maximum_choices, is_required=is_required)
    session.add(group); _event(session, context, "catalog.modifier_group.created", "modifier_group", group.id, {"name": group.name}); session.commit(); session.refresh(group)
    return group


def create_modifier(session: Session, context: TenantContext, group_id: uuid.UUID, name: str, price_delta: float) -> Modifier:
    _tenant_record(session, context, ModifierGroup, group_id, "Grupo de modificadores")
    modifier = Modifier(tenant_id=context.tenant_id, group_id=group_id, name=name.strip(), price_delta=Decimal(str(price_delta)))
    session.add(modifier); _event(session, context, "catalog.modifier.created", "modifier", modifier.id, {"group_id": str(group_id), "name": modifier.name}); session.commit(); session.refresh(modifier)
    return modifier


def link_modifier_group(session: Session, context: TenantContext, product_id: uuid.UUID, group_id: uuid.UUID, position: int) -> ProductModifierGroup:
    _tenant_record(session, context, Product, product_id, "Produto"); _tenant_record(session, context, ModifierGroup, group_id, "Grupo de modificadores")
    link = ProductModifierGroup(tenant_id=context.tenant_id, product_id=product_id, modifier_group_id=group_id, position=position)
    session.add(link); session.commit(); session.refresh(link)
    return link


def create_combo(session: Session, context: TenantContext, product_id: uuid.UUID, name: str, items: list[tuple[uuid.UUID, Decimal]]) -> Combo:
    _tenant_record(session, context, Product, product_id, "Produto do combo")
    combo = Combo(tenant_id=context.tenant_id, product_id=product_id, name=name.strip()); session.add(combo)
    for item_product_id, quantity in items:
        _tenant_record(session, context, Product, item_product_id, "Item do combo")
        session.add(ComboItem(tenant_id=context.tenant_id, combo_id=combo.id, product_id=item_product_id, quantity=quantity))
    _event(session, context, "catalog.combo.created", "combo", combo.id, {"product_id": str(product_id), "items": len(items)}); session.commit(); session.refresh(combo)
    return combo

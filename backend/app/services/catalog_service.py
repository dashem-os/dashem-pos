import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.catalog import (
    Category, Combo, ComboItem, InventoryBalance, ItemTypeEnum, Modifier,
    ModifierGroup, PlatformMediaAsset, Product, ProductModifierGroup, ProductPrice,
    QuickAccessProduct, StoreCatalogLayout, StoreCatalogLayoutItem,
)
from app.models.assortment import SalesContextEnum
from app.services.assortment_service import resolve_effective_product_ids
from app.services import media_service, reliability_service
from app.modules.capabilities.service import capability_allowed_by_activity
from app.services.contract_entitlement_service import resolve_contract_entitlements


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


def list_sellable_products(
    session: Session,
    context: TenantContext,
    page: int,
    page_size: int,
    search: Optional[str],
    category_id: Optional[uuid.UUID],
    quick_access: bool,
    sales_context: Optional[SalesContextEnum] = None,
    channel_id: Optional[uuid.UUID] = None,
    master: bool = False,
    activity: Optional[str] = None,
) -> dict[str, Any]:
    if not context.store_id:
        raise HTTPException(status_code=400, detail="X-Store-ID é obrigatório para o catálogo operacional.")

    # The local subject is an explicit development/test boundary. Every
    # authenticated deployment must carry the management permission; an
    # operational token must never turn the master flag into a publication
    # bypass.
    if master and context.auth_subject != "local-auth-bypass" and "management.read" not in context.permissions:
        raise HTTPException(
            status_code=403,
            detail="O catálogo mestre exige autorização gerencial explícita.",
        )

    authorized_product_ids: set[uuid.UUID] = set()
    if not master:
        if not sales_context:
            raise HTTPException(
                status_code=400,
                detail="Contexto de venda (sales_context: COUNTER, TAKEAWAY, TABLE, DELIVERY, ECOMMERCE) é obrigatório.",
            )

        caps = set(context.capabilities or ())
        if sales_context == SalesContextEnum.TABLE:
            if "table_service" not in caps:
                if not capability_allowed_by_activity(session, context.tenant_id, "table_service"):
                    raise HTTPException(status_code=403, detail="Jornada de mesa indisponível: a atividade FOOD_SERVICE não está contratada e ativa nesta unidade.")
                raise HTTPException(status_code=403, detail="Capacidade 'table_service' não contratada ou inativa para esta unidade.")
        elif sales_context == SalesContextEnum.DELIVERY:
            if "delivery_orders" not in caps:
                raise HTTPException(status_code=403, detail="Capacidade 'delivery_orders' não contratada ou inativa para esta unidade.")
        elif sales_context in {SalesContextEnum.COUNTER, SalesContextEnum.TAKEAWAY}:
            if "counter_order" not in caps:
                raise HTTPException(status_code=403, detail="Capacidade 'counter_order' não contratada ou inativa para esta unidade.")
        elif sales_context == SalesContextEnum.ECOMMERCE:
            if "ecommerce" not in caps:
                raise HTTPException(status_code=403, detail="Jornada de e-commerce não contratada ou habilitada para esta unidade.")

        # The activity narrows the projection to the curated set of that business
        # model. It must be contracted: an operator can never sell through an
        # activity the tenant did not hire, even by crafting the query.
        if activity:
            snapshot = resolve_contract_entitlements(session, context.tenant_id)
            if snapshot is not None and activity not in snapshot.activity_keys:
                raise HTTPException(
                    status_code=403,
                    detail=f"Atividade '{activity}' não está contratada para este tenant.",
                )

        authorized_product_ids = resolve_effective_product_ids(
            session, context.tenant_id, context.store_id, sales_context, channel_id, activity
        )
        if not authorized_product_ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

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
        .where(
            Product.tenant_id == context.tenant_id,
            Product.is_active.is_(True),
        )
    )
    if not master:
        query = query.where(
            Product.available_for_sale.is_(True),
            Product.id.in_(authorized_product_ids),
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

    # The picture is resolved and signed here, for the whole page at once. A card
    # that signed its own URL would turn a window of twenty items into twenty
    # round trips, and the first ones would expire before the last ones loaded.
    if items:
        page_products = session.exec(scope_tenant_query(
            select(Product).where(Product.id.in_([item["id"] for item in items])), Product, context,
        )).all()
        images = media_service.resolve_product_images(session, context, page_products)
        for item in items:
            item["image"] = images.get(item["id"])

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


def set_product_media(
    session: Session, context: TenantContext, product_id: uuid.UUID, *,
    bucket_id: Optional[str] = None, object_path: Optional[str] = None,
    content_type: Optional[str] = None, size_bytes: int = 0,
    original_filename: Optional[str] = None, library_asset_id: Optional[uuid.UUID] = None,
) -> Product:
    """Attach a stored picture to a product — uploaded, or chosen from the shelf.

    `image_url` is left exactly as it was. A shop that pasted an address before
    today keeps it; resolution simply prefers the asset from now on, and the old
    value stays available if the asset is ever cleared.
    """
    product = _tenant_record(session, context, Product, product_id, "Produto")
    if library_asset_id:
        library = session.exec(select(PlatformMediaAsset).where(
            PlatformMediaAsset.id == library_asset_id, PlatformMediaAsset.is_active == True,  # noqa: E712
        )).first()
        if not library:
            raise HTTPException(status_code=404, detail="Imagem da biblioteca não encontrada.")
        asset = media_service.adopt_library_asset(
            session, context, library_asset=library, actor_id=_actor(context),
        )
    else:
        if not bucket_id or not object_path or not content_type:
            raise HTTPException(status_code=400, detail="Informe o arquivo enviado ou uma imagem da biblioteca.")
        try:
            asset = media_service.register_tenant_upload(
                session, context, bucket_id=bucket_id, object_path=object_path,
                content_type=content_type, size_bytes=size_bytes,
                original_filename=original_filename, actor_id=_actor(context),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    product.primary_media_asset_id = asset.id
    product.updated_at = datetime.utcnow()
    session.add(product)
    _event(session, context, "catalog.product.media_set", "product", product.id, {
        "media_asset_id": str(asset.id), "source": asset.source,
    })
    session.commit()
    session.refresh(product)
    return product


def search_media_library(
    session: Session,
    search: Optional[str] = None, activity: Optional[str] = None, limit: int = 60,
) -> list[dict[str, Any]]:
    """The DASHEM shelf. Activity ranks, it never filters something out.

    A lamp shop may want a picture filed under food service, and refusing it
    would be the platform deciding what the shopkeeper sells.
    """
    query = select(PlatformMediaAsset).where(PlatformMediaAsset.is_active == True)  # noqa: E712
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(
            PlatformMediaAsset.name.ilike(term),
            PlatformMediaAsset.code.ilike(term),
            PlatformMediaAsset.tags.cast(String).ilike(term),
        ))
    rows = list(session.exec(query.limit(limit)).all())
    if activity:
        rows.sort(key=lambda asset: activity not in (asset.suggested_activities or []))
    return [
        {
            "id": str(asset.id), "code": asset.code, "name": asset.name,
            "collection": asset.collection, "tags": asset.tags,
            "suggested_activities": asset.suggested_activities,
            "url": (signed[0] if (signed := media_service.sign_library_asset(asset)) else None),
        }
        for asset in rows
    ]


ALL_ACTIVITIES = "ALL"


def _normalised_scope(sales_context: Optional[str], activity: Optional[str]) -> tuple[str, str]:
    """`ALL` is the sentinel for "serves every contracted activity".

    It is a value and not a NULL because a NULL never collides in a unique
    constraint, and the position constraint has to actually constrain.
    """
    return (sales_context or SalesContextEnum.COUNTER.value), (activity or ALL_ACTIVITIES)


def _sellable_products(session: Session, context: TenantContext, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, Product]:
    """Every id must name a live product of this tenant, or the whole call fails.

    An arrangement that quietly drops an unknown id would renumber the rest and
    leave the manager staring at positions they did not choose.
    """
    if not product_ids:
        return {}
    found = {
        product.id: product
        for product in session.exec(
            scope_tenant_query(select(Product).where(Product.id.in_(product_ids)), Product, context)
        ).all()
    }
    missing = [str(pid) for pid in product_ids if pid not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"Produto não encontrado neste tenant: {', '.join(missing)}")
    archived = [str(p.id) for p in found.values() if not p.is_active or not p.available_for_sale]
    if archived:
        raise HTTPException(
            status_code=409,
            detail=f"Produto arquivado ou indisponível não entra na vitrine: {', '.join(archived)}",
        )
    return found


def _load_layout(
    session: Session, context: TenantContext, sales_context: str, activity: str, *, lock: bool
) -> Optional[StoreCatalogLayout]:
    query = select(StoreCatalogLayout).where(
        StoreCatalogLayout.tenant_id == context.tenant_id,
        StoreCatalogLayout.store_id == context.store_id,
        StoreCatalogLayout.sales_context == sales_context,
        StoreCatalogLayout.business_activity == activity,
    )
    if lock:
        query = query.with_for_update()
    return session.exec(query).first()


def get_store_layout(
    session: Session, context: TenantContext,
    sales_context: Optional[str] = None, activity: Optional[str] = None,
) -> dict[str, Any]:
    """The unit's arrangement, in order, without archived items."""
    if not context.store_id:
        raise HTTPException(status_code=400, detail="X-Store-ID é obrigatório para a vitrine da unidade.")
    scope_context, scope_activity = _normalised_scope(sales_context, activity)
    layout = _load_layout(session, context, scope_context, scope_activity, lock=False)
    if not layout:
        return {
            "sales_context": scope_context, "business_activity": scope_activity,
            "version": 0, "product_ids": [], "updated_at": None,
        }
    rows = session.exec(
        select(StoreCatalogLayoutItem, Product)
        .join(Product, Product.id == StoreCatalogLayoutItem.product_id)
        .where(StoreCatalogLayoutItem.layout_id == layout.id)
        .order_by(StoreCatalogLayoutItem.position)
    ).all()
    return {
        "sales_context": layout.sales_context,
        "business_activity": layout.business_activity,
        "version": layout.version,
        # An archived product keeps its row — the manager did choose it — but it
        # never reaches the screen, so a dead button cannot appear on the window.
        "product_ids": [str(item.product_id) for item, product in rows if product.is_active and product.available_for_sale],
        "updated_at": layout.updated_at,
    }


def reorder_store_layout(
    session: Session, context: TenantContext, product_ids: List[uuid.UUID], expected_version: int,
    sales_context: Optional[str] = None, activity: Optional[str] = None,
) -> dict[str, Any]:
    """Apply the whole arrangement in one transaction.

    The header is locked and its version checked, so two managers reordering the
    same window cannot interleave: one wins, the other is told which version it
    was working from. The items are replaced wholesale rather than permuted in
    place — with the position unique deferred, either shape is atomic, and
    replacement keeps the code honest about what the caller sent.
    """
    if not context.store_id:
        raise HTTPException(status_code=400, detail="X-Store-ID é obrigatório para a vitrine da unidade.")
    if len(set(product_ids)) != len(product_ids):
        raise HTTPException(status_code=400, detail="A vitrine não aceita o mesmo produto duas vezes.")
    if len(product_ids) > 99:
        raise HTTPException(status_code=400, detail="A vitrine comporta no máximo 99 posições.")
    scope_context, scope_activity = _normalised_scope(sales_context, activity)
    _sellable_products(session, context, product_ids)

    layout = _load_layout(session, context, scope_context, scope_activity, lock=True)
    created = layout is None
    if created:
        if expected_version not in (0, None):
            raise HTTPException(status_code=409, detail="A vitrine ainda não existe; esperava versão 0.")
        # A persisted layout always carries version 1 or greater; version 0 is
        # how the read side says "this window does not exist yet".
        layout = StoreCatalogLayout(
            tenant_id=context.tenant_id, store_id=context.store_id,
            sales_context=scope_context, business_activity=scope_activity, version=1,
        )
        session.add(layout)
        session.flush()
    elif layout.version != expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"A vitrine mudou: versão atual {layout.version}, recebida {expected_version}.",
        )

    for item in session.exec(
        select(StoreCatalogLayoutItem).where(StoreCatalogLayoutItem.layout_id == layout.id)
    ).all():
        session.delete(item)
    session.flush()
    for position, product_id in enumerate(product_ids, start=1):
        session.add(StoreCatalogLayoutItem(
            tenant_id=context.tenant_id, layout_id=layout.id,
            product_id=product_id, position=position,
        ))

    if not created:
        layout.version += 1
    layout.updated_by = _actor(context)
    layout.updated_at = datetime.utcnow()
    session.add(layout)
    _event(session, context, "catalog.layout.reordered", "store_catalog_layout", layout.id, {
        "sales_context": scope_context, "business_activity": scope_activity,
        "version": layout.version, "positions": len(product_ids),
    })
    _commit_positions(session)
    session.refresh(layout)
    return get_store_layout(session, context, scope_context, scope_activity)


def reorder_quick_access(
    session: Session, context: TenantContext, product_ids: List[uuid.UUID],
    sales_context: Optional[str] = None, activity: Optional[str] = None,
) -> List[QuickAccessProduct]:
    """The person's own band, replaced whole, in the same single transaction."""
    if not context.store_id or not context.membership_id:
        raise HTTPException(status_code=400, detail="Contexto de unidade e membro obrigatório.")
    if len(set(product_ids)) != len(product_ids):
        raise HTTPException(status_code=400, detail="Um atalho não pode repetir o mesmo produto.")
    if len(product_ids) > 99:
        raise HTTPException(status_code=400, detail="A faixa pessoal comporta no máximo 99 atalhos.")
    scope_context, scope_activity = _normalised_scope(sales_context, activity)
    _sellable_products(session, context, product_ids)

    existing = session.exec(select(QuickAccessProduct).where(
        QuickAccessProduct.tenant_id == context.tenant_id,
        QuickAccessProduct.store_id == context.store_id,
        QuickAccessProduct.membership_id == context.membership_id,
        QuickAccessProduct.sales_context == scope_context,
        QuickAccessProduct.business_activity == scope_activity,
    ).with_for_update()).all()
    for row in existing:
        session.delete(row)
    session.flush()
    for position, product_id in enumerate(product_ids, start=1):
        session.add(QuickAccessProduct(
            tenant_id=context.tenant_id, store_id=context.store_id,
            membership_id=context.membership_id, product_id=product_id,
            sales_context=scope_context, business_activity=scope_activity, position=position,
        ))
    _event(session, context, "catalog.quick_access.reordered", "membership", context.membership_id, {
        "sales_context": scope_context, "business_activity": scope_activity, "positions": len(product_ids),
    })
    _commit_positions(session)
    return list_quick_access(session, context, scope_context, scope_activity)


def list_quick_access(
    session: Session, context: TenantContext,
    sales_context: Optional[str] = None, activity: Optional[str] = None,
) -> List[QuickAccessProduct]:
    if not context.store_id or not context.membership_id:
        return []
    scope_context, scope_activity = _normalised_scope(sales_context, activity)
    return list(session.exec(select(QuickAccessProduct).where(
        QuickAccessProduct.tenant_id == context.tenant_id,
        QuickAccessProduct.store_id == context.store_id,
        QuickAccessProduct.membership_id == context.membership_id,
        QuickAccessProduct.sales_context == scope_context,
        QuickAccessProduct.business_activity == scope_activity,
    ).order_by(QuickAccessProduct.position)).all())


def _commit_positions(session: Session) -> None:
    """Commit work guarded by a deferred unique, and speak 409 instead of 500.

    The position constraints are DEFERRABLE INITIALLY DEFERRED, which is what
    makes a permutation possible at all — a non-deferred unique is checked
    during the statement and a swap violates it halfway through. The cost is
    that a genuine collision now surfaces at COMMIT rather than at the offending
    statement, and an uncaught IntegrityError there reaches the operator as a
    500. It is a conflict, and it says so.
    """
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # Only a unique violation on a position constraint is a conflict. Any
        # other IntegrityError is a defect, and dressing it as a friendly 409
        # would hide it — which is exactly how a check violation on `version`
        # first reached this code disguised as contention.
        code = getattr(getattr(exc, "orig", None), "pgcode", None)
        constraint = str(getattr(exc, "orig", "")).lower()
        if code == "23505" and "position" in constraint:
            raise HTTPException(
                status_code=409,
                detail="Conflito de posições ao gravar a ordenação. Recarregue e tente de novo.",
            ) from exc
        raise


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

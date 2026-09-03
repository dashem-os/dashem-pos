"""Publish a starter catalogue coherent with the tenant's contracted activity.

A homologation tenant contracted as food service was showing hardware on its own
point of sale: products left behind by a demo seeder, still published through the
LEGACY-DEFAULT assortment that migration 069 materialised without an activity.

Management publishes here and the operator consumes it: the action creates the set
for one contracted activity and retires the assortments that publish to the same
store without declaring any activity, which is what lets foreign content reach the
counter. Nothing is deleted — a retired set keeps its products and can be
reactivated, and the master catalogue is untouched.

Restricted to internal or test tenants, so a live customer never receives
demonstration products in its catalogue.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.context import TenantContext, resolve_actor
from app.models.assortment import (
    Assortment,
    AssortmentProduct,
    AssortmentScope,
    AssortmentStatusEnum,
    SalesContextEnum,
)
from app.models.catalog import Category, InventoryBalance, ItemTypeEnum, Product, ProductPrice
from app.models.identity import TenantPhaseEnum, TenantProfile, TenantTypeEnum
from app.services.contract_entitlement_service import resolve_contract_entitlements


@dataclass(frozen=True)
class StarterItem:
    name: str
    sku: str
    category: str
    price: str
    quantity: int


CATALOGUES: dict[str, tuple[str, tuple[StarterItem, ...]]] = {
    "FOOD_SERVICE": ("Cardápio inicial", (
        StarterItem("Hambúrguer Artesanal 180g", "DEMO-FOOD-BURGER", "Lanches", "32.90", 40),
        StarterItem("Cheeseburger Duplo", "DEMO-FOOD-CHEESE", "Lanches", "38.50", 40),
        StarterItem("Porção de Batata Frita G", "DEMO-FOOD-FRIES", "Porções", "24.00", 60),
        StarterItem("Refrigerante Lata 350ml", "DEMO-FOOD-SODA", "Bebidas", "7.00", 120),
        StarterItem("Suco Natural de Laranja 500ml", "DEMO-FOOD-JUICE", "Bebidas", "12.90", 60),
        StarterItem("Milkshake de Morango", "DEMO-FOOD-SHAKE", "Sobremesas", "18.50", 30),
    )),
    "RETAIL": ("Sortimento inicial de varejo", (
        StarterItem("Caderno Universitário 200 folhas", "DEMO-RET-NOTE", "Papelaria", "34.90", 50),
        StarterItem("Caneta Esferográfica Azul", "DEMO-RET-PEN", "Papelaria", "3.50", 300),
        StarterItem("Pilha Alcalina AA (cartela com 4)", "DEMO-RET-BATT", "Utilidades", "24.90", 80),
        StarterItem("Fone de Ouvido Intra-auricular", "DEMO-RET-PHONE", "Eletrônicos", "59.90", 25),
        StarterItem("Garrafa Térmica 1L", "DEMO-RET-BOTTLE", "Utilidades", "79.90", 20),
        StarterItem("Carregador USB-C 20W", "DEMO-RET-CHARGER", "Eletrônicos", "89.90", 30),
    )),
    "BEAUTY_RESELLER": ("Sortimento inicial de beleza", (
        StarterItem("Shampoo Hidratante 300ml", "DEMO-BEA-SHAMPOO", "Cabelos", "42.90", 45),
        StarterItem("Condicionador Nutritivo 300ml", "DEMO-BEA-COND", "Cabelos", "44.90", 45),
        StarterItem("Máscara Capilar 250g", "DEMO-BEA-MASK", "Cabelos", "68.00", 25),
        StarterItem("Perfume Floral 100ml", "DEMO-BEA-PERFUME", "Perfumaria", "189.90", 15),
        StarterItem("Base Líquida Matte", "DEMO-BEA-BASE", "Maquiagem", "79.90", 30),
        StarterItem("Batom Cremoso", "DEMO-BEA-LIPS", "Maquiagem", "39.90", 60),
    )),
}

STARTER_CONTEXTS = (SalesContextEnum.COUNTER, SalesContextEnum.TAKEAWAY)


def is_homologation_tenant(session: Session, tenant_id: uuid.UUID) -> bool:
    """Internal tenants and tenants still in the test phase, never a live customer."""
    profile = session.get(TenantProfile, tenant_id)
    if profile is None:
        return False
    return (
        profile.tenant_type == TenantTypeEnum.INTERNAL
        or profile.lifecycle_phase == TenantPhaseEnum.TEST
    )


def _category(session: Session, tenant_id: uuid.UUID, name: str) -> Category:
    found = session.exec(
        select(Category).where(Category.tenant_id == tenant_id, Category.name == name)
    ).first()
    if found:
        return found
    created = Category(tenant_id=tenant_id, name=name, slug=name.lower().replace(" ", "-"))
    session.add(created)
    session.flush()
    return created


def publish_starter_catalogue(
    session: Session,
    context: TenantContext,
    activity: str,
    actor_id: Optional[uuid.UUID] = None,
) -> dict[str, Any]:
    if not context.store_id:
        raise HTTPException(status_code=400, detail="X-Store-ID é obrigatório para publicar o catálogo inicial.")
    if activity not in CATALOGUES:
        raise HTTPException(status_code=400, detail=f"Atividade sem catálogo inicial definido: {activity}.")
    if not is_homologation_tenant(session, context.tenant_id):
        raise HTTPException(
            status_code=403,
            detail="O catálogo inicial existe apenas para tenants internos ou em fase de teste.",
        )

    snapshot = resolve_contract_entitlements(session, context.tenant_id)
    if snapshot is not None and activity not in snapshot.activity_keys:
        raise HTTPException(status_code=403, detail=f"Atividade não contratada para este tenant: {activity}.")

    resolve_actor(context, actor_id)
    label, items = CATALOGUES[activity]
    code = f"STARTER-{activity}"

    assortment = session.exec(
        select(Assortment).where(Assortment.tenant_id == context.tenant_id, Assortment.code == code)
    ).first()
    if assortment is None:
        assortment = Assortment(
            tenant_id=context.tenant_id, code=code, name=label,
            description="Publicado pela Gestão para homologar a operação da atividade contratada.",
            business_activity=activity, status=AssortmentStatusEnum.ACTIVE,
        )
        session.add(assortment)
        session.flush()
    else:
        assortment.business_activity = activity
        assortment.status = AssortmentStatusEnum.ACTIVE

    for sales_context in STARTER_CONTEXTS:
        exists = session.exec(
            select(AssortmentScope).where(
                AssortmentScope.tenant_id == context.tenant_id,
                AssortmentScope.assortment_id == assortment.id,
                AssortmentScope.store_id == context.store_id,
                AssortmentScope.sales_context == sales_context,
                AssortmentScope.channel_id.is_(None),
            )
        ).first()
        if exists is None:
            session.add(AssortmentScope(
                tenant_id=context.tenant_id, assortment_id=assortment.id,
                store_id=context.store_id, sales_context=sales_context,
            ))

    created = 0
    for item in items:
        product = session.exec(
            select(Product).where(Product.tenant_id == context.tenant_id, Product.sku == item.sku)
        ).first()
        if product is None:
            product = Product(
                tenant_id=context.tenant_id, name=item.name, sku=item.sku,
                category_id=_category(session, context.tenant_id, item.category).id,
                item_type=ItemTypeEnum.PRODUCT, is_active=True, available_for_sale=True,
            )
            session.add(product)
            session.flush()
            created += 1
        else:
            product.is_active = True
            product.available_for_sale = True

        price = session.exec(
            select(ProductPrice).where(
                ProductPrice.tenant_id == context.tenant_id,
                ProductPrice.product_id == product.id,
                ProductPrice.store_id == context.store_id,
            )
        ).first()
        if price is None:
            session.add(ProductPrice(
                tenant_id=context.tenant_id, product_id=product.id, store_id=context.store_id,
                cost_price=Decimal(item.price) / 2, sale_price=Decimal(item.price),
            ))

        balance = session.exec(
            select(InventoryBalance).where(
                InventoryBalance.tenant_id == context.tenant_id,
                InventoryBalance.product_id == product.id,
                InventoryBalance.store_id == context.store_id,
            )
        ).first()
        if balance is None:
            session.add(InventoryBalance(
                tenant_id=context.tenant_id, product_id=product.id, store_id=context.store_id,
                quantity=Decimal(item.quantity), minimum_stock=Decimal(5),
            ))

        linked = session.exec(
            select(AssortmentProduct).where(
                AssortmentProduct.tenant_id == context.tenant_id,
                AssortmentProduct.assortment_id == assortment.id,
                AssortmentProduct.product_id == product.id,
            )
        ).first()
        if linked is None:
            session.add(AssortmentProduct(
                tenant_id=context.tenant_id, assortment_id=assortment.id, product_id=product.id,
            ))

    # An active set publishing to this store without declaring an activity is
    # exactly what lets another business model's products reach this counter.
    retired: list[str] = []
    unclassified = session.exec(
        select(Assortment)
        .join(AssortmentScope, AssortmentScope.assortment_id == Assortment.id)
        .where(
            Assortment.tenant_id == context.tenant_id,
            Assortment.status == AssortmentStatusEnum.ACTIVE,
            Assortment.business_activity.is_(None),
            AssortmentScope.tenant_id == context.tenant_id,
            AssortmentScope.store_id == context.store_id,
        )
    ).all()
    for stale in {item.id: item for item in unclassified}.values():
        stale.status = AssortmentStatusEnum.INACTIVE
        stale.version += 1
        retired.append(stale.code)

    session.commit()
    return {
        "assortment_code": code,
        "activity": activity,
        "products_total": len(items),
        "products_created": created,
        "retired_assortments": retired,
    }

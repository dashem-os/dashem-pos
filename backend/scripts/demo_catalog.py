"""Seed or purge a demonstration catalogue coherent with a business activity.

A previous demo seeder wrote a hardware-store catalogue through the interface and
was later removed, leaving food service tenants selling circuit breakers. This
replaces it as a maintenance command: every set it creates is curated for one
contracted activity and reaches the point of sale only through an assortment
carrying that activity, so nothing can drift into the wrong operation again.

    python scripts/demo_catalog.py seed --tenant <uuid> --store <uuid> --activity FOOD_SERVICE
    python scripts/demo_catalog.py purge --tenant <uuid> --store <uuid> --assortment-code DEMO-RETAIL
    python scripts/demo_catalog.py purge --tenant <uuid> --store <uuid> --sku CAB-25M --sku DISJ-32A

Purge refuses to delete a product that already backs a sale, and reports it
instead of forcing the removal.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from decimal import Decimal
from pathlib import Path

# Runnable as `python scripts/demo_catalog.py` from the backend directory,
# without asking the operator to export PYTHONPATH first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.core.tenancy import set_platform_db_context  # noqa: E402
from app.models.assortment import (
    Assortment,
    AssortmentProduct,
    AssortmentScope,
    AssortmentStatusEnum,
    SalesContextEnum,
)
from app.models.catalog import Category, InventoryBalance, ItemTypeEnum, Product, ProductPrice  # noqa: E402
from app.models.sale import SaleItem  # noqa: E402


from app.services.starter_catalog_service import CATALOGUES  # noqa: E402



# The operator-facing journeys a demo set publishes into.
DEMO_CONTEXTS = (SalesContextEnum.COUNTER, SalesContextEnum.TAKEAWAY)


def _category(session: Session, tenant_id: uuid.UUID, name: str) -> Category:
    found = session.exec(
        select(Category).where(Category.tenant_id == tenant_id, Category.name == name)
    ).first()
    if found:
        return found
    slug = name.lower().replace(" ", "-")
    created = Category(tenant_id=tenant_id, name=name, slug=slug)
    session.add(created)
    session.flush()
    return created


def seed(session: Session, tenant_id: uuid.UUID, store_id: uuid.UUID, activity: str) -> None:
    label, items = CATALOGUES[activity]
    code = f"DEMO-{activity}"

    assortment = session.exec(
        select(Assortment).where(Assortment.tenant_id == tenant_id, Assortment.code == code)
    ).first()
    if assortment is None:
        assortment = Assortment(
            tenant_id=tenant_id, code=code, name=label,
            description="Conjunto de demonstração para homologação.",
            business_activity=activity, status=AssortmentStatusEnum.ACTIVE,
        )
        session.add(assortment)
        session.flush()
    else:
        assortment.business_activity = activity
        assortment.status = AssortmentStatusEnum.ACTIVE

    for context in DEMO_CONTEXTS:
        exists = session.exec(
            select(AssortmentScope).where(
                AssortmentScope.tenant_id == tenant_id,
                AssortmentScope.assortment_id == assortment.id,
                AssortmentScope.store_id == store_id,
                AssortmentScope.sales_context == context,
                AssortmentScope.channel_id.is_(None),
            )
        ).first()
        if exists is None:
            session.add(AssortmentScope(
                tenant_id=tenant_id, assortment_id=assortment.id,
                store_id=store_id, sales_context=context,
            ))

    for item in items:
        product = session.exec(
            select(Product).where(Product.tenant_id == tenant_id, Product.sku == item.sku)
        ).first()
        if product is None:
            product = Product(
                tenant_id=tenant_id, name=item.name, sku=item.sku,
                category_id=_category(session, tenant_id, item.category).id,
                item_type=ItemTypeEnum.PRODUCT, is_active=True, available_for_sale=True,
            )
            session.add(product)
            session.flush()

        price = session.exec(
            select(ProductPrice).where(
                ProductPrice.tenant_id == tenant_id,
                ProductPrice.product_id == product.id,
                ProductPrice.store_id == store_id,
            )
        ).first()
        if price is None:
            session.add(ProductPrice(
                tenant_id=tenant_id, product_id=product.id, store_id=store_id,
                cost_price=Decimal(item.price) / 2, sale_price=Decimal(item.price),
            ))

        balance = session.exec(
            select(InventoryBalance).where(
                InventoryBalance.tenant_id == tenant_id,
                InventoryBalance.product_id == product.id,
                InventoryBalance.store_id == store_id,
            )
        ).first()
        if balance is None:
            session.add(InventoryBalance(
                tenant_id=tenant_id, product_id=product.id, store_id=store_id,
                quantity=Decimal(item.quantity), minimum_stock=Decimal(5),
            ))

        linked = session.exec(
            select(AssortmentProduct).where(
                AssortmentProduct.tenant_id == tenant_id,
                AssortmentProduct.assortment_id == assortment.id,
                AssortmentProduct.product_id == product.id,
            )
        ).first()
        if linked is None:
            session.add(AssortmentProduct(
                tenant_id=tenant_id, assortment_id=assortment.id, product_id=product.id,
            ))

    session.commit()
    print(f"{label}: {len(items)} produto(s) publicados em {code} para {activity}.")


def purge(
    session: Session,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    assortment_code: str | None,
    skus: list[str],
) -> None:
    targets: list[Product] = []
    if assortment_code:
        assortment = session.exec(
            select(Assortment).where(
                Assortment.tenant_id == tenant_id, Assortment.code == assortment_code
            )
        ).first()
        if assortment is None:
            print(f"Sortimento '{assortment_code}' não existe neste tenant.")
            return
        product_ids = session.exec(
            select(AssortmentProduct.product_id).where(
                AssortmentProduct.tenant_id == tenant_id,
                AssortmentProduct.assortment_id == assortment.id,
            )
        ).all()
        targets = list(session.exec(
            select(Product).where(Product.tenant_id == tenant_id, Product.id.in_(product_ids))
        ).all()) if product_ids else []
    if skus:
        targets += list(session.exec(
            select(Product).where(Product.tenant_id == tenant_id, Product.sku.in_(skus))
        ).all())

    if not targets:
        print("Nenhum produto correspondente encontrado.")
        return

    removed, kept = 0, 0
    for product in targets:
        sold = session.exec(
            select(SaleItem).where(SaleItem.product_id == product.id).limit(1)
        ).first()
        if sold is not None:
            # Deleting it would break the lineage of a sale that really happened.
            product.is_active = False
            product.available_for_sale = False
            kept += 1
            print(f"  mantido e inativado (possui venda): {product.sku} · {product.name}")
            continue
        for link in session.exec(
            select(AssortmentProduct).where(AssortmentProduct.product_id == product.id)
        ).all():
            session.delete(link)
        for price in session.exec(
            select(ProductPrice).where(ProductPrice.product_id == product.id)
        ).all():
            session.delete(price)
        for balance in session.exec(
            select(InventoryBalance).where(InventoryBalance.product_id == product.id)
        ).all():
            session.delete(balance)
        session.delete(product)
        removed += 1
        print(f"  removido: {product.sku} · {product.name}")

    session.commit()
    print(f"Concluído: {removed} removido(s), {kept} inativado(s) por vínculo com venda.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seed", "purge"))
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--store", required=True)
    parser.add_argument("--activity", choices=tuple(CATALOGUES))
    parser.add_argument("--assortment-code")
    parser.add_argument("--sku", action="append", default=[])
    args = parser.parse_args()

    tenant_id, store_id = uuid.UUID(args.tenant), uuid.UUID(args.store)
    with Session(engine) as session:
        set_platform_db_context(session)
        if args.command == "seed":
            if not args.activity:
                parser.error("seed exige --activity")
            seed(session, tenant_id, store_id, args.activity)
        else:
            if not args.assortment_code and not args.sku:
                parser.error("purge exige --assortment-code ou ao menos um --sku")
            purge(session, tenant_id, store_id, args.assortment_code, args.sku)


if __name__ == "__main__":
    main()

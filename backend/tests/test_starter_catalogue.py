"""Management publishes the catalogue; the point of sale consumes it.

Reproduces the homologation tenant exactly as it was found in production: a
food service contract, and a LEGACY-DEFAULT assortment materialised by migration
069 that publishes hardware to the counter without declaring any activity. The
starter catalogue action has to leave that counter selling food.
"""

import os
import uuid

import httpx
import pytest
from sqlmodel import Session

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.assortment import (
    Assortment,
    AssortmentProduct,
    AssortmentScope,
    AssortmentStatusEnum,
    SalesContextEnum,
)
from app.models.identity import (
    TenantPhaseEnum,
    TenantProfile,
    TenantTypeEnum,
    User,
)
from app.models.platform import EntitlementStatusEnum, TenantCapability, TenantContract

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _homologation_tenant(client: httpx.AsyncClient, suffix: str) -> tuple[dict, dict]:
    """A food service tenant flagged INTERNAL/TEST, as the Owner console shows it."""
    tenant = (await client.post("/api/v1/identity/tenants", json={
        "name": f"Homologacao {suffix}", "slug": f"homologacao-{suffix}",
    })).json()
    store = (await client.post("/api/v1/identity/stores", json={
        "tenant_id": tenant["id"], "name": "Unidade Principal", "code": f"UP-{suffix}",
    })).json()

    with Session(engine) as db:
        set_platform_db_context(db)
        db.add(TenantCapability(
            tenant_id=uuid.UUID(tenant["id"]), key="counter_order",
            enabled=True, status=EntitlementStatusEnum.ACTIVE,
        ))
        db.add(TenantProfile(
            tenant_id=uuid.UUID(tenant["id"]),
            tenant_type=TenantTypeEnum.INTERNAL,
            lifecycle_phase=TenantPhaseEnum.TEST,
            trade_name=f"Homologacao {suffix}",
        ))
        author = User(email=f"starter-{suffix}@example.test", full_name="Homologação")
        db.add(author)
        db.flush()
        db.add(TenantContract(
            tenant_id=uuid.UUID(tenant["id"]),
            version=1, status="ACTIVE",
            limits={"users": 5},
            capability_keys=["counter_order"],
            activity_keys=["FOOD_SERVICE"],
            capability_entitlements=[{"key": "counter_order", "sources": ["PLAN"]}],
            limit_entitlements={"users": {"limit": 5, "sources": ["PLAN"]}},
            storage_entitlement={"measurement_status": "NOT_MEASURED"},
            schema_version=2,
            reason="Contrato de homologação food service.",
            created_by=author.id,
        ))
        db.commit()
    return tenant, store


async def _legacy_hardware(client: httpx.AsyncClient, headers: dict, tenant_id: str, store_id: str, suffix: str) -> str:
    """The unclassified legacy set, holding a product from another business model."""
    product = (await client.post("/api/v1/catalog/products", headers=headers, json={
        "name": "Disjuntor Bipolar 32A", "sku": f"LEGACY-DISJ-{suffix}",
    })).json()
    await client.post("/api/v1/catalog/prices", headers=headers, json={
        "product_id": product["id"], "store_id": store_id, "cost_price": 20, "sale_price": 44.5,
    })
    with Session(engine) as db:
        set_platform_db_context(db)
        assortment = Assortment(
            tenant_id=uuid.UUID(tenant_id), code="LEGACY-DEFAULT",
            name="Sortimento Legado — Balcão e Retirada",
            business_activity=None, status=AssortmentStatusEnum.ACTIVE,
        )
        db.add(assortment)
        db.flush()
        db.add(AssortmentScope(
            tenant_id=uuid.UUID(tenant_id), assortment_id=assortment.id,
            store_id=uuid.UUID(store_id), sales_context=SalesContextEnum.COUNTER,
        ))
        db.add(AssortmentProduct(
            tenant_id=uuid.UUID(tenant_id), assortment_id=assortment.id,
            product_id=uuid.UUID(product["id"]),
        ))
        db.commit()
    return product["id"]


@pytest.mark.asyncio
async def test_starter_catalogue_replaces_foreign_content_on_the_counter():
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant, store = await _homologation_tenant(client, suffix)
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}
        hardware_id = await _legacy_hardware(client, headers, tenant["id"], store["id"], suffix)

        before = (await client.get(
            "/api/v1/catalog/sellable-products?sales_context=COUNTER", headers=headers,
        )).json()["items"]
        assert hardware_id in {item["id"] for item in before}, "cenário precisa reproduzir o defeito"

        published = await client.post("/api/v1/catalog/starter-catalogue", headers=headers, json={
            "activity": "FOOD_SERVICE",
        })
        assert published.status_code == 200, published.text
        body = published.json()
        assert body["assortment_code"] == "STARTER-FOOD_SERVICE"
        assert "LEGACY-DEFAULT" in body["retired_assortments"]

        after = (await client.get(
            "/api/v1/catalog/sellable-products?sales_context=COUNTER", headers=headers,
        )).json()["items"]
        names = {item["name"] for item in after}
        assert hardware_id not in {item["id"] for item in after}, "material elétrico não pode continuar no balcão"
        assert "Hambúrguer Artesanal 180g" in names
        assert len(after) == body["products_total"]

        # The master catalogue keeps every product: nothing was destroyed.
        master = (await client.get(
            "/api/v1/catalog/sellable-products?master=true", headers=headers,
        )).json()["items"]
        assert hardware_id in {item["id"] for item in master}


@pytest.mark.asyncio
async def test_starter_catalogue_is_refused_for_a_live_customer():
    """A paying customer must never receive demonstration products."""
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant, store = await _homologation_tenant(client, suffix)
        with Session(engine) as db:
            set_platform_db_context(db)
            profile = db.get(TenantProfile, uuid.UUID(tenant["id"]))
            profile.tenant_type = TenantTypeEnum.CUSTOMER
            profile.lifecycle_phase = TenantPhaseEnum.PRODUCTION
            db.add(profile)
            db.commit()

        refused = await client.post(
            "/api/v1/catalog/starter-catalogue",
            headers={"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]},
            json={"activity": "FOOD_SERVICE"},
        )
        assert refused.status_code == 403

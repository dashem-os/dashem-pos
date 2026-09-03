"""The contracted business activity scopes what reaches the point of sale.

A tenant contracted exclusively as food service must never surface a hardware or
perfumery catalogue on its own POS. The activity belongs to the curated set, so the
guarantee is structural: content reaches the operator only through an assortment
whose activity matches the one being operated, or one deliberately left open to
every activity.
"""

import os
import uuid

import httpx
import pytest
from sqlmodel import Session

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.identity import User
from app.models.platform import EntitlementStatusEnum, TenantCapability, TenantContract

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _tenant_with_counter(client: httpx.AsyncClient, suffix: str) -> tuple[dict, dict]:
    tenant = (await client.post("/api/v1/identity/tenants", json={
        "name": f"Activity Scope {suffix}", "slug": f"activity-scope-{suffix}",
    })).json()
    store = (await client.post("/api/v1/identity/stores", json={
        "tenant_id": tenant["id"], "name": "Unidade", "code": f"UN-{suffix}",
    })).json()
    with Session(engine) as db:
        set_platform_db_context(db)
        db.add(TenantCapability(
            tenant_id=uuid.UUID(tenant["id"]), key="counter_order",
            enabled=True, status=EntitlementStatusEnum.ACTIVE,
        ))
        db.commit()
    return tenant, store


async def _product(client: httpx.AsyncClient, headers: dict, store_id: str, name: str, sku: str) -> dict:
    product = (await client.post("/api/v1/catalog/products", headers=headers, json={
        "name": name, "sku": sku,
    })).json()
    await client.post("/api/v1/catalog/prices", headers=headers, json={
        "product_id": product["id"], "store_id": store_id, "cost_price": 5, "sale_price": 10,
    })
    return product


@pytest.mark.asyncio
async def test_assortment_of_another_activity_never_reaches_the_pos():
    """A retail set stays out of a food service counter, and an open set still resolves."""
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant, store = await _tenant_with_counter(client, suffix)
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}

        food = await _product(client, headers, store["id"], "Hambúrguer Artesanal", f"FOOD-{suffix}")
        hardware = await _product(client, headers, store["id"], "Disjuntor Bipolar 32A", f"HARD-{suffix}")
        shared = await _product(client, headers, store["id"], "Água Mineral 500ml", f"ANY-{suffix}")

        for code, name, activity, product_id in (
            (f"FOOD-{suffix}", "Cardápio", "FOOD_SERVICE", food["id"]),
            (f"RET-{suffix}", "Loja de materiais", "RETAIL", hardware["id"]),
            (f"ANY-{suffix}", "Itens de conveniência", None, shared["id"]),
        ):
            payload = {
                "code": code, "name": name,
                "scopes": [{"store_id": store["id"], "sales_context": "COUNTER"}],
                "product_ids": [product_id],
            }
            if activity:
                payload["business_activity"] = activity
            created = await client.post("/api/v1/catalog/assortments", headers=headers, json=payload)
            assert created.status_code in (200, 201), created.text
            assert created.json()["business_activity"] == activity

        food_counter = (await client.get(
            "/api/v1/catalog/sellable-products?sales_context=COUNTER&activity=FOOD_SERVICE",
            headers=headers,
        )).json()["items"]
        visible = {item["id"] for item in food_counter}
        assert food["id"] in visible
        assert shared["id"] in visible, "um sortimento sem atividade vale para todas"
        assert hardware["id"] not in visible, "material elétrico não pode aparecer em operação food service"

        # Without an activity the projection keeps its previous behaviour, so
        # tenants that never curated by activity are not cut off.
        unscoped = (await client.get(
            "/api/v1/catalog/sellable-products?sales_context=COUNTER", headers=headers,
        )).json()["items"]
        assert {food["id"], hardware["id"], shared["id"]} <= {item["id"] for item in unscoped}


@pytest.mark.asyncio
async def test_uncontracted_activity_is_refused():
    """An operator cannot sell through an activity the tenant never contracted."""
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant, store = await _tenant_with_counter(client, suffix)
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}

        with Session(engine) as db:
            set_platform_db_context(db)
            author = User(email=f"contract-{suffix}@example.test", full_name="Homologação")
            db.add(author)
            db.flush()
            db.add(TenantContract(
                tenant_id=uuid.UUID(tenant["id"]),
                version=1,
                status="ACTIVE",
                limits={"users": 5},
                capability_keys=["counter_order"],
                activity_keys=["FOOD_SERVICE"],
                capability_entitlements=[{"key": "counter_order", "sources": ["PLAN"]}],
                limit_entitlements={"users": {"limit": 5, "sources": ["PLAN"]}},
                storage_entitlement={"measurement_status": "NOT_MEASURED"},
                schema_version=2,
                reason="Contrato de homologação exclusivamente food service.",
                created_by=author.id,
            ))
            db.commit()

        refused = await client.get(
            "/api/v1/catalog/sellable-products?sales_context=COUNTER&activity=RETAIL",
            headers=headers,
        )
        assert refused.status_code == 403
        assert "RETAIL" in refused.json()["detail"]

        allowed = await client.get(
            "/api/v1/catalog/sellable-products?sales_context=COUNTER&activity=FOOD_SERVICE",
            headers=headers,
        )
        assert allowed.status_code == 200

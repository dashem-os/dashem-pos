import os
import uuid

import httpx
import pytest
from sqlmodel import Session

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.platform import TenantCapability, EntitlementStatusEnum


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


@pytest.mark.asyncio
async def test_s4_catalog_projection_pagination_stock_policy_and_composition():
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={"name": f"S4 {suffix}", "slug": f"s4-{suffix}"})).json()
        store = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "Matriz", "code": f"S4-{suffix}"})).json()
        with Session(engine) as db:
            set_platform_db_context(db)
            db.add(TenantCapability(tenant_id=uuid.UUID(tenant["id"]), key="counter_order", enabled=True, status=EntitlementStatusEnum.ACTIVE))
            db.commit()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}

        parent = (await client.post("/api/v1/catalog/categories", headers=headers, json={"name": "Alimentação", "slug": f"alimentacao-{suffix}"})).json()
        category_response = await client.post("/api/v1/catalog/categories", headers=headers, json={"name": "Lanches", "slug": f"lanches-{suffix}", "parent_id": parent["id"]})
        assert category_response.status_code == 200
        category = category_response.json()
        assert category["parent_id"] == parent["id"]

        product_response = await client.post("/api/v1/catalog/products", headers=headers, json={
            "name": "Hambúrguer S4", "sku": f"BURGER-{suffix}", "barcode": f"789{suffix}",
            "category_id": category["id"], "unit": "UN", "image_url": "https://example.test/burger.png",
            "production_destination": "COZINHA", "allows_multi_flavor": False,
        })
        assert product_response.status_code == 200
        product = product_response.json()

        first_price = await client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": product["id"], "store_id": store["id"], "cost_price": 10, "sale_price": 25,
        })
        assert first_price.status_code == 200
        second_price = await client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": product["id"], "store_id": store["id"], "cost_price": 12, "sale_price": 30,
        })
        assert second_price.status_code == 200
        prices = (await client.get(f"/api/v1/catalog/prices?store_id={store['id']}&product_id={product['id']}", headers=headers)).json()
        assert len(prices) == 1
        assert float(prices[0]["sale_price"]) == 30

        stock = await client.post("/api/v1/inventory/adjust", headers=headers, json={
            "store_id": store["id"], "product_id": product["id"], "actor_id": str(uuid.uuid4()),
            "movement_type": "PURCHASE", "quantity": 3, "reason": "Carga S4",
        })
        assert stock.status_code == 200
        minimum = await client.put("/api/v1/inventory/minimum", headers=headers, json={
            "store_id": store["id"], "product_id": product["id"], "minimum_stock": 5,
        })
        assert minimum.status_code == 200

        assortment_res = await client.post("/api/v1/catalog/assortments", headers=headers, json={
            "code": f"ASSORT-{suffix}",
            "name": "Sortimento Balcão",
            "scopes": [{"store_id": store["id"], "sales_context": "COUNTER"}],
            "product_ids": [product["id"]],
        })
        assert assortment_res.status_code == 201

        projection_response = await client.get(
            "/api/v1/catalog/sellable-products?sales_context=COUNTER&page=1&page_size=1&search=BURGER",
            headers=headers,
        )
        assert projection_response.status_code == 200, projection_response.text
        projection = projection_response.json()
        assert projection["total"] == 1
        assert projection["page_size"] == 1
        item = projection["items"][0]
        assert item["category_name"] == "Lanches"
        assert float(item["sale_price"]) == 30
        assert float(item["cost_price"]) == 12
        assert float(item["margin_percent"]) == 60
        assert float(item["quantity"]) == 3
        assert float(item["minimum_stock"]) == 5
        assert item["is_low_stock"] is True
        assert item["production_destination"] == "COZINHA"

        group_response = await client.post("/api/v1/catalog/modifier-groups", headers=headers, json={
            "name": f"Ponto {suffix}", "minimum_choices": 1, "maximum_choices": 1, "is_required": True,
        })
        assert group_response.status_code == 201
        group = group_response.json()
        modifier_response = await client.post("/api/v1/catalog/modifiers", headers=headers, json={
            "group_id": group["id"], "name": "Bem passado", "price_delta": 0,
        })
        assert modifier_response.status_code == 201
        link_response = await client.post(f"/api/v1/catalog/products/{product['id']}/modifier-groups", headers=headers, json={"group_id": group["id"], "position": 1})
        assert link_response.status_code == 201

        combo_product = (await client.post("/api/v1/catalog/products", headers=headers, json={"name": "Combo S4", "sku": f"COMBO-{suffix}"})).json()
        combo_response = await client.post("/api/v1/catalog/combos", headers=headers, json={
            "product_id": combo_product["id"], "name": "Combo Hambúrguer", "items": [{"product_id": product["id"], "quantity": 1}],
        })
        assert combo_response.status_code == 201

        archived = await client.delete(f"/api/v1/catalog/products/{product['id']}", headers=headers)
        assert archived.status_code == 200
        hidden = await client.get("/api/v1/catalog/sellable-products?sales_context=COUNTER&search=BURGER", headers=headers)
        assert hidden.status_code == 200
        assert hidden.json()["total"] == 0


@pytest.mark.asyncio
async def test_s4_rejects_cross_store_stock_and_price_writes():
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={"name": f"Scope {suffix}", "slug": f"scope-{suffix}"})).json()
        store_a = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "A", "code": f"A-{suffix}"})).json()
        store_b = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "B", "code": f"B-{suffix}"})).json()
        with Session(engine) as db:
            set_platform_db_context(db)
            db.add(TenantCapability(tenant_id=uuid.UUID(tenant["id"]), key="counter_order", enabled=True, status=EntitlementStatusEnum.ACTIVE))
            db.commit()
        headers_a = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store_a["id"]}
        product = (await client.post("/api/v1/catalog/products", headers=headers_a, json={"name": "Scoped", "sku": f"SCOPED-{suffix}"})).json()
        price = await client.post("/api/v1/catalog/prices", headers=headers_a, json={"product_id": product["id"], "store_id": store_b["id"], "cost_price": 1, "sale_price": 2})
        assert price.status_code == 403
        stock = await client.put("/api/v1/inventory/minimum", headers=headers_a, json={"store_id": store_b["id"], "product_id": product["id"], "minimum_stock": 1})
        assert stock.status_code == 403

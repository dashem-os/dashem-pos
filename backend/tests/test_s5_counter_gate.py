import os
import uuid

import httpx
import pytest


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


@pytest.mark.asyncio
async def test_s5_counter_operation_is_contextual_recoverable_and_measured():
    suffix = uuid.uuid4().hex[:8]
    seller_id = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={"name": f"Counter {suffix}", "slug": f"counter-{suffix}"})).json()
        store = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "Balcão", "code": f"C-{suffix}"})).json()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}
        register_response = await client.post("/api/v1/cash/registers", headers=headers, json={"store_id": store["id"], "name": "Terminal 1", "code": f"T-{suffix}"})
        assert register_response.status_code == 200
        register = register_response.json()
        product = (await client.post("/api/v1/catalog/products", headers=headers, json={"name": "Counter Product", "sku": f"CP-{suffix}"})).json()
        await client.post("/api/v1/catalog/prices", headers=headers, json={"product_id": product["id"], "store_id": store["id"], "cost_price": 5, "sale_price": 10})

        payload = {
            "store_id": store["id"], "register_id": register["id"],
            "seller_id": seller_id, "operation_mode": "TAKEAWAY",
        }
        first = await client.post("/api/v1/sales", headers=headers, json=payload)
        assert first.status_code == 200, first.text
        sale = first.json()
        assert sale["operation_mode"] == "TAKEAWAY"
        assert sale["register_id"] == register["id"]
        assert sale["seller_id"] == seller_id
        assert sale["operator_action_count"] == 0

        retry = await client.post("/api/v1/sales", headers=headers, json=payload)
        assert retry.status_code == 200
        assert retry.json()["id"] == sale["id"]

        item = await client.post(f"/api/v1/sales/{sale['id']}/items", headers=headers, json={"product_id": product["id"], "quantity": 1})
        assert item.status_code == 200
        active = await client.get(
            "/api/v1/sales/active",
            headers=headers,
            params={"store_id": store["id"], "register_id": register["id"], "seller_id": seller_id},
        )
        assert active.status_code == 200
        recovered = active.json()
        assert recovered["id"] == sale["id"]
        assert len(recovered["items"]) == 1
        assert recovered["operator_action_count"] == 1
        assert recovered["last_activity_at"] >= recovered["created_at"]

        canceled = await client.post(f"/api/v1/sales/{sale['id']}/cancel", headers=headers, json={"actor_id": seller_id, "reason": "Encerrar teste"})
        assert canceled.status_code == 200
        replacement = await client.post("/api/v1/sales", headers=headers, json={**payload, "operation_mode": "COUNTER"})
        assert replacement.status_code == 200
        assert replacement.json()["id"] != sale["id"]
        assert replacement.json()["operation_mode"] == "COUNTER"


@pytest.mark.asyncio
async def test_s5_rejects_register_from_another_store():
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={"name": f"Terminal {suffix}", "slug": f"terminal-{suffix}"})).json()
        store_a = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "A", "code": f"A-{suffix}"})).json()
        store_b = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "B", "code": f"B-{suffix}"})).json()
        headers_a = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store_a["id"]}
        headers_b = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store_b["id"]}
        register_b = (await client.post("/api/v1/cash/registers", headers=headers_b, json={"store_id": store_b["id"], "name": "B", "code": f"TB-{suffix}"})).json()
        invalid = await client.post("/api/v1/sales", headers=headers_a, json={
            "store_id": store_a["id"], "register_id": register_b["id"], "seller_id": str(uuid.uuid4()),
        })
        assert invalid.status_code == 403

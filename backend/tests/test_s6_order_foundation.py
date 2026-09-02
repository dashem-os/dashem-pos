import os
import uuid

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.reliability import OutboxEvent


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


@pytest.mark.asyncio
async def test_s6_order_stays_open_accepts_idempotent_launches_and_snapshots_modifiers():
    suffix = uuid.uuid4().hex[:8]
    actor_id = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={"name": f"Order {suffix}", "slug": f"order-{suffix}"})).json()
        store = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "Matriz", "code": f"O-{suffix}"})).json()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}
        product = (await client.post("/api/v1/catalog/products", headers=headers, json={
            "name": "Pizza S6", "sku": f"PIZZA-{suffix}", "unit": "UN",
            "requires_fulfillment": True, "production_destination": "COZINHA",
        })).json()
        await client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": product["id"], "store_id": store["id"], "cost_price": 10, "sale_price": 25,
        })
        group = (await client.post("/api/v1/catalog/modifier-groups", headers=headers, json={
            "name": f"Borda {suffix}", "minimum_choices": 1, "maximum_choices": 1, "is_required": True,
        })).json()
        modifier = (await client.post("/api/v1/catalog/modifiers", headers=headers, json={
            "group_id": group["id"], "name": "Catupiry", "price_delta": 3,
        })).json()
        await client.post(f"/api/v1/catalog/products/{product['id']}/modifier-groups", headers=headers, json={"group_id": group["id"], "position": 1})

        await client.post("/api/v1/catalog/assortments", headers=headers, json={
            "code": f"ASSORT-O-{suffix}",
            "name": "Sortimento Retirada",
            "scopes": [{"store_id": store["id"], "sales_context": "TAKEAWAY"}],
            "product_ids": [product["id"]],
        })

        order_key = f"order-open-{suffix}"
        order_payload = {
            "store_id": store["id"], "origin": "POS", "fulfillment": "TAKEAWAY",
            "actor_id": actor_id, "notes": "Pedido aberto",
        }
        created = await client.post("/api/v1/orders", headers={**headers, "Idempotency-Key": order_key}, json=order_payload)
        assert created.status_code == 200, created.text
        order = created.json()
        assert order["status"] == "OPEN"
        assert order["items"] == []

        create_retry = await client.post("/api/v1/orders", headers={**headers, "Idempotency-Key": order_key}, json=order_payload)
        assert create_retry.status_code == 200
        assert create_retry.json()["id"] == order["id"]
        create_mismatch = await client.post("/api/v1/orders", headers={**headers, "Idempotency-Key": order_key}, json={**order_payload, "fulfillment": "COUNTER"})
        assert create_mismatch.status_code == 409

        item_key = f"add-item-{suffix}"
        item_payload = {"product_id": product["id"], "quantity": 1, "modifier_ids": [modifier["id"]], "actor_id": actor_id}
        added = await client.post(f"/api/v1/orders/{order['id']}/items", headers={**headers, "Idempotency-Key": item_key}, json=item_payload)
        assert added.status_code == 200, added.text
        item = added.json()
        assert float(item["unit_price"]) == 28
        assert item["production_state"] == "PENDING"
        assert item["production_destination"] == "COZINHA"
        assert item["modifier_snapshot"][0]["modifier_name"] == "Catupiry"

        add_retry = await client.post(f"/api/v1/orders/{order['id']}/items", headers={**headers, "Idempotency-Key": item_key}, json=item_payload)
        assert add_retry.status_code == 200
        assert add_retry.json()["id"] == item["id"]
        mismatched_retry = await client.post(f"/api/v1/orders/{order['id']}/items", headers={**headers, "Idempotency-Key": item_key}, json={**item_payload, "quantity": 2})
        assert mismatched_retry.status_code == 409

        second = await client.post(f"/api/v1/orders/{order['id']}/items", headers={**headers, "Idempotency-Key": f"add-second-{suffix}"}, json=item_payload)
        assert second.status_code == 200
        assert second.json()["id"] != item["id"]

        update_key = f"update-item-{suffix}"
        update_payload = {"quantity": 2, "notes": "Sem cortar", "actor_id": actor_id}
        updated = await client.patch(f"/api/v1/orders/{order['id']}/items/{item['id']}", headers={**headers, "Idempotency-Key": update_key}, json=update_payload)
        assert updated.status_code == 200
        assert float(updated.json()["quantity"]) == 2
        update_retry = await client.patch(f"/api/v1/orders/{order['id']}/items/{item['id']}", headers={**headers, "Idempotency-Key": update_key}, json=update_payload)
        assert update_retry.status_code == 200
        assert update_retry.json()["id"] == item["id"]

        cancel_key = f"cancel-item-{suffix}"
        cancel_payload = {"reason": "Cliente desistiu do item", "actor_id": actor_id}
        canceled = await client.post(f"/api/v1/orders/{order['id']}/items/{item['id']}/cancel", headers={**headers, "Idempotency-Key": cancel_key}, json=cancel_payload)
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "CANCELED"
        cancel_retry = await client.post(f"/api/v1/orders/{order['id']}/items/{item['id']}/cancel", headers={**headers, "Idempotency-Key": cancel_key}, json=cancel_payload)
        assert cancel_retry.status_code == 200
        assert cancel_retry.json()["status"] == "CANCELED"

        recovered = await client.get(f"/api/v1/orders/{order['id']}", headers=headers)
        assert recovered.status_code == 200
        assert recovered.json()["status"] == "OPEN"
        assert len(recovered.json()["items"]) == 2

    with Session(engine) as session:
        set_platform_db_context(session)
        events = session.exec(select(OutboxEvent).where(
            OutboxEvent.aggregate_type == "order",
            OutboxEvent.aggregate_id == order["id"],
        )).all()
        types = [event.event_type for event in events]
        assert types.count("order.created") == 1
        assert types.count("order.item.added") == 2
        assert types.count("order.item.updated") == 1
        assert types.count("order.item.canceled") == 1


@pytest.mark.asyncio
async def test_s6_preserves_tenant_and_store_isolation():
    suffix = uuid.uuid4().hex[:8]
    actor_id = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant_a = (await client.post("/api/v1/identity/tenants", json={"name": "OA", "slug": f"oa-{suffix}"})).json()
        store_a = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant_a["id"], "name": "A", "code": f"OA-{suffix}"})).json()
        tenant_b = (await client.post("/api/v1/identity/tenants", json={"name": "OB", "slug": f"ob-{suffix}"})).json()
        store_b = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant_b["id"], "name": "B", "code": f"OB-{suffix}"})).json()
        headers_a = {"X-Tenant-ID": tenant_a["id"], "X-Store-ID": store_a["id"], "Idempotency-Key": f"isolation-{suffix}"}
        order = (await client.post("/api/v1/orders", headers=headers_a, json={"store_id": store_a["id"], "actor_id": actor_id})).json()
        headers_b = {"X-Tenant-ID": tenant_b["id"], "X-Store-ID": store_b["id"]}
        hidden = await client.get(f"/api/v1/orders/{order['id']}", headers=headers_b)
        assert hidden.status_code == 404

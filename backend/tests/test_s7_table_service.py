import asyncio
import os
import uuid

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.order import Order
from app.models.reliability import OutboxEvent
from app.models.table_service import ServiceTable, TableSession


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _context(client: httpx.AsyncClient, prefix: str):
    suffix = uuid.uuid4().hex[:8]
    tenant = (await client.post("/api/v1/identity/tenants", json={
        "name": f"{prefix} {suffix}", "slug": f"{prefix.lower()}-{suffix}",
    })).json()
    store = (await client.post("/api/v1/identity/stores", json={
        "tenant_id": tenant["id"], "name": "Matriz", "code": f"{prefix[:3].upper()}-{suffix}",
    })).json()
    return tenant, store, {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}


@pytest.mark.asyncio
async def test_s7_opens_table_idempotently_supports_multiple_tabs_and_consolidates_server_side():
    actor = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant, store, headers = await _context(client, "Table")
        table = (await client.post("/api/v1/tables", headers={**headers, "Idempotency-Key": f"table-{uuid.uuid4()}"}, json={
            "store_id": store["id"], "code": "M-01", "name": "Mesa 01",
            "capacity": 4, "area": "Salão", "actor_id": actor,
        })).json()
        assert table["status"] == "AVAILABLE"

        key = f"open-table-{uuid.uuid4()}"
        payload = {"store_id": store["id"], "service_table_id": table["id"], "actor_id": actor}
        opened = await client.post("/api/v1/tables/sessions", headers={**headers, "Idempotency-Key": key}, json=payload)
        assert opened.status_code == 200, opened.text
        table_session = opened.json()
        assert table_session["kind"] == "TABLE"
        assert table_session["status"] == "OPEN"
        assert len(table_session["orders"]) == 1
        assert table_session["service_table"]["status"] == "OCCUPIED"

        retry = await client.post("/api/v1/tables/sessions", headers={**headers, "Idempotency-Key": key}, json=payload)
        assert retry.status_code == 200
        assert retry.json()["id"] == table_session["id"]
        mismatch = await client.post("/api/v1/tables/sessions", headers={**headers, "Idempotency-Key": key}, json={**payload, "display_label": "Outro"})
        assert mismatch.status_code == 409
        duplicate = await client.post("/api/v1/tables/sessions", headers={**headers, "Idempotency-Key": f"different-{uuid.uuid4()}"}, json=payload)
        assert duplicate.status_code == 409

        product = (await client.post("/api/v1/catalog/products", headers=headers, json={
            "name": "Refeição S7", "sku": f"MEAL-{uuid.uuid4().hex[:8]}", "unit": "UN",
        })).json()
        await client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": product["id"], "store_id": store["id"], "cost_price": 8, "sale_price": 21.5,
        })
        first_order = table_session["orders"][0]
        added = await client.post(f"/api/v1/orders/{first_order['id']}/items", headers={
            **headers, "Idempotency-Key": f"item-{uuid.uuid4()}",
        }, json={"product_id": product["id"], "quantity": 2, "actor_id": actor})
        assert added.status_code == 200, added.text

        second_order = await client.post(f"/api/v1/tables/sessions/{table_session['id']}/orders", headers={
            **headers, "Idempotency-Key": f"second-order-{uuid.uuid4()}",
        }, json={"display_reference": "Comanda Paulo", "actor_id": actor})
        assert second_order.status_code == 200, second_order.text
        assert second_order.json()["table_session_id"] == table_session["id"]

        detail = await client.get(f"/api/v1/tables/sessions/{table_session['id']}", headers=headers)
        assert detail.status_code == 200
        detail_body = detail.json()
        assert detail_body["status"] == "IN_SERVICE"
        assert detail_body["order_count"] == 2
        assert detail_body["active_item_count"] == 1
        assert float(detail_body["consolidated_total"]) == 43
        assert detail_body["version"] > table_session["version"]

        projection = (await client.get("/api/v1/tables", headers=headers)).json()
        selected = next(item for item in projection if item["id"] == table["id"])
        assert selected["status"] == "OCCUPIED"
        assert selected["order_count"] == 2
        assert selected["item_count"] == 1
        assert float(selected["consolidated_total"]) == 43

        blocked_close = await client.post(f"/api/v1/tables/sessions/{table_session['id']}/close", headers={
            **headers, "Idempotency-Key": f"close-{uuid.uuid4()}",
        }, json={"expected_version": detail_body["version"], "reason": "Tentativa antes do financeiro", "actor_id": actor})
        assert blocked_close.status_code == 409

        individual = await client.post("/api/v1/tables/sessions", headers={
            **headers, "Idempotency-Key": f"individual-{uuid.uuid4()}",
        }, json={"store_id": store["id"], "display_label": "Comanda 42", "actor_id": actor})
        assert individual.status_code == 200
        assert individual.json()["kind"] == "INDIVIDUAL_TAB"
        assert individual.json()["service_table_id"] is None
        active_sessions = (await client.get("/api/v1/tables/sessions", headers=headers)).json()
        assert any(item["id"] == individual.json()["id"] for item in active_sessions)

    with Session(engine) as db:
        set_platform_db_context(db)
        persisted = db.get(TableSession, uuid.UUID(table_session["id"]))
        linked_orders = db.exec(select(Order).where(Order.table_session_id == persisted.id)).all()
        events = db.exec(select(OutboxEvent).where(
            OutboxEvent.aggregate_type == "table_session",
            OutboxEvent.aggregate_id == table_session["id"],
        )).all()
        assert persisted is not None
        assert len(linked_orders) == 2
        assert {event.event_type for event in events} >= {
            "table_session.opened", "table_session.item_added", "table_session.order_added",
        }


@pytest.mark.asyncio
async def test_s7_concurrent_opening_has_one_winner_and_empty_close_is_explicit():
    actor = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        _tenant, store, headers = await _context(client, "Race")
        table = (await client.post("/api/v1/tables", headers={**headers, "Idempotency-Key": f"table-{uuid.uuid4()}"}, json={
            "store_id": store["id"], "code": "RACE-01", "name": "Mesa concorrente",
            "capacity": 2, "actor_id": actor,
        })).json()

        async def open_once(key: str):
            return await client.post("/api/v1/tables/sessions", headers={**headers, "Idempotency-Key": key}, json={
                "store_id": store["id"], "service_table_id": table["id"], "actor_id": actor,
            })

        first, second = await asyncio.gather(
            open_once(f"race-a-{uuid.uuid4()}"), open_once(f"race-b-{uuid.uuid4()}"),
        )
        assert sorted([first.status_code, second.status_code]) == [200, 409]
        winner = first.json() if first.status_code == 200 else second.json()

        stale = await client.post(f"/api/v1/tables/sessions/{winner['id']}/close", headers={
            **headers, "Idempotency-Key": f"stale-{uuid.uuid4()}",
        }, json={"expected_version": winner["version"] + 1, "reason": "Versão desatualizada", "actor_id": actor})
        assert stale.status_code == 409

        close_key = f"close-empty-{uuid.uuid4()}"
        close_payload = {"expected_version": winner["version"], "reason": "Atendimento não iniciado", "actor_id": actor}
        closed = await client.post(f"/api/v1/tables/sessions/{winner['id']}/close", headers={
            **headers, "Idempotency-Key": close_key,
        }, json=close_payload)
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "CLOSED"
        assert closed.json()["service_table"]["status"] == "AVAILABLE"
        close_retry = await client.post(f"/api/v1/tables/sessions/{winner['id']}/close", headers={
            **headers, "Idempotency-Key": close_key,
        }, json=close_payload)
        assert close_retry.status_code == 200
        assert close_retry.json()["id"] == winner["id"]


@pytest.mark.asyncio
async def test_s7_tenant_and_store_isolation_hides_tables_and_sessions():
    actor = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        _tenant_a, store_a, headers_a = await _context(client, "IsoA")
        _tenant_b, _store_b, headers_b = await _context(client, "IsoB")
        table = (await client.post("/api/v1/tables", headers={**headers_a, "Idempotency-Key": f"table-{uuid.uuid4()}"}, json={
            "store_id": store_a["id"], "code": "ISO-01", "name": "Mesa A", "capacity": 2, "actor_id": actor,
        })).json()
        opened = (await client.post("/api/v1/tables/sessions", headers={
            **headers_a, "Idempotency-Key": f"iso-{uuid.uuid4()}",
        }, json={"store_id": store_a["id"], "service_table_id": table["id"], "actor_id": actor})).json()

        assert all(item["id"] != table["id"] for item in (await client.get("/api/v1/tables", headers=headers_b)).json())
        hidden = await client.get(f"/api/v1/tables/sessions/{opened['id']}", headers=headers_b)
        assert hidden.status_code == 404

    with Session(engine) as db:
        set_platform_db_context(db)
        assert db.get(ServiceTable, uuid.UUID(table["id"])) is not None

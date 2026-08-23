import asyncio
import os
import uuid

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.negotiation import CheckoutNegotiation, PaymentAllocation, PaymentIntent
from app.models.payment import CashMovement, Payment
from app.models.sale import Sale
from app.models.table_service import ServiceTable, TableSession


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _context(client: httpx.AsyncClient, prefix: str):
    suffix = uuid.uuid4().hex[:8]
    actor = str(uuid.uuid4())
    tenant = (await client.post("/api/v1/identity/tenants", json={
        "name": f"{prefix} {suffix}", "slug": f"{prefix.lower()}-{suffix}",
    })).json()
    store = (await client.post("/api/v1/identity/stores", json={
        "tenant_id": tenant["id"], "name": "Matriz", "code": f"{prefix[:3].upper()}-{suffix}",
    })).json()
    headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}
    table = (await client.post("/api/v1/tables", headers={**headers, "Idempotency-Key": f"table-{suffix}"}, json={
        "store_id": store["id"], "code": "M-01", "name": "Mesa 01", "capacity": 4, "actor_id": actor,
    })).json()
    table_session = (await client.post("/api/v1/tables/sessions", headers={**headers, "Idempotency-Key": f"session-{suffix}"}, json={
        "store_id": store["id"], "service_table_id": table["id"], "actor_id": actor,
    })).json()
    order_id = table_session["orders"][0]["id"]
    for index, price in enumerate((10, 20, 34.9), start=1):
        product = (await client.post("/api/v1/catalog/products", headers=headers, json={
            "name": f"Item {index}", "sku": f"S8-{suffix}-{index}", "unit": "UN", "tracks_inventory": False,
        })).json()
        await client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": product["id"], "store_id": store["id"], "cost_price": 1, "sale_price": price,
        })
        launched = await client.post(f"/api/v1/orders/{order_id}/items", headers={
            **headers, "Idempotency-Key": f"item-{suffix}-{index}",
        }, json={"product_id": product["id"], "quantity": 1, "actor_id": actor})
        assert launched.status_code == 200, launched.text
    register = (await client.post("/api/v1/cash/registers", headers=headers, json={
        "store_id": store["id"], "name": "Caixa S8", "code": f"CX-{suffix}",
    })).json()
    cash_session = (await client.post("/api/v1/cash/sessions/open", headers=headers, json={
        "store_id": store["id"], "register_id": register["id"],
        "operator_id": actor, "opening_balance": 100,
    })).json()
    return tenant, store, headers, actor, table, table_session, order_id, cash_session


async def _intent(client, headers, negotiation_id, actor, method, amount, suffix, cash_session_id=None):
    response = await client.post(f"/api/v1/negotiations/{negotiation_id}/intents", headers={
        **headers, "Idempotency-Key": f"intent-{suffix}",
    }, json={
        "method": method, "amount": amount, "cash_session_id": cash_session_id,
        "tendered_amount": amount if method == "CASH" else None, "actor_id": actor,
    })
    assert response.status_code == 200, response.text
    return response.json(), response.json()["intents"][-1]


@pytest.mark.asyncio
async def test_s8_split_failure_retry_and_explicit_finalization_are_authoritative():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant, store, headers, actor, table, table_session, _order_id, cash = await _context(client, "Split")
        open_key = f"neg-{uuid.uuid4()}"
        payload = {"store_id": store["id"], "table_session_id": table_session["id"], "actor_id": actor}
        opened = await client.post("/api/v1/negotiations", headers={**headers, "Idempotency-Key": open_key}, json=payload)
        assert opened.status_code == 200, opened.text
        negotiation = opened.json()
        assert float(negotiation["total_due"]) == 64.9
        assert float(negotiation["remaining_amount"]) == 64.9
        retry = await client.post("/api/v1/negotiations", headers={**headers, "Idempotency-Key": open_key}, json=payload)
        assert retry.status_code == 200
        assert retry.json()["id"] == negotiation["id"]
        mismatch = await client.post("/api/v1/negotiations", headers={**headers, "Idempotency-Key": open_key}, json={**payload, "order_ids": [str(uuid.uuid4())]})
        assert mismatch.status_code == 409

        first_projection, first = await _intent(client, headers, negotiation["id"], actor, "CASH", 10, uuid.uuid4(), cash["id"])
        confirmed_first = await client.post(f"/api/v1/negotiations/intents/{first['id']}/confirm", headers={
            **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
        }, json={"actor_id": actor})
        assert confirmed_first.status_code == 200, confirmed_first.text
        assert float(confirmed_first.json()["remaining_amount"]) == 54.9

        _, second = await _intent(client, headers, negotiation["id"], actor, "PIX", 20, uuid.uuid4())
        second_key = f"confirm-{uuid.uuid4()}"
        confirmed_second = await client.post(f"/api/v1/negotiations/intents/{second['id']}/confirm", headers={
            **headers, "Idempotency-Key": second_key,
        }, json={"actor_id": actor})
        assert confirmed_second.status_code == 200
        partial = confirmed_second.json()
        assert partial["status"] == "PARTIALLY_COVERED"
        assert float(partial["confirmed_amount"]) == 30
        assert float(partial["remaining_amount"]) == 34.9
        confirm_retry = await client.post(f"/api/v1/negotiations/intents/{second['id']}/confirm", headers={
            **headers, "Idempotency-Key": second_key,
        }, json={"actor_id": actor})
        assert confirm_retry.status_code == 200
        assert float(confirm_retry.json()["confirmed_amount"]) == 30

        _, failed_intent = await _intent(client, headers, negotiation["id"], actor, "DEBIT_CARD", 34.9, uuid.uuid4())
        failed = await client.post(f"/api/v1/negotiations/intents/{failed_intent['id']}/fail", headers={
            **headers, "Idempotency-Key": f"fail-{uuid.uuid4()}",
        }, json={"actor_id": actor, "failure_code": "DECLINED", "reason": "Transação recusada"})
        assert failed.status_code == 200
        assert float(failed.json()["confirmed_amount"]) == 30
        assert float(failed.json()["failed_amount"]) == 34.9
        assert float(failed.json()["remaining_amount"]) == 34.9

        _, replacement = await _intent(client, headers, negotiation["id"], actor, "CREDIT_CARD", 34.9, uuid.uuid4())
        covered = await client.post(f"/api/v1/negotiations/intents/{replacement['id']}/confirm", headers={
            **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
        }, json={"actor_id": actor})
        assert covered.status_code == 200
        covered_body = covered.json()
        assert covered_body["status"] == "COVERED"
        assert float(covered_body["remaining_amount"]) == 0

        table_before_finalize = (await client.get("/api/v1/tables", headers=headers)).json()
        table_projection = next(item for item in table_before_finalize if item["id"] == table["id"])
        assert table_projection["status"] == "OCCUPIED"
        finalize_key = f"finalize-{uuid.uuid4()}"
        finalize_payload = {"expected_version": covered_body["version"], "actor_id": actor}
        finalized = await client.post(f"/api/v1/negotiations/{negotiation['id']}/finalize", headers={
            **headers, "Idempotency-Key": finalize_key,
        }, json=finalize_payload)
        assert finalized.status_code == 200, finalized.text
        assert finalized.json()["status"] == "FINALIZED"
        assert finalized.json()["sale_id"]
        final_retry = await client.post(f"/api/v1/negotiations/{negotiation['id']}/finalize", headers={
            **headers, "Idempotency-Key": finalize_key,
        }, json=finalize_payload)
        assert final_retry.status_code == 200
        assert final_retry.json()["sale_id"] == finalized.json()["sale_id"]
        assert next(item for item in (await client.get("/api/v1/tables", headers=headers)).json() if item["id"] == table["id"])["status"] == "AVAILABLE"

        foreign_tenant, foreign_store, foreign_headers, *_ = await _context(client, "Foreign")
        hidden = await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=foreign_headers)
        assert hidden.status_code == 404

    with Session(engine) as db:
        set_platform_db_context(db)
        negotiation_id = uuid.UUID(negotiation["id"])
        persisted = db.get(CheckoutNegotiation, negotiation_id)
        intents = db.exec(select(PaymentIntent).where(PaymentIntent.negotiation_id == negotiation_id)).all()
        allocations = db.exec(select(PaymentAllocation).where(PaymentAllocation.negotiation_id == negotiation_id)).all()
        sales = db.exec(select(Sale).where(Sale.id == persisted.sale_id)).all()
        payments = db.exec(select(Payment).where(Payment.sale_id == persisted.sale_id)).all()
        cash_intent = next(intent for intent in intents if intent.method.value == "CASH")
        movements = db.exec(select(CashMovement).where(CashMovement.id == cash_intent.cash_movement_id)).all()
        assert len(intents) == 4
        assert len(allocations) == 4
        assert len(sales) == 1
        assert len(payments) == 3
        assert len(movements) == 1
        assert db.get(TableSession, uuid.UUID(table_session["id"])).status.value == "CLOSED"
        assert db.get(ServiceTable, uuid.UUID(table["id"])).status.value == "AVAILABLE"


@pytest.mark.asyncio
async def test_s8_concurrent_intents_cannot_overbook_and_consumption_change_invalidates_snapshot():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        _tenant, store, headers, actor, _table, table_session, order_id, _cash = await _context(client, "RacePay")
        opened = (await client.post("/api/v1/negotiations", headers={
            **headers, "Idempotency-Key": f"neg-{uuid.uuid4()}",
        }, json={"store_id": store["id"], "table_session_id": table_session["id"], "actor_id": actor})).json()

        async def reserve(key):
            return await client.post(f"/api/v1/negotiations/{opened['id']}/intents", headers={
                **headers, "Idempotency-Key": key,
            }, json={"method": "PIX", "amount": 64.9, "actor_id": actor})

        first, second = await asyncio.gather(reserve(f"race-a-{uuid.uuid4()}"), reserve(f"race-b-{uuid.uuid4()}"))
        assert sorted([first.status_code, second.status_code]) == [200, 409]

        product = (await client.post("/api/v1/catalog/products", headers=headers, json={
            "name": "Mudança após snapshot", "sku": f"CHANGE-{uuid.uuid4().hex[:8]}", "unit": "UN", "tracks_inventory": False,
        })).json()
        await client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": product["id"], "store_id": store["id"], "cost_price": 1, "sale_price": 1,
        })
        changed = await client.post(f"/api/v1/orders/{order_id}/items", headers={
            **headers, "Idempotency-Key": f"changed-{uuid.uuid4()}",
        }, json={"product_id": product["id"], "quantity": 1, "actor_id": actor})
        assert changed.status_code == 200
        invalidated = await client.get(f"/api/v1/negotiations/{opened['id']}", headers=headers)
        assert invalidated.status_code == 409

    with Session(engine) as db:
        set_platform_db_context(db)
        assert db.get(CheckoutNegotiation, uuid.UUID(opened["id"])).status.value == "INVALIDATED"

"""S25 contracts 2 and 3 — what each item owes, and nobody paying it twice.

The scenario is the one the owner described on 5 September 2026. A table with a
single comanda: hamburger 35, coke 10, whisky 40, pizza 60. Marcelo pays his
hamburger and his coke; Astra pays the whisky; the pizza stays open because the
other friends are still at the table.

Nothing here moves an item to another comanda. The item was ordered, produced
and delivered at that table; only its financial state changes.
"""

import os
import uuid

import httpx
import pytest
from sqlmodel import Session

from app.core.database import engine
from app.core.tenancy import set_platform_db_context


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")
MENU = (("Hamburguer", 35), ("Coca-Cola", 10), ("Whisky", 40), ("Pizza", 60))


async def _table_with_menu(client: httpx.AsyncClient, prefix: str):
    suffix = uuid.uuid4().hex[:8]
    actor = str(uuid.uuid4())
    tenant = (await client.post("/api/v1/identity/tenants", json={
        "name": f"{prefix} {suffix}", "slug": f"{prefix.lower()}-{suffix}",
    })).json()
    store = (await client.post("/api/v1/identity/stores", json={
        "tenant_id": tenant["id"], "name": "Matriz", "code": f"{prefix[:3].upper()}-{suffix}",
    })).json()
    with Session(engine) as db:
        set_platform_db_context(db)
        from app.models.platform import TenantCapability, EntitlementStatusEnum
        for key in ("counter_order", "table_service"):
            db.add(TenantCapability(
                tenant_id=uuid.UUID(tenant["id"]), key=key,
                enabled=True, status=EntitlementStatusEnum.ACTIVE,
            ))
        db.commit()
    headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}
    table = (await client.post("/api/v1/tables", headers={**headers, "Idempotency-Key": f"table-{suffix}"}, json={
        "store_id": store["id"], "code": "M-01", "name": "Mesa 01", "capacity": 6, "actor_id": actor,
    })).json()
    table_session = (await client.post("/api/v1/tables/sessions", headers={**headers, "Idempotency-Key": f"session-{suffix}"}, json={
        "store_id": store["id"], "service_table_id": table["id"], "actor_id": actor,
    })).json()
    order_id = table_session["orders"][0]["id"]
    # A product only reaches the table through a published assortment; that is
    # the rule Gate 5.4.0 made, and the test obeys it instead of going around.
    assortment = (await client.post("/api/v1/catalog/assortments", headers=headers, json={
        "code": f"ASSORT-S25-{suffix}", "name": "Cardapio",
        "scopes": [{"store_id": store["id"], "sales_context": "TABLE"}],
        "product_ids": [],
    })).json()
    for index, (name, price) in enumerate(MENU, start=1):
        product = (await client.post("/api/v1/catalog/products", headers=headers, json={
            "name": name, "sku": f"S25-{suffix}-{index}", "unit": "UN", "tracks_inventory": False,
        })).json()
        await client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": product["id"], "store_id": store["id"], "cost_price": 1, "sale_price": price,
        })
        await client.post(f"/api/v1/catalog/assortments/{assortment['id']}/products", headers=headers, json={
            "expected_version": index, "product_ids": [product["id"]],
        })
        launched = await client.post(f"/api/v1/orders/{order_id}/items", headers={
            **headers, "Idempotency-Key": f"item-{suffix}-{index}",
        }, json={"product_id": product["id"], "quantity": 1, "actor_id": actor})
        assert launched.status_code == 200, launched.text
    return headers, store, actor, table_session


async def _open(client, headers, store, table_session, actor):
    opened = await client.post("/api/v1/negotiations", headers={
        **headers, "Idempotency-Key": f"neg-{uuid.uuid4()}",
    }, json={"store_id": store["id"], "table_session_id": table_session["id"], "actor_id": actor})
    assert opened.status_code == 200, opened.text
    return opened.json()


def _by_name(projection):
    return {row["product_name"]: row for row in projection["item_settlements"]}


async def _intent(client, headers, negotiation_id, actor, amount, allocations=None):
    return await client.post(f"/api/v1/negotiations/{negotiation_id}/intents", headers={
        **headers, "Idempotency-Key": f"intent-{uuid.uuid4()}",
    }, json={
        "method": "PIX", "amount": amount, "actor_id": actor,
        "allocations": allocations or [],
    })


@pytest.mark.asyncio
async def test_s25_each_item_reports_what_it_owes_and_the_table_stays_open():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Settlement")
        negotiation = await _open(client, headers, store, table_session, actor)
        assert float(negotiation["total_due"]) == 145

        items = _by_name(negotiation)
        assert set(items) == {name for name, _ in MENU}
        for name, price in MENU:
            row = items[name]
            assert float(row["item_total"]) == price
            assert float(row["settled_amount"]) == 0
            assert float(row["reserved_amount"]) == 0
            assert float(row["available_amount"]) == price
            assert row["is_paid"] is False

        # Marcelo takes his hamburger and his coke, and nothing else moves.
        marcelo = await _intent(client, headers, negotiation["id"], actor, 45, [
            {"amount": 35, "order_item_id": items["Hamburguer"]["order_item_id"]},
            {"amount": 10, "order_item_id": items["Coca-Cola"]["order_item_id"]},
        ])
        assert marcelo.status_code == 200, marcelo.text
        reserved = _by_name(marcelo.json())
        # While the payment is in flight the two items are already spoken for.
        assert float(reserved["Hamburguer"]["reserved_amount"]) == 35
        assert float(reserved["Hamburguer"]["available_amount"]) == 0
        assert reserved["Hamburguer"]["is_paid"] is False
        assert float(reserved["Whisky"]["available_amount"]) == 40
        assert float(marcelo.json()["unassigned_reserved_amount"]) == 0

        pending = [row for row in marcelo.json()["intents"] if row["status"] == "PENDING"][-1]
        confirmed = await client.post(f"/api/v1/negotiations/intents/{pending['id']}/confirm", headers={
            **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
        }, json={"actor_id": actor})
        assert confirmed.status_code == 200, confirmed.text
        body = confirmed.json()
        assert body["status"] == "PARTIALLY_COVERED"
        assert float(body["remaining_amount"]) == 100
        settled = _by_name(body)
        for name in ("Hamburguer", "Coca-Cola"):
            assert float(settled[name]["settled_amount"]) == dict(MENU)[name]
            assert float(settled[name]["reserved_amount"]) == 0
            assert float(settled[name]["available_amount"]) == 0
            assert settled[name]["is_paid"] is True
        assert settled["Pizza"]["is_paid"] is False

        # The table did not close because somebody paid their share.
        session_now = await client.get(f"/api/v1/tables/sessions/{table_session['id']}", headers=headers)
        assert session_now.status_code == 200, session_now.text
        assert session_now.json()["status"] == "PARTIALLY_PAID"

        # Astra pays the whisky she drank; the pizza is still anybody's.
        astra = await _intent(client, headers, negotiation["id"], actor, 40, [
            {"amount": 40, "order_item_id": settled["Whisky"]["order_item_id"]},
        ])
        assert astra.status_code == 200, astra.text
        pending = [row for row in astra.json()["intents"] if row["status"] == "PENDING"][-1]
        after = (await client.post(f"/api/v1/negotiations/intents/{pending['id']}/confirm", headers={
            **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
        }, json={"actor_id": actor})).json()
        assert after["status"] == "PARTIALLY_COVERED"
        assert float(after["remaining_amount"]) == 60
        rows = _by_name(after)
        assert rows["Whisky"]["is_paid"] is True
        assert float(rows["Pizza"]["available_amount"]) == 60
        assert rows["Pizza"]["is_paid"] is False


@pytest.mark.asyncio
async def test_s25_the_same_whisky_is_never_taken_twice():
    """The account still has R$105 free, so only the item guard can refuse."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Contention")
        negotiation = await _open(client, headers, store, table_session, actor)
        items = _by_name(negotiation)
        whisky, hamburger = items["Whisky"]["order_item_id"], items["Hamburguer"]["order_item_id"]

        first = await _intent(client, headers, negotiation["id"], actor, 40, [
            {"amount": 40, "order_item_id": whisky},
        ])
        assert first.status_code == 200, first.text
        pending = [row for row in first.json()["intents"] if row["status"] == "PENDING"][-1]

        # A second payer, while the first card is still in flight.
        second = await _intent(client, headers, negotiation["id"], actor, 40, [
            {"amount": 40, "order_item_id": whisky},
        ])
        assert second.status_code == 409, second.text
        detail = second.json()["detail"]
        assert detail["code"] == "ITEM_SETTLEMENT_UNAVAILABLE"
        assert float(detail["available"]) == 0 and float(detail["reserved"]) == 40

        # More than the item is worth, in a single allocation.
        greedy = await _intent(client, headers, negotiation["id"], actor, 40, [
            {"amount": 40, "order_item_id": hamburger},
        ])
        assert greedy.status_code == 409, greedy.text
        assert greedy.json()["detail"]["code"] == "ITEM_SETTLEMENT_UNAVAILABLE"

        # Two allocations for the same item inside one parcel are summed, not
        # checked one by one against a stale balance.
        twice = await _intent(client, headers, negotiation["id"], actor, 35, [
            {"amount": 20, "order_item_id": hamburger},
            {"amount": 15, "order_item_id": hamburger},
        ])
        assert twice.status_code == 200, twice.text
        over = await _intent(client, headers, negotiation["id"], actor, 36, [
            {"amount": 18, "order_item_id": items["Coca-Cola"]["order_item_id"]},
            {"amount": 18, "order_item_id": items["Coca-Cola"]["order_item_id"]},
        ])
        assert over.status_code == 409, over.text

        # A parcel that fails gives the whisky back; it is not lost to a card
        # that never went through.
        failed = await client.post(f"/api/v1/negotiations/intents/{pending['id']}/fail", headers={
            **headers, "Idempotency-Key": f"fail-{uuid.uuid4()}",
        }, json={"failure_code": "DECLINED", "reason": "Cartão recusado", "actor_id": actor})
        assert failed.status_code == 200, failed.text
        assert float(_by_name(failed.json())["Whisky"]["available_amount"]) == 40
        retry = await _intent(client, headers, negotiation["id"], actor, 40, [
            {"amount": 40, "order_item_id": whisky},
        ])
        assert retry.status_code == 200, retry.text


@pytest.mark.asyncio
async def test_s25_a_neighbour_tenant_never_settles_an_item_of_this_table():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Isolation")
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        foreign_headers, foreign_store, foreign_actor, foreign_session = await _table_with_menu(client, "Neighbour")
        foreign = await _open(client, foreign_headers, foreign_store, foreign_session, foreign_actor)

        stolen = await _intent(client, foreign_headers, foreign["id"], foreign_actor, 40, [
            {"amount": 40, "order_item_id": whisky},
        ])
        assert stolen.status_code == 422, stolen.text
        assert float(_by_name((await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json())["Whisky"]["available_amount"]) == 40

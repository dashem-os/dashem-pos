"""S25 — the gate lines that were still only prose.

Written on 5 September 2026 when the owner asked whether only the interface was
left. Four criteria of the sprint's own gate had no test behind them, and one of
them covered code this sprint had changed.
"""

import uuid

import httpx
import pytest

from test_s25_item_settlement import BASE_URL, _by_name, _open, _table_with_menu


async def _settle(client, headers, negotiation_id, actor, amount, allocations=None, payer=None):
    created = await client.post(f"/api/v1/negotiations/{negotiation_id}/intents", headers={
        **headers, "Idempotency-Key": f"intent-{uuid.uuid4()}",
    }, json={
        "method": "PIX", "amount": amount, "actor_id": actor, "payer_label": payer,
        "allocations": allocations or [],
    })
    assert created.status_code == 200, created.text
    pending = [row for row in created.json()["intents"] if row["status"] == "PENDING"][-1]
    confirmed = await client.post(f"/api/v1/negotiations/intents/{pending['id']}/confirm", headers={
        **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
    }, json={"actor_id": actor})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


@pytest.mark.asyncio
async def test_s25_paying_for_an_item_never_moves_the_kitchen():
    """Fulfillment and settlement are different dimensions of the same line.

    A whisky may be DELIVERED and PAID, a pizza DELIVERED and OPEN, a hamburger
    PREPARING and OPEN, all on the same comanda. Nothing a payer does may push a
    ticket forward or backward.
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Kitchen")
        order_id = table_session["orders"][0]["id"]
        suffix = uuid.uuid4().hex[:8]
        product = (await client.post("/api/v1/catalog/products", headers=headers, json={
            "name": "Prato da casa", "sku": f"KIT-{suffix}", "unit": "UN",
            "tracks_inventory": False, "requires_fulfillment": True,
        })).json()
        await client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": product["id"], "store_id": store["id"], "cost_price": 1, "sale_price": 50,
        })
        await client.post("/api/v1/catalog/assortments", headers=headers, json={
            "code": f"ASSORT-KIT-{suffix}", "name": "Cozinha",
            "scopes": [{"store_id": store["id"], "sales_context": "TABLE"}],
            "product_ids": [product["id"]],
        })
        launched = await client.post(f"/api/v1/orders/{order_id}/items", headers={
            **headers, "Idempotency-Key": f"kit-{suffix}",
        }, json={"product_id": product["id"], "quantity": 1, "actor_id": actor})
        assert launched.status_code == 200, launched.text
        before = launched.json()["production_state"]
        assert before == "PENDING", launched.text

        negotiation = await _open(client, headers, store, table_session, actor)
        cooked = _by_name(negotiation)["Prato da casa"]
        await _settle(client, headers, negotiation["id"], actor, 50, [
            {"amount": 50, "order_item_id": cooked["order_item_id"]},
        ], payer="Marcelo")

        session_now = (await client.get(f"/api/v1/tables/sessions/{table_session['id']}", headers=headers)).json()
        item = next(
            row for order in session_now["orders"] for row in order["items"]
            if row["id"] == cooked["order_item_id"]
        )
        assert item["production_state"] == before
        assert item["status"] == "ACTIVE"
        # And the money side did move, so the test is not passing by inertia.
        assert _by_name(
            (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        )["Prato da casa"]["is_paid"] is True


@pytest.mark.asyncio
async def test_s25_a_finalized_bill_accepts_no_further_allocation():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Closed")
        negotiation = await _open(client, headers, store, table_session, actor)
        items = _by_name(negotiation)
        covered = await _settle(client, headers, negotiation["id"], actor, 145)
        assert covered["status"] == "COVERED"
        finalized = await client.post(f"/api/v1/negotiations/{negotiation['id']}/finalize", headers={
            **headers, "Idempotency-Key": f"final-{uuid.uuid4()}",
        }, json={"expected_version": covered["version"], "actor_id": actor})
        assert finalized.status_code == 200 and finalized.json()["status"] == "FINALIZED"

        late = await client.post(f"/api/v1/negotiations/{negotiation['id']}/intents", headers={
            **headers, "Idempotency-Key": f"late-{uuid.uuid4()}",
        }, json={
            "method": "PIX", "amount": 10, "actor_id": actor,
            "allocations": [{"amount": 10, "order_item_id": items["Coca-Cola"]["order_item_id"]}],
        })
        assert late.status_code == 409, late.text


@pytest.mark.asyncio
async def test_s25_a_transfer_may_split_a_covered_item_but_never_below_its_cover():
    """The rule this sprint changed, and had left without a test.

    `transfer_item` used to refuse any item carrying a single allocation. It now
    asks finance through the settlement port and applies the same economic
    boundary as everything else: what stays behind must still be worth what was
    paid on it.
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Splitting")
        order_id = table_session["orders"][0]["id"]
        suffix = uuid.uuid4().hex[:8]
        product = (await client.post("/api/v1/catalog/products", headers=headers, json={
            "name": "Cerveja", "sku": f"BEER-{suffix}", "unit": "UN", "tracks_inventory": False,
        })).json()
        await client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": product["id"], "store_id": store["id"], "cost_price": 1, "sale_price": 12,
        })
        await client.post("/api/v1/catalog/assortments", headers=headers, json={
            "code": f"ASSORT-BEER-{suffix}", "name": "Bar",
            "scopes": [{"store_id": store["id"], "sales_context": "TABLE"}],
            "product_ids": [product["id"]],
        })
        launched = await client.post(f"/api/v1/orders/{order_id}/items", headers={
            **headers, "Idempotency-Key": f"beer-{suffix}",
        }, json={"product_id": product["id"], "quantity": 4, "actor_id": actor})
        assert launched.status_code == 200, launched.text

        negotiation = await _open(client, headers, store, table_session, actor)
        beers = _by_name(negotiation)["Cerveja"]
        assert float(beers["item_total"]) == 48
        # Marcelo pays for one of the four.
        await _settle(client, headers, negotiation["id"], actor, 12, [
            {"amount": 12, "order_item_id": beers["order_item_id"]},
        ], payer="Marcelo")

        destination = (await client.post("/api/v1/tables/sessions", headers={
            **headers, "Idempotency-Key": f"tab-{uuid.uuid4()}",
        }, json={"store_id": store["id"], "display_label": "Comanda avulsa", "actor_id": actor})).json()

        async def move(quantity, source_version, destination_version):
            return await client.post("/api/v1/transfers/items", headers={
                **headers, "Idempotency-Key": f"move-{uuid.uuid4()}",
            }, json={
                "source_session_id": table_session["id"], "destination_session_id": destination["id"],
                "order_item_id": beers["order_item_id"], "quantity": quantity,
                "expected_source_version": source_version,
                "expected_destination_version": destination_version,
                "reason": "Mudou de comanda", "actor_id": actor,
            })

        current = (await client.get(f"/api/v1/tables/sessions/{table_session['id']}", headers=headers)).json()
        # All four would leave nothing behind to carry Marcelo's R$12.
        refused = await move(4, current["version"], destination["version"])
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "ITEM_BELOW_SETTLEMENT", refused.text
        assert float(refused.json()["detail"]["covered"]) == 12

        # Two of them leave R$24 behind, which still covers what he paid.
        allowed = await move(2, current["version"], destination["version"])
        assert allowed.status_code == 200, allowed.text

        after = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        remaining_beers = _by_name(after)["Cerveja"]
        assert float(remaining_beers["item_total"]) == 24
        assert float(remaining_beers["settled_amount"]) == 12
        assert remaining_beers["settled_by"] == ["Marcelo"]
        assert float(remaining_beers["available_amount"]) == 12

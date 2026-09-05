"""S25 contract 1 — the bill follows the table instead of freezing away from it.

Until this contract a negotiation was the snapshot of an account that was
closing: one more beer and the whole thing went to INVALIDATED, so the second
payer could not pay. The room this product serves does not work that way. People
keep ordering while other people settle their share.

What must never bend is the other direction: nothing may make an item worth less
than the money already resting on it.
"""

import uuid

import httpx
import pytest

from test_s25_item_settlement import BASE_URL, MENU, _by_name, _intent, _open, _table_with_menu


async def _settle(client, headers, negotiation, actor, amount, allocations=None):
    created = await _intent(client, headers, negotiation["id"], actor, amount, allocations)
    assert created.status_code == 200, created.text
    pending = [row for row in created.json()["intents"] if row["status"] == "PENDING"][-1]
    confirmed = await client.post(f"/api/v1/negotiations/intents/{pending['id']}/confirm", headers={
        **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
    }, json={"actor_id": actor})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


async def _launch(client, headers, order_id, actor, name, price, suffix):
    product = (await client.post("/api/v1/catalog/products", headers=headers, json={
        "name": name, "sku": f"LIVE-{suffix}", "unit": "UN", "tracks_inventory": False,
    })).json()
    await client.post("/api/v1/catalog/prices", headers=headers, json={
        "product_id": product["id"], "store_id": headers["X-Store-ID"], "cost_price": 1, "sale_price": price,
    })
    assortment = (await client.post("/api/v1/catalog/assortments", headers=headers, json={
        "code": f"ASSORT-LIVE-{suffix}", "name": "Extras",
        "scopes": [{"store_id": headers["X-Store-ID"], "sales_context": "TABLE"}],
        "product_ids": [product["id"]],
    })).json()
    assert assortment.get("id"), assortment
    return await client.post(f"/api/v1/orders/{order_id}/items", headers={
        **headers, "Idempotency-Key": f"live-{suffix}",
    }, json={"product_id": product["id"], "quantity": 1, "actor_id": actor})


@pytest.mark.asyncio
async def test_s25_a_beer_ordered_after_a_payment_does_not_reopen_the_bill():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Live")
        order_id = table_session["orders"][0]["id"]
        negotiation = await _open(client, headers, store, table_session, actor)
        items = _by_name(negotiation)

        after_marcelo = await _settle(client, headers, negotiation, actor, 45, [
            {"amount": 35, "order_item_id": items["Hamburguer"]["order_item_id"]},
            {"amount": 10, "order_item_id": items["Coca-Cola"]["order_item_id"]},
        ])
        assert after_marcelo["status"] == "PARTIALLY_COVERED"
        assert float(after_marcelo["remaining_amount"]) == 100

        launched = await _launch(client, headers, order_id, actor, "Cerveja", 12, uuid.uuid4().hex[:8])
        assert launched.status_code == 200, launched.text

        reconciled = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        assert reconciled["status"] == "PARTIALLY_COVERED"
        assert float(reconciled["total_due"]) == 157
        assert float(reconciled["remaining_amount"]) == 112
        # What Marcelo paid stayed where it was.
        assert float(reconciled["confirmed_amount"]) == 45
        rows = _by_name(reconciled)
        assert rows["Hamburguer"]["is_paid"] is True and rows["Coca-Cola"]["is_paid"] is True
        assert float(rows["Cerveja"]["available_amount"]) == 12

        # And the next payer can still pay, which is the whole point.
        after_astra = await _settle(client, headers, negotiation, actor, 40, [
            {"amount": 40, "order_item_id": rows["Whisky"]["order_item_id"]},
        ])
        assert float(after_astra["remaining_amount"]) == 72
        assert _by_name(after_astra)["Whisky"]["is_paid"] is True


@pytest.mark.asyncio
async def test_s25_covered_is_not_terminal_and_finalized_is():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Reopen")
        order_id = table_session["orders"][0]["id"]
        negotiation = await _open(client, headers, store, table_session, actor)
        covered = await _settle(client, headers, negotiation, actor, 145)
        assert covered["status"] == "COVERED"
        assert float(covered["remaining_amount"]) == 0

        # "Traz mais duas cervejas" — before anyone finalised.
        for index in range(2):
            launched = await _launch(client, headers, order_id, actor, f"Cerveja {index}", 12, uuid.uuid4().hex[:8])
            assert launched.status_code == 200, launched.text
        reopened = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        assert reopened["status"] == "PARTIALLY_COVERED"
        assert float(reopened["remaining_amount"]) == 24

        refused = await client.post(f"/api/v1/negotiations/{negotiation['id']}/finalize", headers={
            **headers, "Idempotency-Key": f"final-{uuid.uuid4()}",
        }, json={"expected_version": reopened["version"], "actor_id": actor})
        assert refused.status_code == 409, refused.text

        paid = await _settle(client, headers, negotiation, actor, 24)
        assert paid["status"] == "COVERED"
        finalized = await client.post(f"/api/v1/negotiations/{negotiation['id']}/finalize", headers={
            **headers, "Idempotency-Key": f"final-{uuid.uuid4()}",
        }, json={"expected_version": paid["version"], "actor_id": actor})
        assert finalized.status_code == 200, finalized.text
        assert finalized.json()["status"] == "FINALIZED"

        # After the irreversible point no consumption enters the closed Order.
        late = await _launch(client, headers, order_id, actor, "Tarde demais", 5, uuid.uuid4().hex[:8])
        assert late.status_code == 409, late.text


@pytest.mark.asyncio
async def test_s25_a_comanda_opened_later_joins_a_table_bill_and_not_an_order_bill():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Joining")
        first_order = table_session["orders"][0]["id"]
        table_bill = await _open(client, headers, store, table_session, actor)
        assert float(table_bill["total_due"]) == 145

        added = await client.post(f"/api/v1/tables/sessions/{table_session['id']}/orders", headers={
            **headers, "Idempotency-Key": f"comanda-{uuid.uuid4()}",
        }, json={"display_reference": "Comanda 2", "actor_id": actor})
        assert added.status_code == 200, added.text
        launched = await _launch(client, headers, added.json()["id"], actor, "Caipirinha", 25, uuid.uuid4().hex[:8])
        assert launched.status_code == 200, launched.text

        joined = (await client.get(f"/api/v1/negotiations/{table_bill['id']}", headers=headers)).json()
        assert float(joined["total_due"]) == 170
        assert len(joined["orders"]) == 2

        # A bill scoped to named Orders is a choice, and a group that sat down
        # later is not part of it.
        _, foreign_store, foreign_actor, foreign_session = await _table_with_menu(client, "Scoped")
        scoped_headers = {"X-Tenant-ID": foreign_store["tenant_id"], "X-Store-ID": foreign_store["id"]}
        scoped_order = foreign_session["orders"][0]["id"]
        scoped = await client.post("/api/v1/negotiations", headers={
            **scoped_headers, "Idempotency-Key": f"scoped-{uuid.uuid4()}",
        }, json={"store_id": foreign_store["id"], "order_ids": [scoped_order], "actor_id": foreign_actor})
        assert scoped.status_code == 200, scoped.text
        assert float(scoped.json()["total_due"]) == 145
        other = await client.post(f"/api/v1/tables/sessions/{foreign_session['id']}/orders", headers={
            **scoped_headers, "Idempotency-Key": f"comanda-{uuid.uuid4()}",
        }, json={"display_reference": "Outro grupo", "actor_id": foreign_actor})
        assert other.status_code == 200, other.text
        await _launch(client, scoped_headers, other.json()["id"], foreign_actor, "Agua", 6, uuid.uuid4().hex[:8])
        unchanged = (await client.get(f"/api/v1/negotiations/{scoped.json()['id']}", headers=scoped_headers)).json()
        assert float(unchanged["total_due"]) == 145
        assert len(unchanged["orders"]) == 1
        assert first_order != scoped_order


@pytest.mark.asyncio
async def test_s25_an_item_may_change_but_never_below_what_was_paid_on_it():
    """The boundary is economic, not a freeze.

    A pizza nobody paid for can be cancelled and the table owes less. A whisky
    already settled cannot be cancelled, nor reduced below what settled on it.
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Boundary")
        order_id = table_session["orders"][0]["id"]
        negotiation = await _open(client, headers, store, table_session, actor)
        items = _by_name(negotiation)

        await _settle(client, headers, negotiation, actor, 40, [
            {"amount": 40, "order_item_id": items["Whisky"]["order_item_id"]},
        ])

        # Nobody paid for the pizza: cancelling it is ordinary work.
        dropped = await client.post(
            f"/api/v1/orders/{order_id}/items/{items['Pizza']['order_item_id']}/cancel",
            headers={**headers, "Idempotency-Key": f"cancel-{uuid.uuid4()}"},
            json={"reason": "Cliente desistiu", "actor_id": actor},
        )
        assert dropped.status_code == 200, dropped.text
        lighter = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        assert float(lighter["total_due"]) == 85
        assert float(lighter["remaining_amount"]) == 45

        # The whisky carries R$40 and cannot be cancelled away.
        refused = await client.post(
            f"/api/v1/orders/{order_id}/items/{items['Whisky']['order_item_id']}/cancel",
            headers={**headers, "Idempotency-Key": f"cancel-{uuid.uuid4()}"},
            json={"reason": "Tentativa indevida", "actor_id": actor},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "ITEM_BELOW_SETTLEMENT"
        assert float(refused.json()["detail"]["covered"]) == 40

        # Nor reduced below it. One whisky at R$40 stays at least one whisky.
        shrunk = await client.patch(
            f"/api/v1/orders/{order_id}/items/{items['Whisky']['order_item_id']}",
            headers={**headers, "Idempotency-Key": f"update-{uuid.uuid4()}"},
            json={"quantity": 0.5, "actor_id": actor},
        )
        assert shrunk.status_code == 409, shrunk.text
        assert shrunk.json()["detail"]["code"] == "ITEM_BELOW_SETTLEMENT"

        # Growing it is fine, and the bill grows with it.
        grown = await client.patch(
            f"/api/v1/orders/{order_id}/items/{items['Whisky']['order_item_id']}",
            headers={**headers, "Idempotency-Key": f"update-{uuid.uuid4()}"},
            json={"quantity": 2, "actor_id": actor},
        )
        assert grown.status_code == 200, grown.text
        after = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        assert float(after["total_due"]) == 125
        whisky = _by_name(after)["Whisky"]
        assert float(whisky["item_total"]) == 80 and float(whisky["settled_amount"]) == 40
        assert float(whisky["available_amount"]) == 40 and whisky["is_paid"] is False

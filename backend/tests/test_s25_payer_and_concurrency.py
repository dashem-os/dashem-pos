"""S25 contracts 4 and 5 — who paid, and nobody paying the same thing twice.

Contract 4 separates two people the model used to conflate: the operator who
executed the parcel and the payer whose money it was. Contract 5 makes the item
guard true under concurrency, which is the only state that matters on a counter
with two terminals.
"""

import asyncio
import uuid

import httpx
import pytest

from test_s25_item_settlement import BASE_URL, _by_name, _intent, _open, _table_with_menu


@pytest.mark.asyncio
async def test_s25_a_parcel_knows_whose_money_it_was():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Payer")
        negotiation = await _open(client, headers, store, table_session, actor)
        items = _by_name(negotiation)

        created = await client.post(f"/api/v1/negotiations/{negotiation['id']}/intents", headers={
            **headers, "Idempotency-Key": f"intent-{uuid.uuid4()}",
        }, json={
            "method": "PIX", "amount": 45, "actor_id": actor, "payer_label": "Marcelo",
            "allocations": [
                {"amount": 35, "order_item_id": items["Hamburguer"]["order_item_id"]},
                {"amount": 10, "order_item_id": items["Coca-Cola"]["order_item_id"]},
            ],
        })
        assert created.status_code == 200, created.text
        pending = [row for row in created.json()["intents"] if row["status"] == "PENDING"][-1]
        assert pending["payer_label"] == "Marcelo"
        assert pending["payer_customer_id"] is None
        # In flight, the screen can already say who is taking those two lines.
        assert _by_name(created.json())["Hamburguer"]["reserved_by"] == ["Marcelo"]

        confirmed = (await client.post(f"/api/v1/negotiations/intents/{pending['id']}/confirm", headers={
            **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
        }, json={"actor_id": actor})).json()
        rows = _by_name(confirmed)
        assert rows["Hamburguer"]["settled_by"] == ["Marcelo"] and rows["Hamburguer"]["is_paid"] is True
        assert rows["Coca-Cola"]["settled_by"] == ["Marcelo"]
        assert rows["Whisky"]["settled_by"] == [] and rows["Whisky"]["reserved_by"] == []

        # The payer is the person, never the operator who typed it.
        assert pending["payer_label"] != actor

        # A registered customer may carry the value instead, and must be ours.
        customer = (await client.post("/api/v1/sales/customers", headers=headers, json={
            "name": "Carlos Empresa", "cpf_cnpj": f"{uuid.uuid4().int % 10**11:011d}",
        })).json()
        charged = await client.post(f"/api/v1/negotiations/{negotiation['id']}/intents", headers={
            **headers, "Idempotency-Key": f"intent-{uuid.uuid4()}",
        }, json={
            "method": "PIX", "amount": 40, "actor_id": actor,
            "payer_label": "Carlos Empresa", "payer_customer_id": customer["id"],
            "allocations": [{"amount": 40, "order_item_id": rows["Whisky"]["order_item_id"]}],
        })
        assert charged.status_code == 200, charged.text
        assert [row for row in charged.json()["intents"] if row["status"] == "PENDING"][-1]["payer_customer_id"] == customer["id"]

        stranger = await client.post(f"/api/v1/negotiations/{negotiation['id']}/intents", headers={
            **headers, "Idempotency-Key": f"intent-{uuid.uuid4()}",
        }, json={
            "method": "PIX", "amount": 10, "actor_id": actor, "payer_customer_id": str(uuid.uuid4()),
        })
        assert stranger.status_code == 404, stranger.text

        # And nothing forces a name: friends split a bill without registering.
        anonymous = await _intent(client, headers, negotiation["id"], actor, 10)
        assert anonymous.status_code == 200, anonymous.text
        assert [row for row in anonymous.json()["intents"] if row["status"] == "PENDING"][-1]["payer_label"] is None


@pytest.mark.asyncio
async def test_s25_two_terminals_reaching_for_the_same_whisky_at_the_same_instant():
    """Real concurrent transactions, not two calls in a row.

    The account still owes R$145 and each parcel asks for R$40, so the account
    guard lets both through: only the item guard, decided over a FOR UPDATE read
    inside the transaction that holds the negotiation, can be what refuses.
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Race")
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]

        async def take(payer):
            return await client.post(f"/api/v1/negotiations/{negotiation['id']}/intents", headers={
                **headers, "Idempotency-Key": f"race-{uuid.uuid4()}",
            }, json={
                "method": "PIX", "amount": 40, "actor_id": actor, "payer_label": payer,
                "allocations": [{"amount": 40, "order_item_id": whisky}],
            })

        first, second = await asyncio.gather(take("Astra"), take("Joao"))
        assert sorted([first.status_code, second.status_code]) == [200, 409]
        loser = first if first.status_code == 409 else second
        assert loser.json()["detail"]["code"] == "ITEM_SETTLEMENT_UNAVAILABLE"

        state = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        whisky_row = _by_name(state)["Whisky"]
        assert float(whisky_row["reserved_amount"]) == 40
        assert float(whisky_row["available_amount"]) == 0
        assert len(whisky_row["reserved_by"]) == 1


@pytest.mark.asyncio
async def test_s25_a_comanda_is_never_paid_by_two_open_bills_at_once():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "TwoBills")
        order_id = table_session["orders"][0]["id"]
        table_bill = await _open(client, headers, store, table_session, actor)
        assert table_bill["status"] in ("OPEN", "PARTIALLY_COVERED")

        # The same comanda, now as a bill of its own. Different scope_key, so the
        # unique index says nothing; the guard has to.
        clashing = await client.post("/api/v1/negotiations", headers={
            **headers, "Idempotency-Key": f"clash-{uuid.uuid4()}",
        }, json={"store_id": store["id"], "order_ids": [order_id], "actor_id": actor})
        assert clashing.status_code == 409, clashing.text
        assert clashing.json()["detail"]["code"] == "ORDER_ALREADY_IN_NEGOTIATION"
        assert clashing.json()["detail"]["order_id"] == order_id

        # The reverse order too, on a second table.
        other_headers, other_store, other_actor, other_session = await _table_with_menu(client, "Reverse")
        other_order = other_session["orders"][0]["id"]
        order_bill = await client.post("/api/v1/negotiations", headers={
            **other_headers, "Idempotency-Key": f"order-{uuid.uuid4()}",
        }, json={"store_id": other_store["id"], "order_ids": [other_order], "actor_id": other_actor})
        assert order_bill.status_code == 200, order_bill.text
        table_after = await client.post("/api/v1/negotiations", headers={
            **other_headers, "Idempotency-Key": f"table-{uuid.uuid4()}",
        }, json={"store_id": other_store["id"], "table_session_id": other_session["id"], "actor_id": other_actor})
        assert table_after.status_code == 409, table_after.text
        assert table_after.json()["detail"]["code"] == "ORDER_ALREADY_IN_NEGOTIATION"


@pytest.mark.asyncio
async def test_s25_a_table_bill_does_not_absorb_a_comanda_that_is_already_being_paid():
    """Absorption is generous, but never at another bill's expense."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Absorb")
        table_bill = await _open(client, headers, store, table_session, actor)
        assert float(table_bill["total_due"]) == 145

        added = await client.post(f"/api/v1/tables/sessions/{table_session['id']}/orders", headers={
            **headers, "Idempotency-Key": f"comanda-{uuid.uuid4()}",
        }, json={"display_reference": "Comanda do Joao", "actor_id": actor})
        assert added.status_code == 200, added.text
        new_order = added.json()["id"]
        product = (await client.post("/api/v1/catalog/products", headers=headers, json={
            "name": "Batata", "sku": f"ABS-{uuid.uuid4().hex[:8]}", "unit": "UN", "tracks_inventory": False,
        })).json()
        await client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": product["id"], "store_id": store["id"], "cost_price": 1, "sale_price": 30,
        })
        await client.post("/api/v1/catalog/assortments", headers=headers, json={
            "code": f"ASSORT-ABS-{uuid.uuid4().hex[:8]}", "name": "Petiscos",
            "scopes": [{"store_id": store["id"], "sales_context": "TABLE"}],
            "product_ids": [product["id"]],
        })
        launched = await client.post(f"/api/v1/orders/{new_order}/items", headers={
            **headers, "Idempotency-Key": f"abs-{uuid.uuid4()}",
        }, json={"product_id": product["id"], "quantity": 1, "actor_id": actor})
        assert launched.status_code == 200, launched.text

        # João opens his own bill before anyone refreshes the table's.
        own = await client.post("/api/v1/negotiations", headers={
            **headers, "Idempotency-Key": f"own-{uuid.uuid4()}",
        }, json={"store_id": store["id"], "order_ids": [new_order], "actor_id": actor})
        assert own.status_code == 200, own.text
        assert float(own.json()["total_due"]) == 30

        # The table's bill grows with its own comandas and leaves João's alone.
        refreshed = (await client.get(f"/api/v1/negotiations/{table_bill['id']}", headers=headers)).json()
        assert float(refreshed["total_due"]) == 145
        assert [row["order_id"] for row in refreshed["orders"]] == [table_session["orders"][0]["id"]]

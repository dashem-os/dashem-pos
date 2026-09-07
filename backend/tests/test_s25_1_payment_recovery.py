"""S25.1 — getting a reserve back, without ever guessing about money.

S25 made the per-item reserve real and, by doing so, made abandonment
expensive: a parcel stuck at PENDING holds one line of the bill and nobody else
can pay it. The only release that existed was `fail_intent`, which declared a
failure without asking whether a card was still authorising, and which had no
button anywhere.

The rule these tests defend is the owner's: never release money merely because
the clock passed. Cancelling, failing, expiring and refunding are four different
things, and what separates them is how far the money actually went.
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.negotiation import PaymentIntent, PaymentSettlementDivergence

from test_s25_item_settlement import BASE_URL, _by_name, _open, _table_with_menu


async def _reserve(client, headers, negotiation_id, actor, amount, item_id=None, payer=None, binding=None):
    body = {
        "method": "CREDIT_CARD" if binding else "PIX", "amount": amount,
        "actor_id": actor, "payer_label": payer,
        "allocations": [{"amount": amount, "order_item_id": item_id}] if item_id else [],
    }
    if binding:
        body["payment_device_binding_id"] = binding
    return await client.post(f"/api/v1/negotiations/{negotiation_id}/intents", headers={
        **headers, "Idempotency-Key": f"intent-{uuid.uuid4()}",
    }, json=body)


async def _pending(response):
    return [row for row in response.json()["intents"] if row["status"] == "PENDING"][-1]


async def _tef(client, headers, tenant, store, actor, register_id, suffix, online=True):
    """A provider, a paired bridge and a POS binding — the real chain."""
    configuration = (await client.post("/api/v1/providers/configurations", headers={
        **headers, "Idempotency-Key": f"config-{uuid.uuid4()}",
    }, json={"store_id": store["id"], "provider_code": "SITEF",
             "credentials_ref": "secret://tenant/sitef", "actor_id": actor})).json()
    paired = (await client.post("/api/v1/providers/bridge/terminals", headers={
        **headers, "Idempotency-Key": f"pair-{uuid.uuid4()}",
    }, json={"store_id": store["id"], "register_id": register_id,
             "provider_configuration_id": configuration["id"],
             "terminal_code": f"PINPAD-{suffix}", "actor_id": actor})).json()
    terminal, pairing_code = paired["terminal"], paired["pairing_code"]
    if online:
        beat = await client.post(f"/api/v1/providers/bridge/terminals/{terminal['id']}/heartbeat", json={
            "tenant_id": tenant["id"], "store_id": store["id"], "pairing_code": pairing_code,
            "bridge_version": "1.0.0", "protocol_version": "1.0",
        })
        assert beat.status_code == 200 and beat.json()["status"] == "ONLINE", beat.text
    device = (await client.post("/api/v1/devices", headers=headers, json={
        "store_id": store["id"], "code": f"POS-{suffix}", "name": "POS de pagamento",
        "device_type": "POS", "register_id": register_id, "actor_id": actor,
    })).json()
    binding = (await client.post("/api/v1/providers/device-bindings", headers={
        **headers, "Idempotency-Key": f"binding-{uuid.uuid4()}",
    }, json={"store_id": store["id"], "register_id": register_id,
             "operational_device_id": device["id"], "provider_configuration_id": configuration["id"],
             "execution_mode": "TEF_BRIDGE", "tef_bridge_terminal_id": terminal["id"],
             "actor_id": actor})).json()
    return {"terminal": terminal, "pairing_code": pairing_code, "binding": binding}


async def _register(client, headers, store, actor):
    register = (await client.post("/api/v1/cash/registers", headers=headers, json={
        "store_id": store["id"], "name": "Caixa S25.1", "code": f"CX-{uuid.uuid4().hex[:6]}",
    })).json()
    return register["id"]


@pytest.mark.asyncio
async def test_s25_1_a_reserve_never_sent_is_given_back_and_the_command_is_idempotent():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "GiveBack")
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]

        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra")
        assert created.status_code == 200, created.text
        held = _by_name(created.json())["Whisky"]
        assert float(held["available_amount"]) == 0 and held["reserved_by"] == ["Astra"]
        intent = await _pending(created)
        # Nothing was sent, so the parcel says so and offers the way out. A PIX
        # taken by hand carries no clock: the server cannot prove money did not
        # change hands, so only a person releases it.
        assert intent["can_cancel"] is True and intent["awaiting_provider"] is False
        assert intent["reserve_expires_at"] is None

        key = f"cancel-{uuid.uuid4()}"
        body = {"reason": "Cliente desistiu antes de passar o cartão", "actor_id": actor}
        canceled = await client.post(
            f"/api/v1/negotiations/intents/{intent['id']}/cancel",
            headers={**headers, "Idempotency-Key": key}, json=body,
        )
        assert canceled.status_code == 200, canceled.text
        back = _by_name(canceled.json())["Whisky"]
        assert float(back["available_amount"]) == 40 and back["reserved_by"] == []
        parcel = next(row for row in canceled.json()["intents"] if row["id"] == intent["id"])
        assert parcel["status"] == "CANCELED" and parcel["cancel_reason"] == body["reason"]
        assert parcel["can_cancel"] is False and parcel["reserve_expires_at"] is None

        # The same command twice is one cancellation.
        again = await client.post(
            f"/api/v1/negotiations/intents/{intent['id']}/cancel",
            headers={**headers, "Idempotency-Key": key}, json=body,
        )
        assert again.status_code == 200, again.text
        assert float(_by_name(again.json())["Whisky"]["available_amount"]) == 40
        # A different command on the same parcel is a conflict, not a second one.
        other = await client.post(
            f"/api/v1/negotiations/intents/{intent['id']}/cancel",
            headers={**headers, "Idempotency-Key": f"cancel-{uuid.uuid4()}"},
            json={"reason": "Outro motivo qualquer", "actor_id": actor},
        )
        assert other.status_code == 409, other.text

        # And the whisky really is payable again, by somebody else.
        retaken = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Joao")
        assert retaken.status_code == 200, retaken.text


@pytest.mark.asyncio
async def test_s25_1_a_confirmed_payment_is_never_cancelled_to_free_a_line():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "NoUndo")
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra")
        intent = await _pending(created)
        confirmed = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/confirm", headers={
            **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
        }, json={"actor_id": actor})
        assert confirmed.status_code == 200

        refused = await client.post(
            f"/api/v1/negotiations/intents/{intent['id']}/cancel",
            headers={**headers, "Idempotency-Key": f"cancel-{uuid.uuid4()}"},
            json={"reason": "Tentativa de liberar saldo pago", "actor_id": actor},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "CONFIRMED_PAYMENT_NEEDS_REVERSAL"
        assert _by_name((await client.get(
            f"/api/v1/negotiations/{negotiation['id']}", headers=headers,
        )).json())["Whisky"]["is_paid"] is True


@pytest.mark.asyncio
async def test_s25_1_a_charge_in_flight_blocks_release_and_hand_confirmation():
    """The defect this sprint exists for.

    `fail_intent` used to release the reserve after checking only that the
    parcel was open. A card still authorising could be declared failed and its
    line handed to somebody else, and the same hole let an operator confirm by
    hand a payment the acquirer had never approved.
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "InFlight")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "FLY")

        created = await _reserve(
            client, headers, negotiation["id"], actor, 40, whisky, "Astra",
            binding=tef["binding"]["id"],
        )
        assert created.status_code == 200, created.text
        intent = await _pending(created)
        # It carries a clock while it has not been sent — a parcel abandoned
        # before reaching the TEF used to be unreachable by the sweep.
        assert intent["reserve_expires_at"] is not None

        sent = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": intent["id"], "payment_device_binding_id": tef["binding"]["id"],
                 "actor_id": actor})
        assert sent.status_code == 200, sent.text
        assert sent.json()["transaction"]["status"] == "PROCESSING"

        state = await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)
        parcel = next(row for row in state.json()["intents"] if row["id"] == intent["id"])
        assert parcel["status"] == "PROCESSING"
        # And once it left, the clock stops: from here only an answer decides.
        assert parcel["reserve_expires_at"] is None
        assert parcel["awaiting_provider"] is True and parcel["can_cancel"] is False
        assert parcel["can_query_provider"] is True

        for path, body in (
            ("cancel", {"reason": "Quero liberar o item", "actor_id": actor}),
            ("fail", {"failure_code": "MANUAL", "reason": "Marcando falha na mão", "actor_id": actor}),
        ):
            blocked = await client.post(
                f"/api/v1/negotiations/intents/{intent['id']}/{path}",
                headers={**headers, "Idempotency-Key": f"{path}-{uuid.uuid4()}"}, json=body,
            )
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["detail"]["code"] == "EXTERNAL_CHARGE_IN_FLIGHT", blocked.text

        hand_confirm = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/confirm", headers={
            **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
        }, json={"actor_id": actor})
        assert hand_confirm.status_code == 409, hand_confirm.text
        assert hand_confirm.json()["detail"]["code"] == "EXTERNAL_CHARGE_IN_FLIGHT"

        # The reserve is kept while the question is open — that is the point.
        assert float(_by_name(state.json())["Whisky"]["available_amount"]) == 0

        # Consulting is the way out, and an unknown answer keeps the reserve.
        queried = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/query", headers=headers,
                                    json={"actor_id": actor})
        assert queried.status_code == 200, queried.text
        still = next(row for row in queried.json()["intents"] if row["id"] == intent["id"])
        assert still["status"] == "PROCESSING" and still["awaiting_provider"] is True
        assert float(_by_name(queried.json())["Whisky"]["available_amount"]) == 0

        # The bridge finally reports, and only then the line comes back.
        reported = await client.post(
            f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}/transactions/{sent.json()['transaction']['id']}/result",
            json={"tenant_id": tenant_id, "store_id": store["id"], "pairing_code": tef["pairing_code"],
                  "status": "FAILED", "failure_code": "DENIED", "failure_reason": "Cartão recusado"},
        )
        assert reported.status_code == 200, reported.text
        assert float(_by_name(reported.json()["negotiation"])["Whisky"]["available_amount"]) == 40


@pytest.mark.asyncio
async def test_s25_1_expiry_needs_evidence_that_nothing_was_ever_charged():
    """A clock alone never releases money.

    Three reserves, and only one of them is provably unsent: the card that
    declared a device and never used it. The card already sent is left to
    reconciliation, because a lost answer is not a lost charge. The manual PIX
    is left to a person, because nobody ever promised the system a transaction
    and its absence says nothing about what happened at the counter.
    """
    from app.services.negotiation_service import expire_abandoned_reserves

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Clock")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        lines = _by_name(negotiation)
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "CLK")

        abandoned = await _reserve(client, headers, negotiation["id"], actor, 60,
                                   lines["Pizza"]["order_item_id"], "Ninguem",
                                   binding=tef["binding"]["id"])
        assert abandoned.status_code == 200, abandoned.text
        abandoned_id = (await _pending(abandoned))["id"]

        # A manual receipt: no device was ever declared, so no clock and no sweep.
        manual = await _reserve(client, headers, negotiation["id"], actor, 10,
                                lines["Coca-Cola"]["order_item_id"], "Balcao")
        assert manual.status_code == 200, manual.text
        manual_id = (await _pending(manual))["id"]
        assert (await _pending(manual))["reserve_expires_at"] is None

        sent_intent = await _reserve(
            client, headers, negotiation["id"], actor, 40, lines["Whisky"]["order_item_id"], "Astra",
            binding=tef["binding"]["id"],
        )
        sent_id = (await _pending(sent_intent))["id"]
        executed = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": sent_id, "payment_device_binding_id": tef["binding"]["id"], "actor_id": actor})
        assert executed.status_code == 200, executed.text

    # Both clocks are forced into the past; only one of them may be honoured.
    with Session(engine) as db:
        set_platform_db_context(db)
        past = datetime.utcnow() - timedelta(minutes=1)
        for intent_id in (abandoned_id, sent_id, manual_id):
            row = db.get(PaymentIntent, uuid.UUID(intent_id))
            row.reserve_expires_at = past
            db.add(row)
        db.commit()
        expired = expire_abandoned_reserves(db)
        assert uuid.UUID(abandoned_id) in expired
        assert uuid.UUID(sent_id) not in expired
        # Forcing a clock onto a manual reserve is not enough: the sweep still
        # refuses it, because no charge was ever due for it.
        assert uuid.UUID(manual_id) not in expired
        assert db.get(PaymentIntent, uuid.UUID(sent_id)).status.value == "PROCESSING"
        assert db.get(PaymentIntent, uuid.UUID(manual_id)).status.value == "PENDING"
        assert db.get(PaymentIntent, uuid.UUID(abandoned_id)).status.value == "CANCELED"

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        state = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        rows = _by_name(state)
        assert float(rows["Pizza"]["available_amount"]) == 60
        assert float(rows["Whisky"]["available_amount"]) == 0
        assert float(rows["Coca-Cola"]["available_amount"]) == 0, "reserva manual continua de pé"


@pytest.mark.asyncio
async def test_s25_1_the_provider_closing_the_charge_closes_the_parcel():
    """CANCELED used to fall through and leave the item held forever."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "ExtCancel")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "XCN")

        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra",
                                 binding=tef["binding"]["id"])
        intent = await _pending(created)
        sent = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": intent["id"], "payment_device_binding_id": tef["binding"]["id"],
                 "actor_id": actor})
        transaction_id = sent.json()["transaction"]["id"]

        canceled = await client.post(
            f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}/transactions/{transaction_id}/result",
            json={"tenant_id": tenant_id, "store_id": store["id"], "pairing_code": tef["pairing_code"],
                  "status": "CANCELED", "failure_reason": "Operação cancelada no pinpad"},
        )
        assert canceled.status_code == 200, canceled.text
        body = canceled.json()["negotiation"]
        parcel = next(row for row in body["intents"] if row["id"] == intent["id"])
        assert parcel["status"] == "CANCELED"
        assert float(_by_name(body)["Whisky"]["available_amount"]) == 40
        assert body["divergences"] == []


@pytest.mark.asyncio
async def test_s25_1_a_late_or_repeated_answer_is_written_down_and_never_applied():
    """The money moved in the world and could not move here.

    A confirmation arriving after the parcel closed cannot be applied — the line
    may already have been paid by somebody else — and cannot be discarded, since
    a real payment happened. It becomes one divergence, and stays one however
    many times the provider repeats itself.
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Late")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "LATE")

        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra",
                                 binding=tef["binding"]["id"])
        intent = await _pending(created)
        sent = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": intent["id"], "payment_device_binding_id": tef["binding"]["id"],
                 "actor_id": actor})
        transaction_id = sent.json()["transaction"]["id"]

        # The bridge says the card was refused, so the line goes back and Joao
        # pays for the same whisky.
        await client.post(
            f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}/transactions/{transaction_id}/result",
            json={"tenant_id": tenant_id, "store_id": store["id"], "pairing_code": tef["pairing_code"],
                  "status": "FAILED", "failure_code": "DENIED", "failure_reason": "Recusado"},
        )
        joao = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Joao")
        assert joao.status_code == 200, joao.text
        joao_intent = await _pending(joao)
        await client.post(f"/api/v1/negotiations/intents/{joao_intent['id']}/confirm", headers={
            **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
        }, json={"actor_id": actor})

        # Now the acquirer changes its mind about the first attempt.
        late = await client.post(
            f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}/transactions/{transaction_id}/result",
            json={"tenant_id": tenant_id, "store_id": store["id"], "pairing_code": tef["pairing_code"],
                  "status": "CONFIRMED", "nsu": "NSU-LATE", "authorization_code": "OK"},
        )
        assert late.status_code == 200, late.text
        body = late.json()["negotiation"]
        first = next(row for row in body["intents"] if row["id"] == intent["id"])
        assert first["status"] == "FAILED", "a parcela encerrada não é reaberta em silêncio"
        assert [str(row["kind"]) for row in body["divergences"]] == ["LATE_CONFIRMATION"], body["divergences"]
        # Joao's payment is untouched: the line stays his.
        assert _by_name(body)["Whisky"]["settled_by"] == ["Joao"]

        # The provider repeating itself, and out of order, is still one fact.
        for status in ("CONFIRMED", "CONFIRMED"):
            repeated = await client.post(
                f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}/transactions/{transaction_id}/result",
                json={"tenant_id": tenant_id, "store_id": store["id"], "pairing_code": tef["pairing_code"],
                      "status": status, "nsu": "NSU-LATE"},
            )
            assert repeated.status_code == 200, repeated.text
        with Session(engine) as db:
            set_platform_db_context(db)
            rows = db.exec(select(PaymentSettlementDivergence).where(
                PaymentSettlementDivergence.payment_intent_id == uuid.UUID(intent["id"]),
            )).all()
            assert len(rows) == 1, rows
            assert float(rows[0].amount) == 40


@pytest.mark.asyncio
async def test_s25_1_a_refund_is_a_reversal_and_never_a_released_reserve():
    """REFUNDED on a settled parcel is money that left and came back.

    Treating it as a cancellation would silently undo a confirmed payment with
    no reversal behind it. The fact is recorded and the money is left alone.
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Refund")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "RFD")

        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra",
                                 binding=tef["binding"]["id"])
        intent = await _pending(created)
        sent = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": intent["id"], "payment_device_binding_id": tef["binding"]["id"],
                 "actor_id": actor})
        transaction_id = sent.json()["transaction"]["id"]
        await client.post(
            f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}/transactions/{transaction_id}/result",
            json={"tenant_id": tenant_id, "store_id": store["id"], "pairing_code": tef["pairing_code"],
                  "status": "CONFIRMED", "nsu": "NSU-1", "authorization_code": "OK"},
        )

        refunded = await client.post(
            f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}/transactions/{transaction_id}/result",
            json={"tenant_id": tenant_id, "store_id": store["id"], "pairing_code": tef["pairing_code"],
                  "status": "REFUNDED", "failure_reason": "Estorno solicitado no adquirente"},
        )
        assert refunded.status_code == 200, refunded.text
        body = refunded.json()["negotiation"]
        parcel = next(row for row in body["intents"] if row["id"] == intent["id"])
        assert parcel["status"] == "CONFIRMED", "estorno não desfaz pagamento por conta própria"
        assert float(_by_name(body)["Whisky"]["settled_amount"]) == 40
        assert [str(row["kind"]) for row in body["divergences"]] == ["REFUND_REQUIRES_REVERSAL"], body["divergences"]


@pytest.mark.asyncio
async def test_s25_1_cancelling_and_confirming_at_the_same_instant_has_one_winner():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Race251")
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra")
        intent = await _pending(created)

        cancel = client.post(
            f"/api/v1/negotiations/intents/{intent['id']}/cancel",
            headers={**headers, "Idempotency-Key": f"cancel-{uuid.uuid4()}"},
            json={"reason": "Desistiu no balcao", "actor_id": actor},
        )
        confirm = client.post(f"/api/v1/negotiations/intents/{intent['id']}/confirm", headers={
            **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
        }, json={"actor_id": actor})
        first, second = await asyncio.gather(cancel, confirm)
        assert sorted([first.status_code, second.status_code]) == [200, 409]

        state = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        parcel = next(row for row in state["intents"] if row["id"] == intent["id"])
        assert parcel["status"] in {"CANCELED", "CONFIRMED"}
        line = _by_name(state)["Whisky"]
        # Whichever won, the line is coherent: either free again or settled once.
        if parcel["status"] == "CANCELED":
            assert float(line["available_amount"]) == 40 and float(line["settled_amount"]) == 0
        else:
            assert float(line["available_amount"]) == 0 and float(line["settled_amount"]) == 40


@pytest.mark.asyncio
async def test_s25_1_a_lost_answer_is_retried_on_the_same_attempt_not_a_new_charge():
    """Pressing again must never send the card twice."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Retry")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "RTY")
        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra",
                                 binding=tef["binding"]["id"])
        intent = await _pending(created)

        body = {"payment_intent_id": intent["id"], "payment_device_binding_id": tef["binding"]["id"],
                "actor_id": actor}
        first = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}"}, json=body)
        assert first.status_code == 200, first.text
        # A fresh key, as a second press would produce: still the same charge.
        second = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}"}, json=body)
        assert second.status_code == 200, second.text
        assert second.json()["transaction"]["id"] == first.json()["transaction"]["id"]
        # And so is asking through the bill.
        queried = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/query",
                                    headers=headers, json={"actor_id": actor})
        assert queried.status_code == 200, queried.text

        with Session(engine) as db:
            set_platform_db_context(db)
            from app.models.provider import ProviderTransaction
            charges = db.exec(select(ProviderTransaction).where(
                ProviderTransaction.payment_intent_id == uuid.UUID(intent["id"]),
            )).all()
            assert len(charges) == 1, charges


@pytest.mark.asyncio
async def test_s25_1_an_offline_bridge_leaves_no_reserve_behind():
    """The screen used to create the parcel and only then find the bridge down."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Offline")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "OFF", online=False)

        refused = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra",
                                 binding=tef["binding"]["id"])
        # The chain check that ADR-022 already owned now runs before the
        # reserve, so the refusal is the same one and the bill is untouched.
        assert refused.status_code == 503, refused.text
        assert "offline" in refused.json()["detail"].lower()

        state = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        assert state["intents"] == []
        assert float(_by_name(state)["Whisky"]["available_amount"]) == 40


@pytest.mark.asyncio
async def test_s25_1_a_neighbour_never_cancels_or_queries_this_bill():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Fence")
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra")
        intent = await _pending(created)
        foreign_headers, _s, _a, _t = await _table_with_menu(client, "Neighbour251")

        stolen = await client.post(
            f"/api/v1/negotiations/intents/{intent['id']}/cancel",
            headers={**foreign_headers, "Idempotency-Key": f"cancel-{uuid.uuid4()}"},
            json={"reason": "Cancelamento do vizinho", "actor_id": str(uuid.uuid4())},
        )
        assert stolen.status_code == 404, stolen.text
        peeked = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/query",
                                   headers=foreign_headers, json={})
        assert peeked.status_code == 404, peeked.text
        assert float(_by_name((await client.get(
            f"/api/v1/negotiations/{negotiation['id']}", headers=headers,
        )).json())["Whisky"]["available_amount"]) == 0


def test_s25_1_releasing_money_needs_its_own_permission():
    """The HTTP suite runs with AUTH_MODE=disabled, so the mapping is asserted
    directly — the same way Gate C proved its PIN branch."""
    from app.core.permissions import route_requirement

    assert route_requirement("POST", "/api/v1/negotiations/intents/abc/cancel").permission == "checkout.payment.cancel"
    for path in ("/api/v1/negotiations/intents/abc/confirm", "/api/v1/negotiations/intents/abc/fail"):
        assert route_requirement("POST", path).permission == "checkout.payment"
    assert route_requirement("GET", "/api/v1/negotiations/abc").permission == "checkout.read"


@pytest.mark.asyncio
async def test_s25_1_a_crash_between_the_two_commits_never_frees_an_approved_card():
    """The window the review found.

    `_apply_result` persists the provider answer and only then touches the
    parcel. A process dying in between leaves a CONFIRMED charge beside an open
    parcel — and the first cut of this sprint, which looked only for charges
    *in flight*, would have let an operator cancel that reserve and hand the
    line to somebody else while the customer's card had been approved.
    """
    from app.services.provider_service import recover_unapplied_results

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Crash")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "CRS")
        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra",
                                 binding=tef["binding"]["id"])
        intent_id = (await _pending(created))["id"]
        sent = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": intent_id, "payment_device_binding_id": tef["binding"]["id"],
                 "actor_id": actor})
        transaction_id = sent.json()["transaction"]["id"]

    # Exactly the crash: the answer is on the row, the parcel never heard it.
    with Session(engine) as db:
        set_platform_db_context(db)
        from app.models.provider import ProviderTransaction, ProviderTransactionStatusEnum
        row = db.get(ProviderTransaction, uuid.UUID(transaction_id))
        row.status = ProviderTransactionStatusEnum.CONFIRMED
        row.nsu, row.authorization_code = "NSU-CRASH", "OK"
        db.add(row)
        db.commit()
        assert db.get(PaymentIntent, uuid.UUID(intent_id)).status.value == "PROCESSING"

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        state = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        parcel = next(row for row in state["intents"] if row["id"] == intent_id)
        assert parcel["can_cancel"] is False, "não se libera reserva de cartão aprovado"
        assert parcel["awaiting_provider"] is True and parcel["can_query_provider"] is True

        for path, body in (
            ("cancel", {"reason": "Liberar o item", "actor_id": actor}),
            ("fail", {"failure_code": "MANUAL", "reason": "Marcando falha", "actor_id": actor}),
        ):
            blocked = await client.post(
                f"/api/v1/negotiations/intents/{intent_id}/{path}",
                headers={**headers, "Idempotency-Key": f"{path}-{uuid.uuid4()}"}, json=body,
            )
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["detail"]["code"] == "EXTERNAL_CHARGE_IN_FLIGHT"

        # Consulting replays the answer already on the row: no second charge.
        recovered = await client.post(f"/api/v1/negotiations/intents/{intent_id}/query",
                                      headers=headers, json={"actor_id": actor})
        assert recovered.status_code == 200, recovered.text
        parcel = next(row for row in recovered.json()["intents"] if row["id"] == intent_id)
        assert parcel["status"] == "CONFIRMED"
        assert _by_name(recovered.json())["Whisky"]["settled_by"] == ["Astra"]

    # And the worker's sweep does the same unattended, for parcels nobody opens.
    # This one is already settled, so the sweep has nothing left to do with it.
    with Session(engine) as db:
        set_platform_db_context(db)
        assert uuid.UUID(transaction_id) not in recover_unapplied_results(db)
        assert db.get(PaymentIntent, uuid.UUID(intent_id)).status.value == "CONFIRMED"


@pytest.mark.asyncio
async def test_s25_1_a_refund_on_an_open_parcel_holds_the_line_until_someone_reconciles():
    """The second review refused the easy answer twice, and was right.

    Cancelling claimed nothing was sent. Failing released the whole reserve on
    the strength of a word — and a refund can be partial, while the adapter
    contract carries no reversed amount. With no evidence of an integral
    reversal, releasing the line is a financial decision this code does not get
    to make. The reserve is held and the fact is written down.
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "RefundOpen")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "RFO")
        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra",
                                 binding=tef["binding"]["id"])
        intent = await _pending(created)
        sent = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": intent["id"], "payment_device_binding_id": tef["binding"]["id"],
                 "actor_id": actor})

        refunded = await client.post(
            f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}/transactions/{sent.json()['transaction']['id']}/result",
            json={"tenant_id": tenant_id, "store_id": store["id"], "pairing_code": tef["pairing_code"],
                  "status": "REFUNDED", "failure_reason": "Estornado no adquirente"},
        )
        assert refunded.status_code == 200, refunded.text
        body = refunded.json()["negotiation"]
        parcel = next(row for row in body["intents"] if row["id"] == intent["id"])
        assert parcel["status"] == "PROCESSING", "estorno sem prova de reversão não encerra a parcela"
        assert parcel["cancel_reason"] is None and parcel["canceled_at"] is None
        assert [str(row["kind"]) for row in body["divergences"]] == ["REFUND_WITHOUT_CAPTURE"]
        # The line stays held: no saldo is released without evidence.
        assert float(_by_name(body)["Whisky"]["available_amount"]) == 0

        # And it cannot be released by hand either, for the same reason.
        blocked = await client.post(
            f"/api/v1/negotiations/intents/{intent['id']}/cancel",
            headers={**headers, "Idempotency-Key": f"cancel-{uuid.uuid4()}"},
            json={"reason": "Quero liberar mesmo assim", "actor_id": actor},
        )
        assert blocked.status_code == 409, blocked.text


@pytest.mark.asyncio
async def test_s25_1_a_settled_parcel_is_never_sent_to_the_card_machine_again():
    """Retries and queries stay valid; a closed parcel stops being executable."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "NoReExec")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        lines = _by_name(negotiation)
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "NRX")

        given_back = await _reserve(client, headers, negotiation["id"], actor, 60,
                                    lines["Pizza"]["order_item_id"], "Ninguem",
                                    binding=tef["binding"]["id"])
        canceled_id = (await _pending(given_back))["id"]
        assert (await client.post(
            f"/api/v1/negotiations/intents/{canceled_id}/cancel",
            headers={**headers, "Idempotency-Key": f"cancel-{uuid.uuid4()}"},
            json={"reason": "Desistiu antes de enviar", "actor_id": actor},
        )).status_code == 200
        refused = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": canceled_id, "payment_device_binding_id": tef["binding"]["id"],
                 "actor_id": actor})
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "INTENT_NOT_EXECUTABLE"

        settled = await _reserve(client, headers, negotiation["id"], actor, 40,
                                 lines["Whisky"]["order_item_id"], "Astra", binding=tef["binding"]["id"])
        settled_id = (await _pending(settled))["id"]
        first = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": settled_id, "payment_device_binding_id": tef["binding"]["id"],
                 "actor_id": actor})
        transaction_id = first.json()["transaction"]["id"]
        await client.post(
            f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}/transactions/{transaction_id}/result",
            json={"tenant_id": tenant_id, "store_id": store["id"], "pairing_code": tef["pairing_code"],
                  "status": "CONFIRMED", "nsu": "NSU-1", "authorization_code": "OK"},
        )
        again = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": settled_id, "payment_device_binding_id": tef["binding"]["id"],
                 "actor_id": actor})
        assert again.status_code == 409, again.text
        assert again.json()["detail"]["code"] in {"INTENT_NOT_EXECUTABLE", "CHARGE_ALREADY_SETTLED"}

        query = await client.post(f"/api/v1/negotiations/intents/{settled_id}/query",
                                  headers=headers, json={"actor_id": actor})
        assert query.status_code == 200, query.text
        assert float(_by_name(query.json())["Whisky"]["settled_amount"]) == 40


@pytest.mark.asyncio
async def test_s25_1_a_stale_answer_never_walks_the_charge_backwards():
    """A queued UNKNOWN arriving after the acquirer already said CONFIRMED would
    reopen a closed charge and, with it, the reserve on the line."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Stale")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "STL")
        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra",
                                 binding=tef["binding"]["id"])
        intent = await _pending(created)
        sent = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": intent["id"], "payment_device_binding_id": tef["binding"]["id"],
                 "actor_id": actor})
        transaction_id = sent.json()["transaction"]["id"]
        result_url = f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}/transactions/{transaction_id}/result"
        base = {"tenant_id": tenant_id, "store_id": store["id"], "pairing_code": tef["pairing_code"]}

        confirmed = await client.post(result_url, json={**base, "status": "CONFIRMED", "nsu": "NSU-1"})
        assert confirmed.status_code == 200, confirmed.text

        stale = await client.post(result_url, json={**base, "status": "UNKNOWN"})
        assert stale.status_code == 200, stale.text
        assert stale.json()["transaction"]["status"] == "CONFIRMED", "a transação não retrocede"
        body = stale.json()["negotiation"]
        parcel = next(row for row in body["intents"] if row["id"] == intent["id"])
        assert parcel["status"] == "CONFIRMED"
        assert float(_by_name(body)["Whisky"]["settled_amount"]) == 40
        assert [str(row["kind"]) for row in body["divergences"]] == ["STATE_REGRESSION_REFUSED"]

        await client.post(result_url, json={**base, "status": "UNKNOWN"})
        with Session(engine) as db:
            set_platform_db_context(db)
            rows = db.exec(select(PaymentSettlementDivergence).where(
                PaymentSettlementDivergence.payment_intent_id == uuid.UUID(intent["id"]),
            )).all()
            assert len(rows) == 1, rows


@pytest.mark.asyncio
async def test_s25_1_a_reserve_abandoned_before_reaching_the_tef_still_expires():
    """The eligibility hole: a parcel bound to a device but never executed had
    no clock at all, so it held its line forever."""
    from app.services.negotiation_service import expire_abandoned_reserves

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "BeforeTef")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "BTF")
        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra",
                                 binding=tef["binding"]["id"])
        intent = await _pending(created)
        assert intent["reserve_expires_at"] is not None

    with Session(engine) as db:
        set_platform_db_context(db)
        row = db.get(PaymentIntent, uuid.UUID(intent["id"]))
        row.reserve_expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.add(row); db.commit()
        assert uuid.UUID(intent["id"]) in expire_abandoned_reserves(db)
        reason = db.get(PaymentIntent, uuid.UUID(intent["id"])).cancel_reason
        # The wording is about the declared route, never about the drawer.
        assert "declarado e nunca enviado ao provider" in reason

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        state = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        assert float(_by_name(state)["Whisky"]["available_amount"]) == 40


@pytest.mark.asyncio
async def test_s25_1_the_sweep_reaches_the_oldest_stuck_parcel_not_only_the_newest():
    """The filter has to be in the query.

    Taking the newest terminal transactions and *then* keeping the unapplied
    ones meant a backlog older than one page was never reached — and the oldest
    stuck parcel is precisely the one that has been holding a line the longest.
    """
    from app.services.negotiation_service import unapplied_results

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Backlog")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "BKL")
        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra",
                                 binding=tef["binding"]["id"])
        intent_id = (await _pending(created))["id"]
        sent = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": intent_id, "payment_device_binding_id": tef["binding"]["id"],
                 "actor_id": actor})
        transaction_id = sent.json()["transaction"]["id"]

    with Session(engine) as db:
        set_platform_db_context(db)
        from app.models.provider import ProviderTransaction, ProviderTransactionStatusEnum
        row = db.get(ProviderTransaction, uuid.UUID(transaction_id))
        row.status = ProviderTransactionStatusEnum.CONFIRMED
        # Old enough to fall off any page ordered by recency.
        row.updated_at = datetime.utcnow() - timedelta(days=30)
        db.add(row); db.commit()

        # Even asking for a single row, the oldest stuck one comes first.
        found = unapplied_results(db, limit=1)
        assert [item.id for item in found] == [uuid.UUID(transaction_id)], found
        # And every row it returns really is unapplied, filtered by the database.
        for item in unapplied_results(db, limit=50):
            assert db.get(PaymentIntent, item.payment_intent_id).status.value in {"PENDING", "PROCESSING"}


@pytest.mark.asyncio
async def test_s25_1_one_damaged_row_does_not_block_the_queue_behind_it():
    """A sweep that aborts on the first bad row never drains a backlog."""
    from app.services import negotiation_service
    from app.services.provider_service import recover_unapplied_results

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "Damaged")
        tenant_id = headers["X-Tenant-ID"]
        register_id = await _register(client, headers, store, actor)
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        tef = await _tef(client, headers, {"id": tenant_id}, store, actor, register_id, "DMG")
        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra",
                                 binding=tef["binding"]["id"])
        intent_id = (await _pending(created))["id"]
        sent = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": intent_id, "payment_device_binding_id": tef["binding"]["id"],
                 "actor_id": actor})
        good_transaction = sent.json()["transaction"]["id"]

    with Session(engine) as db:
        set_platform_db_context(db)
        from app.models.provider import ProviderTransaction, ProviderTransactionStatusEnum
        from app.models.provider import PaymentExecutionEvent
        good = db.get(ProviderTransaction, uuid.UUID(good_transaction))
        good.status = ProviderTransactionStatusEnum.CONFIRMED
        db.add(good)
        # A row whose audit chain is gone: unreplayable, and older than the
        # healthy one so the sweep meets it first.
        damaged = ProviderTransaction(
            tenant_id=good.tenant_id, store_id=good.store_id,
            payment_intent_id=good.payment_intent_id,
            payment_device_binding_id=good.payment_device_binding_id,
            provider_configuration_id=good.provider_configuration_id,
            bridge_terminal_id=good.bridge_terminal_id, provider_code=good.provider_code,
            adapter_version=good.adapter_version, correlation_id=str(uuid.uuid4()),
            idempotency_key=f"damaged-{uuid.uuid4()}", request_hash="0" * 64,
            created_by=good.created_by, status=ProviderTransactionStatusEnum.CONFIRMED,
        )
        damaged.updated_at = datetime.utcnow() - timedelta(days=60)
        db.add(damaged); db.commit()
        assert db.exec(select(PaymentExecutionEvent).where(
            PaymentExecutionEvent.provider_transaction_id == damaged.id,
        )).all() == []

        # A fila é global e não drena sozinha: uma linha cujo resultado é
        # aplicável mas cuja parcela continua aberta permanece nela para sempre
        # e ocupa um lugar do lote. Com lote fixo de 50, bastavam 49 linhas
        # alheias para que a linha saudável deste teste — a mais nova, e a fila
        # é varrida da mais antiga para a mais nova — ficasse fora da janela, e
        # o teste falhava por volume de banco, não por regressão.
        #
        # Medir a fila e pedir um lote que a cubra mantém exatamente o que este
        # teste prova: a danificada é pulada, e a saudável atrás dela é aplicada.
        backlog = len(negotiation_service.unapplied_results(db, limit=10_000))
        recovered = recover_unapplied_results(db, limit=backlog)
        # The damaged row is skipped and the healthy one behind it is applied.
        assert damaged.id not in recovered
        assert uuid.UUID(good_transaction) in recovered
        assert db.get(PaymentIntent, uuid.UUID(intent_id)).status.value == "CONFIRMED"

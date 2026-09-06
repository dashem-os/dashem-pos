"""ADR-030 — devolver dinheiro sem fingir que ele nunca entrou.

O S25.1 fechou com um bloqueio declarado: uma parcela confirmada dentro de uma
conta ainda aberta não tinha estorno, porque o estorno que existia opera sobre
`Payment`, e `Payment` só nasce quando a venda é materializada. A mesa que
continua servindo depois que o primeiro amigo pagou a sua parte não tem
`Payment`.

Duas rodadas de revisão recusaram atalhos aqui, e tinham razão nas duas: tratar
estorno como cancelamento de reserva afirma que nada foi enviado, e liberar a
reserva inteira pela palavra do provider ignora que estorno pode ser parcial.

A regra que estes testes defendem: um estorno *pedido* não move saldo nenhum. Só
o valor comprovadamente revertido move, e o que conta como prova é a mesma coisa
que comprovou a entrada — o movimento de caixa, a resposta do adquirente com
valor declarado, ou a palavra nomeada de uma pessoa.
"""

import uuid

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.negotiation import PaymentAllocation, PaymentIntent, PaymentIntentRefund

from test_s25_item_settlement import BASE_URL, _by_name, _open, _table_with_menu
from test_s25_1_payment_recovery import _pending, _register, _reserve, _tef


async def _cash_shift(client, headers, store, actor, register_id):
    opened = await client.post("/api/v1/cash/sessions/open", headers=headers, json={
        "store_id": store["id"], "register_id": register_id,
        "operator_id": actor, "opening_balance": 200.0,
    })
    assert opened.status_code == 200, opened.text
    return opened.json()


async def _settled_cash(client, headers, negotiation_id, actor, amount, item_id, cash_session_id):
    """Dinheiro que entrou pela gaveta e foi confirmado."""
    created = await client.post(f"/api/v1/negotiations/{negotiation_id}/intents", headers={
        **headers, "Idempotency-Key": f"intent-{uuid.uuid4()}",
    }, json={
        "method": "CASH", "amount": amount, "actor_id": actor, "payer_label": "Astra",
        "cash_session_id": cash_session_id, "tendered_amount": amount,
        "allocations": [{"amount": amount, "order_item_id": item_id}],
    })
    assert created.status_code == 200, created.text
    intent = await _pending(created)
    confirmed = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/confirm", headers={
        **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
    }, json={"actor_id": actor})
    assert confirmed.status_code == 200, confirmed.text
    return intent, confirmed.json()


async def _settled_manual(client, headers, negotiation_id, actor, amount, item_id):
    """PIX recebido na mão: entrou pela palavra de uma pessoa."""
    created = await _reserve(client, headers, negotiation_id, actor, amount, item_id, "Astra")
    assert created.status_code == 200, created.text
    intent = await _pending(created)
    confirmed = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/confirm", headers={
        **headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}",
    }, json={"actor_id": actor})
    assert confirmed.status_code == 200, confirmed.text
    return intent, confirmed.json()


def _parcel(projection, intent_id):
    return next(row for row in projection["intents"] if row["id"] == intent_id)


@pytest.mark.asyncio
async def test_s25_2_cash_refund_leaves_the_drawer_and_gives_the_line_back():
    """O dinheiro sai da gaveta, e a linha volta a poder ser paga por outro."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "RefundCash")
        negotiation = await _open(client, headers, store, table_session, actor)
        register_id = await _register(client, headers, store, actor)
        shift = await _cash_shift(client, headers, store, actor, register_id)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]

        intent, paid = await _settled_cash(
            client, headers, negotiation["id"], actor, 40, whisky, shift["id"],
        )
        assert _by_name(paid)["Whisky"]["is_paid"] is True
        assert float(_by_name(paid)["Whisky"]["available_amount"]) == 0
        assert _parcel(paid, intent["id"])["can_refund"] is True

        refunded = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund", headers={
            **headers, "Idempotency-Key": f"refund-{uuid.uuid4()}",
        }, json={"amount": 40, "reason": "Cliente devolveu a bebida", "actor_id": actor})
        assert refunded.status_code == 200, refunded.text
        body = refunded.json()

        # A linha volta a ficar disponível: outra pessoa pode pagá-la.
        line = _by_name(body)["Whisky"]
        assert float(line["available_amount"]) == 40
        assert float(line["settled_amount"]) == 0
        assert float(line["refunded_amount"]) == 40
        assert line["is_paid"] is False

        # E a parcela continua confirmada: o dinheiro entrou, e isso é verdade.
        parcel = _parcel(body, intent["id"])
        assert parcel["status"] == "CONFIRMED"
        assert float(parcel["amount"]) == 40
        assert float(parcel["refunded_amount"]) == 40
        assert parcel["can_refund"] is False and float(parcel["refundable_amount"]) == 0

        # A conta volta a dever o que devia.
        assert float(body["confirmed_amount"]) == 0
        assert float(body["gross_confirmed_amount"]) == 40
        assert float(body["refunded_amount"]) == 40
        assert float(body["remaining_amount"]) == float(body["total_due"])

        record = body["refunds"][0]
        assert record["route"] == "CASH" and record["status"] == "CONFIRMED"
        assert float(record["reverted_amount"]) == 40

        # O movimento compensatório existe, e o da entrada continua lá.
        movements = (await client.get(
            f"/api/v1/cash/sessions/{shift['id']}/movements", headers=headers,
        )).json()
        kinds = [row["movement_type"] for row in movements]
        assert kinds.count("REFUND") == 1 and kinds.count("SALE_PAYMENT") == 1


@pytest.mark.asyncio
async def test_s25_2_a_cash_refund_without_an_open_register_is_refused_and_writes_nothing():
    """Sem gaveta aberta não há de onde tirar o dinheiro — e nada fica pendente."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "RefundClosed")
        negotiation = await _open(client, headers, store, table_session, actor)
        register_id = await _register(client, headers, store, actor)
        shift = await _cash_shift(client, headers, store, actor, register_id)
        pizza = _by_name(negotiation)["Pizza"]["order_item_id"]
        intent, _ = await _settled_cash(
            client, headers, negotiation["id"], actor, 60, pizza, shift["id"],
        )

        closed = await client.post(f"/api/v1/cash/sessions/{shift['id']}/close", headers=headers, json={
            "closing_balance": 260.0, "operator_id": actor,
        })
        assert closed.status_code == 200, closed.text

        refused = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund", headers={
            **headers, "Idempotency-Key": f"refund-{uuid.uuid4()}",
        }, json={"amount": 60, "reason": "Cliente desistiu da pizza", "actor_id": actor})
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "REFUND_NEEDS_OPEN_REGISTER"

        # Caixa fechado não é um estorno esperando: é condição a satisfazer.
        # Nada pode ter ficado pendente segurando o dinheiro da parcela.
        with Session(engine) as db:
            set_platform_db_context(db)
            left = db.exec(select(PaymentIntentRefund).where(
                PaymentIntentRefund.payment_intent_id == uuid.UUID(intent["id"]),
            )).all()
        assert left == []

        state = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        assert float(_by_name(state)["Pizza"]["settled_amount"]) == 60
        assert _parcel(state, intent["id"])["can_refund"] is True


@pytest.mark.asyncio
async def test_s25_2_a_partial_refund_returns_only_what_came_back():
    """Metade volta, metade fica — e a soma continua fechando."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "RefundPart")
        negotiation = await _open(client, headers, store, table_session, actor)
        register_id = await _register(client, headers, store, actor)
        shift = await _cash_shift(client, headers, store, actor, register_id)
        items = _by_name(negotiation)
        pizza = items["Pizza"]["order_item_id"]
        intent, _ = await _settled_cash(
            client, headers, negotiation["id"], actor, 60, pizza, shift["id"],
        )

        partial = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund", headers={
            **headers, "Idempotency-Key": f"refund-{uuid.uuid4()}",
        }, json={"amount": 25, "reason": "Metade da pizza voltou fria", "actor_id": actor})
        assert partial.status_code == 200, partial.text
        body = partial.json()

        line = _by_name(body)["Pizza"]
        assert float(line["settled_amount"]) == 35
        assert float(line["available_amount"]) == 25
        assert float(line["refunded_amount"]) == 25
        assert line["is_paid"] is False

        parcel = _parcel(body, intent["id"])
        assert parcel["status"] == "CONFIRMED"
        assert float(parcel["refunded_amount"]) == 25
        assert float(parcel["refundable_amount"]) == 35
        assert parcel["can_refund"] is True

        # O resto ainda pode voltar, e aí a linha fica inteira de novo.
        rest = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund", headers={
            **headers, "Idempotency-Key": f"refund-{uuid.uuid4()}",
        }, json={"amount": 35, "reason": "O cliente devolveu o resto", "actor_id": actor})
        assert rest.status_code == 200, rest.text
        assert float(_by_name(rest.json())["Pizza"]["available_amount"]) == 60
        assert float(_parcel(rest.json(), intent["id"])["refundable_amount"]) == 0

        # E um centavo a mais é recusado, porque não há mais de onde tirar.
        over = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund", headers={
            **headers, "Idempotency-Key": f"refund-{uuid.uuid4()}",
        }, json={"amount": 1, "reason": "Tentativa de estornar a mais", "actor_id": actor})
        assert over.status_code == 409, over.text
        assert over.json()["detail"]["code"] == "REFUND_EXCEEDS_PARCEL"


@pytest.mark.asyncio
async def test_s25_2_the_same_command_twice_is_one_refund():
    """Dois toques no botão devolvem o mesmo dinheiro uma vez só."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "RefundOnce")
        negotiation = await _open(client, headers, store, table_session, actor)
        register_id = await _register(client, headers, store, actor)
        shift = await _cash_shift(client, headers, store, actor, register_id)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        intent, _ = await _settled_cash(
            client, headers, negotiation["id"], actor, 40, whisky, shift["id"],
        )

        key = f"refund-{uuid.uuid4()}"
        body = {"amount": 40, "reason": "Cliente devolveu a bebida", "actor_id": actor}
        first = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund",
                                  headers={**headers, "Idempotency-Key": key}, json=body)
        again = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund",
                                  headers={**headers, "Idempotency-Key": key}, json=body)
        assert first.status_code == 200 and again.status_code == 200, again.text
        assert len(again.json()["refunds"]) == 1
        assert float(again.json()["refunded_amount"]) == 40

        # Uma gaveta, um movimento de saída.
        movements = (await client.get(
            f"/api/v1/cash/sessions/{shift['id']}/movements", headers=headers,
        )).json()
        assert [row["movement_type"] for row in movements].count("REFUND") == 1

        # A mesma chave com outro comando é conflito, não um segundo estorno.
        different = await client.post(
            f"/api/v1/negotiations/intents/{intent['id']}/refund",
            headers={**headers, "Idempotency-Key": key},
            json={"amount": 10, "reason": "Outro valor", "actor_id": actor},
        )
        assert different.status_code == 409, different.text


@pytest.mark.asyncio
async def test_s25_2_a_card_refund_moves_nothing_until_the_acquirer_says_how_much():
    """Cartão só volta pela resposta do adquirente, e só com valor declarado."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "RefundCard")
        negotiation = await _open(client, headers, store, table_session, actor)
        register_id = await _register(client, headers, store, actor)
        tef = await _tef(client, headers, {"id": headers["X-Tenant-ID"]}, store, actor, register_id, "RFD")
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]

        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra",
                                 binding=tef["binding"]["id"])
        assert created.status_code == 200, created.text
        intent = await _pending(created)
        executed = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"exec-{uuid.uuid4()}",
        }, json={"payment_intent_id": intent["id"],
                 "payment_device_binding_id": tef["binding"]["id"], "actor_id": actor})
        assert executed.status_code == 200, executed.text
        transaction_id = executed.json()["transaction"]["id"]
        approved = await client.post(
            f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}"
            f"/transactions/{transaction_id}/result",
            json={"tenant_id": headers["X-Tenant-ID"], "store_id": store["id"],
                  "pairing_code": tef["pairing_code"], "status": "CONFIRMED",
                  "nsu": "NSU5150", "authorization_code": "OK1234"},
        )
        assert approved.status_code == 200, approved.text

        asked = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund", headers={
            **headers, "Idempotency-Key": f"refund-{uuid.uuid4()}",
        }, json={"amount": 40, "reason": "Cliente devolveu a bebida", "actor_id": actor})
        assert asked.status_code == 200, asked.text
        body = asked.json()

        # Pedido, enfileirado no bridge — e nada liberado.
        record = body["refunds"][0]
        assert record["route"] == "PROVIDER" and record["status"] == "PENDING"
        assert float(record["reverted_amount"]) == 0
        parcel = _parcel(body, intent["id"])
        assert parcel["awaiting_refund"] is True
        assert float(parcel["refunded_amount"]) == 0
        assert float(parcel["refundable_amount"]) == 0  # o pedido segura o resto
        assert float(_by_name(body)["Whisky"]["settled_amount"]) == 40
        assert float(_by_name(body)["Whisky"]["available_amount"]) == 0
        assert float(body["confirmed_amount"]) == 40

        # Uma resposta sem quantia não é prova: nada se move, e o fato fica.
        vague = await client.post(
            f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}"
            f"/transactions/{transaction_id}/result",
            json={"tenant_id": headers["X-Tenant-ID"], "store_id": store["id"],
                  "pairing_code": tef["pairing_code"], "status": "REFUNDED"},
        )
        assert vague.status_code == 200, vague.text
        held = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        assert float(held["confirmed_amount"]) == 40
        assert held["refunds"][0]["status"] == "PENDING"
        assert any(row["kind"] == "REFUND_REQUIRES_REVERSAL" for row in held["divergences"])

        # Com quantia declarada, o estorno tem prova e o saldo enfim se move.
        proven = await client.post(
            f"/api/v1/providers/bridge/terminals/{tef['terminal']['id']}"
            f"/transactions/{transaction_id}/result",
            json={"tenant_id": headers["X-Tenant-ID"], "store_id": store["id"],
                  "pairing_code": tef["pairing_code"], "status": "REFUNDED",
                  "refunded_amount": 40},
        )
        assert proven.status_code == 200, proven.text
        final = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        assert final["refunds"][0]["status"] == "CONFIRMED"
        assert float(final["refunds"][0]["reverted_amount"]) == 40
        assert float(final["confirmed_amount"]) == 0
        assert float(_by_name(final)["Whisky"]["available_amount"]) == 40
        assert _parcel(final, intent["id"])["status"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_s25_2_a_reserve_is_cancelled_and_never_refunded():
    """Não se estorna o que ainda não entrou; para isso existe o cancelamento."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "RefundOpen")
        negotiation = await _open(client, headers, store, table_session, actor)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        created = await _reserve(client, headers, negotiation["id"], actor, 40, whisky, "Astra")
        intent = await _pending(created)

        refused = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund", headers={
            **headers, "Idempotency-Key": f"refund-{uuid.uuid4()}",
        }, json={"amount": 40, "reason": "Tentativa de estornar reserva", "actor_id": actor})
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "PARCEL_NOT_SETTLED"
        assert _parcel(created.json(), intent["id"])["can_refund"] is False


@pytest.mark.asyncio
async def test_s25_2_a_manual_receipt_is_reversed_by_a_named_person():
    """PIX na mão entrou pela palavra de alguém, e sai pela palavra de alguém."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "RefundManual")
        negotiation = await _open(client, headers, store, table_session, actor)
        hamburger = _by_name(negotiation)["Hamburguer"]["order_item_id"]
        intent, _ = await _settled_manual(client, headers, negotiation["id"], actor, 35, hamburger)

        refunded = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund", headers={
            **headers, "Idempotency-Key": f"refund-{uuid.uuid4()}",
        }, json={"amount": 35, "reason": "PIX devolvido ao cliente pelo app do banco",
                 "actor_id": actor})
        assert refunded.status_code == 200, refunded.text
        body = refunded.json()
        record = body["refunds"][0]
        assert record["route"] == "MANUAL" and record["status"] == "CONFIRMED"
        assert float(_by_name(body)["Hamburguer"]["available_amount"]) == 35
        # Sem motivo não há estorno, porque a trilha é o contrapeso da autoridade.
        empty = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund", headers={
            **headers, "Idempotency-Key": f"refund-{uuid.uuid4()}",
        }, json={"amount": 1, "reason": "  ", "actor_id": actor})
        assert empty.status_code == 422, empty.text


@pytest.mark.asyncio
async def test_s25_2_the_financial_trail_survives_the_reversal():
    """Estornar é escrever ao lado, nunca reescrever o que aconteceu."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "RefundTrail")
        negotiation = await _open(client, headers, store, table_session, actor)
        register_id = await _register(client, headers, store, actor)
        shift = await _cash_shift(client, headers, store, actor, register_id)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        intent, _ = await _settled_cash(
            client, headers, negotiation["id"], actor, 40, whisky, shift["id"],
        )
        refunded = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund", headers={
            **headers, "Idempotency-Key": f"refund-{uuid.uuid4()}",
        }, json={"amount": 40, "reason": "Cliente devolveu a bebida", "actor_id": actor})
        assert refunded.status_code == 200, refunded.text

        with Session(engine) as db:
            set_platform_db_context(db)
            row = db.exec(select(PaymentIntent).where(
                PaymentIntent.id == uuid.UUID(intent["id"]),
            )).one()
            allocations = db.exec(select(PaymentAllocation).where(
                PaymentAllocation.payment_intent_id == uuid.UUID(intent["id"]),
            )).all()

        # A parcela não foi reescrita: valor, autor e data continuam sendo os
        # que sempre foram. Quem ler depois vê que o dinheiro entrou e voltou.
        assert row.status.value == "CONFIRMED"
        assert float(row.amount) == 40
        assert row.confirmed_at is not None and row.confirmed_by is not None
        assert row.canceled_at is None and row.cancel_reason is None
        assert [float(item.amount) for item in allocations] == [40]

        events = (await client.get(
            f"/api/v1/negotiations/{negotiation['id']}", headers=headers,
        )).json()
        assert float(events["gross_confirmed_amount"]) == 40
        assert float(events["refunded_amount"]) == 40


@pytest.mark.asyncio
async def test_s25_2_a_neighbour_never_refunds_this_bill():
    """O estorno é do dono da conta, e de mais ninguém."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        headers, store, actor, table_session = await _table_with_menu(client, "RefundMine")
        negotiation = await _open(client, headers, store, table_session, actor)
        register_id = await _register(client, headers, store, actor)
        shift = await _cash_shift(client, headers, store, actor, register_id)
        whisky = _by_name(negotiation)["Whisky"]["order_item_id"]
        intent, _ = await _settled_cash(
            client, headers, negotiation["id"], actor, 40, whisky, shift["id"],
        )

        stranger_headers, *_ = await _table_with_menu(client, "RefundYours")
        intruded = await client.post(f"/api/v1/negotiations/intents/{intent['id']}/refund", headers={
            **stranger_headers, "Idempotency-Key": f"refund-{uuid.uuid4()}",
        }, json={"amount": 40, "reason": "Estorno do vizinho", "actor_id": str(uuid.uuid4())})
        assert intruded.status_code == 404, intruded.text

        intact = (await client.get(f"/api/v1/negotiations/{negotiation['id']}", headers=headers)).json()
        assert float(_by_name(intact)["Whisky"]["settled_amount"]) == 40
        assert intact["refunds"] == []


def test_s25_2_giving_money_back_needs_its_own_permission():
    """Estornar não é criar parcela nem soltar reserva que nunca saiu."""
    from app.core.permissions import route_requirement

    refund = route_requirement("POST", "/api/v1/negotiations/intents/abc/refund")
    cancel = route_requirement("POST", "/api/v1/negotiations/intents/abc/cancel")
    create = route_requirement("POST", "/api/v1/negotiations/abc/intents")
    assert refund.permission == "checkout.payment.refund"
    assert cancel.permission == "checkout.payment.cancel"
    assert create.permission == "checkout.payment"
    assert len({refund.permission, cancel.permission, create.permission}) == 3

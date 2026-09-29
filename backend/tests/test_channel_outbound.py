"""S10.1, step 6: notices to the channel, and what each answer does to them.

Proposal `docs/product/proposta-s10-1-channel-hub.md`, §3.6. The channel is the
reference connector, driven by this test: every answer — delivered, refused,
timed out, unable to confirm — is simulated here. What is real: the queue, the
lease, the backoff, the database state after each answer, and the rule that no
transaction is held while the channel is called.

What these tests prove, and only that:
- a notice is `DELIVERED` only when the adapter says so (R12);
- a transient failure waits longer each time and ends in `DEAD_LETTER`, which a
  person can resend (R12);
- a timeout resends the same identity when the channel deduplicates (E4), and
  otherwise asks the channel before sending again, never sending twice while it
  cannot say (E5, R13);
- a lost lease does not write another attempt's answer;
- a capability the adapter did not declare is never called (R18);
- nothing personal reaches the outbox, and a notice naming a person is refused (P4);
- an unavailable or slow channel during notice delivery has `checkedout == 0`
  at connector entry (including on a repeated `Idempotency-Key`) and neither
  blocks a local POS counter sale nor shows regression above the threshold in
  this measurement (R14, H10).
"""

import asyncio
from contextlib import asynccontextmanager
import json
import math
import os
from pathlib import Path
import platform
import socket
import statistics
import threading
import time
import uuid
from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, select
import uvicorn

import app.main  # noqa: F401 — compõe a aplicação como a API
from app.core.config import settings
from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.catalog import InventoryBalance
from app.models.channel_hub import ChannelOutboundMessage, ChannelOutboundStatusEnum
from app.models.reliability import OutboxEvent
from app.models.sale import Sale, SaleStatusEnum
from app.modules.channels import inbox, outbound
from app.modules.channels.adapters.reference import ReferenceChannelAdapter
from app.modules.channels.contracts import ChannelCapability, DeliveryOutcome, DeliveryResult
from app.services import payment_service
from test_channel_inbox import _connected, _event, _line, _mapping, _receive, _row

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")
R14_WARMUP_SAMPLES = 3
R14_MEASURED_SAMPLES = 15


async def _external_order(client, prefix):
    tenant, headers, actor, _product, connection = await _connected(client, prefix, "ITEM-A")
    order_ref = f"pedido-{uuid.uuid4()}"
    placed = _event(connection["merchant_external_id"], "ORDER_PLACED", order_ref, lines=[_line("l1", "ITEM-A", 1)])
    _receive(placed)
    assert inbox.process_event(_row(placed["id"]).id).value == "APPLIED"
    context = TenantContext(tenant_id=uuid.UUID(tenant["id"]), store_id=uuid.UUID(connection["store_id"]), user_id=uuid.UUID(actor))
    return context, headers, actor, _mapping(connection["id"], order_ref).order_id


def _queue(context, order_id, message_type="ORDER_ACCEPTED", payload=None):
    with Session(engine) as db:
        set_platform_db_context(db)
        message = outbound.enqueue(
            db, context, order_id, message_type=message_type, payload=payload or {"status": "ACCEPTED"},
            actor_id=context.user_id, idempotency_key=f"aviso-{uuid.uuid4()}",
        )
        return message.id


def _message(message_id) -> ChannelOutboundMessage:
    with Session(engine) as db:
        set_platform_db_context(db)
        return db.get(ChannelOutboundMessage, message_id)


@pytest.mark.asyncio
async def test_aviso_so_e_entregue_quando_o_canal_confirma():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        context, *_rest, order_id = await _external_order(client, "AvisoOk")
    message_id = _queue(context, order_id)
    assert _message(message_id).status == ChannelOutboundStatusEnum.PENDING, "na fila não é entrega"
    assert outbound.deliver(message_id) == ChannelOutboundStatusEnum.DELIVERED
    delivered = _message(message_id)
    assert delivered.delivered_at is not None and delivered.provider_reference == f"ref-{message_id}"
    assert delivered.attempt_count == 1 and delivered.last_error_code is None
    assert outbound.deliver(message_id) is None, "entregue não sai de novo"


@pytest.mark.asyncio
async def test_falha_transitoria_espera_cada_vez_mais_esgota_e_uma_pessoa_reenvia(monkeypatch):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        context, headers, actor, order_id = await _external_order(client, "AvisoRetry")
        message_id = _queue(context, order_id)
        monkeypatch.setattr(ReferenceChannelAdapter, "send_notice",
                            lambda self, notice: DeliveryOutcome(DeliveryResult.RETRYABLE, code="CHANNEL_UNAVAILABLE"))
        now = datetime.utcnow()
        waits = []
        for attempt in range(1, outbound.MAX_ATTEMPTS + 1):
            status = outbound.deliver(message_id, now=now)
            row = _message(message_id)
            if attempt < outbound.MAX_ATTEMPTS:
                assert status == ChannelOutboundStatusEnum.RETRY and row.last_error_code == "CHANNEL_UNAVAILABLE"
                waits.append(row.next_retry_at - now)
                assert outbound.deliver(message_id, now=now + timedelta(seconds=1)) is None, "antes da espera não sai"
                now = row.next_retry_at + timedelta(seconds=1)
            else:
                assert status == ChannelOutboundStatusEnum.DEAD_LETTER
        assert waits == sorted(waits) and waits[0] < waits[-1], "a espera cresce"

        # Uma pessoa reenvia, pela rota, sob channel.manage; o servidor fala com o canal simulado de verdade.
        monkeypatch.undo()
        resent = await client.post(f"/api/v1/channels/outbound/{message_id}/resend", headers=headers, json={"actor_id": actor})
        assert resent.status_code == 200, resent.text
        assert resent.json()["status"] == "DELIVERED"
        not_again = await client.post(f"/api/v1/channels/outbound/{message_id}/resend", headers=headers, json={"actor_id": actor})
        assert not_again.status_code == 409 and not_again.json()["detail"]["code"] == "NOTICE_NOT_RESENDABLE"


@pytest.mark.asyncio
async def test_recusa_permanente_vai_direto_para_nao_entregue():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        context, *_rest, order_id = await _external_order(client, "AvisoPermanente")
    message_id = _queue(context, order_id, message_type="ORDER_TELEPORTED")
    assert outbound.deliver(message_id) == ChannelOutboundStatusEnum.DEAD_LETTER
    row = _message(message_id)
    assert row.attempt_count == 1 and row.last_error_code == "NOTICE_TYPE_NOT_SUPPORTED"


@pytest.mark.asyncio
async def test_tempo_esgotado_com_canal_que_deduplica_reenvia_a_mesma_identidade(monkeypatch):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        context, *_rest, order_id = await _external_order(client, "AvisoE4")
    message_id = _queue(context, order_id)
    seen = []

    def times_out_once(self, notice):
        seen.append(notice.notice_id)
        if len(seen) == 1:
            raise TimeoutError("o canal não respondeu")
        return DeliveryOutcome(DeliveryResult.DELIVERED, provider_reference="ref-e4")

    monkeypatch.setattr(ReferenceChannelAdapter, "send_notice", times_out_once)
    assert outbound.deliver(message_id) == ChannelOutboundStatusEnum.RETRY
    assert _message(message_id).last_error_code == "CALL_FAILED"
    later = _message(message_id).next_retry_at + timedelta(seconds=1)
    assert outbound.deliver(message_id, now=later) == ChannelOutboundStatusEnum.DELIVERED
    assert seen == [str(message_id), str(message_id)], "reenviar repete a identidade"


@pytest.mark.asyncio
async def test_tempo_esgotado_sem_deduplicacao_pergunta_antes_e_nunca_manda_duas_vezes_as_cegas(monkeypatch):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        context, *_rest, order_id = await _external_order(client, "AvisoE5")
    sends, answers = [], []

    def times_out(self, notice):
        sends.append(notice.notice_id)
        raise TimeoutError("o canal não respondeu")

    def confirm(self, notice):
        return answers.pop(0)

    monkeypatch.setattr(ReferenceChannelAdapter, "idempotent_delivery", False)
    monkeypatch.setattr(ReferenceChannelAdapter, "send_notice", times_out)
    monkeypatch.setattr(ReferenceChannelAdapter, "confirm_notice", confirm)

    arrived = _queue(context, order_id)
    assert outbound.deliver(arrived) == ChannelOutboundStatusEnum.UNCONFIRMED
    assert _message(arrived).last_error_code == "AMBIGUOUS:CALL_FAILED"
    answers.extend([None, True])
    now = _message(arrived).next_retry_at + timedelta(seconds=1)
    assert outbound.deliver(arrived, now=now) == ChannelOutboundStatusEnum.UNCONFIRMED, "o canal não sabe dizer: segue sem confirmação"
    now = _message(arrived).next_retry_at + timedelta(seconds=1)
    assert outbound.deliver(arrived, now=now) == ChannelOutboundStatusEnum.DELIVERED, "o canal confirma que chegou"
    assert sends == [str(arrived)], "nada foi mandado de novo enquanto o canal não sabia"

    lost = _queue(context, order_id)
    assert outbound.deliver(lost) == ChannelOutboundStatusEnum.UNCONFIRMED
    monkeypatch.setattr(ReferenceChannelAdapter, "send_notice",
                        lambda self, notice: (sends.append(notice.notice_id), DeliveryOutcome(DeliveryResult.DELIVERED))[1])
    answers.append(False)
    now = _message(lost).next_retry_at + timedelta(seconds=1)
    assert outbound.deliver(lost, now=now) == ChannelOutboundStatusEnum.DELIVERED, "o canal disse que não chegou: agora manda"
    assert sends.count(str(lost)) == 2


@pytest.mark.asyncio
async def test_reenviar_um_nao_entregue_ambiguo_pergunta_ao_canal_antes(monkeypatch):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        context, *_rest, order_id = await _external_order(client, "AvisoReenvioAmbiguo")
    sends = []
    monkeypatch.setattr(ReferenceChannelAdapter, "idempotent_delivery", False)
    monkeypatch.setattr(ReferenceChannelAdapter, "send_notice",
                        lambda self, notice: (_ for _ in ()).throw(TimeoutError("sem resposta")) if not sends.append(notice.notice_id) else None)
    monkeypatch.setattr(ReferenceChannelAdapter, "confirm_notice", lambda self, notice: None)
    message_id = _queue(context, order_id)
    now = datetime.utcnow()
    status = outbound.deliver(message_id, now=now)
    while status != ChannelOutboundStatusEnum.DEAD_LETTER:
        now = _message(message_id).next_retry_at + timedelta(seconds=1)
        status = outbound.deliver(message_id, now=now)
    assert _message(message_id).last_error_code.startswith("AMBIGUOUS:")
    assert len(sends) == 1, "sem confirmação, nada foi mandado de novo"

    monkeypatch.setattr(ReferenceChannelAdapter, "confirm_notice", lambda self, notice: True)
    with Session(engine) as db:
        set_platform_db_context(db)
        row = outbound.resend(db, context, message_id, context.user_id)
        assert row.status == ChannelOutboundStatusEnum.DELIVERED
    assert len(sends) == 1, "o reenvio perguntou antes e o canal confirmou: não mandou de novo"


@pytest.mark.asyncio
async def test_resposta_de_tentativa_que_perdeu_o_lease_nao_e_escrita():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        context, *_rest, order_id = await _external_order(client, "AvisoLease")
    message_id = _queue(context, order_id)
    first = outbound.claim(message_id)  # e este processador some no meio da chamada
    later = datetime.utcnow() + timedelta(seconds=outbound.LEASE_SECONDS + 1)
    assert outbound.deliver(message_id, now=later) == ChannelOutboundStatusEnum.DELIVERED
    assert outbound._record(first, datetime.utcnow(), DeliveryOutcome(DeliveryResult.RETRYABLE, code="TARDE")) is None
    row = _message(message_id)
    assert row.status == ChannelOutboundStatusEnum.DELIVERED and row.last_error_code is None


@pytest.mark.asyncio
async def test_capacidade_nao_declarada_nunca_e_chamada(monkeypatch):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        context, *_rest, order_id = await _external_order(client, "AvisoSemCapacidade")
    message_id = _queue(context, order_id)
    monkeypatch.setattr(ReferenceChannelAdapter, "capabilities", frozenset({ChannelCapability.ORDER_INGRESS}))

    def must_not_be_called(self, notice):
        raise AssertionError("chamou capacidade não declarada")

    monkeypatch.setattr(ReferenceChannelAdapter, "send_notice", must_not_be_called)
    assert outbound.deliver(message_id) == ChannelOutboundStatusEnum.DEAD_LETTER
    assert _message(message_id).last_error_code == "CAPABILITY_NOT_DECLARED"


@pytest.mark.asyncio
async def test_aviso_nao_leva_pessoa_para_a_trilha_nem_aceita_carga_pessoal():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        context, headers, actor, order_id = await _external_order(client, "AvisoSemPessoa")
        refused = await client.post(f"/api/v1/channels/orders/{order_id}/outbound", headers={
            **headers, "Idempotency-Key": f"aviso-{uuid.uuid4()}",
        }, json={"message_type": "ORDER_DISPATCHED", "payload": {"entregador": {"customerPhone": "11900000000"}}, "actor_id": actor})
        assert refused.status_code == 422 and refused.json()["detail"]["code"] == "NOTICE_PAYLOAD_PERSONAL"
    message_id = _queue(context, order_id, payload={"status": "ACCEPTED", "estimated_minutes": 30})
    with Session(engine) as db:
        set_platform_db_context(db)
        queued = [event for event in db.exec(select(OutboxEvent).where(
            OutboxEvent.aggregate_type == "channel_outbound", OutboxEvent.aggregate_id == str(message_id),
        )).all()]
    assert queued, "a fila interna ouviu o aviso"
    for event in queued:
        assert "estimated_minutes" not in event.payload and '"payload"' not in event.payload, "conteúdo do aviso foi para a outbox"


@asynccontextmanager
async def _live_api():
    """Run the real FastAPI app over TCP in this process so both jobs share server, pool and DB."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app.main.app, host="127.0.0.1", port=port, log_level="error"))
    serve_task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
            yield client
    finally:
        server.should_exit = True
        await serve_task
        sock.close()


async def _local_pos_setup(client: httpx.AsyncClient, headers: dict, store_id: str, actor_id: str) -> tuple[str, str, str]:
    suffix = uuid.uuid4().hex[:8]
    register = (await client.post("/api/v1/cash/registers", headers=headers, json={
        "store_id": store_id, "name": "Caixa PDV R14", "code": f"R14-{suffix}",
    })).json()
    cash_session = (await client.post("/api/v1/cash/sessions/open", headers=headers, json={
        "store_id": store_id, "register_id": register["id"], "operator_id": actor_id, "opening_balance": 500.0,
    })).json()
    product = (await client.post("/api/v1/catalog/products", headers=headers, json={
        "name": "Produto Balcão R14", "sku": f"PDV-R14-{suffix}", "unit": "UN", "tracks_inventory": True,
    })).json()
    await client.post("/api/v1/catalog/prices", headers=headers, json={
        "product_id": product["id"], "store_id": store_id, "cost_price": 6.0, "sale_price": 15.0,
    })
    stocked = await client.post("/api/v1/inventory/adjust", headers=headers, json={
        "store_id": store_id, "product_id": product["id"], "actor_id": actor_id,
        "movement_type": "PURCHASE", "quantity": 200.0, "reason": "Estoque inicial R14",
    })
    assert stocked.status_code == 200, stocked.text
    return register["id"], cash_session["id"], product["id"]


async def _local_pos_sale(
    client: httpx.AsyncClient, headers: dict, store_id: str,
    register_id: str, cash_session_id: str, product_id: str, actor_id: str,
) -> dict:
    """Execute one representative 5-step counter sale through the real PDV API routes."""
    started_at = time.perf_counter()
    created = await client.post("/api/v1/sales", headers=headers, json={
        "store_id": store_id, "register_id": register_id, "seller_id": actor_id, "operation_mode": "COUNTER",
    })
    sale_id = created.json()["id"]
    added = await client.post(f"/api/v1/sales/{sale_id}/items", headers=headers, json={
        "product_id": product_id, "quantity": 1.0,
    })
    checked_out = await client.post(f"/api/v1/sales/{sale_id}/checkout", headers=headers, json={
        "actor_id": actor_id,
    })
    pay_created = await client.post("/api/v1/payments", headers={
        **headers, "Idempotency-Key": f"pay-create-{uuid.uuid4()}",
    }, json={
        "sale_id": sale_id, "method": "CASH", "amount": 15.0,
        "cash_session_id": cash_session_id, "tendered_amount": 15.0,
    })
    payment_id = pay_created.json()["id"]
    confirmed = await client.post(f"/api/v1/payments/{payment_id}/confirm", headers={
        **headers, "Idempotency-Key": f"pay-confirm-{uuid.uuid4()}",
    }, json={"actor_id": actor_id})
    finished_at = time.perf_counter()
    return {
        "sale_id": sale_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "latency_ms": round((finished_at - started_at) * 1000.0, 3),
        "status_codes": [
            created.status_code, added.status_code, checked_out.status_code,
            pay_created.status_code, confirmed.status_code,
        ],
        "sale_status": confirmed.json().get("sale_status"),
    }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = max(0, math.ceil(len(sorted_values) * fraction) - 1)
    return round(sorted_values[index], 3)


def _latency_summary(samples: list[dict]) -> dict:
    latencies = sorted(sample["latency_ms"] for sample in samples)
    return {
        "samples": len(latencies),
        "min_ms": round(latencies[0], 3),
        "p50_ms": round(statistics.median(latencies), 3),
        "p95_ms": _percentile(latencies, 0.95),
        "max_ms": round(latencies[-1], 3),
        "mean_ms": round(statistics.mean(latencies), 3),
        "all_http_200": all(sample["status_codes"] == [200, 200, 200, 200, 200] for sample in samples),
        "all_paid": all(sample["sale_status"] == "PAID" for sample in samples),
        "latencies_ms": latencies,
    }


def _r14_regression_limits(baseline_summary: dict) -> dict:
    """Criterion defined before comparing baseline vs channel unavailability.

    A local 5-step counter sale takes ~25-60 ms on local PostgreSQL. Using
    `max(factor * baseline, baseline + fixed_margin_ms)` prevents false failures
    from normal OS/container scheduling jitter while catching any real wait on
    an unavailable channel or connection pool stall.
    """
    return {
        "p50_max_ms": round(max(baseline_summary["p50_ms"] * 2.0, baseline_summary["p50_ms"] + 60.0), 3),
        "p95_max_ms": round(max(baseline_summary["p95_ms"] * 2.5, baseline_summary["p95_ms"] + 120.0), 3),
    }


def _r14_violations(
    baseline_summary: dict, unavailable_samples: list[dict],
    channel_entered_at: float, channel_exited_at: float,
) -> list[str]:
    summary = _latency_summary(unavailable_samples)
    limits = _r14_regression_limits(baseline_summary)
    reasons = []
    if not summary["all_http_200"] or not summary["all_paid"]:
        reasons.append("http_or_sale_status_failed")
    if any(
        not (channel_entered_at <= sample["started_at"] < sample["finished_at"] <= channel_exited_at)
        for sample in unavailable_samples
    ):
        reasons.append("sale_not_completed_while_channel_blocked")
    if summary["p50_ms"] > limits["p50_max_ms"]:
        reasons.append(f"p50_regression:{summary['p50_ms']}>{limits['p50_max_ms']}")
    if summary["p95_ms"] > limits["p95_max_ms"]:
        reasons.append(f"p95_regression:{summary['p95_ms']}>{limits['p95_max_ms']}")
    return reasons


@pytest.mark.asyncio
async def test_venda_local_no_pdv_segue_enquanto_o_envio_de_aviso_ao_canal_esta_bloqueado(monkeypatch):
    async with _live_api() as client:
        context, headers, actor, order_id = await _external_order(client, "AvisoR14")
        store_id = str(context.store_id)
        register_id, cash_session_id, pos_product_id = await _local_pos_setup(client, headers, store_id, actor)

        # 1. Aquecimento: prepara pool, mappers e rotas antes de medir.
        warmup_samples = [
            await _local_pos_sale(client, headers, store_id, register_id, cash_session_id, pos_product_id, actor)
            for _ in range(R14_WARMUP_SAMPLES)
        ]
        assert _latency_summary(warmup_samples)["all_http_200"]
        assert _latency_summary(warmup_samples)["all_paid"]

        # 2. Linha de base: canal ocioso, 15 vendas locais completas pelas rotas reais.
        baseline_samples = [
            await _local_pos_sale(client, headers, store_id, register_id, cash_session_id, pos_product_id, actor)
            for _ in range(R14_MEASURED_SAMPLES)
        ]
        baseline_summary = _latency_summary(baseline_samples)
        limits = _r14_regression_limits(baseline_summary)
        assert baseline_summary["all_http_200"] and baseline_summary["all_paid"]
        assert len({sample["sale_id"] for sample in baseline_samples}) == R14_MEASURED_SAMPLES

        # 3. Sob indisponibilidade do canal: o conector trava dentro de `send_notice`
        # e só é liberado depois que todas as 15 vendas locais terminaram.
        send_blocked = threading.Event()
        release_send = threading.Event()
        channel_window: dict = {}

        def blocked_channel_send(self, notice):
            channel_window["notice_id"] = uuid.UUID(notice.notice_id)
            channel_window["entered_at"] = time.perf_counter()
            channel_window["checkedout_at_send_entry"] = engine.pool.checkedout()
            send_blocked.set()
            assert release_send.wait(timeout=30.0), "o teste não liberou a chamada bloqueada do canal"
            channel_window["exited_at"] = time.perf_counter()
            raise TimeoutError("canal indisponível durante o envio do aviso")

        monkeypatch.setattr(ReferenceChannelAdapter, "send_notice", blocked_channel_send)

        outbound_idem_key = f"aviso-r14-{uuid.uuid4()}"
        outbound_body = {"message_type": "ORDER_ACCEPTED", "payload": {"status": "ACCEPTED"}, "actor_id": actor}
        outbound_task = asyncio.create_task(client.post(
            f"/api/v1/channels/orders/{order_id}/outbound",
            headers={**headers, "Idempotency-Key": outbound_idem_key},
            json=outbound_body,
        ))
        assert await asyncio.to_thread(send_blocked.wait, 10.0), "o envio do aviso não entrou no conector"

        # Sincronização observável no banco antes da primeira venda: o aviso está em SENDING com lease ativo.
        in_flight_before = _message(channel_window["notice_id"])
        assert in_flight_before.status == ChannelOutboundStatusEnum.SENDING
        assert in_flight_before.lease_expires_at is not None
        assert channel_window["checkedout_at_send_entry"] == 0, (
            "nenhuma conexão ou transação do pool pode ficar retida na entrada da chamada ao conector"
        )

        unavailable_samples = []
        for _ in range(R14_MEASURED_SAMPLES):
            assert send_blocked.is_set() and "exited_at" not in channel_window
            sample = await _local_pos_sale(
                client, headers, store_id, register_id, cash_session_id, pos_product_id, actor,
            )
            assert "exited_at" not in channel_window, "o envio do canal terminou antes da venda local"
            unavailable_samples.append(sample)

        # Sincronização observável no banco após a última venda e antes de soltar o conector: segue em SENDING.
        in_flight_after = _message(channel_window["notice_id"])
        assert in_flight_after.status == ChannelOutboundStatusEnum.SENDING

        release_send.set()
        outbound_response = await outbound_task
        assert outbound_response.status_code == 200, outbound_response.text

        deadline = time.monotonic() + 5.0
        settled_notice = _message(channel_window["notice_id"])
        while settled_notice.status == ChannelOutboundStatusEnum.SENDING and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
            settled_notice = _message(channel_window["notice_id"])
        assert settled_notice.status == ChannelOutboundStatusEnum.RETRY
        assert settled_notice.last_error_code == "CALL_FAILED"
        assert settled_notice.attempt_count == 1 and settled_notice.next_retry_at is not None

        unavailable_summary = _latency_summary(unavailable_samples)
        assert len({sample["sale_id"] for sample in unavailable_samples}) == R14_MEASURED_SAMPLES
        violations = _r14_violations(
            baseline_summary, unavailable_samples,
            channel_window["entered_at"], channel_window["exited_at"],
        )
        assert violations == [], f"R14 violado: {violations} (baseline={baseline_summary}, indisponivel={unavailable_summary})"

        # 3b. Caminho de Idempotency-Key repetida na rota (e verificação de que o serviço
        # `outbound.enqueue` não fecha a Session do chamador): ao repetir a mesma chave
        # na rota, a resposta é materializada e a sessão da rota é fechada antes do
        # `BackgroundTasks`, mantendo `checkedout == 0` na entrada do conector.
        with Session(engine) as db:
            set_platform_db_context(db)
            same_row = outbound.enqueue(
                db, context, order_id, message_type="ORDER_ACCEPTED",
                payload={"status": "ACCEPTED"}, actor_id=uuid.UUID(actor),
                idempotency_key=outbound_idem_key,
            )
            assert same_row.id == channel_window["notice_id"]
            # A sessão pertence ao chamador de `outbound.enqueue` e permanece utilizável.
            same_row.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
            db.add(same_row)
            db.commit()

        repeat_entered = threading.Event()
        repeat_checkedout: dict = {}

        def repeat_idempotent_send(self, notice):
            repeat_checkedout["checkedout_at_send_entry"] = engine.pool.checkedout()
            repeat_entered.set()
            return DeliveryOutcome(DeliveryResult.DELIVERED, provider_reference="ack-r14-repeat")

        monkeypatch.setattr(ReferenceChannelAdapter, "send_notice", repeat_idempotent_send)
        repeat_response = await client.post(
            f"/api/v1/channels/orders/{order_id}/outbound",
            headers={**headers, "Idempotency-Key": outbound_idem_key},
            json=outbound_body,
        )
        assert repeat_response.status_code == 200, repeat_response.text
        assert repeat_response.json()["id"] == outbound_response.json()["id"]
        assert await asyncio.to_thread(repeat_entered.wait, 5.0), "BackgroundTasks não chamou send_notice na chave repetida"
        assert repeat_checkedout.get("checkedout_at_send_entry") == 0, (
            "caminho de Idempotency-Key repetida na rota reteve conexão do pool durante deliver_now"
        )
        deadline = time.monotonic() + 5.0
        delivered_notice = _message(channel_window["notice_id"])
        while delivered_notice.status != ChannelOutboundStatusEnum.DELIVERED and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
            delivered_notice = _message(channel_window["notice_id"])
        assert delivered_notice.status == ChannelOutboundStatusEnum.DELIVERED

        # 4. Controle: se a confirmação da venda local passasse a esperar o canal,
        # a mesma verificação reprovaria tanto pela janela de bloqueio quanto pela latência.
        control_blocked = threading.Event()
        control_release = threading.Event()
        control_window: dict = {}
        hold_seconds = max(0.35, (limits["p50_max_ms"] + 80.0) / 1000.0)

        def timed_channel_block(self, notice):
            control_window["notice_id"] = uuid.UUID(notice.notice_id)
            control_window["entered_at"] = time.perf_counter()
            control_blocked.set()
            time.sleep(hold_seconds)
            control_window["exited_at"] = time.perf_counter()
            control_release.set()
            raise TimeoutError("canal indisponível no controle R14")

        real_confirm_payment = payment_service.confirm_payment

        def coupled_confirm_payment(*args, **kwargs):
            # Acoplamento plantado para o controle: a venda espera o canal terminar.
            control_release.wait(timeout=5.0)
            return real_confirm_payment(*args, **kwargs)

        monkeypatch.setattr(ReferenceChannelAdapter, "send_notice", timed_channel_block)
        monkeypatch.setattr(payment_service, "confirm_payment", coupled_confirm_payment)

        control_outbound_task = asyncio.create_task(client.post(
            f"/api/v1/channels/orders/{order_id}/outbound",
            headers={**headers, "Idempotency-Key": f"aviso-r14-ctrl-{uuid.uuid4()}"},
            json={"message_type": "ORDER_READY", "payload": {"status": "READY"}, "actor_id": actor},
        ))
        assert await asyncio.to_thread(control_blocked.wait, 10.0)
        control_sample = await _local_pos_sale(
            client, headers, store_id, register_id, cash_session_id, pos_product_id, actor,
        )
        control_outbound_response = await control_outbound_task
        assert control_outbound_response.status_code == 200
        monkeypatch.setattr(payment_service, "confirm_payment", real_confirm_payment)

        control_violations = _r14_violations(
            baseline_summary, [control_sample],
            control_window["entered_at"], control_window["exited_at"],
        )
        assert "sale_not_completed_while_channel_blocked" in control_violations, control_violations
        assert any(item.startswith("p50_regression:") for item in control_violations), control_violations

    with Session(engine) as db:
        set_platform_db_context(db)
        total_expected_sales = R14_WARMUP_SAMPLES + (2 * R14_MEASURED_SAMPLES) + 1
        paid_sales = db.exec(select(Sale).where(
            Sale.tenant_id == context.tenant_id, Sale.status == SaleStatusEnum.PAID,
        )).all()
        assert len(paid_sales) == total_expected_sales
        balance = db.exec(select(InventoryBalance).where(
            InventoryBalance.tenant_id == context.tenant_id,
            InventoryBalance.product_id == uuid.UUID(pos_product_id),
        )).one()
        assert float(balance.quantity) == 200.0 - total_expected_sales

    report_path = os.getenv("R14_EVIDENCE_PATH") or os.getenv("R14_REPORT_PATH")
    if report_path:
        report = {
            "gate": "S10.1-R14-H10",
            "measured_at": datetime.utcnow().isoformat() + "Z",
            "environment": {
                "os": platform.platform(),
                "python": platform.python_version(),
                "database": "PostgreSQL 15 (isolated container 127.0.0.1:5439)",
                "auth_mode": settings.AUTH_MODE,
                "environment_mode": settings.ENVIRONMENT,
                "db_pool_size": settings.DB_POOL_SIZE,
                "db_max_overflow": settings.DB_MAX_OVERFLOW,
                "warmup_samples": R14_WARMUP_SAMPLES,
                "measured_samples_per_phase": R14_MEASURED_SAMPLES,
            },
            "criterion": limits,
            "baseline": baseline_summary,
            "under_channel_unavailability": {
                **unavailable_summary,
                "channel_blocked_window_ms": round(
                    (channel_window["exited_at"] - channel_window["entered_at"]) * 1000.0, 3,
                ),
                "checkedout_db_connections_at_send_entry": channel_window["checkedout_at_send_entry"],
                "repeated_idempotency_checkedout_at_send_entry": repeat_checkedout["checkedout_at_send_entry"],
                "outbound_http_status": outbound_response.status_code,
                "outbound_final_status": settled_notice.status.value,
                "outbound_error_code": settled_notice.last_error_code,
            },
            "control_coupled_sale": {
                "hold_ms": round(hold_seconds * 1000.0, 3),
                "latency_ms": control_sample["latency_ms"],
                "detected_violations": control_violations,
            },
        }
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

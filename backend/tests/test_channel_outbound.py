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
- nothing personal reaches the outbox, and a notice naming a person is refused (P4).

Not proven here: R14 — that the local sale keeps its latency while the channel
is down. The executor is not on the sale's path, but no baseline was measured.
"""

import os
import uuid
from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, select

import app.main  # noqa: F401 — compõe a aplicação como a API
from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.channel_hub import ChannelOutboundMessage, ChannelOutboundStatusEnum
from app.models.reliability import OutboxEvent
from app.modules.channels import inbox, outbound
from app.modules.channels.adapters.reference import ReferenceChannelAdapter
from app.modules.channels.contracts import ChannelCapability, DeliveryOutcome, DeliveryResult
from test_channel_inbox import _connected, _event, _line, _mapping, _receive, _row

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


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

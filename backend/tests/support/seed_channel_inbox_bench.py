#!/usr/bin/env python
"""Uma caixa de entrada de canal com um evento em cada estado, para olhar a tela.

Monta, pelas rotas do produto e pelo código real da caixa de entrada, um tenant
com uma conexão do conector de referência e eventos que terminam em: aplicado,
em quarentena, precisando de uma pessoa, aguardando processamento e expirado.
Os eventos carregam marcadores de dado pessoal, para a bancada conferir que a
tela não os mostra.

Tudo aqui é simulado do lado do canal. Não toca produção: fala com a API local
indicada por `--api` e com o banco do `DATABASE_URL` do processo.

Uso, de dentro do contêiner do backend, em /app/tests:
    PYTHONPATH=/app:/app/tests python support/seed_channel_inbox_bench.py --api http://127.0.0.1:8000
"""

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timedelta

import httpx
from sqlmodel import Session, select

import app.main  # noqa: F401 — compõe a aplicação como a API: liga a porta de liquidação
from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.channel_hub import ChannelInboxEvent, ExternalOrderMapping
from app.models.order import OrderItem, ProductionStateEnum
from app.core.context import TenantContext
from app.modules.channels import inbox, ingress, outbound
from app.modules.channels.adapters import reference
from app.modules.channels.contracts import DeliveryOutcome, DeliveryResult
from test_s10_channel_hub import _base, _map_item

MARKERS = {"name": "Bancada Marcadora", "phone": "5511900001111", "address": {"street": "Rua Marcadora 9"}}


def _receive(*events):
    body = json.dumps({"events": list(events)}).encode("utf-8")
    ingress.receive("CONTRACT_TEST", {reference.SIGNATURE_HEADER: reference.sign(body)}, body)


def _row(event):
    with Session(engine) as db:
        set_platform_db_context(db)
        return db.exec(select(ChannelInboxEvent).where(ChannelInboxEvent.provider_event_id == event["id"])).one()


def _event(merchant, kind, order_id, *, sequence=None, code=None):
    event = {"id": f"bancada-{uuid.uuid4()}", "merchant_id": merchant, "type": kind, "order_id": order_id,
             "customer": MARKERS}
    if sequence is not None:
        event["sequence"] = sequence
    if code is not None:
        event["order"] = {"fulfillment": "DELIVERY", "payment": {"status": "PAID_ONLINE"},
                          "lines": [{"id": "l1", "item_code": code, "quantity": "1"}]}
    return event


async def main(api: str) -> dict:
    async with httpx.AsyncClient(base_url=api, timeout=30) as client:
        tenant, store, headers, actor, product, connection = await _base(client, "Bancada Canal")
        await _map_item(client, headers, actor, connection, product, "ITEM-BANCADA")
    merchant = connection["merchant_external_id"]

    applied = _event(merchant, "ORDER_PLACED", f"pedido-aplicado-{uuid.uuid4().hex[:6]}", sequence=1, code="ITEM-BANCADA")
    quarantined = _event(merchant, "ORDER_PLACED", f"pedido-sem-codigo-{uuid.uuid4().hex[:6]}", code="CODIGO-DESCONHECIDO")
    busy_ref = f"pedido-em-preparo-{uuid.uuid4().hex[:6]}"
    busy = _event(merchant, "ORDER_PLACED", busy_ref, sequence=1, code="ITEM-BANCADA")
    waiting = _event(merchant, "ORDER_PLACED", f"pedido-aguardando-{uuid.uuid4().hex[:6]}", code="ITEM-BANCADA")
    stale = _event(merchant, "ORDER_PLACED", f"pedido-vencido-{uuid.uuid4().hex[:6]}", code="OUTRO-DESCONHECIDO")
    _receive(applied, quarantined, busy, waiting, stale)

    inbox.process_event(_row(applied).id)
    inbox.process_event(_row(quarantined).id)
    inbox.process_event(_row(busy).id)
    with Session(engine) as db:
        set_platform_db_context(db)
        mapping = db.exec(select(ExternalOrderMapping).where(ExternalOrderMapping.external_order_id == busy_ref)).one()
        for item in db.exec(select(OrderItem).where(OrderItem.order_id == mapping.order_id)):
            item.production_state = ProductionStateEnum.IN_PREPARATION
            db.add(item)
        db.commit()
    cancel = _event(merchant, "ORDER_CANCELLED", busy_ref, sequence=2)
    _receive(cancel)
    inbox.process_event(_row(cancel).id)

    inbox.process_event(_row(stale).id)
    with Session(engine) as db:
        set_platform_db_context(db)
        row = db.get(ChannelInboxEvent, _row(stale).id)
        row.retention_until = datetime.utcnow() - timedelta(minutes=1)
        db.add(row)
        db.commit()
    inbox.expire_overdue()

    # Avisos ao canal, um em cada situação. As respostas do canal são simuladas aqui.
    with Session(engine) as db:
        set_platform_db_context(db)
        applied_mapping = db.exec(select(ExternalOrderMapping).where(
            ExternalOrderMapping.external_order_id == applied["order_id"])).one()
    context = TenantContext(tenant_id=uuid.UUID(tenant["id"]), store_id=uuid.UUID(store["id"]), user_id=uuid.UUID(actor))

    def queue(message_type, payload):
        with Session(engine) as db:
            set_platform_db_context(db)
            return outbound.enqueue(db, context, applied_mapping.order_id, message_type=message_type,
                                    payload=payload, actor_id=context.user_id,
                                    idempotency_key=f"bancada-aviso-{uuid.uuid4()}").id

    delivered = queue("ORDER_ACCEPTED", {"status": "ACCEPTED", "texto_secreto_do_aviso": "CONTEUDO-DO-AVISO"})
    outbound.deliver(delivered)
    dead = queue("ORDER_TELEPORTED", {"status": "?"})
    outbound.deliver(dead)
    original_send, original_idempotent = reference.ReferenceChannelAdapter.send_notice, reference.ReferenceChannelAdapter.idempotent_delivery
    reference.ReferenceChannelAdapter.send_notice = lambda self, notice: DeliveryOutcome(DeliveryResult.RETRYABLE, code="CHANNEL_UNAVAILABLE")
    retry = queue("ORDER_READY", {"status": "READY"})
    outbound.deliver(retry)

    def times_out(self, notice):
        raise TimeoutError("sem resposta")

    reference.ReferenceChannelAdapter.send_notice = times_out
    reference.ReferenceChannelAdapter.idempotent_delivery = False
    unconfirmed = queue("ORDER_DISPATCHED", {"status": "DISPATCHED"})
    outbound.deliver(unconfirmed)
    reference.ReferenceChannelAdapter.send_notice, reference.ReferenceChannelAdapter.idempotent_delivery = original_send, original_idempotent

    def notice_status(message_id):
        with Session(engine) as db:
            set_platform_db_context(db)
            from app.models.channel_hub import ChannelOutboundMessage
            return db.get(ChannelOutboundMessage, message_id).status.value

    return {
        "tenant": tenant["id"], "store": store["id"], "operator": actor,
        "markers": [MARKERS["name"], MARKERS["phone"], MARKERS["address"]["street"], "CONTEUDO-DO-AVISO"],
        "notices": {name: notice_status(message_id) for name, message_id in {
            "delivered": delivered, "dead": dead, "retry": retry, "unconfirmed": unconfirmed,
        }.items()},
        "states": {name: _row(event).status.value for name, event in {
            "applied": applied, "quarantined": quarantined, "review": cancel,
            "waiting": waiting, "expired": stale,
        }.items()},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    print(json.dumps(asyncio.run(main(parser.parse_args().api))))

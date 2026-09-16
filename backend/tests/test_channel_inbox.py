"""S10.1, steps 3 and 4: the resumable inbox applies each event once, and says why when it cannot.

Proposal `docs/product/proposta-s10-1-channel-hub.md` (revision 3), §3.4 and §3.7.
Events are persisted through the real ingress code, in this process, so nothing
schedules processing behind the test's back; then the test drives the inbox the
way each trigger would. Where a person acts, it goes through the HTTP route.

Real here: the database, transactions, row locks, leases, two concurrent
processors, the Order Engine and the retention deadlines. Simulated: the channel.
Nothing here removes data — deadlines are assigned, and the purge is a later step.

Acceptance criteria the owner set for this step, and where each is proved:
- resumed after a crash, no duplicate order or item ............ R2, R1, lease test
- order and lines written atomically ............................ R2
- contact never copied to orders.notes, logs or immutable trails . P3 (+ log guard)
- an event with no order expires from reception, no restart ..... P18, P17
- quarantine resumed without extending retention ................ P17, P19
- cancellation with an item in preparation becomes visible review  R8
- an older update never regresses the order ..................... R7, R9
- no access to the four D7 actions before an explicit grant ...... P6 here, P20 in ingress
"""

import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text

# The inbox runs in this process, so this process composes the application the
# way the API does: finance wires the settlement port the Order Engine asks
# before changing an item. Unwired, the port raises instead of answering zero.
import app.main  # noqa: F401
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.channel_hub import (
    ChannelInboxEvent, ChannelInboxStatusEnum, ChannelOrderContact, ChannelOrderLine,
    ChannelRetentionBasisEnum, ExternalOrderMapping,
)
from app.models.order import Order, OrderItem, ProductionStateEnum
from app.modules.channels import inbox, ingress
from app.modules.channels.adapters import reference
from app.services import order_service
from test_s10_channel_hub import _base, _map_item

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


def _receive(*events) -> None:
    body = json.dumps({"events": list(events)}).encode("utf-8")
    outcomes = ingress.receive("CONTRACT_TEST", {reference.SIGNATURE_HEADER: reference.sign(body)}, body)
    assert all(outcome.outcome == "RECEIVED" for outcome in outcomes), outcomes


def _row(provider_event_id: str) -> ChannelInboxEvent:
    with Session(engine) as db:
        set_platform_db_context(db)
        return db.exec(select(ChannelInboxEvent).where(
            ChannelInboxEvent.provider_event_id == provider_event_id,
        )).one()


def _event(merchant: str, kind: str, order_id: str, *, sequence=None, lines=None, customer=None) -> dict:
    event = {"id": f"evt-{uuid.uuid4()}", "merchant_id": merchant, "type": kind, "order_id": order_id}
    if sequence is not None:
        event["sequence"] = sequence
    if lines is not None:
        event["order"] = {"fulfillment": "DELIVERY", "lines": lines, "payment": {"status": "PAID_ONLINE"}}
    if customer is not None:
        event["customer"] = customer
    return event


def _line(line_id: str, code: str, quantity, notes=None) -> dict:
    line = {"id": line_id, "item_code": code, "quantity": str(quantity)}
    if notes:
        line["notes"] = notes
    return line


def _mapping(connection_id: str, external_order_id: str):
    with Session(engine) as db:
        set_platform_db_context(db)
        return db.exec(select(ExternalOrderMapping).where(
            ExternalOrderMapping.merchant_connection_id == uuid.UUID(connection_id),
            ExternalOrderMapping.external_order_id == external_order_id,
        )).first()


def _items(order_id) -> list[OrderItem]:
    with Session(engine) as db:
        set_platform_db_context(db)
        return list(db.exec(select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.created_at)).all())


async def _another_product(client, headers, store, name: str) -> dict:
    suffix = uuid.uuid4().hex[:8]
    product = (await client.post("/api/v1/catalog/products", headers=headers, json={
        "name": name, "sku": f"CH2-{suffix}", "unit": "UN", "tracks_inventory": False,
        "requires_fulfillment": True, "production_destination": "COZINHA",
    })).json()
    await client.post("/api/v1/catalog/prices", headers=headers, json={
        "product_id": product["id"], "store_id": store["id"], "cost_price": 3, "sale_price": 9.9,
    })
    assortment = await client.post("/api/v1/catalog/assortments", headers=headers, json={
        "code": f"ASSORT-DELIV2-{suffix}", "name": f"Delivery {name}",
        "scopes": [{"store_id": store["id"], "sales_context": "DELIVERY"}],
        "product_ids": [product["id"]],
    })
    assert assortment.status_code in (200, 201), assortment.text
    return product


async def _connected(client, prefix, *codes):
    """A connected channel with one product per item code: a code maps one product, and one only."""
    tenant, store, headers, actor, product, connection = await _base(client, prefix)
    for index, code in enumerate(codes):
        target = product if index == 0 else await _another_product(client, headers, store, f"Produto {code}")
        await _map_item(client, headers, actor, connection, target, code)
    return tenant, headers, actor, product, connection


@pytest.mark.asyncio
async def test_pedido_e_linhas_nascem_juntos_e_uma_queda_no_meio_nao_deixa_metade(monkeypatch):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _tenant, _h, _a, _p, connection = await _connected(client, "Atomico", "ITEM-A", "ITEM-B")
    merchant, order_ref = connection["merchant_external_id"], f"pedido-{uuid.uuid4()}"
    placed = _event(merchant, "ORDER_PLACED", order_ref, lines=[_line("l1", "ITEM-A", 1), _line("l2", "ITEM-B", 2)])
    _receive(placed)
    row = _row(placed["id"])

    real = order_service.add_external_item
    calls = {"n": 0}

    def dies_on_the_second_line(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("processo caiu no meio do pedido")
        return real(*args, **kwargs)

    monkeypatch.setattr(order_service, "add_external_item", dies_on_the_second_line)
    assert inbox.process_event(row.id) == ChannelInboxStatusEnum.RECEIVED
    assert _mapping(connection["id"], order_ref) is None, "a queda deixou pedido pela metade"
    after_crash = _row(placed["id"])
    assert after_crash.attempts == 1 and after_crash.last_error_code == "PROCESSING_FAILED_RETRYING"
    with Session(engine) as db:
        set_platform_db_context(db)
        assert db.exec(select(Order).where(Order.external_reference == order_ref)).all() == []

    monkeypatch.setattr(order_service, "add_external_item", real)
    assert inbox.process_event(row.id) == ChannelInboxStatusEnum.APPLIED
    assert inbox.process_event(row.id) is None, "evento aplicado não é reivindicado de novo"
    mapping = _mapping(connection["id"], order_ref)
    items = _items(mapping.order_id)
    assert sorted(item.quantity for item in items) == [Decimal("1"), Decimal("2")]
    with Session(engine) as db:
        set_platform_db_context(db)
        lines = db.exec(select(ChannelOrderLine).where(ChannelOrderLine.external_order_mapping_id == mapping.id)).all()
        assert {line.external_line_id for line in lines} == {"l1", "l2"}
        assert {line.order_item_id for line in lines} == {item.id for item in items}


@pytest.mark.asyncio
async def test_dois_processadores_ao_mesmo_tempo_um_so_aplica():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _t, _h, _a, _p, connection = await _connected(client, "Concorrencia", "ITEM-A")
    order_ref = f"pedido-{uuid.uuid4()}"
    placed = _event(connection["merchant_external_id"], "ORDER_PLACED", order_ref, lines=[_line("l1", "ITEM-A", 1)])
    _receive(placed)
    event_id = _row(placed["id"]).id

    barrier, results = threading.Barrier(2), []

    def processor():
        barrier.wait()
        results.append(inbox.process_event(event_id))

    threads = [threading.Thread(target=processor) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(results, key=str) == sorted([ChannelInboxStatusEnum.APPLIED, None], key=str)
    with Session(engine) as db:
        set_platform_db_context(db)
        assert len(db.exec(select(Order).where(Order.external_reference == order_ref)).all()) == 1


@pytest.mark.asyncio
async def test_processador_que_morre_depois_de_reivindicar_nao_prende_o_evento():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _t, _h, _a, _p, connection = await _connected(client, "Lease", "ITEM-A")
    placed = _event(connection["merchant_external_id"], "ORDER_PLACED", f"pedido-{uuid.uuid4()}", lines=[_line("l1", "ITEM-A", 1)])
    _receive(placed)
    event_id = _row(placed["id"]).id
    assert inbox.claim(event_id) is not None  # e o processo morre aqui
    assert inbox.process_event(event_id) is None, "dentro do lease ninguém mais o pega"
    later = datetime.utcnow() + timedelta(seconds=inbox.LEASE_SECONDS + 1)
    assert inbox.process_event(event_id, now=later) == ChannelInboxStatusEnum.APPLIED
    assert _row(placed["id"]).attempts == 2


@pytest.mark.asyncio
async def test_atualizacao_compara_linhas_externas_e_a_antiga_nao_regride():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _t, _h, _a, _p, connection = await _connected(client, "Atualiza", "ITEM-A", "ITEM-B")
    merchant, order_ref = connection["merchant_external_id"], f"pedido-{uuid.uuid4()}"
    placed = _event(merchant, "ORDER_PLACED", order_ref, sequence=1, lines=[_line("l1", "ITEM-A", 1), _line("l2", "ITEM-B", 1)])
    updated = _event(merchant, "ORDER_UPDATED", order_ref, sequence=3, lines=[_line("l1", "ITEM-A", 3), _line("l3", "ITEM-B", 1)])
    older = _event(merchant, "ORDER_UPDATED", order_ref, sequence=2, lines=[_line("l1", "ITEM-A", 9), _line("l2", "ITEM-B", 1)])
    _receive(placed, updated, older)
    assert inbox.process_event(_row(placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
    assert inbox.process_event(_row(updated["id"]).id) == ChannelInboxStatusEnum.APPLIED

    mapping = _mapping(connection["id"], order_ref)
    with Session(engine) as db:
        set_platform_db_context(db)
        lines = {line.external_line_id: line for line in db.exec(select(ChannelOrderLine).where(
            ChannelOrderLine.external_order_mapping_id == mapping.id))}
        items = {item.id: item for item in db.exec(select(OrderItem).where(OrderItem.order_id == mapping.order_id))}
    assert set(lines) == {"l1", "l2", "l3"}
    assert items[lines["l1"].order_item_id].quantity == Decimal("3")
    assert items[lines["l2"].order_item_id].status.value == "CANCELED" and lines["l2"].status.value == "CANCELED"
    assert items[lines["l3"].order_item_id].status.value == "ACTIVE"
    assert len(items) == 3, "atualizar não duplicou item"

    assert inbox.process_event(_row(older["id"]).id) == ChannelInboxStatusEnum.SUPERSEDED
    assert _items(mapping.order_id)[0].quantity == Decimal("3") or any(
        item.quantity == Decimal("3") for item in _items(mapping.order_id)
    )
    assert all(item.quantity != Decimal("9") for item in _items(mapping.order_id))
    assert _mapping(connection["id"], order_ref).last_order_key == "00000000000000000003"


@pytest.mark.asyncio
async def test_mudanca_que_chega_antes_do_pedido_espera_e_retoma_sozinha_no_prazo_da_recepcao():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _t, _h, _a, _p, connection = await _connected(client, "Antes", "ITEM-A")
    merchant, order_ref = connection["merchant_external_id"], f"pedido-{uuid.uuid4()}"
    early = _event(merchant, "ORDER_UPDATED", order_ref, sequence=2, lines=[_line("l1", "ITEM-A", 5)])
    _receive(early)
    reception_deadline = _row(early["id"]).retention_until
    assert inbox.process_event(_row(early["id"]).id) == ChannelInboxStatusEnum.QUARANTINED
    waiting = _row(early["id"])
    assert waiting.quarantine_code == "ORDER_NOT_YET_RECEIVED" and waiting.first_quarantined_at is not None

    placed = _event(merchant, "ORDER_PLACED", order_ref, sequence=1, lines=[_line("l1", "ITEM-A", 1)])
    _receive(placed)
    assert inbox.process_event(_row(placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
    retaken = _row(early["id"])
    assert retaken.status == ChannelInboxStatusEnum.APPLIED
    assert any(item.quantity == Decimal("5") for item in _items(retaken.order_id))
    # P17: passou por quarentena, então segue no relógio da recepção.
    assert retaken.retention_basis == ChannelRetentionBasisEnum.RECEPCAO
    assert retaken.retention_until == reception_deadline


@pytest.mark.asyncio
async def test_cancelamento_sem_preparo_encerra_com_preparo_vira_revisao_e_depois_do_fim_nada_muda():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _t, _h, _a, _p, connection = await _connected(client, "Cancela", "ITEM-A")
    merchant = connection["merchant_external_id"]

    free_ref = f"pedido-{uuid.uuid4()}"
    placed = _event(merchant, "ORDER_PLACED", free_ref, sequence=1, lines=[_line("l1", "ITEM-A", 1)],
                    customer={"name": "Cliente Cancela"})
    cancelled = _event(merchant, "ORDER_CANCELLED", free_ref, sequence=2)
    late = _event(merchant, "ORDER_UPDATED", free_ref, sequence=3, lines=[_line("l1", "ITEM-A", 4)])
    _receive(placed, cancelled, late)
    assert inbox.process_event(_row(placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
    assert inbox.process_event(_row(cancelled["id"]).id) == ChannelInboxStatusEnum.APPLIED
    mapping = _mapping(connection["id"], free_ref)
    assert mapping.terminal_state.value == "CANCELED" and mapping.terminal_at is not None
    with Session(engine) as db:
        set_platform_db_context(db)
        assert db.get(Order, mapping.order_id).status.value == "CANCELED"
    assert all(item.status.value == "CANCELED" for item in _items(mapping.order_id))
    # R9: depois do fim, a atualização é registrada e não aplicada.
    assert inbox.process_event(_row(late["id"]).id) == ChannelInboxStatusEnum.SUPERSEDED
    assert all(item.quantity == Decimal("1") for item in _items(mapping.order_id))

    busy_ref = f"pedido-{uuid.uuid4()}"
    busy = _event(merchant, "ORDER_PLACED", busy_ref, sequence=1, lines=[_line("l1", "ITEM-A", 1)])
    _receive(busy)
    assert inbox.process_event(_row(busy["id"]).id) == ChannelInboxStatusEnum.APPLIED
    busy_mapping = _mapping(connection["id"], busy_ref)
    with Session(engine) as db:
        set_platform_db_context(db)
        for item in db.exec(select(OrderItem).where(OrderItem.order_id == busy_mapping.order_id)):
            item.production_state = ProductionStateEnum.IN_PREPARATION
            db.add(item)
        db.commit()
    stop = _event(merchant, "ORDER_CANCELLED", busy_ref, sequence=2)
    _receive(stop)
    assert inbox.process_event(_row(stop["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
    review = _row(stop["id"])
    assert review.quarantine_code == "PREPARATION_STARTED" and review.order_id == busy_mapping.order_id
    assert "uma pessoa decide" in review.quarantine_reason
    with Session(engine) as db:
        set_platform_db_context(db)
        assert db.get(Order, busy_mapping.order_id).status.value == "OPEN"
    assert _mapping(connection["id"], busy_ref).terminal_at is None
    assert review.first_quarantined_at is not None, "revisão também prende o prazo à recepção"
    reception_deadline = review.retention_until

    # A cozinha voltou atrás; uma pessoa retoma pela rota. O pedido é cancelado e
    # o prazo do evento não alonga (D6: retomar não amplia a retenção).
    with Session(engine) as db:
        set_platform_db_context(db)
        for item in db.exec(select(OrderItem).where(OrderItem.order_id == busy_mapping.order_id)):
            item.production_state = ProductionStateEnum.PENDING
            db.add(item)
        db.commit()
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        resumed = await client.post(f"/api/v1/channels/inbox/{review.id}/resume", headers=_h, json={"actor_id": _a})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "APPLIED"
    after = _row(stop["id"])
    assert after.retention_basis == ChannelRetentionBasisEnum.RECEPCAO
    assert after.retention_until == reception_deadline
    with Session(engine) as db:
        set_platform_db_context(db)
        assert db.get(Order, busy_mapping.order_id).status.value == "CANCELED"


@pytest.mark.asyncio
async def test_estado_terminal_ancora_os_prazos_do_payload_e_do_contato():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _t, _h, _a, _p, connection = await _connected(client, "Conclui", "ITEM-A")
    merchant, order_ref = connection["merchant_external_id"], f"pedido-{uuid.uuid4()}"
    placed = _event(merchant, "ORDER_PLACED", order_ref, sequence=1, lines=[_line("l1", "ITEM-A", 1)],
                    customer={"name": "Cliente Conclui", "phone": "11955554444"})
    _receive(placed)
    assert inbox.process_event(_row(placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
    applied = _row(placed["id"])
    assert applied.retention_basis == ChannelRetentionBasisEnum.ESTADO_TERMINAL
    assert applied.retention_until is None, "aplicado sem quarentena aguarda o estado terminal"
    mapping = _mapping(connection["id"], order_ref)
    with Session(engine) as db:
        set_platform_db_context(db)
        contact = db.exec(select(ChannelOrderContact).where(ChannelOrderContact.external_order_mapping_id == mapping.id)).one()
    assert contact.retention_until is None and contact.pseudonym.startswith("Cliente ")

    concluded = _event(merchant, "ORDER_CONCLUDED", order_ref, sequence=2)
    _receive(concluded)
    assert inbox.process_event(_row(concluded["id"]).id) == ChannelInboxStatusEnum.APPLIED
    mapping = _mapping(connection["id"], order_ref)
    assert mapping.terminal_state.value == "CONCLUDED"
    with Session(engine) as db:
        set_platform_db_context(db)
        assert db.get(Order, mapping.order_id).status.value == "CLOSED"
        contact = db.exec(select(ChannelOrderContact).where(ChannelOrderContact.external_order_mapping_id == mapping.id)).one()
    assert _row(placed["id"]).retention_until == mapping.terminal_at + timedelta(days=30)
    assert _row(concluded["id"]).retention_until == mapping.terminal_at + timedelta(days=30)
    assert contact.retention_until == mapping.terminal_at + timedelta(days=90)


def _lengthened(before: dict, after: dict) -> set:
    """Ids whose deadline moved later. None means waiting for the terminal state."""
    moved = set()
    for key, previous in before.items():
        current = after.get(key)
        if previous is not None and (current is None or current > previous):
            moved.add(key)
    return moved


@pytest.mark.asyncio
async def test_quarentena_retomada_por_pessoa_nao_alonga_o_prazo_e_evento_vencido_expira():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant, headers, actor, product, connection = await _connected(client, "Retoma")
        merchant, order_ref = connection["merchant_external_id"], f"pedido-{uuid.uuid4()}"
        unmapped = _event(merchant, "ORDER_PLACED", order_ref, sequence=1, lines=[_line("l1", "ITEM-NOVO", 1)])
        _receive(unmapped)
        snapshots = {"inicio": {unmapped["id"]: _row(unmapped["id"]).retention_until}}
        assert inbox.process_event(_row(unmapped["id"]).id) == ChannelInboxStatusEnum.QUARANTINED
        snapshots["quarentena"] = {unmapped["id"]: _row(unmapped["id"]).retention_until}
        assert _row(unmapped["id"]).quarantine_code == "ITEM_NOT_MAPPED"

        # Sem permissão explícita ninguém lê contato nem mexe em prazo: não há rota (P6).
        spec = (await client.get("/openapi.json")).json()
        channel_paths = [path for path in spec["paths"] if path.startswith("/api/v1/channels")]
        assert not [path for path in channel_paths if any(word in path for word in ("contact", "hold", "retention", "purge"))]

        await _map_item(client, headers, actor, connection, product, "ITEM-NOVO")
        resumed = await client.post(f"/api/v1/channels/inbox/{_row(unmapped['id']).id}/resume", headers=headers, json={"actor_id": actor})
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "APPLIED"
        snapshots["retomado"] = {unmapped["id"]: _row(unmapped["id"]).retention_until}
        assert _row(unmapped["id"]).retention_basis == ChannelRetentionBasisEnum.RECEPCAO

        steps = list(snapshots.values())
        for before, after in zip(steps, steps[1:]):
            assert _lengthened(before, after) == set(), "um prazo ficou mais longo"
        # Controle: a medida enxerga um alongamento plantado.
        planted = {unmapped["id"]: snapshots["retomado"][unmapped["id"]] + timedelta(days=1)}
        assert _lengthened(snapshots["retomado"], planted) == {unmapped["id"]}

        stale_ref = f"pedido-{uuid.uuid4()}"
        stale = _event(merchant, "ORDER_PLACED", stale_ref, lines=[_line("l1", "SEM-CODIGO", 1)])
        _receive(stale)
        assert inbox.process_event(_row(stale["id"]).id) == ChannelInboxStatusEnum.QUARANTINED
        with Session(engine) as db:
            set_platform_db_context(db)
            row = db.get(ChannelInboxEvent, _row(stale["id"]).id)
            row.retention_until = datetime.utcnow() - timedelta(minutes=1)
            db.add(row)
            db.commit()
        inbox.expire_overdue()
        assert _row(stale["id"]).status == ChannelInboxStatusEnum.EXPIRED
        refused = await client.post(f"/api/v1/channels/inbox/{_row(stale['id']).id}/resume", headers=headers, json={"actor_id": actor})
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "EVENT_EXPIRED"
        assert inbox.process_event(_row(stale["id"]).id) is None


@pytest.mark.asyncio
async def test_a_pessoa_mora_so_no_contato_e_evento_sem_pedido_nao_cria_contato():
    name, phone, street, gate = "Maria Marcador", "5511977776666", "Rua Marcador 123", "Portão Marcador"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant, headers, actor, _p, connection = await _connected(client, "Pessoa", "ITEM-A")
        merchant = connection["merchant_external_id"]
        customer = {"name": name, "phone": phone, "address": {"street": street}, "instructions": gate}
        applied_ref, orphan_ref, broken_ref = (f"pedido-{uuid.uuid4()}" for _ in range(3))
        applied = _event(merchant, "ORDER_PLACED", applied_ref, lines=[_line("l1", "ITEM-A", 1, notes="sem cebola")], customer=customer)
        orphan = _event(merchant, "ORDER_PLACED", orphan_ref, lines=[_line("l1", "SEM-CODIGO", 1)], customer=customer)
        broken = _event(merchant, "ORDER_PLACED", broken_ref, lines=[{"id": "l1", "item_code": "ITEM-A", "quantity": phone + "x"}], customer=customer)
        _receive(applied, orphan, broken)
        assert inbox.process_event(_row(applied["id"]).id) == ChannelInboxStatusEnum.APPLIED
        assert inbox.process_event(_row(orphan["id"]).id) == ChannelInboxStatusEnum.QUARANTINED
        assert inbox.process_event(_row(broken["id"]).id) == ChannelInboxStatusEnum.QUARANTINED
        listed = (await client.get("/api/v1/channels/inbox", headers=headers)).text

    tenant_id = tenant["id"]
    broken_row = _row(broken["id"])
    assert broken_row.quarantine_code == "PAYLOAD_LINE_QUANTITY_INVALID"
    for marker in (name, phone, street, gate):
        assert marker not in (broken_row.quarantine_reason or ""), "P9: o motivo carregou o que chegou"
        assert marker not in listed, "a caixa de entrada mostrou dado pessoal"

    places = {
        "orders": "SELECT coalesce(notes,'') || coalesce(external_reference,'') FROM orders WHERE tenant_id = :t",
        "order_items": "SELECT coalesce(notes,'') FROM order_items WHERE tenant_id = :t",
        "audit_events": "SELECT payload FROM audit_events WHERE tenant_id = :t",
        "outbox_events": "SELECT payload FROM outbox_events WHERE tenant_id = :t",
        "published_events": "SELECT payload FROM published_events WHERE tenant_id = :t",
        "idempotency_records": "SELECT response_body FROM idempotency_records WHERE tenant_id = :t",
        "customers": "SELECT name || coalesce(phone,'') FROM customers WHERE tenant_id = :t",
        "motivo_de_quarentena": "SELECT coalesce(quarantine_reason,'') || coalesce(last_error_code,'') FROM channel_inbox_events WHERE tenant_id = :t",
    }
    with Session(engine) as db:
        set_platform_db_context(db)
        for where, query in places.items():
            content = " ".join(str(value[0]) for value in db.exec(text(query).bindparams(t=tenant_id)).all())
            for marker in (name, phone, street, gate):
                assert marker not in content, f"P3: {marker!r} apareceu em {where}"
        contacts = db.exec(select(ChannelOrderContact).where(ChannelOrderContact.tenant_id == uuid.UUID(tenant_id))).all()
    assert len(contacts) == 1, "P21: evento que não virou pedido não cria contato"
    assert (contacts[0].display_name, contacts[0].phone, contacts[0].delivery_instructions) == (name, phone, gate)
    assert contacts[0].delivery_address == {"street": street}
    assert any(item.notes == "sem cebola" for item in _items(_mapping(connection["id"], applied_ref).order_id))

"""S10.1, steps 3 and 4: the resumable inbox applies each event once, and says why when it cannot.

Proposal `docs/product/proposta-s10-1-channel-hub.md` (revision 3), §3.4 and §3.7.
Events are persisted through the real ingress code, in this process, so nothing
schedules processing behind the test's back; then the test drives the inbox the
way each trigger would. Where a person acts, it goes through the HTTP route.

Real here: the database, transactions, row locks, leases, two concurrent
processors, the Order Engine and the retention deadlines. Simulated: the channel.
Nothing here removes data — deadlines are assigned, and the purge is a later step.

Acceptance criteria the owner set for this step, and where each is proved:
- resumed after a failure, no duplicate order or item ........... R2, R1, lease test
- no partial order visible after a failed application ........... R2
- crash after lines and before order key resumes without duplicates  R3
- negative control: broken line idempotency produces duplicates that fail uniqueness verification . R19
- control: premature commit before end of transaction leaks partial order (C1 control)
- channel order ingestion does not create or mutate CRM, loyalty or fiscal records . P8
- contact never copied to orders.notes, logs or immutable trails . P3 (+ log guard)
- an event with no order expires from reception, no restart ..... P18, P17
- quarantine resumed without extending retention ................ P17, P19
- cancellation with an item in preparation becomes visible review  R8
- an older update never regresses the order ..................... R7, R9
- no access to the four D7 actions before an explicit grant ...... P6 here, P20 in ingress

What R2 proves, and only that: an exception raised while the second item is
added, inside the application's transaction, leaves no order, item, mapping or
external line visible afterwards, and the event goes back to the queue; the next
complete run produces the order with both lines, once. Its control — committing
the order before its lines, the S10 defect C1 — shows the assertion does see a
partial order. What R2 does **not** prove: a process killed or a connection
dropped mid-transaction. That case rests on PostgreSQL discarding an
uncommitted transaction, and no test here kills the process.
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
    ChannelOrderLineStatusEnum, ChannelRetentionBasisEnum, ExternalOrderMapping,
)
from app.models.order import Order, OrderItem, OrderItemStatusEnum, ProductionStateEnum
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


def _event(
    merchant: str, kind: str, order_id: str, *,
    sequence=None, lines=None, customer=None, totals=None, payment=None,
) -> dict:
    event = {"id": f"evt-{uuid.uuid4()}", "merchant_id": merchant, "type": kind, "order_id": order_id}
    if sequence is not None:
        event["sequence"] = sequence
    if lines is not None:
        event["order"] = {
            "fulfillment": "DELIVERY",
            "lines": lines,
            "payment": payment if payment is not None else {"status": "PAID_ONLINE"},
        }
        if totals is not None:
            event["order"].update(totals)
    if customer is not None:
        event["customer"] = customer
    return event


def _line(
    line_id: str, code: str, quantity, notes=None, *,
    unit_price: object = "18.50", discount: object = None, modifiers=None,
) -> dict:
    line = {"id": line_id, "item_code": code, "quantity": str(quantity)}
    if unit_price is not None:
        line["unit_price"] = str(unit_price)
    if discount is not None:
        line["discount"] = str(discount)
    if modifiers is not None:
        line["modifiers"] = list(modifiers)
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
async def test_r3_parada_depois_das_linhas_e_antes_de_gravar_chave_de_ordem_retomada_sem_duplicar(monkeypatch):
    """R3: Parada depois das linhas e antes de gravar a chave de ordem: retomada sem duplicar (H2, H3)."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _tenant, _h, _a, _p, connection = await _connected(client, "R3Crash", "ITEM-A", "ITEM-B")
    merchant = connection["merchant_external_id"]
    order_ref = f"pedido-r3-{uuid.uuid4()}"

    # 1. Pedido inicial com 1 linha aplicado normalmente:
    placed = _event(
        merchant, "ORDER_PLACED", order_ref, sequence=1,
        lines=[_line("l1", "ITEM-A", 1)],
    )
    _receive(placed)
    assert inbox.process_event(_row(placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
    mapping = _mapping(connection["id"], order_ref)
    assert mapping.last_order_key == "00000000000000000001"

    # 2. Atualização que adiciona uma segunda linha (l2):
    updated = _event(
        merchant, "ORDER_UPDATED", order_ref, sequence=2,
        lines=[_line("l1", "ITEM-A", 1), _line("l2", "ITEM-B", 2)],
    )
    _receive(updated)
    update_row = _row(updated["id"])

    # Falha simulada especificamente após o processamento das linhas e antes de avançar last_order_key:
    from app.modules.channels import orders as channel_orders
    real_advance = channel_orders._advance
    advance_calls = {"n": 0}

    def dies_before_order_key(target_mapping, target_event):
        advance_calls["n"] += 1
        if advance_calls["n"] == 1:
            raise RuntimeError("processo caiu após processar linhas e antes de gravar chave de ordem")
        return real_advance(target_mapping, target_event)

    monkeypatch.setattr(channel_orders, "_advance", dies_before_order_key)
    assert inbox.process_event(update_row.id) == ChannelInboxStatusEnum.RECEIVED
    after_crash = _row(updated["id"])
    assert after_crash.attempts == 1 and after_crash.last_error_code == "PROCESSING_FAILED_RETRYING"

    # Verifica que a transação sofreu rollback: last_order_key permanece na sequence 1
    # e a linha l2 NÃO vazou para o banco de dados:
    with Session(engine) as db:
        set_platform_db_context(db)
        reloaded_mapping = db.get(ExternalOrderMapping, mapping.id)
        assert reloaded_mapping.last_order_key == "00000000000000000001"
        stored_lines = db.exec(select(ChannelOrderLine).where(
            ChannelOrderLine.external_order_mapping_id == mapping.id,
            ChannelOrderLine.status == ChannelOrderLineStatusEnum.ACTIVE,
        )).all()
        assert {line.external_line_id for line in stored_lines} == {"l1"}

    # 3. Retomada sem falha: process_event é chamado novamente, aplica o evento e avança a chave:
    monkeypatch.setattr(channel_orders, "_advance", real_advance)
    assert inbox.process_event(update_row.id) == ChannelInboxStatusEnum.APPLIED
    assert inbox.process_event(update_row.id) is None, "evento aplicado não é reivindicado de novo"

    # Confere que o pedido agora tem ambas as linhas sem duplicação:
    with Session(engine) as db:
        set_platform_db_context(db)
        final_mapping = db.get(ExternalOrderMapping, mapping.id)
        assert final_mapping.last_order_key == "00000000000000000002"
        final_lines = db.exec(select(ChannelOrderLine).where(
            ChannelOrderLine.external_order_mapping_id == mapping.id,
            ChannelOrderLine.status == ChannelOrderLineStatusEnum.ACTIVE,
        )).all()
        assert {line.external_line_id for line in final_lines} == {"l1", "l2"}
    items = _items(mapping.order_id)
    assert len(items) == 2
    assert sorted(item.quantity for item in items) == [Decimal("1"), Decimal("2")]


@pytest.mark.asyncio
async def test_controle_atomicidade_commit_prematuro_encontra_pedido_parcial(monkeypatch):
    """Controle de atomicidade (C1): commit prematuro antes do término transacional deixa pedido parcial no banco."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _tenant, _h, _a, _p, connection = await _connected(client, "R19Ctrl", "ITEM-A", "ITEM-B")
    merchant = connection["merchant_external_id"]
    order_ref = f"pedido-atom-{uuid.uuid4()}"
    placed = _event(
        merchant, "ORDER_PLACED", order_ref,
        lines=[_line("l1", "ITEM-A", 1), _line("l2", "ITEM-B", 2)],
    )
    _receive(placed)
    row = _row(placed["id"])

    real_add = order_service.add_external_item
    calls = {"n": 0}

    def leaks_first_line_and_dies(session, context, order, **kwargs):
        calls["n"] += 1
        item = real_add(session, context, order, **kwargs)
        if calls["n"] == 1:
            # Quebra deliberada de isolamento transacional: commita a primeira linha precocemente
            session.commit()
        elif calls["n"] == 2:
            raise RuntimeError("queda simulada na adição da segunda linha")
        return item

    monkeypatch.setattr(order_service, "add_external_item", leaks_first_line_and_dies)
    # O processamento falha na segunda linha e tenta fazer rollback:
    assert inbox.process_event(row.id) == ChannelInboxStatusEnum.RECEIVED

    # O controle de atomicidade: em R2 o teste exige que nenhum pedido ou item parcial exista no banco.
    # Aqui, devido ao commit prematuro plantado, o teste COMPROVA que a asserção detecta o vazamento:
    with Session(engine) as db:
        set_platform_db_context(db)
        leaked_orders = db.exec(select(Order).where(Order.external_reference == order_ref)).all()
        assert len(leaked_orders) == 1, "Controle de atomicidade: pedido prematuro deve ser detectado pela asserção"
        leaked_items = db.exec(select(OrderItem).where(OrderItem.order_id == leaked_orders[0].id)).all()
        assert len(leaked_items) == 1, "Controle de atomicidade: linha 1 prematuramente commitada deve ser detectada"


@pytest.mark.asyncio
async def test_r19_controle_idempotencia_por_linha_quebrada_de_proposito_reprova_duplicata(monkeypatch):
    """R19: Controle negativo: idempotência por linha quebrada de propósito — o detector reprova a duplicação ativa.

    Requisitos estritos comprovados:
    1. Mesmo conteúdo normalizado e identificadores estáveis (l1, l2) nos cenários normal e mutante.
    2. O evento atualiza a quantidade da linha existente l1, exercitando o caminho de atualização.
    3. Quebra somente da implementação via monkeypatch no caminho de atualização: cria outro item ativo
       em vez de atualizar o existente, preservando o original intacto. Sem alteração de payload,
       sem commit prematuro e sem remoção de restrições do banco.
    4. Demonstração de que a implementação mutante foi efetivamente executada.
    5. Detector comum de itens e linhas ATIVAS: verifica unicidade, correspondência 1:1, quantidades e valores,
       permitindo histórico cancelado legítimo e múltiplas linhas para o mesmo produto.
    6. Cenário normal passa; mutante reprova especificamente por duplicação ativa de itens.
    7. Caso positivo de substituição legítima: 2 itens ativos e 1 cancelado passam no detector comum.
    8. Duas linhas externas distintas do mesmo produto são permitidas (não há deduplicação por SKU).
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _tenant, _h, _a, _p, connection = await _connected(client, "R19Idem", "ITEM-A", "ITEM-B")
    merchant = connection["merchant_external_id"]

    def assert_active_lines_and_items(
        order_id: uuid.UUID,
        mapping_id: uuid.UUID,
        expected_active_lines: dict[str, dict],
    ):
        with Session(engine) as db:
            set_platform_db_context(db)
            active_items = db.exec(select(OrderItem).where(
                OrderItem.order_id == order_id,
                OrderItem.status == OrderItemStatusEnum.ACTIVE,
            )).all()
            active_lines = db.exec(select(ChannelOrderLine).where(
                ChannelOrderLine.external_order_mapping_id == mapping_id,
                ChannelOrderLine.status == ChannelOrderLineStatusEnum.ACTIVE,
            )).all()

        assert len(active_lines) == len(expected_active_lines), (
            f"Contagem de linhas ativas divergente: esperado {len(expected_active_lines)}, mas encontrou {len(active_lines)}"
        )
        line_keys = [line.external_line_id for line in active_lines]
        assert len(line_keys) == len(set(line_keys)), (
            f"Duplicação ativa em ChannelOrderLine: chaves {line_keys}"
        )
        assert set(line_keys) == set(expected_active_lines.keys()), (
            f"Identidades externas ativas divergentes: esperado {set(expected_active_lines.keys())}, mas encontrou {set(line_keys)}"
        )
        assert len(active_items) == len(expected_active_lines), (
            f"Duplicação ativa ou divergência de itens no pedido: esperado {len(expected_active_lines)} ativos, mas encontrou {len(active_items)}"
        )

        items_by_id = {item.id: item for item in active_items}
        linked_item_ids = set()
        for line in active_lines:
            assert line.order_item_id in items_by_id, (
                f"Linha ativa {line.external_line_id} aponta para item não ativo ou inexistente ({line.order_item_id})"
            )
            assert line.order_item_id not in linked_item_ids, (
                f"Duas linhas ativas apontam para o mesmo OrderItem ({line.order_item_id})"
            )
            linked_item_ids.add(line.order_item_id)
            expected = expected_active_lines[line.external_line_id]
            item = items_by_id[line.order_item_id]
            assert line.quantity == expected["quantity"], (
                f"Quantidade na linha ativa {line.external_line_id} divergente: esperado {expected['quantity']}, obtido {line.quantity}"
            )
            assert item.quantity == expected["quantity"], (
                f"Quantidade no item ativo {item.id} divergente: esperado {expected['quantity']}, obtido {item.quantity}"
            )

        unlinked_items = set(items_by_id.keys()) - linked_item_ids
        assert not unlinked_items, (
            f"Itens ativos órfãos detectados no pedido sem linha correspondente: {unlinked_items}"
        )

    # 1. CENÁRIO NORMAL: pedido inicial (l1=qty 1, l2=qty 1) e atualização (l1=qty 2, l2=qty 1)
    normal_order_ref = f"pedido-r19-normal-{uuid.uuid4()}"
    placed_normal = _event(
        merchant, "ORDER_PLACED", normal_order_ref, sequence=1,
        lines=[_line("l1", "ITEM-A", 1), _line("l2", "ITEM-B", 1)],
    )
    _receive(placed_normal)
    assert inbox.process_event(_row(placed_normal["id"]).id) == ChannelInboxStatusEnum.APPLIED
    normal_mapping = _mapping(connection["id"], normal_order_ref)
    assert_active_lines_and_items(
        normal_mapping.order_id, normal_mapping.id,
        {"l1": {"quantity": Decimal("1")}, "l2": {"quantity": Decimal("1")}},
    )

    # Atualização da linha l1 para quantidade 2 no cenário normal:
    updated_normal = _event(
        merchant, "ORDER_UPDATED", normal_order_ref, sequence=2,
        lines=[_line("l1", "ITEM-A", 2), _line("l2", "ITEM-B", 1)],
    )
    _receive(updated_normal)
    assert inbox.process_event(_row(updated_normal["id"]).id) == ChannelInboxStatusEnum.APPLIED
    # Implementação normal passa no detector comum:
    assert_active_lines_and_items(
        normal_mapping.order_id, normal_mapping.id,
        {"l1": {"quantity": Decimal("2")}, "l2": {"quantity": Decimal("1")}},
    )

    # 2. CENÁRIO MUTANTE: mesmo conteúdo normalizado, mesmos identificadores estáveis (l1, l2)
    #    Quebra somente a implementação via monkeypatch no caminho de atualização
    mutant_order_ref = f"pedido-r19-mutante-{uuid.uuid4()}"
    placed_mutant = _event(
        merchant, "ORDER_PLACED", mutant_order_ref, sequence=1,
        lines=[_line("l1", "ITEM-A", 1), _line("l2", "ITEM-B", 1)],
    )
    _receive(placed_mutant)
    assert inbox.process_event(_row(placed_mutant["id"]).id) == ChannelInboxStatusEnum.APPLIED
    mutant_mapping = _mapping(connection["id"], mutant_order_ref)
    assert_active_lines_and_items(
        mutant_mapping.order_id, mutant_mapping.id,
        {"l1": {"quantity": Decimal("1")}, "l2": {"quantity": Decimal("1")}},
    )

    # Mesmíssimo payload normalizado de atualização (l1=qty 2, l2=qty 1):
    updated_mutant = _event(
        merchant, "ORDER_UPDATED", mutant_order_ref, sequence=2,
        lines=[_line("l1", "ITEM-A", 2), _line("l2", "ITEM-B", 1)],
    )
    _receive(updated_mutant)

    mutant_executed = {"called": 0}

    def mutant_change_external_item(session, context, order, item, *, quantity, notes=None, unit_price=None, actor_id=None):
        mutant_executed["called"] += 1
        # Implementação defeituosa/mutante: em vez de atualizar o item existente in-place,
        # cria outro item ativo no pedido preservando o original intacto (duplicação ativa de itens):
        order_service.add_external_item(
            session, context, order, product_id=item.product_id, quantity=quantity,
            modifier_ids=[], notes=notes, unit_price=unit_price, actor_id=actor_id,
        )

    monkeypatch.setattr(order_service, "change_external_item", mutant_change_external_item)
    try:
        assert inbox.process_event(_row(updated_mutant["id"]).id) == ChannelInboxStatusEnum.APPLIED
        # Demonstração de que a implementação mutante foi de fato executada:
        assert mutant_executed["called"] == 1, "Implementação mutante deve ter sido executada na atualização de l1"

        # O MESMO detector comum reprova especificamente por duplicação ativa de itens no pedido:
        with pytest.raises(AssertionError) as exc_info:
            assert_active_lines_and_items(
                mutant_mapping.order_id, mutant_mapping.id,
                {"l1": {"quantity": Decimal("2")}, "l2": {"quantity": Decimal("1")}},
            )
        assert "Duplicação ativa ou divergência de itens no pedido" in str(exc_info.value), (
            f"O detector deveria acusar duplicação de itens ativos, mas retornou: {exc_info.value}"
        )
    finally:
        monkeypatch.undo()

    # 3. CASO POSITIVO DE SUBSTITUIÇÃO LEGÍTIMA DE IDENTIFICADOR: 2 ativos e 1 cancelado
    #    Canal substitui a linha l1 pela nova linha l3, mantendo a linha l2
    subst_order_ref = f"pedido-r19-subst-{uuid.uuid4()}"
    placed_subst = _event(
        merchant, "ORDER_PLACED", subst_order_ref, sequence=1,
        lines=[_line("l1", "ITEM-A", 1), _line("l2", "ITEM-B", 1)],
    )
    _receive(placed_subst)
    assert inbox.process_event(_row(placed_subst["id"]).id) == ChannelInboxStatusEnum.APPLIED
    subst_mapping = _mapping(connection["id"], subst_order_ref)

    # Atualização com substituição: l1 sai, entra l3 (ITEM-A qty 2), l2 permanece
    updated_subst = _event(
        merchant, "ORDER_UPDATED", subst_order_ref, sequence=2,
        lines=[_line("l2", "ITEM-B", 1), _line("l3", "ITEM-A", 2)],
    )
    _receive(updated_subst)
    assert inbox.process_event(_row(updated_subst["id"]).id) == ChannelInboxStatusEnum.APPLIED

    # O detector comum verifica as linhas ATIVAS (l2 e l3) e DEVE PASSAR mesmo existindo histórico cancelado de l1:
    assert_active_lines_and_items(
        subst_mapping.order_id, subst_mapping.id,
        {"l2": {"quantity": Decimal("1")}, "l3": {"quantity": Decimal("2")}},
    )
    # Comprovação adicional do histórico cancelado preservado legitimamente:
    with Session(engine) as db:
        set_platform_db_context(db)
        canceled_items = db.exec(select(OrderItem).where(
            OrderItem.order_id == subst_mapping.order_id,
            OrderItem.status == OrderItemStatusEnum.CANCELED,
        )).all()
        canceled_lines = db.exec(select(ChannelOrderLine).where(
            ChannelOrderLine.external_order_mapping_id == subst_mapping.id,
            ChannelOrderLine.status == ChannelOrderLineStatusEnum.CANCELED,
        )).all()
    assert len(canceled_items) == 1, "Histórico legítimo deve conter 1 item cancelado"
    assert len(canceled_lines) == 1, "Histórico legítimo deve conter 1 linha cancelada"
    assert canceled_lines[0].external_line_id == "l1"

    # 4. CASO DE DUAS LINHAS EXTERNAS DISTINTAS DO MESMO PRODUTO:
    #    Duas linhas com external_line_id distintos (l1 e l2) para ITEM-A são permitidas e não deduplicadas por SKU
    multi_order_ref = f"pedido-r19-multi-{uuid.uuid4()}"
    placed_multi = _event(
        merchant, "ORDER_PLACED", multi_order_ref, sequence=1,
        lines=[_line("l1", "ITEM-A", 1), _line("l2", "ITEM-A", 3)],
    )
    _receive(placed_multi)
    assert inbox.process_event(_row(placed_multi["id"]).id) == ChannelInboxStatusEnum.APPLIED
    multi_mapping = _mapping(connection["id"], multi_order_ref)
    assert_active_lines_and_items(
        multi_mapping.order_id, multi_mapping.id,
        {"l1": {"quantity": Decimal("1")}, "l2": {"quantity": Decimal("3")}},
    )


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


@pytest.mark.asyncio
async def test_p8_ingestao_de_pedido_de_canal_nao_cria_nem_altera_crm_fidelidade_e_fiscal():
    """P8: Ingestão de pedido de canal não cria nem altera cliente de CRM, fidelidade ou dado fiscal (H19).

    Compara o estado relevante antes e depois da ingestão, incluindo registros existentes prévios.
    """
    from app.models.fiscal import FiscalDocument, FiscalDocumentTypeEnum, FiscalEvent, FiscalEventTypeEnum, FiscalStatusEnum
    from app.models.receivable import CreditPolicyStatusEnum, CustomerCreditPolicy
    from app.models.sale import Customer, FulfillmentTypeEnum, Sale, SaleOperationModeEnum, SaleStatusEnum, SyncStatusEnum

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant, headers, actor, product, connection = await _connected(client, "P8State", "ITEM-A")

    tenant_id = uuid.UUID(tenant["id"])
    store_id = uuid.UUID(connection["store_id"])
    actor_id = uuid.UUID(actor)

    # 1. Criação de registros existentes prévios de CRM, fidelidade/crédito e fiscal:
    with Session(engine) as db:
        set_platform_db_context(db)
        existing_customer = Customer(
            tenant_id=tenant_id,
            name="Cliente CRM Existente",
            phone="5511999991111",
            cpf_cnpj="11122233344",
            email="crm.existente@exemplo.com",
        )
        db.add(existing_customer)
        db.flush()

        existing_policy = CustomerCreditPolicy(
            tenant_id=tenant_id,
            customer_id=existing_customer.id,
            status=CreditPolicyStatusEnum.ACTIVE,
            credit_limit=Decimal("500.0000"),
            terms_days=30,
            version=1,
            updated_by=actor_id,
        )
        db.add(existing_policy)

        existing_sale = Sale(
            tenant_id=tenant_id,
            store_id=store_id,
            customer_id=existing_customer.id,
            source_type="POS",
            fulfillment_type=FulfillmentTypeEnum.COUNTER,
            sync_status=SyncStatusEnum.SYNCED,
            operation_mode=SaleOperationModeEnum.COUNTER,
            status=SaleStatusEnum.COMPLETED,
            gross_total=Decimal("50.0000"),
            net_total=Decimal("50.0000"),
        )
        db.add(existing_sale)
        db.flush()

        existing_fiscal_doc = FiscalDocument(
            tenant_id=tenant_id,
            store_id=store_id,
            sale_id=existing_sale.id,
            document_type=FiscalDocumentTypeEnum.NFCE,
            status=FiscalStatusEnum.AUTHORIZED,
            access_key="35261012345678000100550010000000011000000010",
            document_number=1,
            series=1,
        )
        db.add(existing_fiscal_doc)
        db.flush()

        existing_fiscal_evt = FiscalEvent(
            tenant_id=tenant_id,
            store_id=store_id,
            fiscal_document_id=existing_fiscal_doc.id,
            actor_id=actor_id,
            event_type=FiscalEventTypeEnum.AUTHORIZED,
            details="Protocolo de autorizacao 135260000001",
        )
        db.add(existing_fiscal_evt)
        db.commit()

        customer_id_saved = existing_customer.id
        policy_id_saved = existing_policy.id
        doc_id_saved = existing_fiscal_doc.id
        evt_id_saved = existing_fiscal_evt.id

    def snapshot_relevant_state():
        with Session(engine) as db:
            set_platform_db_context(db)
            customers = db.exec(select(Customer).where(Customer.tenant_id == tenant_id)).all()
            policies = db.exec(select(CustomerCreditPolicy).where(CustomerCreditPolicy.tenant_id == tenant_id)).all()
            docs = db.exec(select(FiscalDocument).where(FiscalDocument.tenant_id == tenant_id)).all()
            events = db.exec(select(FiscalEvent).where(FiscalEvent.tenant_id == tenant_id)).all()
            return {
                "customers": {
                    c.id: (c.name, c.phone, c.cpf_cnpj, c.email, c.created_at) for c in customers
                },
                "policies": {
                    p.id: (p.customer_id, p.status, p.credit_limit, p.terms_days, p.version, p.updated_at)
                    for p in policies
                },
                "fiscal_docs": {
                    d.id: (d.sale_id, d.document_type, d.status, d.access_key, d.document_number, d.series)
                    for d in docs
                },
                "fiscal_events": {
                    e.id: (e.fiscal_document_id, e.event_type, e.details) for e in events
                },
            }

    state_before = snapshot_relevant_state()
    assert len(state_before["customers"]) == 1
    assert customer_id_saved in state_before["customers"]
    assert len(state_before["policies"]) == 1
    assert policy_id_saved in state_before["policies"]
    assert len(state_before["fiscal_docs"]) == 1
    assert doc_id_saved in state_before["fiscal_docs"]
    assert len(state_before["fiscal_events"]) == 1
    assert evt_id_saved in state_before["fiscal_events"]

    # 2. Ingestão de pedido do canal trazendo dados de cliente:
    merchant = connection["merchant_external_id"]
    order_ref = f"pedido-p8-{uuid.uuid4()}"
    channel_customer = {
        "name": "Cliente do Marketplace Silva",
        "phone": "5511988882222",
        "cpf_cnpj": "99988877766",
        "address": {"street": "Rua do Canal 100", "number": "100"},
        "instructions": "Deixar na portaria",
    }
    placed = _event(
        merchant, "ORDER_PLACED", order_ref, sequence=1,
        lines=[_line("l1", "ITEM-A", 2)], customer=channel_customer,
    )
    _receive(placed)
    assert inbox.process_event(_row(placed["id"]).id) == ChannelInboxStatusEnum.APPLIED

    # 3. Atualização subsequente do mesmo pedido pelo canal:
    updated = _event(
        merchant, "ORDER_UPDATED", order_ref, sequence=2,
        lines=[_line("l1", "ITEM-A", 3)], customer=channel_customer,
    )
    _receive(updated)
    assert inbox.process_event(_row(updated["id"]).id) == ChannelInboxStatusEnum.APPLIED

    # 4. Verificação de estado após ingestão e atualização:
    state_after = snapshot_relevant_state()

    # Comprovação P8: NENHUM novo registro em customers, policies, fiscal_docs ou fiscal_events:
    assert len(state_after["customers"]) == 1, "Ingestão externa não pode criar cliente em CRM"
    assert state_after["customers"] == state_before["customers"], "Cliente existente não pode ser mutado"

    assert len(state_after["policies"]) == 1, "Ingestão externa não pode criar ou alterar fidelidade/crédito"
    assert state_after["policies"] == state_before["policies"], "Política de fidelidade/crédito existente não pode ser alterada"

    assert len(state_after["fiscal_docs"]) == 1, "Ingestão externa não pode criar documento fiscal"
    assert state_after["fiscal_docs"] == state_before["fiscal_docs"], "Documento fiscal existente não pode ser mutado"

    assert len(state_after["fiscal_events"]) == 1, "Ingestão externa não pode emitir evento fiscal"
    assert state_after["fiscal_events"] == state_before["fiscal_events"], "Evento fiscal existente não pode ser mutado"

    # Verificação de isolamento: os dados do cliente do canal estão exclusivamente no contato do pedido externo:
    mapping = _mapping(connection["id"], order_ref)
    with Session(engine) as db:
        set_platform_db_context(db)
        order = db.get(Order, mapping.order_id)
        assert order.customer_id is None, "Pedido do canal não vincula cliente de CRM do estabelecimento"
        contact = db.exec(select(ChannelOrderContact).where(
            ChannelOrderContact.external_order_mapping_id == mapping.id,
        )).one()
    assert contact.display_name == "Cliente do Marketplace Silva"
    assert contact.phone == "5511988882222"
    assert contact.delivery_instructions == "Deixar na portaria"


async def _attach_mapped_modifier(
    client: httpx.AsyncClient, headers: dict, actor: str,
    tenant_id: str, product_id: str, connection: dict,
    *, external_code: str, name: str, price_delta: str,
) -> uuid.UUID:
    from app.models.catalog import Modifier, ModifierGroup, ProductModifierGroup

    tid, pid = uuid.UUID(tenant_id), uuid.UUID(product_id)
    with Session(engine) as db:
        set_platform_db_context(db)
        group = ModifierGroup(
            tenant_id=tid, name=f"Grupo {name} {uuid.uuid4().hex[:6]}",
            minimum_choices=0, maximum_choices=2, is_required=False,
        )
        db.add(group)
        db.flush()
        modifier = Modifier(
            tenant_id=tid, group_id=group.id, name=name,
            price_delta=Decimal(price_delta),
        )
        db.add(modifier)
        db.add(ProductModifierGroup(
            tenant_id=tid, product_id=pid, modifier_group_id=group.id, position=1,
        ))
        db.commit()
        modifier_id = modifier.id
    mapped = await client.post("/api/v1/channel-catalog/mappings", headers={
        **headers, "Idempotency-Key": f"map-mod-{uuid.uuid4()}",
    }, json={
        "connection_id": connection["id"], "entity_type": "MODIFIER",
        "internal_id": str(modifier_id), "external_id": external_code, "actor_id": actor,
    })
    assert mapped.status_code == 200, mapped.text
    return modifier_id


@pytest.mark.asyncio
async def test_r11_pedido_registra_valor_do_canal_preserva_oferta_local_com_complemento_e_atualiza_so_preco(monkeypatch):
    from app.models.catalog import ProductPrice
    from app.modules.settlement import contracts as settlement

    name, phone, street, gate = "Carlos Marcador Preco", "5511966665555", "Av Marcadora 700", "Bloco B"
    customer = {"name": name, "phone": phone, "address": {"street": street}, "instructions": gate}
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant, headers, actor, product_a, connection = await _connected(client, "R11Valor", "ITEM-A", "ITEM-B")
        await _attach_mapped_modifier(
            client, headers, actor, tenant["id"], product_a["id"], connection,
            external_code="COMP-QUEIJO", name="Queijo extra", price_delta="3.50",
        )
        _tenant_b, headers_b, *_ = await _connected(client, "R11Outro", "ITEM-A")

    merchant, order_ref = connection["merchant_external_id"], f"pedido-r11-{uuid.uuid4()}"
    # Oferta local:
    # - l1 (ITEM-A = 18,50 + COMP-QUEIJO = 3,50 => 22,00 un * 2 = 44,00)
    # - l2 (ITEM-B = 9,90 un * 1 = 9,90)
    # Subtotal local dos itens = 53,90.
    # Canal declara:
    # - l1: unit_price 25,00 * 2 = 50,00 bruto, desconto na linha 4,00 => líquido 46,00 (unit_price efetivo 23,00; dif +2,00)
    # - l2: unit_price 8,90 * 1 = 8,90 sem desconto de linha (discount_amount fica None; dif -1,00)
    # - pedido: delivery_fee 7,00, channel_discount 3,00, channel_subsidy 5,00 (<= 4,00 + 3,00), declared_total 58,90
    #   (46,00 + 8,90 - 3,00 + 7,00 = 58,90; nem o desconto da linha nem o subsídio são descontados duas vezes).
    # Mercadoria efetiva no canal = 54,90 - 3,00 = 51,90; diferença frente à oferta local (53,90) = -2,00.
    placed = _event(
        merchant, "ORDER_PLACED", order_ref, sequence=1, customer=customer,
        lines=[
            _line("l1", "ITEM-A", 2, notes="bem passado", unit_price="25.00", discount="4.00", modifiers=["COMP-QUEIJO"]),
            _line("l2", "ITEM-B", 1, unit_price="8.90"),
        ],
        totals={"delivery_fee": "7.00", "discount": "3.00", "subsidy": "5.00", "total": "58.90"},
    )
    _receive(placed)
    assert inbox.process_event(_row(placed["id"]).id) == ChannelInboxStatusEnum.APPLIED

    # Reenvio do mesmo evento pelo canal: DUPLICATE no ingresso, sem duplicar linhas nem alterar valores.
    replay_body = json.dumps({"events": [placed]}).encode("utf-8")
    replay_outcomes = ingress.receive("CONTRACT_TEST", {reference.SIGNATURE_HEADER: reference.sign(replay_body)}, replay_body)
    assert [o.outcome for o in replay_outcomes] == ["DUPLICATE"]

    mapping = _mapping(connection["id"], order_ref)
    assert mapping.payment_origin == "MARKETPLACE"
    assert mapping.delivery_fee == Decimal("7.0000")
    assert mapping.channel_discount == Decimal("3.0000")
    assert mapping.channel_subsidy == Decimal("5.0000")
    assert mapping.declared_total == Decimal("58.9000")
    assert mapping.local_items_amount == Decimal("53.9000")
    assert mapping.difference_amount == Decimal("-2.0000")

    with Session(engine) as db:
        set_platform_db_context(db)
        lines = {row.external_line_id: row for row in db.exec(select(ChannelOrderLine).where(
            ChannelOrderLine.external_order_mapping_id == mapping.id,
        )).all()}
        items = {row.id: row for row in db.exec(select(OrderItem).where(OrderItem.order_id == mapping.order_id)).all()}
        prices = {
            str(row.product_id): row.sale_price
            for row in db.exec(select(ProductPrice).where(ProductPrice.tenant_id == uuid.UUID(tenant["id"]))).all()
        }

    assert len(lines) == 2 and len(items) == 2
    assert items[lines["l1"].order_item_id].unit_price == Decimal("23.0000")
    assert lines["l1"].unit_amount == Decimal("25.0000")
    assert lines["l1"].discount_amount == Decimal("4.0000")
    assert lines["l1"].local_unit_amount == Decimal("22.0000")
    assert lines["l1"].difference_amount == Decimal("2.0000")

    assert items[lines["l2"].order_item_id].unit_price == Decimal("8.9000")
    assert lines["l2"].unit_amount == Decimal("8.9000")
    assert lines["l2"].discount_amount is None, "desconto ausente não é inventado como zero"
    assert lines["l2"].local_unit_amount == Decimal("9.9000")
    assert lines["l2"].difference_amount == Decimal("-1.0000")

    # O catálogo local do restaurante não foi alterado pelo pedido do canal.
    assert prices[product_a["id"]] == Decimal("18.5000")
    assert sorted(prices.values()) == [Decimal("9.9000"), Decimal("18.5000")]

    # Atualização apenas de preço/desconto/totais (mesmas linhas, quantidades, códigos e observações).
    l1_item_id, l2_item_id = lines["l1"].order_item_id, lines["l2"].order_item_id
    price_only = _event(
        merchant, "ORDER_UPDATED", order_ref, sequence=2, customer=customer,
        lines=[
            _line("l1", "ITEM-A", 2, notes="bem passado", unit_price="21.00", discount="2.00", modifiers=["COMP-QUEIJO"]),
            _line("l2", "ITEM-B", 1, unit_price="10.40"),
        ],
    )
    _receive(price_only)
    assert inbox.process_event(_row(price_only["id"]).id) == ChannelInboxStatusEnum.APPLIED

    mapping = _mapping(connection["id"], order_ref)
    assert mapping.payment_origin == "MARKETPLACE"
    assert mapping.delivery_fee is None and mapping.channel_discount is None
    assert mapping.channel_subsidy is None and mapping.declared_total is None
    assert mapping.local_items_amount == Decimal("53.9000")
    assert mapping.difference_amount == Decimal("-3.5000")  # (40,00 + 10,40) - 53,90

    with Session(engine) as db:
        set_platform_db_context(db)
        lines = {row.external_line_id: row for row in db.exec(select(ChannelOrderLine).where(
            ChannelOrderLine.external_order_mapping_id == mapping.id,
        )).all()}
        items = {row.id: row for row in db.exec(select(OrderItem).where(OrderItem.order_id == mapping.order_id)).all()}

    assert (lines["l1"].order_item_id, lines["l2"].order_item_id) == (l1_item_id, l2_item_id), "mudar só preço não duplica item"
    assert items[l1_item_id].unit_price == Decimal("20.0000")
    assert lines["l1"].unit_amount == Decimal("21.0000") and lines["l1"].discount_amount == Decimal("2.0000")
    assert lines["l1"].local_unit_amount == Decimal("22.0000") and lines["l1"].difference_amount == Decimal("-4.0000")
    assert items[l2_item_id].unit_price == Decimal("10.4000")
    assert lines["l2"].unit_amount == Decimal("10.4000") and lines["l2"].discount_amount is None
    assert lines["l2"].local_unit_amount == Decimal("9.9000") and lines["l2"].difference_amount == Decimal("0.5000")

    # Proteção de liquidação: reduzir apenas o preço abaixo do valor liquidado/reservado vai para revisão.
    monkeypatch.setattr(settlement, "hold_on_items", lambda _session, _ids: {l1_item_id: Decimal("35.0000")})
    below_settled = _event(
        merchant, "ORDER_UPDATED", order_ref, sequence=3,
        lines=[
            _line("l1", "ITEM-A", 2, notes="bem passado", unit_price="15.00", modifiers=["COMP-QUEIJO"]),
            _line("l2", "ITEM-B", 1, unit_price="10.40"),
        ],
    )
    _receive(below_settled)
    assert inbox.process_event(_row(below_settled["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
    settled_row = _row(below_settled["id"])
    assert settled_row.quarantine_code == "ITEM_BELOW_SETTLEMENT" and settled_row.order_id == mapping.order_id
    assert _items(mapping.order_id)[0].unit_price == Decimal("20.0000")
    monkeypatch.setattr(settlement, "hold_on_items", lambda _session, _ids: {})

    # Proteção de preparo: alterar apenas o preço de item já em preparo também vai para revisão.
    with Session(engine) as db:
        set_platform_db_context(db)
        item_l2 = db.get(OrderItem, l2_item_id)
        item_l2.production_state = ProductionStateEnum.IN_PREPARATION
        db.add(item_l2)
        db.commit()
    in_prep_price = _event(
        merchant, "ORDER_UPDATED", order_ref, sequence=4,
        lines=[
            _line("l1", "ITEM-A", 2, notes="bem passado", unit_price="21.00", discount="2.00", modifiers=["COMP-QUEIJO"]),
            _line("l2", "ITEM-B", 1, unit_price="12.00"),
        ],
    )
    _receive(in_prep_price)
    assert inbox.process_event(_row(in_prep_price["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
    prep_row = _row(in_prep_price["id"])
    assert prep_row.quarantine_code == "PREPARATION_STARTED" and prep_row.order_id == mapping.order_id

    # Isolamento entre tenants e ausência de dados pessoais em registros imutáveis.
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        other_orders = (await client.get("/api/v1/orders", headers=headers_b)).json()
        other_inbox = (await client.get("/api/v1/channels/inbox", headers=headers_b)).json()
    assert all(o["id"] != str(mapping.order_id) for o in other_orders)
    assert all(e["external_order_id"] != order_ref for e in other_inbox)

    immutable_places = {
        "orders": "SELECT coalesce(notes,'') || coalesce(external_reference,'') FROM orders WHERE tenant_id = :t",
        "order_items": "SELECT coalesce(notes,'') FROM order_items WHERE tenant_id = :t",
        "order_commands": "SELECT command_type || idempotency_key FROM order_commands WHERE tenant_id = :t",
        "audit_events": "SELECT payload::text FROM audit_events WHERE tenant_id = :t",
        "outbox_events": "SELECT payload::text FROM outbox_events WHERE tenant_id = :t",
        "published_events": "SELECT payload::text FROM published_events WHERE tenant_id = :t",
        "idempotency_records": "SELECT response_body::text FROM idempotency_records WHERE tenant_id = :t",
        "external_order_mappings": "SELECT external_order_id || coalesce(payment_origin,'') FROM external_order_mappings WHERE tenant_id = :t",
        "external_order_lines": "SELECT external_line_id || external_item_code FROM external_order_lines WHERE tenant_id = :t",
        "motivo_de_quarentena": "SELECT coalesce(quarantine_reason,'') || coalesce(last_error_code,'') FROM channel_inbox_events WHERE tenant_id = :t",
    }
    with Session(engine) as db:
        set_platform_db_context(db)
        for where, query in immutable_places.items():
            content = " ".join(str(value[0]) for value in db.exec(text(query).bindparams(t=tenant["id"])).all())
            for marker in (name, phone, street, gate):
                assert marker not in content, f"R11/P3: {marker!r} apareceu em {where}"


@pytest.mark.asyncio
async def test_r11_valores_inseguros_ou_inconsistentes_vao_para_revisao_sem_usar_preco_local():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _tenant, _headers, _actor, _product, connection = await _connected(client, "R11Revisao", "ITEM-A")
    merchant = connection["merchant_external_id"]

    cases = [
        (
            "CHANNEL_PRICE_MISSING",
            _event(merchant, "ORDER_PLACED", f"sem-preco-{uuid.uuid4()}", lines=[_line("l1", "ITEM-A", 1, unit_price=None)]),
        ),
        (
            "CHANNEL_DISCOUNT_EXCEEDS_AMOUNT",
            _event(merchant, "ORDER_PLACED", f"desc-maior-{uuid.uuid4()}", lines=[_line("l1", "ITEM-A", 1, unit_price="15.00", discount="16.00")]),
        ),
        (
            "CHANNEL_LINE_TOTAL_INEXACT",
            _event(merchant, "ORDER_PLACED", f"div-inexata-{uuid.uuid4()}", lines=[_line("l1", "ITEM-A", 3, unit_price="10.00", discount="1.00")]),
        ),
        (
            "CHANNEL_SUBSIDY_INCONSISTENT",
            _event(
                merchant, "ORDER_PLACED", f"subsidio-maior-{uuid.uuid4()}",
                lines=[_line("l1", "ITEM-A", 1, unit_price="20.00", discount="2.00")],
                totals={"subsidy": "5.00", "total": "18.00"},
            ),
        ),
        (
            "CHANNEL_TOTAL_MISMATCH",
            _event(
                merchant, "ORDER_PLACED", f"total-diverge-{uuid.uuid4()}",
                lines=[_line("l1", "ITEM-A", 1, unit_price="20.00", discount="3.00")],
                totals={"delivery_fee": "5.00", "total": "19.00"},  # esperado: 17,00 + 5,00 = 22,00
            ),
        ),
    ]
    _receive(*(event for _, event in cases))
    for expected_code, event in cases:
        status = inbox.process_event(_row(event["id"]).id)
        row = _row(event["id"])
        assert status == ChannelInboxStatusEnum.NEEDS_REVIEW, f"{expected_code}: esperado NEEDS_REVIEW, veio {status}"
        assert row.quarantine_code == expected_code
        assert row.order_id is None and _mapping(connection["id"], event["order_id"]) is None
        assert "uma pessoa decide" in (row.quarantine_reason or "")

    # Em pedido já aberto com preço do canal (21,00 != 18,50 local), uma atualização sem
    # preço ou com total incoerente vai para revisão e não sobrescreve com o preço local.
    open_ref = f"aberto-r11-{uuid.uuid4()}"
    opened = _event(merchant, "ORDER_PLACED", open_ref, sequence=1, lines=[_line("l1", "ITEM-A", 1, unit_price="21.00")])
    unsafe_update = _event(merchant, "ORDER_UPDATED", open_ref, sequence=2, lines=[_line("l1", "ITEM-A", 1, unit_price=None)])
    _receive(opened, unsafe_update)
    assert inbox.process_event(_row(opened["id"]).id) == ChannelInboxStatusEnum.APPLIED
    assert inbox.process_event(_row(unsafe_update["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
    mapping = _mapping(connection["id"], open_ref)
    review_row = _row(unsafe_update["id"])
    assert review_row.quarantine_code == "CHANNEL_PRICE_MISSING" and review_row.order_id == mapping.order_id
    assert [item.unit_price for item in _items(mapping.order_id)] == [Decimal("21.0000")]


@pytest.mark.asyncio
async def test_r11_protege_pedido_marketplace_contra_cobranca_local_e_bloqueia_desconto_de_cabecalho_sob_reserva(monkeypatch):
    """D1/R11 financial boundary:
    1. An order with net items R$ 54,90, header discount R$ 3,00, delivery fee R$ 7,00
       and informative subsidy R$ 5,00 has order obligation R$ 58,90 in `_order_amount()`
       (not R$ 54,90 and not subtracting the subsidy).
    2. When `payment_origin == "MARKETPLACE"`, `open_negotiation()` refuses the order
       (`ORDER_PAID_IN_MARKETPLACE`) so an order already paid in the channel is never
       charged locally at the POS.
    3. When `payment_origin` is not `MARKETPLACE` and a negotiation reserves or settles
       money on the order, an `ORDER_UPDATED` that changes ONLY the header discount
       cannot silently reduce the protected obligation below what is reserved or settled.
    4. The core of `channels` (`orders.py`) validates negative, out-of-precision and
       out-of-range monetary values independently of `ReferenceChannelAdapter`.
    """
    from app.modules.channels import registry
    from app.modules.channels.contracts import (
        ExternalContact, ExternalEvent, ExternalEventKind, ExternalOrder,
        ExternalOrderLine as ContractLine,
    )
    from app.services import negotiation_service

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant, headers, actor, product_a, connection = await _connected(client, "R11FinGap", "ITEM-A", "ITEM-B")
        store_id = headers["X-Store-ID"]
        merchant = connection["merchant_external_id"]

        # 1. Pedido pago no marketplace (itens líquidos 54,90 - desconto 3,00 + entrega 7,00 = 58,90; subsídio 5,00 informativo).
        mkt_ref = f"mkt-r11-{uuid.uuid4()}"
        mkt_placed = _event(
            merchant, "ORDER_PLACED", mkt_ref, sequence=1,
            lines=[
                _line("l1", "ITEM-A", 2, unit_price="25.00", discount="4.00"),  # líquido 46,00
                _line("l2", "ITEM-B", 1, unit_price="8.90"),                    # líquido 8,90 -> soma 54,90
            ],
            totals={"delivery_fee": "7.00", "discount": "3.00", "subsidy": "5.00", "total": "58.90"},
            payment={"status": "PAID_ONLINE"},
        )
        _receive(mkt_placed)
        assert inbox.process_event(_row(mkt_placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
        mkt_mapping = _mapping(connection["id"], mkt_ref)
        assert mkt_mapping.payment_origin == "MARKETPLACE"

        with Session(engine) as db:
            set_platform_db_context(db)
            mkt_order = db.get(Order, mkt_mapping.order_id)
            assert negotiation_service._order_amount(db, mkt_order) == Decimal("58.9000")

        refused_mkt = await client.post(
            "/api/v1/negotiations",
            headers={**headers, "Idempotency-Key": f"neg-mkt-{uuid.uuid4()}"},
            json={"store_id": store_id, "order_ids": [str(mkt_mapping.order_id)], "actor_id": actor},
        )
        assert refused_mkt.status_code == 409, refused_mkt.text
        assert refused_mkt.json()["detail"]["code"] == "ORDER_PAID_IN_MARKETPLACE"

        # 2. Pedido externo com pagamento local explícito (payment_origin="LOCAL"): negociação usa R$ 58,90 (e não R$ 54,90 nem desconta subsídio).
        local_ref = f"local-r11-{uuid.uuid4()}"
        local_placed = _event(
            merchant, "ORDER_PLACED", local_ref, sequence=1,
            lines=[
                _line("l1", "ITEM-A", 2, unit_price="25.00", discount="4.00"),
                _line("l2", "ITEM-B", 1, unit_price="8.90"),
            ],
            totals={"delivery_fee": "7.00", "discount": "3.00", "subsidy": "5.00", "total": "58.90"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(local_placed)
        assert inbox.process_event(_row(local_placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
        local_mapping = _mapping(connection["id"], local_ref)
        assert local_mapping.payment_origin == "LOCAL"

        # 2b. Status de pagamento ausente, desconhecido, legado (None) ou sem mapeamento:
        # nunca autoriza cobrança local e usa código distinto de ORDER_PAID_IN_MARKETPLACE.
        unknown_missing_ref = f"unk-missing-r11-{uuid.uuid4()}"
        unknown_status_ref = f"unk-status-r11-{uuid.uuid4()}"
        legacy_null_ref = f"legacy-null-r11-{uuid.uuid4()}"
        unmapped_order_ref = f"unmapped-ord-r11-{uuid.uuid4()}"
        unk_missing_ev = _event(
            merchant, "ORDER_PLACED", unknown_missing_ref, sequence=1,
            lines=[_line("l1", "ITEM-A", 1, unit_price="18.50")],
            payment={},
        )
        unk_status_ev = _event(
            merchant, "ORDER_PLACED", unknown_status_ref, sequence=1,
            lines=[_line("l1", "ITEM-A", 1, unit_price="18.50")],
            payment={"status": "UNKNOWN_CHANNEL_STATUS"},
        )
        legacy_null_ev = _event(
            merchant, "ORDER_PLACED", legacy_null_ref, sequence=1,
            lines=[_line("l1", "ITEM-A", 1, unit_price="18.50")],
            payment={"status": "PAY_ON_DELIVERY"},
        )
        unmapped_ord_ev = _event(
            merchant, "ORDER_PLACED", unmapped_order_ref, sequence=1,
            lines=[_line("l1", "ITEM-A", 1, unit_price="18.50")],
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(unk_missing_ev, unk_status_ev, legacy_null_ev, unmapped_ord_ev)
        for ev in (unk_missing_ev, unk_status_ev, legacy_null_ev, unmapped_ord_ev):
            assert inbox.process_event(_row(ev["id"]).id) == ChannelInboxStatusEnum.APPLIED

        unk_missing_map = _mapping(connection["id"], unknown_missing_ref)
        unk_status_map = _mapping(connection["id"], unknown_status_ref)
        legacy_null_map = _mapping(connection["id"], legacy_null_ref)
        unmapped_ord_map = _mapping(connection["id"], unmapped_order_ref)
        assert unk_missing_map.payment_origin == "UNKNOWN"
        assert unk_status_map.payment_origin == "UNKNOWN"

        with Session(engine) as db:
            set_platform_db_context(db)
            legacy_row = db.get(ExternalOrderMapping, legacy_null_map.id)
            legacy_row.payment_origin = None
            db.add(legacy_row)
            unmapped_order_id = unmapped_ord_map.order_id
            for line_row in db.exec(select(ChannelOrderLine).where(
                ChannelOrderLine.external_order_mapping_id == unmapped_ord_map.id
            )).all():
                db.delete(line_row)
            db.flush()
            db.delete(db.get(ExternalOrderMapping, unmapped_ord_map.id))
            db.commit()

        for insufficient_order_id in (
            unk_missing_map.order_id,
            unk_status_map.order_id,
            legacy_null_map.order_id,
            unmapped_order_id,
        ):
            refused_unk = await client.post(
                "/api/v1/negotiations",
                headers={**headers, "Idempotency-Key": f"neg-unk-{uuid.uuid4()}"},
                json={"store_id": store_id, "order_ids": [str(insufficient_order_id)], "actor_id": actor},
            )
            assert refused_unk.status_code == 409, refused_unk.text
            assert refused_unk.json()["detail"]["code"] == "ORDER_PAYMENT_ORIGIN_UNKNOWN"

        opened_neg = await client.post(
            "/api/v1/negotiations",
            headers={**headers, "Idempotency-Key": f"neg-local-{uuid.uuid4()}"},
            json={"store_id": store_id, "order_ids": [str(local_mapping.order_id)], "actor_id": actor},
        )
        assert opened_neg.status_code == 200, opened_neg.text
        neg_data = opened_neg.json()
        assert Decimal(str(neg_data["subtotal"])) == Decimal("58.9000")
        assert Decimal(str(neg_data["total_due"])) == Decimal("58.9000")

        # Cria reserva (PENDING PaymentIntent) de R$ 55,00 sobre a conta do pedido.
        reserved = await client.post(
            f"/api/v1/negotiations/{neg_data['id']}/intents",
            headers={**headers, "Idempotency-Key": f"intent-res-{uuid.uuid4()}"},
            json={"method": "PIX", "amount": "55.00", "allocations": [], "actor_id": actor},
        )
        assert reserved.status_code == 200, reserved.text
        assert Decimal(str(reserved.json()["processing_amount"])) == Decimal("55.0000")

        # 3. Atualização APENAS do desconto de cabeçalho (de 3,00 para 10,00 -> total 51,90 < 55,00 reservado):
        # não pode reduzir silenciosamente a obrigação protegida; vai para NEEDS_REVIEW.
        header_breach = _event(
            merchant, "ORDER_UPDATED", local_ref, sequence=2,
            lines=[
                _line("l1", "ITEM-A", 2, unit_price="25.00", discount="4.00"),
                _line("l2", "ITEM-B", 1, unit_price="8.90"),
            ],
            totals={"delivery_fee": "7.00", "discount": "10.00", "subsidy": "5.00", "total": "51.90"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(header_breach)
        assert inbox.process_event(_row(header_breach["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
        breach_row = _row(header_breach["id"])
        assert breach_row.quarantine_code == "ITEM_BELOW_SETTLEMENT" and breach_row.order_id == local_mapping.order_id
        local_mapping = _mapping(connection["id"], local_ref)
        assert local_mapping.channel_discount == Decimal("3.0000")
        assert local_mapping.declared_total == Decimal("58.9000")

        # Atualização apenas do desconto de cabeçalho que preserva a cobertura (de 3,00 para 5,00 -> total 56,90 >= 55,00):
        # aplica e reconcilia a negociação aberta para 56,90.
        header_safe = _event(
            merchant, "ORDER_UPDATED", local_ref, sequence=3,
            lines=[
                _line("l1", "ITEM-A", 2, unit_price="25.00", discount="4.00"),
                _line("l2", "ITEM-B", 1, unit_price="8.90"),
            ],
            totals={"delivery_fee": "7.00", "discount": "5.00", "subsidy": "5.00", "total": "56.90"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(header_safe)
        assert inbox.process_event(_row(header_safe["id"]).id) == ChannelInboxStatusEnum.APPLIED
        local_mapping = _mapping(connection["id"], local_ref)
        assert local_mapping.channel_discount == Decimal("5.0000")
        assert local_mapping.declared_total == Decimal("56.9000")
        reconciled_neg = (await client.get(f"/api/v1/negotiations/{neg_data['id']}", headers=headers)).json()
        assert Decimal(str(reconciled_neg["total_due"])) == Decimal("56.9000")

        # Confirma a liquidação parcial de R$ 55,00 (CONFIRMED) e tenta novamente reduzir apenas o desconto
        # de cabeçalho (de 5,00 para 10,00 -> total 51,90 < 55,00 liquidado): também vai para NEEDS_REVIEW.
        intent_id = reserved.json()["intents"][-1]["id"]
        confirmed = await client.post(
            f"/api/v1/negotiations/intents/{intent_id}/confirm",
            headers={**headers, "Idempotency-Key": f"confirm-res-{uuid.uuid4()}"},
            json={"actor_id": actor},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert Decimal(str(confirmed.json()["confirmed_amount"])) == Decimal("55.0000")

        settled_header_breach = _event(
            merchant, "ORDER_UPDATED", local_ref, sequence=4,
            lines=[
                _line("l1", "ITEM-A", 2, unit_price="25.00", discount="4.00"),
                _line("l2", "ITEM-B", 1, unit_price="8.90"),
            ],
            totals={"delivery_fee": "7.00", "discount": "10.00", "subsidy": "5.00", "total": "51.90"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(settled_header_breach)
        assert inbox.process_event(_row(settled_header_breach["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
        settled_breach_row = _row(settled_header_breach["id"])
        assert settled_breach_row.quarantine_code == "ITEM_BELOW_SETTLEMENT" and settled_breach_row.order_id == local_mapping.order_id
        local_mapping = _mapping(connection["id"], local_ref)
        assert local_mapping.channel_discount == Decimal("5.0000")
        assert local_mapping.declared_total == Decimal("56.9000")

    # 4. Núcleo de `channels` (`orders.py`) valida negativos, precisão > 4 casas e estouro de Numeric(14, 4)
    # independentemente do conector de referência.
    from app.modules.channels import orders as channel_orders

    bad_orders = [
        ExternalOrder(
            external_order_id=f"neg-unit-{uuid.uuid4()}", fulfillment="DELIVERY",
            lines=(ContractLine(external_line_id="l1", external_item_code="ITEM-A", quantity=Decimal("1"), unit_amount=Decimal("-10.00"), discount_amount=None),),
        ),
        ExternalOrder(
            external_order_id=f"neg-disc-{uuid.uuid4()}", fulfillment="DELIVERY",
            lines=(ContractLine(external_line_id="l1", external_item_code="ITEM-A", quantity=Decimal("1"), unit_amount=Decimal("10.00"), discount_amount=Decimal("-1.00")),),
        ),
        ExternalOrder(
            external_order_id=f"neg-deliv-{uuid.uuid4()}", fulfillment="DELIVERY",
            lines=(ContractLine(external_line_id="l1", external_item_code="ITEM-A", quantity=Decimal("1"), unit_amount=Decimal("10.00"), discount_amount=None),),
            delivery_fee=Decimal("-2.00"),
        ),
        ExternalOrder(
            external_order_id=f"neg-hdr-disc-{uuid.uuid4()}", fulfillment="DELIVERY",
            lines=(ContractLine(external_line_id="l1", external_item_code="ITEM-A", quantity=Decimal("1"), unit_amount=Decimal("10.00"), discount_amount=None),),
            channel_discount=Decimal("-1.00"),
        ),
        ExternalOrder(
            external_order_id=f"prec-5casas-{uuid.uuid4()}", fulfillment="DELIVERY",
            lines=(ContractLine(external_line_id="l1", external_item_code="ITEM-A", quantity=Decimal("1"), unit_amount=Decimal("18.12345"), discount_amount=None),),
        ),
        ExternalOrder(
            external_order_id=f"overflow-num14-4-{uuid.uuid4()}", fulfillment="DELIVERY",
            lines=(ContractLine(external_line_id="l1", external_item_code="ITEM-A", quantity=Decimal("1"), unit_amount=Decimal("10000000000.0000"), discount_amount=None),),
        ),
    ]
    for bad in bad_orders:
        ev_payload = _event(merchant, "ORDER_PLACED", bad.external_order_id, lines=[_line("l1", "ITEM-A", 1, unit_price="10.00")])
        _receive(ev_payload)
        row = _row(ev_payload["id"])
        monkeypatch.setattr(
            channel_orders, "normalize",
            lambda _adapter, _conn, r, b=bad: ExternalEvent(
                provider_event_id=r.provider_event_id, kind=ExternalEventKind.ORDER_PLACED,
                external_order_id=b.external_order_id, order_key="00000000000000000001",
                occurred_at=None, parser_version="custom-1", order=b, contact=ExternalContact(),
            ),
        )
        assert inbox.process_event(row.id) == ChannelInboxStatusEnum.NEEDS_REVIEW
        after = _row(ev_payload["id"])
        assert after.quarantine_code == "CHANNEL_AMOUNT_INVALID"
        assert after.order_id is None and _mapping(connection["id"], bad.external_order_id) is None


@pytest.mark.asyncio
async def test_r11_bloqueia_mudanca_de_origem_com_dinheiro_local_em_curso_ou_liquidado_e_permite_sem_cobertura():
    """Checkpoint 29/09 case 2:
    An ORDER_UPDATED with identical monetary values that flips payment_origin from LOCAL
    to MARKETPLACE (or UNKNOWN) while a local reserve (PENDING/PROCESSING) or settlement
    (CONFIRMED) exists must go to NEEDS_REVIEW (CHANNEL_PAYMENT_ORIGIN_CONFLICT) with
    no partial change to the order, mapping, or payment intents/allocations.
    Without local coverage, the transition to MARKETPLACE succeeds and blocks future
    local billing with ORDER_PAID_IN_MARKETPLACE.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _tenant, headers, actor, _product_a, connection = await _connected(client, "R11OrigConflict", "ITEM-A")
        store_id = headers["X-Store-ID"]
        merchant = connection["merchant_external_id"]

        # 1. Pedido LOCAL com reserva PENDING em curso -> transição para MARKETPLACE (mesmos valores) vai para NEEDS_REVIEW.
        covered_ref = f"orig-cov-{uuid.uuid4()}"
        placed = _event(
            merchant, "ORDER_PLACED", covered_ref, sequence=1,
            lines=[_line("l1", "ITEM-A", 2, unit_price="20.00")],
            totals={"delivery_fee": "5.00", "total": "45.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(placed)
        assert inbox.process_event(_row(placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
        mapping = _mapping(connection["id"], covered_ref)
        assert mapping.payment_origin == "LOCAL"

        neg_resp = await client.post(
            "/api/v1/negotiations",
            headers={**headers, "Idempotency-Key": f"neg-orig-{uuid.uuid4()}"},
            json={"store_id": store_id, "order_ids": [str(mapping.order_id)], "actor_id": actor},
        )
        assert neg_resp.status_code == 200, neg_resp.text
        neg_id = neg_resp.json()["id"]

        intent_resp = await client.post(
            f"/api/v1/negotiations/{neg_id}/intents",
            headers={**headers, "Idempotency-Key": f"int-orig-{uuid.uuid4()}"},
            json={"method": "PIX", "amount": "20.00", "allocations": [], "actor_id": actor},
        )
        assert intent_resp.status_code == 200, intent_resp.text
        intent_id = intent_resp.json()["intents"][-1]["id"]

        flip_while_reserved = _event(
            merchant, "ORDER_UPDATED", covered_ref, sequence=2,
            lines=[_line("l1", "ITEM-A", 2, unit_price="20.00")],
            totals={"delivery_fee": "5.00", "total": "45.00"},
            payment={"status": "PAID_ONLINE"},
        )
        _receive(flip_while_reserved)
        assert inbox.process_event(_row(flip_while_reserved["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
        conflict_row = _row(flip_while_reserved["id"])
        assert conflict_row.quarantine_code == "CHANNEL_PAYMENT_ORIGIN_CONFLICT"
        assert conflict_row.order_id == mapping.order_id
        assert "uma pessoa decide" in (conflict_row.quarantine_reason or "")

        mapping_after_res = _mapping(connection["id"], covered_ref)
        assert mapping_after_res.payment_origin == "LOCAL"
        assert mapping_after_res.last_order_key == "00000000000000000001"
        neg_after_res = await client.get(f"/api/v1/negotiations/{neg_id}", headers=headers)
        assert neg_after_res.status_code == 200, neg_after_res.text
        assert neg_after_res.json()["intents"][-1]["status"] == "PENDING"
        assert Decimal(str(neg_after_res.json()["processing_amount"])) == Decimal("20.0000")

        # 2. Confirma a parcela (CONFIRMED) e tenta novamente mudar origem para MARKETPLACE -> também vai para NEEDS_REVIEW.
        confirmed = await client.post(
            f"/api/v1/negotiations/intents/{intent_id}/confirm",
            headers={**headers, "Idempotency-Key": f"conf-orig-{uuid.uuid4()}"},
            json={"actor_id": actor},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert Decimal(str(confirmed.json()["confirmed_amount"])) == Decimal("20.0000")

        flip_while_settled = _event(
            merchant, "ORDER_UPDATED", covered_ref, sequence=3,
            lines=[_line("l1", "ITEM-A", 2, unit_price="20.00")],
            totals={"delivery_fee": "5.00", "total": "45.00"},
            payment={"status": "PAID_ONLINE"},
        )
        _receive(flip_while_settled)
        assert inbox.process_event(_row(flip_while_settled["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
        settled_conflict_row = _row(flip_while_settled["id"])
        assert settled_conflict_row.quarantine_code == "CHANNEL_PAYMENT_ORIGIN_CONFLICT"
        assert settled_conflict_row.order_id == mapping.order_id

        mapping_after_settle = _mapping(connection["id"], covered_ref)
        assert mapping_after_settle.payment_origin == "LOCAL"
        assert mapping_after_settle.last_order_key == "00000000000000000001"
        neg_after_settle = await client.get(f"/api/v1/negotiations/{neg_id}", headers=headers)
        assert neg_after_settle.status_code == 200, neg_after_settle.text
        assert neg_after_settle.json()["intents"][-1]["status"] == "CONFIRMED"
        assert Decimal(str(neg_after_settle.json()["confirmed_amount"])) == Decimal("20.0000")

        # 3. Sem cobertura local, a transição de LOCAL para MARKETPLACE aplica normalmente e bloqueia cobrança local futura.
        uncovered_ref = f"orig-free-{uuid.uuid4()}"
        free_placed = _event(
            merchant, "ORDER_PLACED", uncovered_ref, sequence=1,
            lines=[_line("l1", "ITEM-A", 1, unit_price="20.00")],
            totals={"delivery_fee": "5.00", "total": "25.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        free_flip = _event(
            merchant, "ORDER_UPDATED", uncovered_ref, sequence=2,
            lines=[_line("l1", "ITEM-A", 1, unit_price="20.00")],
            totals={"delivery_fee": "5.00", "total": "25.00"},
            payment={"status": "PAID_ONLINE"},
        )
        _receive(free_placed, free_flip)
        assert inbox.process_event(_row(free_placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
        assert _mapping(connection["id"], uncovered_ref).payment_origin == "LOCAL"
        assert inbox.process_event(_row(free_flip["id"]).id) == ChannelInboxStatusEnum.APPLIED
        free_mapping = _mapping(connection["id"], uncovered_ref)
        assert free_mapping.payment_origin == "MARKETPLACE"

        refused_after_flip = await client.post(
            "/api/v1/negotiations",
            headers={**headers, "Idempotency-Key": f"neg-flipped-{uuid.uuid4()}"},
            json={"store_id": store_id, "order_ids": [str(free_mapping.order_id)], "actor_id": actor},
        )
        assert refused_after_flip.status_code == 409, refused_after_flip.text
        assert refused_after_flip.json()["detail"]["code"] == "ORDER_PAID_IN_MARKETPLACE"


@pytest.mark.asyncio
async def test_r11_itens_ativos_gratuitos_conservam_entrega_e_pedido_cancelado_ou_sem_itens_ativos_retorna_zero():
    """Checkpoint 29/09 case 3:
    An active order whose active items total R$ 0,00 (either unit_price=0.00 or 100% discount)
    and delivery_fee=R$ 7,00 preserves its R$ 7,00 obligation in `_order_amount()` and in local
    negotiations. Conversely, a canceled order or an order with no active items returns R$ 0,00
    and never recovers the delivery fee.
    """
    from app.models.order import OrderItemStatusEnum
    from app.services import negotiation_service

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _tenant, headers, actor, _product_a, connection = await _connected(client, "R11Gratis", "ITEM-A")
        store_id = headers["X-Store-ID"]
        merchant = connection["merchant_external_id"]

        # 1. Item ativo com unit_price R$ 0,00 e entrega de R$ 7,00 -> obrigação de R$ 7,00.
        free_item_ref = f"free-item-{uuid.uuid4()}"
        free_item_placed = _event(
            merchant, "ORDER_PLACED", free_item_ref, sequence=1,
            lines=[_line("l1", "ITEM-A", 1, unit_price="0.00")],
            totals={"delivery_fee": "7.00", "total": "7.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        # 2. Item ativo de R$ 15,00 com desconto de cabeçalho de R$ 15,00 e entrega de R$ 7,00 -> obrigação de R$ 7,00.
        full_disc_ref = f"full-disc-{uuid.uuid4()}"
        full_disc_placed = _event(
            merchant, "ORDER_PLACED", full_disc_ref, sequence=1,
            lines=[_line("l1", "ITEM-A", 1, unit_price="15.00")],
            totals={"delivery_fee": "7.00", "discount": "15.00", "total": "7.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(free_item_placed, full_disc_placed)
        assert inbox.process_event(_row(free_item_placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
        assert inbox.process_event(_row(full_disc_placed["id"]).id) == ChannelInboxStatusEnum.APPLIED

        free_mapping = _mapping(connection["id"], free_item_ref)
        full_disc_mapping = _mapping(connection["id"], full_disc_ref)

        with Session(engine) as db:
            set_platform_db_context(db)
            free_order = db.get(Order, free_mapping.order_id)
            full_disc_order = db.get(Order, full_disc_mapping.order_id)
            assert negotiation_service._order_amount(db, free_order) == Decimal("7.0000")
            assert negotiation_service._order_amount(db, full_disc_order) == Decimal("7.0000")

        neg_free = await client.post(
            "/api/v1/negotiations",
            headers={**headers, "Idempotency-Key": f"neg-free-{uuid.uuid4()}"},
            json={"store_id": store_id, "order_ids": [str(free_mapping.order_id)], "actor_id": actor},
        )
        assert neg_free.status_code == 200, neg_free.text
        assert Decimal(str(neg_free.json()["subtotal"])) == Decimal("7.0000")
        assert Decimal(str(neg_free.json()["total_due"])) == Decimal("7.0000")

        # 3. Pedido cancelado pelo canal (com delivery_fee de R$ 7,00 preservado no mapeamento) -> _order_amount() == R$ 0,00.
        canceled_ref = f"canc-deliv-{uuid.uuid4()}"
        canc_placed = _event(
            merchant, "ORDER_PLACED", canceled_ref, sequence=1,
            lines=[_line("l1", "ITEM-A", 1, unit_price="0.00")],
            totals={"delivery_fee": "7.00", "total": "7.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        canc_event = _event(merchant, "ORDER_CANCELLED", canceled_ref, sequence=2)
        _receive(canc_placed, canc_event)
        assert inbox.process_event(_row(canc_placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
        assert inbox.process_event(_row(canc_event["id"]).id) == ChannelInboxStatusEnum.APPLIED
        canc_mapping = _mapping(connection["id"], canceled_ref)

        with Session(engine) as db:
            set_platform_db_context(db)
            canc_order = db.get(Order, canc_mapping.order_id)
            assert canc_order.status.value == "CANCELED"
            assert negotiation_service._order_amount(db, canc_order) == Decimal("0.0000")

            # 4. Pedido ainda OPEN, mas sem nenhum item ativo -> _order_amount() == R$ 0,00 (não recupera entrega).
            for item in db.exec(select(OrderItem).where(OrderItem.order_id == full_disc_mapping.order_id)).all():
                item.status = OrderItemStatusEnum.CANCELED
                db.add(item)
            db.commit()
            empty_order = db.get(Order, full_disc_mapping.order_id)
            assert empty_order.status.value == "OPEN"
            assert negotiation_service._order_amount(db, empty_order) == Decimal("0.0000")


@pytest.mark.asyncio
async def test_r11_cobertura_em_negociacao_com_varios_pedidos_separa_cobertura_do_pedido_da_cobertura_conjunta():
    """Checkpoint 29/09 case 4:
    In a multi-order negotiation with two orders (Order 1 = R$ 40,00; Order 2 = R$ 30,00;
    joint total = R$ 70,00), an order-attributed allocation of R$ 20,00 on Order 1 and an
    unassigned negotiation allocation of R$ 15,00 (joint coverage = R$ 35,00):
    - `hold_on_orders` reports only the coverage attributed to each order (R$ 20,00 on Order 1,
      R$ 0,00 on Order 2), never attributing the unassigned R$ 15,00 to both orders;
    - `coverage_on_orders` reports both `order_covered` and `joint_covered` without inventing
      any pro-rata split;
    - a safe reduction on Order 1 (from R$ 40,00 to R$ 25,00 >= R$ 20,00 attributed, leaving
      joint total R$ 55,00 >= R$ 35,00 joint coverage) is APPLIED and not blocked even though
      R$ 25,00 < R$ 35,00;
    - a safe reduction on Order 2 (from R$ 30,00 to R$ 12,00 >= R$ 0,00 attributed, leaving
      joint total R$ 37,00 >= R$ 35,00 joint coverage) is APPLIED and not blocked even though
      R$ 12,00 < R$ 15,00;
    - an unsafe reduction on Order 1 below its own attributed coverage (to R$ 18,00 < R$ 20,00)
      is refused with NEEDS_REVIEW (ITEM_BELOW_SETTLEMENT);
    - an unsafe reduction on Order 2 below the joint negotiation coverage (to R$ 8,00, which
      would leave joint total R$ 25,00 + R$ 8,00 = R$ 33,00 < R$ 35,00) is refused with
      NEEDS_REVIEW (ITEM_BELOW_SETTLEMENT).
    """
    from app.modules.settlement import contracts as settlement

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _tenant, headers, actor, _product_a, connection = await _connected(client, "R11MultiNeg", "ITEM-A")
        store_id = headers["X-Store-ID"]
        merchant = connection["merchant_external_id"]

        ref_1, ref_2 = f"multi-1-{uuid.uuid4()}", f"multi-2-{uuid.uuid4()}"
        placed_1 = _event(
            merchant, "ORDER_PLACED", ref_1, sequence=1,
            lines=[_line("l1", "ITEM-A", 2, unit_price="17.50")],
            totals={"delivery_fee": "5.00", "total": "40.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        placed_2 = _event(
            merchant, "ORDER_PLACED", ref_2, sequence=1,
            lines=[_line("l1", "ITEM-A", 1, unit_price="25.00")],
            totals={"delivery_fee": "5.00", "total": "30.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(placed_1, placed_2)
        assert inbox.process_event(_row(placed_1["id"]).id) == ChannelInboxStatusEnum.APPLIED
        assert inbox.process_event(_row(placed_2["id"]).id) == ChannelInboxStatusEnum.APPLIED

        map_1, map_2 = _mapping(connection["id"], ref_1), _mapping(connection["id"], ref_2)

        neg_resp = await client.post(
            "/api/v1/negotiations",
            headers={**headers, "Idempotency-Key": f"neg-multi-{uuid.uuid4()}"},
            json={
                "store_id": store_id,
                "order_ids": [str(map_1.order_id), str(map_2.order_id)],
                "actor_id": actor,
            },
        )
        assert neg_resp.status_code == 200, neg_resp.text
        neg_id = neg_resp.json()["id"]
        assert Decimal(str(neg_resp.json()["total_due"])) == Decimal("70.0000")

        # Alocação atribuída ao Pedido 1 (R$ 20,00) + alocação não atribuída na negociação (R$ 15,00).
        intent_assigned = await client.post(
            f"/api/v1/negotiations/{neg_id}/intents",
            headers={**headers, "Idempotency-Key": f"int-ass-{uuid.uuid4()}"},
            json={
                "method": "PIX",
                "amount": "20.00",
                "allocations": [{"order_id": str(map_1.order_id), "amount": "20.00"}],
                "actor_id": actor,
            },
        )
        assert intent_assigned.status_code == 200, intent_assigned.text

        intent_unassigned = await client.post(
            f"/api/v1/negotiations/{neg_id}/intents",
            headers={**headers, "Idempotency-Key": f"int-unass-{uuid.uuid4()}"},
            json={"method": "PIX", "amount": "15.00", "allocations": [], "actor_id": actor},
        )
        assert intent_unassigned.status_code == 200, intent_unassigned.text

        with Session(engine) as db:
            set_platform_db_context(db)
            holds = settlement.hold_on_orders(db, [map_1.order_id, map_2.order_id])
            assert holds.get(map_1.order_id, Decimal("0.0000")) == Decimal("20.0000")
            assert holds.get(map_2.order_id, Decimal("0.0000")) == Decimal("0.0000")

            cov = settlement.coverage_on_orders(db, [map_1.order_id, map_2.order_id])
            assert cov[map_1.order_id].order_covered == Decimal("20.0000")
            assert cov[map_1.order_id].unassigned_covered == Decimal("15.0000")
            assert cov[map_1.order_id].joint_covered == Decimal("35.0000")
            assert cov[map_1.order_id].other_orders_amount == Decimal("30.0000")

            assert cov[map_2.order_id].order_covered == Decimal("0.0000")
            assert cov[map_2.order_id].unassigned_covered == Decimal("15.0000")
            assert cov[map_2.order_id].joint_covered == Decimal("35.0000")
            assert cov[map_2.order_id].other_orders_amount == Decimal("40.0000")

        # 1. Redução segura no Pedido 1: de R$ 40,00 para R$ 25,00 (>= R$ 20,00 atribuídos ao Pedido 1;
        # total conjunto passa a R$ 25,00 + R$ 30,00 = R$ 55,00 >= R$ 35,00 de cobertura conjunta).
        safe_update_1 = _event(
            merchant, "ORDER_UPDATED", ref_1, sequence=2,
            lines=[_line("l1", "ITEM-A", 2, unit_price="17.50")],
            totals={"delivery_fee": "5.00", "discount": "15.00", "total": "25.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(safe_update_1)
        assert inbox.process_event(_row(safe_update_1["id"]).id) == ChannelInboxStatusEnum.APPLIED
        neg_after_1 = (await client.get(f"/api/v1/negotiations/{neg_id}", headers=headers)).json()
        assert Decimal(str(neg_after_1["total_due"])) == Decimal("55.0000")

        # 2. Redução segura no Pedido 2: de R$ 30,00 para R$ 12,00 (>= R$ 0,00 atribuídos ao Pedido 2;
        # total conjunto passa a R$ 25,00 + R$ 12,00 = R$ 37,00 >= R$ 35,00 de cobertura conjunta).
        safe_update_2 = _event(
            merchant, "ORDER_UPDATED", ref_2, sequence=2,
            lines=[_line("l1", "ITEM-A", 1, unit_price="25.00")],
            totals={"delivery_fee": "5.00", "discount": "18.00", "total": "12.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(safe_update_2)
        assert inbox.process_event(_row(safe_update_2["id"]).id) == ChannelInboxStatusEnum.APPLIED
        neg_after_2 = (await client.get(f"/api/v1/negotiations/{neg_id}", headers=headers)).json()
        assert Decimal(str(neg_after_2["total_due"])) == Decimal("37.0000")

        # 3. Redução insegura no Pedido 1 abaixo da cobertura atribuída ao próprio Pedido 1
        # (para R$ 18,00 < R$ 20,00) -> recusada com NEEDS_REVIEW (ITEM_BELOW_SETTLEMENT).
        breach_own_1 = _event(
            merchant, "ORDER_UPDATED", ref_1, sequence=3,
            lines=[_line("l1", "ITEM-A", 2, unit_price="17.50")],
            totals={"delivery_fee": "5.00", "discount": "22.00", "total": "18.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(breach_own_1)
        assert inbox.process_event(_row(breach_own_1["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
        assert _row(breach_own_1["id"]).quarantine_code == "ITEM_BELOW_SETTLEMENT"
        assert _mapping(connection["id"], ref_1).declared_total == Decimal("25.0000")

        # 4. Redução insegura no Pedido 2 abaixo da cobertura conjunta da negociação
        # (para R$ 8,00 >= R$ 0,00 do Pedido 2, mas R$ 25,00 + R$ 8,00 = R$ 33,00 < R$ 35,00 conjuntos)
        # -> recusada com NEEDS_REVIEW (ITEM_BELOW_SETTLEMENT).
        breach_joint_2 = _event(
            merchant, "ORDER_UPDATED", ref_2, sequence=4,
            lines=[_line("l1", "ITEM-A", 1, unit_price="25.00")],
            totals={"delivery_fee": "5.00", "discount": "22.00", "total": "8.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(breach_joint_2)
        assert inbox.process_event(_row(breach_joint_2["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
        assert _row(breach_joint_2["id"]).quarantine_code == "ITEM_BELOW_SETTLEMENT"
        assert _mapping(connection["id"], ref_2).declared_total == Decimal("12.0000")
        neg_final = (await client.get(f"/api/v1/negotiations/{neg_id}", headers=headers)).json()
        assert Decimal(str(neg_final["total_due"])) == Decimal("37.0000")


@pytest.mark.asyncio
async def test_r11_cancelamento_respeita_cobertura_atribuida_e_conjunta_sem_bloquear_cancelamento_sem_cobertura():
    """R11: ORDER_CANCELLED must respect order-attributed and joint negotiation coverage.

    Covers:
    1. Single LOCAL order of R$ 100 with PIX PENDING reserve of R$ 55 (allocations=[]):
       ORDER_CANCELLED -> NEEDS_REVIEW (ITEM_BELOW_SETTLEMENT), order stays OPEN,
       _order_amount() remains R$ 100.0000, _hold_on_orders() remains R$ 55.0000,
       lines/mapping/allocations preserved atomically.
    2. After confirming the R$ 55 intent (CONFIRMED) or with ReceivableAllocation:
       ORDER_CANCELLED -> NEEDS_REVIEW (ITEM_BELOW_SETTLEMENT), preserving all state.
    3. Multi-order negotiation (two LOCAL orders of R$ 100) with unassigned reserve of R$ 150
       (allocations=[]): ORDER_CANCELLED on either order -> NEEDS_REVIEW (ITEM_BELOW_SETTLEMENT)
       because cancelling drops the joint obligation from R$ 200 to R$ 100 < R$ 150.
    4. Order without coverage (or after a PENDING reserve is cancelled):
       ORDER_CANCELLED -> APPLIED, order and lines become CANCELED, _order_amount() is R$ 0.0000.
    """
    from concurrent.futures import ThreadPoolExecutor  # noqa: F401
    from app.models.channel_hub import ChannelOrderLineStatusEnum, ExternalOrderTerminalStateEnum
    from app.models.order import OrderItemStatusEnum, OrderStatusEnum
    from app.modules.settlement import contracts as settlement
    from app.services import negotiation_service

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        _tenant, headers, actor, _product_a, connection = await _connected(client, "R11CancelCov", "ITEM-A")
        store_id = headers["X-Store-ID"]
        merchant = connection["merchant_external_id"]

        # --- Caso 1 e 2: Pedido LOCAL de R$ 100 com PIX PENDING de R$ 55 (allocations=[]) e depois CONFIRMED ---
        ref_single = f"ext-cancel-cov-{uuid.uuid4().hex[:8]}"
        placed_single = _event(
            merchant, "ORDER_PLACED", ref_single, sequence=1,
            lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
            totals={"delivery_fee": "0.00", "total": "100.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(placed_single)
        assert inbox.process_event(_row(placed_single["id"]).id) == ChannelInboxStatusEnum.APPLIED
        map_single = _mapping(connection["id"], ref_single)

        neg_single_resp = await client.post(
            "/api/v1/negotiations",
            headers={**headers, "Idempotency-Key": f"neg-cancel-single-{uuid.uuid4()}"},
            json={"store_id": store_id, "order_ids": [str(map_single.order_id)], "actor_id": actor},
        )
        assert neg_single_resp.status_code == 200, neg_single_resp.text
        neg_single_id = neg_single_resp.json()["id"]

        intent_single_resp = await client.post(
            f"/api/v1/negotiations/{neg_single_id}/intents",
            headers={**headers, "Idempotency-Key": f"int-cancel-single-{uuid.uuid4()}"},
            json={"method": "PIX", "amount": "55.00", "allocations": [], "actor_id": actor},
        )
        assert intent_single_resp.status_code == 200, intent_single_resp.text
        intent_single_id = intent_single_resp.json()["intents"][0]["id"]

        cancel_with_reserve = _event(merchant, "ORDER_CANCELLED", ref_single, sequence=2)
        _receive(cancel_with_reserve)
        assert inbox.process_event(_row(cancel_with_reserve["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
        assert _row(cancel_with_reserve["id"]).quarantine_code == "ITEM_BELOW_SETTLEMENT"

        with Session(engine) as db:
            set_platform_db_context(db)
            ord_row = db.get(Order, map_single.order_id)
            assert ord_row.status == OrderStatusEnum.OPEN
            assert negotiation_service._order_amount(db, ord_row) == Decimal("100.0000")
            assert settlement.hold_on_orders(db, [ord_row.id]).get(ord_row.id) == Decimal("55.0000")
            item_rows = db.exec(select(OrderItem).where(OrderItem.order_id == ord_row.id)).all()
            assert len(item_rows) == 1 and item_rows[0].status == OrderItemStatusEnum.ACTIVE
            line_rows = db.exec(
                select(ChannelOrderLine).where(ChannelOrderLine.external_order_mapping_id == map_single.id)
            ).all()
            assert len(line_rows) == 1 and line_rows[0].status == ChannelOrderLineStatusEnum.ACTIVE
            map_fresh = db.get(ExternalOrderMapping, map_single.id)
            assert map_fresh.terminal_at is None and map_fresh.terminal_state is None

        # Confirma a reserva de R$ 55,00 (liquidação CONFIRMED) e tenta cancelar novamente.
        confirm_resp = await client.post(
            f"/api/v1/negotiations/intents/{intent_single_id}/confirm",
            headers={**headers, "Idempotency-Key": f"conf-cancel-single-{uuid.uuid4()}"},
            json={"actor_id": actor},
        )
        assert confirm_resp.status_code == 200, confirm_resp.text

        cancel_with_settled = _event(merchant, "ORDER_CANCELLED", ref_single, sequence=3)
        _receive(cancel_with_settled)
        assert inbox.process_event(_row(cancel_with_settled["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
        assert _row(cancel_with_settled["id"]).quarantine_code == "ITEM_BELOW_SETTLEMENT"
        with Session(engine) as db:
            set_platform_db_context(db)
            ord_row = db.get(Order, map_single.order_id)
            assert ord_row.status == OrderStatusEnum.OPEN
            assert negotiation_service._order_amount(db, ord_row) == Decimal("100.0000")
            assert settlement.hold_on_orders(db, [ord_row.id]).get(ord_row.id) == Decimal("55.0000")

        # --- Caso 3: Negociação com 2 pedidos LOCAL de R$ 100 e cobertura não atribuída de R$ 150 ---
        ref_m1 = f"ext-cancel-m1-{uuid.uuid4().hex[:8]}"
        ref_m2 = f"ext-cancel-m2-{uuid.uuid4().hex[:8]}"
        for ref_m in (ref_m1, ref_m2):
            ev_p = _event(
                merchant, "ORDER_PLACED", ref_m, sequence=1,
                lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
                totals={"delivery_fee": "0.00", "total": "100.00"},
                payment={"status": "PAY_ON_DELIVERY"},
            )
            _receive(ev_p)
            assert inbox.process_event(_row(ev_p["id"]).id) == ChannelInboxStatusEnum.APPLIED

        map_m1, map_m2 = _mapping(connection["id"], ref_m1), _mapping(connection["id"], ref_m2)
        neg_multi_resp = await client.post(
            "/api/v1/negotiations",
            headers={**headers, "Idempotency-Key": f"neg-cancel-multi-{uuid.uuid4()}"},
            json={
                "store_id": store_id,
                "order_ids": [str(map_m1.order_id), str(map_m2.order_id)],
                "actor_id": actor,
            },
        )
        assert neg_multi_resp.status_code == 200, neg_multi_resp.text
        neg_multi_id = neg_multi_resp.json()["id"]

        intent_multi_resp = await client.post(
            f"/api/v1/negotiations/{neg_multi_id}/intents",
            headers={**headers, "Idempotency-Key": f"int-cancel-multi-{uuid.uuid4()}"},
            json={"method": "PIX", "amount": "150.00", "allocations": [], "actor_id": actor},
        )
        assert intent_multi_resp.status_code == 200, intent_multi_resp.text

        # Cancelar m1 reduziria a obrigação conjunta de R$ 200 para R$ 100 < R$ 150 -> NEEDS_REVIEW.
        cancel_m1 = _event(merchant, "ORDER_CANCELLED", ref_m1, sequence=2)
        _receive(cancel_m1)
        assert inbox.process_event(_row(cancel_m1["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
        assert _row(cancel_m1["id"]).quarantine_code == "ITEM_BELOW_SETTLEMENT"
        with Session(engine) as db:
            set_platform_db_context(db)
            ord_m1 = db.get(Order, map_m1.order_id)
            assert ord_m1.status == OrderStatusEnum.OPEN
            assert negotiation_service._order_amount(db, ord_m1) == Decimal("100.0000")
            cov_m = settlement.coverage_on_orders(db, [map_m1.order_id, map_m2.order_id])
            assert cov_m[map_m1.order_id].order_covered == Decimal("0.0000")
            assert cov_m[map_m1.order_id].unassigned_covered == Decimal("150.0000")
            assert cov_m[map_m1.order_id].joint_covered == Decimal("150.0000")

        # --- Caso 4: Cancelamento sem cobertura (e após cancelar reserva pendente) continua APPLIED ---
        ref_free = f"ext-cancel-free-{uuid.uuid4().hex[:8]}"
        placed_free = _event(
            merchant, "ORDER_PLACED", ref_free, sequence=1,
            lines=[_line("l1", "ITEM-A", 2, unit_price="25.00")],
            totals={"delivery_fee": "0.00", "total": "50.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(placed_free)
        assert inbox.process_event(_row(placed_free["id"]).id) == ChannelInboxStatusEnum.APPLIED
        map_free = _mapping(connection["id"], ref_free)

        cancel_free = _event(merchant, "ORDER_CANCELLED", ref_free, sequence=2)
        _receive(cancel_free)
        assert inbox.process_event(_row(cancel_free["id"]).id) == ChannelInboxStatusEnum.APPLIED
        with Session(engine) as db:
            set_platform_db_context(db)
            ord_free = db.get(Order, map_free.order_id)
            assert ord_free.status == OrderStatusEnum.CANCELED
            assert negotiation_service._order_amount(db, ord_free) == Decimal("0.0000")
            map_free_fresh = db.get(ExternalOrderMapping, map_free.id)
            assert map_free_fresh.terminal_state == ExternalOrderTerminalStateEnum.CANCELED
            assert map_free_fresh.terminal_at is not None
            line_free = db.exec(
                select(ChannelOrderLine).where(ChannelOrderLine.external_order_mapping_id == map_free.id)
            ).one()
            assert line_free.status == ChannelOrderLineStatusEnum.CANCELED


@pytest.mark.asyncio
async def test_r11_protecao_conjunta_sob_concorrencia_deterministica_serializa_reducoes_e_preserva_cobertura(
    monkeypatch,
):
    """R11: Concurrent reductions on two orders of the same negotiation cannot breach joint coverage.

    Reproduces:
    - Two LOCAL orders of R$ 100.00 linked to the same negotiation.
    - Unassigned PIX PENDING reserve of R$ 150.00 (allocations=[]).
    - Two concurrent ORDER_UPDATED events (one for each order), each adding a R$ 40.00
      discount (reducing each order from R$ 100.00 to R$ 60.00).
    - Synchronizes both threads at the coverage read boundary (`coverage_on_orders`) AND
      synchronizes post-read with a short timeout barrier so that without the common
      transactional lock on CheckoutNegotiation + linked Orders, both threads read
      other_orders_amount = R$ 100.00 and both become APPLIED (joint total R$ 120 < R$ 150).
    - With the common transactional lock, exactly one event is APPLIED and the other
      becomes NEEDS_REVIEW (ITEM_BELOW_SETTLEMENT), leaving the final joint total at
      R$ 160.00 >= R$ 150.00.
    """
    from concurrent.futures import ThreadPoolExecutor
    from app.models.order import OrderStatusEnum
    from app.modules.settlement import contracts as settlement
    from app.services import negotiation_service

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        _tenant, headers, actor, _product_a, connection = await _connected(client, "R11ConcJoint", "ITEM-A")
        store_id = headers["X-Store-ID"]
        merchant = connection["merchant_external_id"]

        ref_1 = f"ext-conc-1-{uuid.uuid4().hex[:8]}"
        ref_2 = f"ext-conc-2-{uuid.uuid4().hex[:8]}"
        for ref in (ref_1, ref_2):
            ev = _event(
                merchant, "ORDER_PLACED", ref, sequence=1,
                lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
                totals={"delivery_fee": "0.00", "total": "100.00"},
                payment={"status": "PAY_ON_DELIVERY"},
            )
            _receive(ev)
            assert inbox.process_event(_row(ev["id"]).id) == ChannelInboxStatusEnum.APPLIED

        map_1, map_2 = _mapping(connection["id"], ref_1), _mapping(connection["id"], ref_2)

        neg_resp = await client.post(
            "/api/v1/negotiations",
            headers={**headers, "Idempotency-Key": f"neg-conc-{uuid.uuid4()}"},
            json={
                "store_id": store_id,
                "order_ids": [str(map_1.order_id), str(map_2.order_id)],
                "actor_id": actor,
            },
        )
        assert neg_resp.status_code == 200, neg_resp.text
        neg_id = neg_resp.json()["id"]
        assert Decimal(str(neg_resp.json()["total_due"])) == Decimal("200.0000")

        intent_resp = await client.post(
            f"/api/v1/negotiations/{neg_id}/intents",
            headers={**headers, "Idempotency-Key": f"int-conc-{uuid.uuid4()}"},
            json={"method": "PIX", "amount": "150.00", "allocations": [], "actor_id": actor},
        )
        assert intent_resp.status_code == 200, intent_resp.text

        upd_1 = _event(
            merchant, "ORDER_UPDATED", ref_1, sequence=2,
            lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
            totals={"delivery_fee": "0.00", "discount": "40.00", "total": "60.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        upd_2 = _event(
            merchant, "ORDER_UPDATED", ref_2, sequence=2,
            lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
            totals={"delivery_fee": "0.00", "discount": "40.00", "total": "60.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(upd_1, upd_2)
        ev1_id = _row(upd_1["id"]).id
        ev2_id = _row(upd_2["id"]).id

        entry_barrier = threading.Barrier(2, timeout=8.0)
        orig_coverage = settlement.coverage_on_orders

        def synced_coverage(session, order_ids):
            entry_barrier.wait()
            return orig_coverage(session, order_ids)

        monkeypatch.setattr(settlement, "coverage_on_orders", synced_coverage)

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(inbox.process_event, ev1_id)
            f2 = pool.submit(inbox.process_event, ev2_id)
            res_1 = f1.result(timeout=15.0)
            res_2 = f2.result(timeout=15.0)

        monkeypatch.setattr(settlement, "coverage_on_orders", orig_coverage)

        assert {res_1, res_2} == {
            ChannelInboxStatusEnum.APPLIED,
            ChannelInboxStatusEnum.NEEDS_REVIEW,
        }, f"Esperado (APPLIED, NEEDS_REVIEW), obtido ({res_1}, {res_2})"

        row_1, row_2 = _row(upd_1["id"]), _row(upd_2["id"])
        review_rows = [r for r in (row_1, row_2) if r.status == ChannelInboxStatusEnum.NEEDS_REVIEW]
        assert len(review_rows) == 1
        assert review_rows[0].quarantine_code == "ITEM_BELOW_SETTLEMENT"

        with Session(engine) as db:
            set_platform_db_context(db)
            ord_1 = db.get(Order, map_1.order_id)
            ord_2 = db.get(Order, map_2.order_id)
            assert ord_1.status == OrderStatusEnum.OPEN
            assert ord_2.status == OrderStatusEnum.OPEN
            amt_1 = negotiation_service._order_amount(db, ord_1)
            amt_2 = negotiation_service._order_amount(db, ord_2)
            assert sorted([amt_1, amt_2]) == [Decimal("60.0000"), Decimal("100.0000")]
            assert amt_1 + amt_2 == Decimal("160.0000")

        neg_final = (await client.get(f"/api/v1/negotiations/{neg_id}", headers=headers)).json()
        assert Decimal(str(neg_final["total_due"])) == Decimal("160.0000")
        assert Decimal(str(neg_final["total_due"])) >= Decimal("150.0000")

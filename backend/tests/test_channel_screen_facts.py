"""S10.1, step 7: what the channel screen is told, and what it is never told.

Proposal `docs/product/proposta-s10-1-channel-hub.md`, §3.8. The screen names the
order by its local state instead of a UUID, shows each connection by what its
connector can do here, asks no credential, and shows deadlines as counts: orders
whose clocks have not started, and records past their deadline still waiting for
a cleanup that does not exist yet (H20). Nothing personal travels to it.

Real here: the database, the API and the inbox. Simulated: the channel. Deadlines
are pushed into the past directly in the database — nothing waits 30 days.
"""

import json
import os
import uuid
from datetime import datetime, timedelta

import httpx
import pytest

import app.main  # noqa: F401 — the inbox runs in this process, composed like the API
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.channel_hub import ChannelInboxEvent, ChannelInboxStatusEnum, ChannelOrderContact
from app.models.order import Order
from app.modules.channels import inbox
from test_channel_inbox import _connected, _event, _line, _mapping, _receive, _row
from test_s10_channel_hub import _base

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")
MARKERS = ("Pessoa Marcadora Prazo", "11977776666", "Rua Marcadora Prazo")
ALL_CAPABILITIES = ["CONNECTION_VALIDATION", "ORDER_EVENTS", "ORDER_INGRESS", "ORDER_STATUS_OUTBOUND"]


def _push_into_past(model, row_id) -> None:
    with Session(engine) as db:
        set_platform_db_context(db)
        row = db.get(model, row_id)
        row.retention_until = datetime.utcnow() - timedelta(minutes=5)
        db.add(row)
        db.commit()


async def _deadlines(client, headers) -> dict:
    response = await client.get("/api/v1/channels/deadlines", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_conexao_mostra_o_que_o_conector_sabe_fazer_aqui_e_nao_aceita_credencial_digitada():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant, store, headers, actor, _product, connection = await _base(client, "Capacidade")
        listed = (await client.get("/api/v1/channels/connections", headers=headers)).json()
        assert [item["capabilities"] for item in listed if item["id"] == connection["id"]] == [ALL_CAPABILITIES]

        # Provedor sem conector neste ambiente: cadastrado, e sem nenhuma capacidade.
        ifood = await client.post("/api/v1/channels/connections", headers={
            **headers, "Idempotency-Key": f"conn-{uuid.uuid4()}",
        }, json={"store_id": store["id"], "provider_code": "IFOOD",
                 "merchant_external_id": f"loja-{uuid.uuid4().hex[:8]}", "channel_name": "iFood", "actor_id": actor})
        assert ifood.status_code == 200, ifood.text
        assert ifood.json()["connection"]["capabilities"] == []
        assert ifood.json()["connection"]["status"] == "NOT_CONNECTED"

        # Credencial não é digitada pelo lojista (H12): recusada, e nada é cadastrado.
        merchant = f"com-segredo-{uuid.uuid4().hex[:8]}"
        refused = await client.post("/api/v1/channels/connections", headers={
            **headers, "Idempotency-Key": f"conn-{uuid.uuid4()}",
        }, json={"store_id": store["id"], "provider_code": "CONTRACT_TEST", "merchant_external_id": merchant,
                 "channel_name": "Com segredo", "credentials_ref": "secret://tenant/canal", "actor_id": actor})
        assert refused.status_code == 422, refused.text
        after = (await client.get("/api/v1/channels/connections", headers=headers)).json()
        assert merchant not in {item["merchant_external_id"] for item in after}
        spec = (await client.get("/openapi.json")).json()
        create = spec["components"]["schemas"]["MerchantConnectionCreateDTO"]
        assert "credentials_ref" not in create["properties"]


@pytest.mark.asyncio
async def test_caixa_de_entrada_nomeia_o_pedido_pelo_estado_local_e_nao_pelo_identificador():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        _tenant, headers, _actor, _product, connection = await _connected(client, "EstadoLocal", "ITEM-A")
        merchant = connection["merchant_external_id"]
        applied = _event(merchant, "ORDER_PLACED", f"pedido-{uuid.uuid4()}", sequence=1, lines=[_line("l1", "ITEM-A", 1)])
        waiting = _event(merchant, "ORDER_PLACED", f"pedido-{uuid.uuid4()}", sequence=1, lines=[_line("l1", "SEM-CODIGO", 1)])
        _receive(applied, waiting)
        assert inbox.process_event(_row(applied["id"]).id) == ChannelInboxStatusEnum.APPLIED
        assert inbox.process_event(_row(waiting["id"]).id) == ChannelInboxStatusEnum.QUARANTINED

        rows = {row["provider_event_id"]: row for row in (await client.get("/api/v1/channels/inbox", headers=headers)).json()}
        with Session(engine) as db:
            set_platform_db_context(db)
            order = db.get(Order, _row(applied["id"]).order_id)
        assert rows[applied["id"]]["order_status"] == order.status.value
        assert rows[waiting["id"]]["order_status"] is None and rows[waiting["id"]]["order_id"] is None


@pytest.mark.asyncio
async def test_prazos_contam_o_que_espera_e_o_que_venceu_e_nunca_dizem_que_algo_saiu():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant, headers, actor, product, connection = await _connected(client, "Prazos", "ITEM-A")
        empty = await _deadlines(client, headers)
        assert (empty["orders_awaiting_terminal"], empty["overdue_events"], empty["overdue_contacts"]) == (0, 0, 0)
        assert empty["cleanup_exists"] is False and empty["last_cleanup_at"] is None

        merchant, order_ref = connection["merchant_external_id"], f"pedido-{uuid.uuid4()}"
        placed = _event(merchant, "ORDER_PLACED", order_ref, sequence=1, lines=[_line("l1", "ITEM-A", 1)],
                        customer={"name": MARKERS[0], "phone": MARKERS[1], "address": {"street": MARKERS[2]}})
        unmapped = _event(merchant, "ORDER_PLACED", f"pedido-{uuid.uuid4()}", lines=[_line("l1", "SEM-CODIGO", 1)],
                          customer={"name": MARKERS[0]})
        _receive(placed, unmapped)
        assert inbox.process_event(_row(placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
        assert inbox.process_event(_row(unmapped["id"]).id) == ChannelInboxStatusEnum.QUARANTINED

        open_order = await _deadlines(client, headers)
        assert open_order["orders_awaiting_terminal"] == 1
        assert open_order["oldest_awaiting_terminal_created_at"] is not None
        assert open_order["overdue_events"] == 0, "prazo da recepção ainda não venceu"

        _push_into_past(ChannelInboxEvent, _row(unmapped["id"]).id)
        overdue = await _deadlines(client, headers)
        assert overdue["overdue_events"] == 1 and overdue["oldest_overdue_until"] is not None

        concluded = _event(merchant, "ORDER_CONCLUDED", order_ref, sequence=2)
        _receive(concluded)
        assert inbox.process_event(_row(concluded["id"]).id) == ChannelInboxStatusEnum.APPLIED
        mapping = _mapping(connection["id"], order_ref)
        with Session(engine) as db:
            set_platform_db_context(db)
            contact_id = db.exec(select(ChannelOrderContact.id).where(
                ChannelOrderContact.external_order_mapping_id == mapping.id)).one()
        _push_into_past(ChannelOrderContact, contact_id)
        ended = await _deadlines(client, headers)
        assert ended["orders_awaiting_terminal"] == 0
        assert ended["overdue_contacts"] == 1

        # Hold vigente tira o registro da conta de quem aguarda limpeza; a mesma
        # medida que contou 1 acima passa a contar 0 só por causa do hold.
        with Session(engine) as db:
            set_platform_db_context(db)
            contact = db.get(ChannelOrderContact, contact_id)
            contact.legal_hold_until = datetime.utcnow() + timedelta(days=10)
            contact.legal_hold_reason, contact.legal_hold_reference = "teste de contagem", "CASO-1"
            contact.legal_hold_by, contact.legal_hold_review_at = uuid.UUID(actor), datetime.utcnow() + timedelta(days=5)
            db.add(contact)
            db.commit()
        held = await _deadlines(client, headers)
        assert held["overdue_contacts"] == 0

        diagnostic = await client.get("/api/v1/diagnostics", headers=headers)
        assert diagnostic.status_code == 200, diagnostic.text
        check = {item["chave"]: item for item in diagnostic.json()["verificacoes"]}["prazos_dos_canais"]
        assert check["situacao"] == "ATENCAO" and check["detalhes"]["vencidos"] == 1
        assert "ainda não existe" in check["resumo"]

        said = json.dumps([empty, open_order, overdue, ended, held, diagnostic.json()], ensure_ascii=False).lower()
        for marker in MARKERS:
            assert marker.lower() not in said, f"dado pessoal na resposta: {marker}"
        for word in ("removid", "eliminad", "apagad", "excluíd"):
            assert word not in said, f"a resposta afirma o que não aconteceu: {word}"


@pytest.mark.asyncio
async def test_loja_sem_canal_nao_ve_prazos_de_canal_no_diagnostico():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        suffix = uuid.uuid4().hex[:8]
        tenant = (await client.post("/api/v1/identity/tenants", json={"name": "SemCanal", "slug": f"semcanal-{suffix}"})).json()
        store = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "Matriz", "code": f"SC-{suffix}"})).json()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}
        diagnostic = await client.get("/api/v1/diagnostics", headers=headers)
        assert diagnostic.status_code == 200, diagnostic.text
        assert "prazos_dos_canais" not in {item["chave"] for item in diagnostic.json()["verificacoes"]}

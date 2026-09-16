"""The charge reaches the bridge, and only a proven answer frees the pinpad.

Until 16/09/2026 `BridgeQueuedAdapter.start` wrote `bridge_command: START` into a
payload nobody read. With an acquirer contracted and a pinpad in hand, no charge
would have left the server. These tests walk the path through the real API: the
charge creates its command and its occupancy together, the bridge takes the
command with its own credential, acknowledges it and answers it.

What is simulated, and said so: every answer of the acquirer. Nothing here says
anything about real money — only about transport, persistence and the rule that
time and ignorance never free a terminal.
"""

import asyncio
import os
import time
import uuid
from decimal import Decimal

import httpx
import pytest

from test_s8_checkout_negotiation import _context, _intent
from test_s9_payment_providers import _payment_binding


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _balcao(client, prefix):
    """A bill with two card parcels and one paired, online pinpad."""
    tenant, store, headers, actor, _table, table_session, _order, cash = await _context(client, prefix)
    negotiation = (await client.post("/api/v1/negotiations", headers={
        **headers, "Idempotency-Key": f"neg-{uuid.uuid4()}",
    }, json={"store_id": store["id"], "table_session_id": table_session["id"], "actor_id": actor})).json()
    _, primeira = await _intent(client, headers, negotiation["id"], actor, "CREDIT_CARD", 20, uuid.uuid4())
    _, segunda = await _intent(client, headers, negotiation["id"], actor, "CREDIT_CARD", 20, uuid.uuid4())
    configuration = (await client.post("/api/v1/providers/configurations", headers={
        **headers, "Idempotency-Key": f"config-{uuid.uuid4()}",
    }, json={"store_id": store["id"], "provider_code": "SITEF",
             "credentials_ref": "secret://tenant/sitef", "actor_id": actor})).json()
    paired = (await client.post("/api/v1/providers/bridge/terminals", headers={
        **headers, "Idempotency-Key": f"pair-{uuid.uuid4()}",
    }, json={"store_id": store["id"], "register_id": cash["register_id"],
             "provider_configuration_id": configuration["id"],
             "terminal_code": f"PINPAD-{prefix}", "actor_id": actor})).json()
    terminal, credential = paired["terminal"], paired["pairing_code"]
    beat = await client.post(f"/api/v1/providers/bridge/terminals/{terminal['id']}/heartbeat", json={
        "tenant_id": tenant["id"], "store_id": store["id"], "pairing_code": credential,
        "bridge_version": "1.0.0", "protocol_version": "1.0",
    })
    assert beat.status_code == 200, beat.text
    binding, _device = await _payment_binding(
        client, headers, actor, store["id"], cash["register_id"], configuration["id"],
        terminal["id"], f"DLV-{uuid.uuid4().hex[:6]}",
    )
    return {
        "tenant": tenant, "store": store, "headers": headers, "actor": actor,
        "terminal": terminal, "credential": credential, "binding": binding,
        "parcelas": (primeira, segunda),
    }


async def _cobrar(client, balcao, parcela):
    return await client.post("/api/v1/providers/transactions", headers={
        **balcao["headers"], "Idempotency-Key": f"exec-{uuid.uuid4()}",
    }, json={"payment_intent_id": parcela["id"],
             "payment_device_binding_id": balcao["binding"]["id"], "actor_id": balcao["actor"]})


def _bridge(balcao, credential=None):
    return {"X-Bridge-Credential": credential or balcao["credential"]}


async def _proximo(client, balcao, wait=0, credential=None):
    return await client.get(
        f"/api/v1/providers/bridge/terminals/{balcao['terminal']['id']}/commands",
        params={"wait": wait}, headers=_bridge(balcao, credential),
    )


async def _responder(client, balcao, comando_id, status, **extra):
    return await client.post(
        f"/api/v1/providers/bridge/terminals/{balcao['terminal']['id']}/commands/{comando_id}/result",
        headers=_bridge(balcao), json={"status": status, **extra},
    )


@pytest.mark.asyncio
async def test_a_cobranca_chega_ao_bridge_e_so_a_resposta_solta_a_maquininha():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        balcao = await _balcao(client, "Entrega")
        primeira, segunda = balcao["parcelas"]

        enviada = await _cobrar(client, balcao, primeira)
        assert enviada.status_code == 200, enviada.text
        transacao = enviada.json()["transaction"]
        assert transacao["status"] == "PROCESSING"

        entregue = await _proximo(client, balcao)
        assert entregue.status_code == 200, entregue.text
        comando = entregue.json()
        assert comando["command_type"] == "START" and comando["command_class"] == "EXECUTION"
        assert comando["provider_transaction_id"] == transacao["id"]
        assert comando["attempts"] == 1
        assert Decimal(comando["payload"]["amount"]) == Decimal("20")
        assert comando["payload"]["method"] == "CREDIT_CARD"

        recebido = await client.post(
            f"/api/v1/providers/bridge/terminals/{balcao['terminal']['id']}/commands/{comando['id']}/ack",
            headers=_bridge(balcao),
        )
        assert recebido.status_code == 200 and recebido.json()["delivery_status"] == "ACKED"
        # Confirmado o recebimento, não há o que reentregar.
        assert (await _proximo(client, balcao)).status_code == 204

        # A maquininha está com a primeira cobrança, sem resposta.
        ocupada = await _cobrar(client, balcao, segunda)
        assert ocupada.status_code == 409, ocupada.text
        assert ocupada.json()["detail"]["code"] == "TERMINAL_OCCUPIED"
        assert ocupada.json()["detail"]["provider_transaction_id"] == transacao["id"]

        respondida = await _responder(
            client, balcao, comando["id"], "CONFIRMED",
            external_transaction_id="SITEF-DLV-1", nsu="000111", authorization_code="A1",
        )
        assert respondida.status_code == 200, respondida.text
        assert respondida.json()["command"]["delivery_status"] == "CLOSED"
        assert respondida.json()["transaction_status"] == "CONFIRMED"

        liberada = await _cobrar(client, balcao, segunda)
        assert liberada.status_code == 200, liberada.text
        seguinte = await _proximo(client, balcao)
        assert seguinte.status_code == 200
        assert seguinte.json()["provider_transaction_id"] == liberada.json()["transaction"]["id"]
        assert seguinte.json()["sequence"] == comando["sequence"] + 1


@pytest.mark.asyncio
async def test_nao_saber_segura_a_maquininha_e_a_recusa_a_solta():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        balcao = await _balcao(client, "Incerta")
        primeira, segunda = balcao["parcelas"]
        assert (await _cobrar(client, balcao, primeira)).status_code == 200
        comando = (await _proximo(client, balcao)).json()

        # Resultado antes do ACK: o comando fecha, e "não sei" não prova nada.
        incerta = await _responder(client, balcao, comando["id"], "UNKNOWN", failure_code="SDK_TIMEOUT")
        assert incerta.status_code == 200, incerta.text
        assert incerta.json()["command"]["delivery_status"] == "CLOSED"
        assert incerta.json()["transaction_status"] == "UNKNOWN"
        assert (await _cobrar(client, balcao, segunda)).status_code == 409

        # A resposta de verdade chega depois, no mesmo comando: o adquirente recusou.
        recusada = await _responder(client, balcao, comando["id"], "FAILED", failure_code="DECLINED")
        assert recusada.status_code == 200, recusada.text
        assert recusada.json()["transaction_status"] == "FAILED"
        assert (await _cobrar(client, balcao, segunda)).status_code == 200


@pytest.mark.asyncio
async def test_cancelada_sem_significado_declarado_pelo_provider_segura_a_maquininha():
    """Cancelar pode ter sido antes ou depois da captura. Sem declaração, não se presume."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        balcao = await _balcao(client, "Cancelada")
        primeira, segunda = balcao["parcelas"]
        assert (await _cobrar(client, balcao, primeira)).status_code == 200
        comando = (await _proximo(client, balcao)).json()
        cancelada = await _responder(client, balcao, comando["id"], "CANCELED")
        assert cancelada.status_code == 200, cancelada.text
        assert cancelada.json()["transaction_status"] == "CANCELED"
        ocupada = await _cobrar(client, balcao, segunda)
        assert ocupada.status_code == 409
        assert ocupada.json()["detail"]["financial_resolution"] == "INCERTA"


@pytest.mark.asyncio
async def test_o_bridge_e_reconhecido_pela_credencial_e_nao_pelo_que_diz():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        balcao = await _balcao(client, "Credencial")
        vizinho = await _balcao(client, "Vizinho")
        assert (await _cobrar(client, balcao, balcao["parcelas"][0])).status_code == 200

        errada = "credencial-que-nao-e-desta-maquininha"
        assert (await _proximo(client, balcao, credential=errada)).status_code == 401
        comando = (await _proximo(client, balcao)).json()
        rota = f"/api/v1/providers/bridge/terminals/{balcao['terminal']['id']}/commands/{comando['id']}"
        assert (await client.post(f"{rota}/ack", headers=_bridge(balcao, errada))).status_code == 401
        assert (await client.post(f"{rota}/result", headers=_bridge(balcao, errada),
                                  json={"status": "CONFIRMED"})).status_code == 401

        # O bridge vizinho, com a própria credencial válida, não enxerga o comando.
        alheia = f"/api/v1/providers/bridge/terminals/{vizinho['terminal']['id']}/commands/{comando['id']}"
        assert (await client.post(f"{alheia}/ack", headers=_bridge(vizinho))).status_code == 404
        assert (await client.post(f"{alheia}/result", headers=_bridge(vizinho),
                                  json={"status": "CONFIRMED"})).status_code == 404

        # O corpo do heartbeat não escolhe o tenant: credencial válida, tenant alheio.
        batida = await client.post(f"/api/v1/providers/bridge/terminals/{balcao['terminal']['id']}/heartbeat", json={
            "tenant_id": vizinho["tenant"]["id"], "store_id": vizinho["store"]["id"],
            "pairing_code": balcao["credential"], "bridge_version": "1.0.0", "protocol_version": "1.0",
        })
        assert batida.status_code == 401


@pytest.mark.asyncio
async def test_a_espera_devolve_o_comando_quando_ele_nasce_e_desiste_no_prazo():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=40) as client:
        balcao = await _balcao(client, "Espera")

        inicio = time.monotonic()
        vazia = await _proximo(client, balcao, wait=2)
        assert vazia.status_code == 204
        assert 1.5 <= time.monotonic() - inicio < 6

        inicio = time.monotonic()
        espera = asyncio.create_task(_proximo(client, balcao, wait=15))
        await asyncio.sleep(1.5)
        assert not espera.done(), "a espera respondeu antes de haver comando"
        assert (await _cobrar(client, balcao, balcao["parcelas"][0])).status_code == 200
        chegou = await espera
        decorrido = time.monotonic() - inicio
        assert chegou.status_code == 200, chegou.text
        assert chegou.json()["command_type"] == "START"
        assert decorrido < 10, f"o comando levou {decorrido:.1f}s para sair da fila"

#!/usr/bin/env python
"""Um salão pronto para uma cobrança TEF que fica esperando resposta.

Este roteiro **não** inventa estado no banco: ele constrói o cenário pelas
próprias rotas do produto, com a sessão da gestora, como a configuração seria
feita de verdade. O que ele monta:

1. provedor de pagamento configurado na unidade;
2. terminal de bridge pareado, e o **heartbeat enviado por este roteiro**, no
   papel do Dashem TEF Bridge — não há bridge instalado, e nada aqui prova que
   exista;
3. vínculo de maquininha ao caixa e ao aparelho operacional;
4. ambiente, mesa, sessão aberta, comanda e um item consumido.

Sobre o provedor: qualquer código diferente de `CONTRACT_TEST` cai no
`BridgeQueuedAdapter`, cujo `start` devolve **PROCESSING** e cujo `query`
devolve **UNKNOWN**. É exatamente o estado que a homologação precisa percorrer —
a cobrança saiu, e a resposta não voltou — sem nenhum provedor real envolvido.

Não toca produção: fala com a API local indicada por `--api`.
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

import httpx

PROVEDOR_TIMEOUT = 60


def _chave() -> str:
    return f"hom06-{uuid.uuid4().hex}"


class Api:
    """A API local, com os cabeçalhos da gestora e erro que diz o que falhou."""

    def __init__(self, base: str, fixture: dict) -> None:
        self.cliente = httpx.Client(base_url=base, timeout=60.0)
        self.cabecalhos = {
            "X-Tenant-ID": fixture["tenant_id"],
            "X-Store-ID": fixture["store_id"],
            "Authorization": f"Bearer {fixture['manager_token']}",
        }

    def post(self, rota: str, corpo: dict, *, idempotente: bool = False) -> dict:
        cabecalhos = dict(self.cabecalhos)
        if idempotente:
            cabecalhos["Idempotency-Key"] = _chave()
        resposta = self.cliente.post(rota, json=corpo, headers=cabecalhos)
        if resposta.status_code >= 400:
            raise RuntimeError(f"POST {rota} devolveu {resposta.status_code}: {resposta.text[:400]}")
        return resposta.json()

    def get(self, rota: str, **parametros) -> dict | list:
        resposta = self.cliente.get(rota, headers=self.cabecalhos, params=parametros or None)
        if resposta.status_code >= 400:
            raise RuntimeError(f"GET {rota} devolveu {resposta.status_code}: {resposta.text[:400]}")
        return resposta.json()


def montar(fixture_path: Path, saida: Path, base: str) -> None:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    api = Api(base, fixture)
    marca = uuid.uuid4().hex[:6]
    gestora = fixture["gestora_id"]

    # ---- 1. provedor -------------------------------------------------------
    configuracao = api.post("/api/v1/providers/configurations", {
        "store_id": fixture["store_id"], "provider_code": f"HOMOLOG{marca.upper()}",
        "credentials_ref": f"cofre://homologacao/{marca}", "timeout_seconds": PROVEDOR_TIMEOUT,
        "actor_id": gestora,
    }, idempotente=True)

    # ---- 2. bridge pareado, e o heartbeat que este roteiro envia -----------
    pareamento = api.post("/api/v1/providers/bridge/terminals", {
        "store_id": fixture["store_id"], "register_id": fixture["register_id"],
        "provider_configuration_id": configuracao["id"],
        "terminal_code": f"BRIDGE-{marca.upper()}", "actor_id": gestora,
    }, idempotente=True)
    terminal = pareamento["terminal"]

    # O heartbeat vem "de fora", sem sessão de tela, como viria de um bridge de
    # verdade. A máquina, aqui, é este roteiro — e a evidência diz isso.
    batida = api.cliente.post(
        f"/api/v1/providers/bridge/terminals/{terminal['id']}/heartbeat",
        json={
            "pairing_code": pareamento["pairing_code"],
            "tenant_id": fixture["tenant_id"], "store_id": fixture["store_id"],
            "bridge_version": "0.0.0-simulado",
            "protocol_version": terminal["protocol_version"],
        },
    )
    if batida.status_code != 200:
        raise RuntimeError(f"heartbeat devolveu {batida.status_code}: {batida.text[:300]}")
    terminal_online = batida.json()
    if terminal_online["status"] != "ONLINE":
        raise RuntimeError(f"o terminal não ficou ONLINE: {terminal_online['status']}")

    # ---- 3. vínculo de maquininha -----------------------------------------
    vinculo = api.post("/api/v1/providers/device-bindings", {
        "store_id": fixture["store_id"], "register_id": fixture["register_id"],
        "operational_device_id": fixture["operational_device_id"],
        "provider_configuration_id": configuracao["id"],
        # Sem `external_device_reference`: no modo TEF_BRIDGE quem endereça o
        # aparelho é o terminal do bridge, e o servidor recusa a referência de
        # SmartPOS aqui — a rota não deixa misturar os dois caminhos.
        "execution_mode": "TEF_BRIDGE", "tef_bridge_terminal_id": terminal["id"],
        "actor_id": gestora,
    }, idempotente=True)

    # ---- 3b. o terminal autorizado ----------------------------------------
    # O salão é ponto de operação: sem terminal autorizado, `/tables` mostra
    # "Ative este ponto de operação" e nada mais. Autorizar é ato de quem
    # responde pela unidade, feito uma vez na abertura.
    autorizacao = api.post(
        f"/api/v1/operational-access/terminals/{fixture['operational_device_id']}/authorize", {},
    )

    # ---- 4. salão: ambiente, mesa, sessão, comanda e consumo ---------------
    ambiente = api.post("/api/v1/tables/areas", {
        "store_id": fixture["store_id"], "code": f"SAL-{marca.upper()}",
        "name": "Salão principal", "kind": "INTERNAL", "sort_order": 1, "actor_id": gestora,
    })
    mesa = api.post("/api/v1/tables", {
        "store_id": fixture["store_id"], "code": f"M-{marca.upper()}", "name": "Mesa 7",
        "capacity": 4, "area_id": ambiente["id"], "sort_order": 1, "actor_id": gestora,
    }, idempotente=True)
    sessao = api.post("/api/v1/tables/sessions", {
        "store_id": fixture["store_id"], "service_table_id": mesa["id"],
        "attendant_id": gestora, "actor_id": gestora,
    }, idempotente=True)
    comanda = sessao["orders"][0] if sessao.get("orders") else api.post(
        f"/api/v1/tables/sessions/{sessao['id']}/orders",
        {"display_reference": "Comanda 1", "actor_id": gestora}, idempotente=True,
    )
    # **Dois itens, de propósito.** Com um só, cobrar parte da conta pelo TEF
    # trava tudo — e o cenário de processamento **parcial** não existe. Com o
    # chopp e a porção, cobrar o chopp deixa a porção cobrável, que é onde a
    # tela precisa dizer qual é o teto.
    consumo = []
    for sku, produto_id in fixture["produtos"].items():
        item = api.post(f"/api/v1/orders/{comanda['id']}/items", {
            "product_id": produto_id, "quantity": 1, "actor_id": gestora,
        }, idempotente=True)
        consumo.append({"sku": sku, "produto_id": produto_id,
                        "valor": str(item.get("unit_price", ""))})

    fixture.update({
        "provider_configuration_id": configuracao["id"],
        "provider_code": configuracao["provider_code"],
        # O código de pareamento é o segredo com que o bridge se identifica. Ele
        # entra na fixture porque o roteiro de resposta tardia fala **como** o
        # bridge; é cenário local de homologação, e nada disto vai para produção.
        "bridge_terminal": {"id": terminal["id"], "code": terminal["terminal_code"],
                            "status": terminal_online["status"],
                            "bridge_version": terminal_online.get("bridge_version"),
                            "pairing_code": pareamento["pairing_code"]},
        "payment_device_binding_id": vinculo["id"],
        "terminal_token": autorizacao["terminal_token"],
        "service_table": {"id": mesa["id"], "name": mesa["name"], "code": mesa["code"]},
        "table_session_id": sessao["id"],
        "order_id": comanda["id"],
        "consumo": consumo,
        # O que este roteiro construiu, e sob que rótulo. Sem isto a evidência
        # da travessia não consegue separar configuração de integração real.
        "camadas": {
            "configuracao_pelas_rotas_do_produto": "provedor, bridge, vínculo, mesa, comanda e item",
            "simulacao_de_bridge": "heartbeat enviado por este roteiro, no papel do bridge",
            "integracao_real_com_provedor": "NÃO — o adaptador é o BridgeQueuedAdapter, que enfileira e não aprova",
        },
    })
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"salão pronto: mesa {mesa['name']}, bridge {terminal['terminal_code']} "
          f"{terminal_online['status']}, vínculo {vinculo['id']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path,
                        help="Saída de seed_food_service_walkthrough.py")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--api", default="http://127.0.0.1:8004")
    argumentos = parser.parse_args()
    montar(argumentos.fixture, argumentos.output, argumentos.api)

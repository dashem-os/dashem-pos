"""A mesma intenção de pagamento, reenviada, não cobra duas vezes.

Confirmar já era idempotente por estado: um pagamento `CONFIRMED` reconfirmado
devolve ele mesmo. **Criar não era.**

O caso que faltava é o que o aceite da UX-07 nomeia — *timeout depois do envio*.
A criação passa, a confirmação estoura no meio, e a venda continua
`AWAITING_PAYMENT`. Quem repete a operação criava um segundo pagamento e o
confirmava, enquanto o primeiro ficava pendente. Se o provedor capturou o
primeiro, são duas cobranças.

Em pagamento **dividido** é pior: entre as parcelas a venda nunca chega a `PAID`,
então nada barra a repetição.

Estes testes falam HTTP porque é aí que a chave viaja: o cabeçalho
`Idempotency-Key` é parte do contrato, não um detalhe interno.
"""

import os
import uuid

import httpx
import pytest

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _venda_pronta_para_pagar(client: httpx.AsyncClient) -> tuple[dict, dict, float]:
    """Um tenant novo, com caixa aberto e uma venda de valor conhecido."""
    sufixo = uuid.uuid4().hex[:8]
    ator = str(uuid.uuid4())
    tenant = (await client.post("/api/v1/identity/tenants", json={
        "name": f"Cobranca {sufixo}", "slug": f"cobranca-{sufixo}",
    })).json()
    loja = (await client.post("/api/v1/identity/stores", json={
        "tenant_id": tenant["id"], "name": "Matriz", "code": f"M-{sufixo}",
    })).json()
    cabecalhos = {"X-Tenant-ID": tenant["id"], "X-Store-ID": loja["id"]}

    caixa = (await client.post("/api/v1/cash/registers", headers=cabecalhos, json={
        "store_id": loja["id"], "name": "Caixa 01", "code": f"CX-{sufixo}",
    })).json()
    sessao = (await client.post("/api/v1/cash/sessions/open", headers=cabecalhos, json={
        "store_id": loja["id"], "register_id": caixa["id"], "operator_id": ator,
        "opening_balance": 100.00,
    })).json()

    # Serviço: não controla estoque, então a venda não depende de reserva.
    produto = (await client.post("/api/v1/catalog/products", headers=cabecalhos, json={
        "name": "Instalação", "sku": f"SERV-{sufixo}", "item_type": "SERVICE",
    })).json()
    await client.post("/api/v1/catalog/prices", headers=cabecalhos, json={
        "product_id": produto["id"], "store_id": loja["id"], "cost_price": 0.00, "sale_price": 50.00,
    })

    venda = (await client.post("/api/v1/sales", headers=cabecalhos, json={"store_id": loja["id"]})).json()
    # A rota de itens devolve o item, não a venda: o total vem do checkout.
    await client.post(f"/api/v1/sales/{venda['id']}/items", headers=cabecalhos, json={
        "product_id": produto["id"], "quantity": 2.0,
    })
    venda = (await client.post(f"/api/v1/sales/{venda['id']}/checkout", headers=cabecalhos,
                               json={"actor_id": ator})).json()
    return cabecalhos, {"venda": venda, "caixa": sessao, "ator": ator}, float(venda["net_total"])


@pytest.mark.asyncio
async def test_a_mesma_intencao_reenviada_nao_abre_um_segundo_pagamento():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        cabecalhos, dados, total = await _venda_pronta_para_pagar(client)
        venda, caixa = dados["venda"], dados["caixa"]

        chave = f"intencao-{uuid.uuid4()}"
        corpo = {
            "sale_id": venda["id"], "method": "CASH", "amount": total,
            "cash_session_id": caixa["id"], "tendered_amount": total,
        }

        primeira = await client.post("/api/v1/payments", headers={**cabecalhos, "Idempotency-Key": chave}, json=corpo)
        assert primeira.status_code == 200, primeira.text
        # O reenvio da MESMA intenção — o operador clicou de novo depois do
        # timeout — devolve o pagamento que já existe.
        segunda = await client.post("/api/v1/payments", headers={**cabecalhos, "Idempotency-Key": chave}, json=corpo)
        assert segunda.status_code == 200, segunda.text
        assert segunda.json()["id"] == primeira.json()["id"]

        pagamentos = (await client.get(f"/api/v1/payments?sale_id={venda['id']}", headers=cabecalhos)).json()
        assert len(pagamentos) == 1, f"a venda ficou com {len(pagamentos)} pagamentos"


@pytest.mark.asyncio
async def test_sem_chave_o_reenvio_ainda_abre_dois_e_e_por_isso_que_a_chave_existe():
    """O contrato só protege quem carimba — e é isso que o cliente precisa fazer.

    Este teste não descreve um defeito a corrigir: descreve por que a chave é
    obrigatória do lado de cá. Sem ela, o servidor não tem como saber que as
    duas chamadas são a mesma intenção.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        cabecalhos, dados, total = await _venda_pronta_para_pagar(client)
        venda, caixa = dados["venda"], dados["caixa"]
        corpo = {
            "sale_id": venda["id"], "method": "CASH", "amount": total / 2,
            "cash_session_id": caixa["id"],
        }
        await client.post("/api/v1/payments", headers=cabecalhos, json=corpo)
        await client.post("/api/v1/payments", headers=cabecalhos, json=corpo)
        pagamentos = (await client.get(f"/api/v1/payments?sale_id={venda['id']}", headers=cabecalhos)).json()
        assert len(pagamentos) == 2


@pytest.mark.asyncio
async def test_intencoes_diferentes_continuam_sendo_pagamentos_diferentes():
    """Dividir a conta não pode virar um pagamento só.

    A idempotência protege o reenvio da mesma intenção. Duas parcelas são duas
    intenções, e transformá-las em uma perderia metade do dinheiro.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        cabecalhos, dados, total = await _venda_pronta_para_pagar(client)
        venda, caixa = dados["venda"], dados["caixa"]
        metade = total / 2

        for parcela in range(2):
            resposta = await client.post(
                "/api/v1/payments",
                headers={**cabecalhos, "Idempotency-Key": f"parcela-{parcela}-{uuid.uuid4()}"},
                json={"sale_id": venda["id"], "method": "CASH", "amount": metade,
                      "cash_session_id": caixa["id"], "tendered_amount": metade},
            )
            assert resposta.status_code == 200, resposta.text

        pagamentos = (await client.get(f"/api/v1/payments?sale_id={venda['id']}", headers=cabecalhos)).json()
        assert len(pagamentos) == 2
        assert sum(float(p["amount"]) for p in pagamentos) == pytest.approx(total)


@pytest.mark.asyncio
async def test_confirmar_duas_vezes_continua_confirmando_uma():
    """A guarda que já existia não pode ter sido perdida no caminho."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        cabecalhos, dados, total = await _venda_pronta_para_pagar(client)
        venda, caixa, ator = dados["venda"], dados["caixa"], dados["ator"]

        pagamento = (await client.post(
            "/api/v1/payments", headers={**cabecalhos, "Idempotency-Key": str(uuid.uuid4())},
            json={"sale_id": venda["id"], "method": "CASH", "amount": total,
                  "cash_session_id": caixa["id"], "tendered_amount": total},
        )).json()

        chave = str(uuid.uuid4())
        primeira = await client.post(f"/api/v1/payments/{pagamento['id']}/confirm",
                                     headers={**cabecalhos, "Idempotency-Key": chave}, json={"actor_id": ator})
        segunda = await client.post(f"/api/v1/payments/{pagamento['id']}/confirm",
                                    headers={**cabecalhos, "Idempotency-Key": chave}, json={"actor_id": ator})
        assert primeira.status_code == 200, primeira.text
        assert segunda.status_code == 200, segunda.text

        pagamentos = (await client.get(f"/api/v1/payments?sale_id={venda['id']}", headers=cabecalhos)).json()
        confirmados = [p for p in pagamentos if p["status"] == "CONFIRMED"]
        assert len(confirmados) == 1
        assert sum(float(p["amount"]) for p in confirmados) == pytest.approx(total)

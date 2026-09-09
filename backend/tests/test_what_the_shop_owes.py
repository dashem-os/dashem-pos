"""Contas a pagar: o contrato da UX-10, incluindo o que ele proíbe.

O contrato está em `docs/product/ux-10-contas-a-pagar-contrato.md`. Metade
destas provas guarda o que a sprint **não** entrega, porque a fronteira é o que
o dono nomeou primeiro: *receber mercadoria não deve gerar automaticamente uma
dívida*. Um gatilho acrescentado depois passaria despercebido em toda prova que
só olhasse o caminho feliz.

As provas falam HTTP porque é aí que o contrato vive: `Idempotency-Key`,
`version` e o isolamento por tenant só existem de verdade na borda.
"""

import asyncio
import os
import threading
import uuid
from decimal import Decimal
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


def reais(valor) -> Decimal:
    """Dinheiro se compara como número.

    Comparar a string devolvida mede a formatação do serializador, não o saldo:
    "480.00" e "480.0000" sao o mesmo dinheiro, e uma prova que reprova por
    causa das duas casas a mais reprova o produto por um motivo que ele nao tem.
    """
    return Decimal(str(valor)).quantize(Decimal("0.01"))


async def _tenant(client: httpx.AsyncClient) -> dict:
    sufixo = uuid.uuid4().hex[:8]
    tenant = (await client.post("/api/v1/identity/tenants", json={
        "name": f"Devedora {sufixo}", "slug": f"devedora-{sufixo}",
    })).json()
    loja = (await client.post("/api/v1/identity/stores", json={
        "tenant_id": tenant["id"], "name": "Matriz", "code": f"M-{sufixo}",
    })).json()
    return {"headers": {"X-Tenant-ID": tenant["id"], "X-Store-ID": loja["id"]},
            "tenant": tenant, "loja": loja, "sufixo": sufixo}


def _chave() -> dict:
    return {"Idempotency-Key": str(uuid.uuid4())}


async def _lancar(client, h, **campos) -> dict:
    corpo = {"payee_name": "Companhia de Energia", "amount": "480.00",
             "due_on": str(date.today() + timedelta(days=10))}
    corpo.update(campos)
    resposta = await client.post("/api/v1/payables", headers={**h, **_chave()}, json=corpo)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


# ---------------------------------------------------------------------------
# O aceite: lançamento → consulta por vencimento → baixa → conferência
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lancar_consultar_baixar_e_conferir():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]

        conta = await _lancar(client, h, description="Energia de setembro")
        assert reais(conta["balance"]) == reais("480.0000")
        assert reais(conta["paid_amount"]) == reais("0.0000")
        assert conta["status"] == "OPEN"
        assert conta["is_overdue"] is False
        # A abertura já é um lançamento na razão: o saldo vem da razão, não de
        # aritmética guardada numa variável.
        assert [e["entry_type"] for e in conta["ledger"]] == ["ISSUE"]

        # A consulta que a operação faz é por vencimento.
        abertas = (await client.get("/api/v1/payables?situacao=ABERTAS", headers=h)).json()
        assert [c["id"] for c in abertas] == [conta["id"]]

        baixa = await client.post(
            f"/api/v1/payables/{conta['id']}/baixas", headers={**h, **_chave()},
            json={"amount": "480.00", "method": "Pix", "version": conta["version"]})
        assert baixa.status_code == 201, baixa.text
        paga = baixa.json()
        assert paga["status"] == "PAID"
        assert reais(paga["balance"]) == reais("0.0000")
        assert reais(paga["paid_amount"]) == reais("480.0000")

        # Conferência: ela sai de "em aberto" e aparece em "pagas".
        assert (await client.get("/api/v1/payables?situacao=ABERTAS", headers=h)).json() == []
        pagas = (await client.get("/api/v1/payables?situacao=PAGAS", headers=h)).json()
        assert [c["id"] for c in pagas] == [conta["id"]]


@pytest.mark.asyncio
async def test_baixa_parcial_deixa_a_conta_aberta_pelo_saldo_certo():
    """Um sistema que só aceita baixa total obriga a pessoa a registrar como
    paga uma conta que não está — e o dado passa a valer menos que o caderno
    que ele substituiu."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        conta = await _lancar(client, h, amount="500.00")

        meio = (await client.post(
            f"/api/v1/payables/{conta['id']}/baixas", headers={**h, **_chave()},
            json={"amount": "300.00", "version": conta["version"]})).json()
        assert meio["status"] == "PARTIALLY_PAID"
        assert reais(meio["balance"]) == reais("200.0000")
        assert reais(meio["paid_amount"]) == reais("300.0000")

        # Pagar a mais não é baixa.
        demais = await client.post(
            f"/api/v1/payables/{conta['id']}/baixas", headers={**h, **_chave()},
            json={"amount": "200.01", "version": meio["version"]})
        assert demais.status_code == 422, demais.text
        assert "200.00" in demais.json()["detail"]

        resto = (await client.post(
            f"/api/v1/payables/{conta['id']}/baixas", headers={**h, **_chave()},
            json={"amount": "200.00", "version": meio["version"]})).json()
        assert resto["status"] == "PAID"
        assert reais(resto["balance"]) == reais("0.0000")


@pytest.mark.asyncio
async def test_reverter_devolve_o_saldo_e_o_historico_mostra_as_duas_coisas():
    """Nada é apagado. Quem confere precisa ver que houve um engano e que ele
    foi desfeito, não uma conta que sempre esteve certa."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        conta = await _lancar(client, h, amount="480.00")
        paga = (await client.post(
            f"/api/v1/payables/{conta['id']}/baixas", headers={**h, **_chave()},
            json={"amount": "480.00", "version": conta["version"]})).json()
        pagamento = next(e for e in paga["ledger"] if e["entry_type"] == "PAYMENT")

        revertida = await client.post(
            f"/api/v1/payables/{conta['id']}/reversoes", headers={**h, **_chave()},
            json={"entry_id": pagamento["id"], "reason": "Paguei a conta errada",
                  "version": paga["version"]})
        assert revertida.status_code == 201, revertida.text
        depois = revertida.json()
        assert depois["status"] == "OPEN"
        assert reais(depois["balance"]) == reais("480.0000")
        assert reais(depois["paid_amount"]) == reais("0.0000")

        # As duas coisas continuam à vista, e a baixa sabe que foi desfeita.
        tipos = [e["entry_type"] for e in depois["ledger"]]
        assert tipos == ["ISSUE", "PAYMENT", "REVERSAL"]
        desfeita = next(e for e in depois["ledger"] if e["entry_type"] == "PAYMENT")
        assert desfeita["reversed_by_entry_id"] is not None

        # E uma baixa só se desfaz uma vez: dois cliques em "Desfazer"
        # devolveriam o saldo duas vezes.
        de_novo = await client.post(
            f"/api/v1/payables/{conta['id']}/reversoes", headers={**h, **_chave()},
            json={"entry_id": pagamento["id"], "reason": "Cliquei sem querer",
                  "version": depois["version"]})
        assert de_novo.status_code == 409, de_novo.text


# ---------------------------------------------------------------------------
# A fronteira que o dono nomeou, nos dois sentidos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receber_mercadoria_nao_cria_conta_a_pagar():
    """A mercadoria pode ter sido paga à vista, ser consignada, bonificação ou
    troca de avaria. Quem sabe é a pessoa, e ela lança se for o caso."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, loja, sufixo = ctx["headers"], ctx["loja"], ctx["sufixo"]
        fornecedor = (await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Distribuidora do Vale"})).json()
        produto = (await client.post("/api/v1/catalog/products", headers=h, json={
            "name": "Cabo 6mm", "sku": f"CAB6-{sufixo}", "item_type": "PRODUCT"})).json()

        entrada = await client.post("/api/v1/inventory/adjust", headers=h, json={
            "store_id": loja["id"], "product_id": produto["id"], "actor_id": str(uuid.uuid4()),
            "movement_type": "PURCHASE", "quantity": 40.0, "supplier_id": fornecedor["id"],
        })
        assert entrada.status_code == 200, entrada.text

        contas = (await client.get("/api/v1/payables?situacao=TODAS", headers=h)).json()
        assert contas == [], f"o recebimento criou dívida sozinho: {contas}"


@pytest.mark.asyncio
async def test_dar_baixa_nao_movimenta_estoque():
    """O sentido que costuma ser esquecido: pagar a fatura de setembro não faz
    mercadoria entrar na prateleira."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, loja, sufixo = ctx["headers"], ctx["loja"], ctx["sufixo"]
        fornecedor = (await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Atacado Silencioso"})).json()
        produto = (await client.post("/api/v1/catalog/products", headers=h, json={
            "name": "Fita isolante", "sku": f"FIT-{sufixo}", "item_type": "PRODUCT"})).json()
        rota = f"/api/v1/inventory/movements?store_id={loja['id']}&product_id={produto['id']}"
        assert (await client.get(rota, headers=h)).json() == []

        conta = await _lancar(client, h, supplier_id=fornecedor["id"], payee_name=None)
        await client.post(f"/api/v1/payables/{conta['id']}/baixas", headers={**h, **_chave()},
                          json={"amount": "480.00", "version": conta["version"]})

        assert (await client.get(rota, headers=h)).json() == [], "a baixa mexeu no estoque"


@pytest.mark.asyncio
async def test_nao_existe_parcelamento_nem_calculo_de_juros():
    """O contrato deixa os dois expressamente fora da primeira entrega."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        # Nenhuma rota de parcelamento.
        for caminho in ("/api/v1/payables/installments", "/api/v1/payables/parcelas"):
            resposta = await client.get(caminho, headers=h)
            assert resposta.status_code in (404, 405, 422), (caminho, resposta.status_code)

        # E o lançamento recusa campos que a primeira entrega não tem, em vez de
        # aceitá-los em silêncio e ignorá-los.
        inventado = await client.post("/api/v1/payables", headers={**h, **_chave()}, json={
            "payee_name": "Fornecedor", "amount": "300.00",
            "due_on": str(date.today()), "installments": 3, "interest_rate": "2.5",
        })
        assert inventado.status_code == 422, inventado.text


@pytest.mark.asyncio
async def test_o_ajuste_e_digitado_e_exige_motivo():
    """Juros e desconto entram como decisão humana registrada, nunca como regra
    calculada — regra de cálculo é decisão do dono."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        conta = await _lancar(client, h, amount="480.00")

        sem_motivo = await client.post(
            f"/api/v1/payables/{conta['id']}/ajustes", headers={**h, **_chave()},
            json={"amount": "20.00", "version": conta["version"]})
        assert sem_motivo.status_code == 422, sem_motivo.text

        com_juros = (await client.post(
            f"/api/v1/payables/{conta['id']}/ajustes", headers={**h, **_chave()},
            json={"amount": "20.00", "reason": "Multa de atraso combinada por telefone",
                  "version": conta["version"]})).json()
        assert reais(com_juros["balance"]) == reais("500.0000")

        abatimento = (await client.post(
            f"/api/v1/payables/{conta['id']}/ajustes", headers={**h, **_chave()},
            json={"amount": "-50.00", "reason": "Desconto por pagamento adiantado",
                  "version": com_juros["version"]})).json()
        assert reais(abatimento["balance"]) == reais("450.0000")

        # Um abatimento não zera a dívida: para isso, dê baixa ou arquive.
        exagerado = await client.post(
            f"/api/v1/payables/{conta['id']}/ajustes", headers={**h, **_chave()},
            json={"amount": "-450.00", "reason": "Perdoaram tudo",
                  "version": abatimento["version"]})
        assert exagerado.status_code == 422, exagerado.text


# ---------------------------------------------------------------------------
# Falha e concorrência, que o aceite pede explicitamente
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_o_reenvio_nao_lanca_a_segunda_conta_nem_a_segunda_baixa():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        chave = _chave()
        corpo = {"payee_name": "Aluguel", "amount": "2500.00", "due_on": str(date.today())}

        primeira = await client.post("/api/v1/payables", headers={**h, **chave}, json=corpo)
        segunda = await client.post("/api/v1/payables", headers={**h, **chave}, json=corpo)
        assert primeira.status_code == 201, primeira.text
        assert segunda.json()["id"] == primeira.json()["id"]
        assert len((await client.get("/api/v1/payables", headers=h)).json()) == 1

        conta = primeira.json()
        chave_baixa = _chave()
        um = await client.post(f"/api/v1/payables/{conta['id']}/baixas",
                               headers={**h, **chave_baixa},
                               json={"amount": "1000.00", "version": conta["version"]})
        dois = await client.post(f"/api/v1/payables/{conta['id']}/baixas",
                                 headers={**h, **chave_baixa},
                                 json={"amount": "1000.00", "version": conta["version"]})
        assert um.status_code == 201, um.text
        assert reais(dois.json()["paid_amount"]) == reais("1000.00"), "o reenvio pagou duas vezes"


@pytest.mark.asyncio
async def test_dinheiro_exige_chave_de_idempotencia():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        sem_chave = await client.post("/api/v1/payables", headers=h, json={
            "payee_name": "Sem carimbo", "amount": "10.00", "due_on": str(date.today())})
        assert sem_chave.status_code == 400, sem_chave.text


@pytest.mark.asyncio
async def test_duas_pessoas_pagando_a_mesma_conta_nao_a_pagam_duas_vezes():
    """Concorrência otimista: quem perde a corrida é recusado **com o saldo
    atual à vista**, que é a informação que decide se ainda quer pagar."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        conta = await _lancar(client, h, amount="900.00")
        versao = conta["version"]

        respostas = await asyncio.gather(*[
            client.post(f"/api/v1/payables/{conta['id']}/baixas", headers={**h, **_chave()},
                        json={"amount": "900.00", "version": versao})
            for _ in range(3)
        ])
        aceitas = [r for r in respostas if r.status_code == 201]
        assert len(aceitas) == 1, [r.status_code for r in respostas]
        for recusada in [r for r in respostas if r.status_code != 201]:
            assert recusada.status_code == 409, recusada.text
            assert "saldo" in recusada.json()["detail"]

        final = (await client.get(f"/api/v1/payables/{conta['id']}", headers=h)).json()
        assert reais(final["paid_amount"]) == reais("900.0000"), "a conta foi paga mais de uma vez"


# ---------------------------------------------------------------------------
# Favorecido, arquivamento e isolamento
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_o_favorecido_tem_duas_formas_e_uma_delas_precisa_existir():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        fornecedor = (await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Atacadão Central"})).json()

        # Pelo cadastro: o nome fica gravado do mesmo jeito, para a conta
        # continuar legível se o fornecedor for arquivado depois.
        pelo_cadastro = await _lancar(client, h, supplier_id=fornecedor["id"], payee_name=None)
        assert pelo_cadastro["payee_name"] == "Atacadão Central"
        assert pelo_cadastro["supplier_id"] == fornecedor["id"]

        # Por nome livre: a conta de luz não tem fornecedor cadastrado.
        livre = await _lancar(client, h, payee_name="Companhia de Água")
        assert livre["supplier_id"] is None

        # Sem nenhum dos dois, não dá para saber para quem é.
        sem_ninguem = await client.post("/api/v1/payables", headers={**h, **_chave()}, json={
            "amount": "10.00", "due_on": str(date.today())})
        assert sem_ninguem.status_code == 422, sem_ninguem.text


@pytest.mark.asyncio
async def test_conta_com_baixa_nao_se_arquiva():
    """Arquivar é para a conta lançada por engano — a dívida que nunca existiu.
    Se houve dinheiro saindo, apagar a obrigação deixaria o pagamento órfão."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        conta = await _lancar(client, h, amount="480.00")
        paga = (await client.post(
            f"/api/v1/payables/{conta['id']}/baixas", headers={**h, **_chave()},
            json={"amount": "100.00", "version": conta["version"]})).json()

        recusa = await client.post(f"/api/v1/payables/{conta['id']}/arquivamento", headers=h,
                                   json={"reason": "Não era nossa", "version": paga["version"]})
        assert recusa.status_code == 409, recusa.text
        assert "Reverta" in recusa.json()["detail"]

        outra = await _lancar(client, h)
        arquivada = await client.post(f"/api/v1/payables/{outra['id']}/arquivamento", headers=h,
                                      json={"reason": "Lancei duas vezes",
                                            "version": outra["version"]})
        assert arquivada.status_code == 200, arquivada.text
        assert arquivada.json()["status"] == "ARCHIVED"


@pytest.mark.asyncio
async def test_vencida_e_derivada_da_data_e_nao_de_uma_coluna():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        atrasada = await _lancar(client, h, payee_name="Atrasada",
                                 due_on=str(date.today() - timedelta(days=3)))
        hoje = await _lancar(client, h, payee_name="Hoje", due_on=str(date.today()))
        futura = await _lancar(client, h, payee_name="Futura",
                               due_on=str(date.today() + timedelta(days=5)))

        assert atrasada["is_overdue"] is True and atrasada["days_to_due"] == -3
        assert hoje["is_overdue"] is False and hoje["days_to_due"] == 0
        assert futura["is_overdue"] is False and futura["days_to_due"] == 5

        vencidas = (await client.get("/api/v1/payables?situacao=VENCIDAS", headers=h)).json()
        assert [c["id"] for c in vencidas] == [atrasada["id"]]

        # E a lista em aberto vem ordenada por vencimento: quem entra aqui está
        # decidindo o que pagar hoje.
        abertas = (await client.get("/api/v1/payables?situacao=ABERTAS", headers=h)).json()
        assert [c["id"] for c in abertas] == [atrasada["id"], hoje["id"], futura["id"]]


@pytest.mark.asyncio
async def test_a_conta_de_um_tenant_nao_aparece_no_outro():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        a = await _tenant(client)
        b = await _tenant(client)
        conta = await _lancar(client, a["headers"], payee_name="Só do tenant A")

        assert (await client.get("/api/v1/payables?situacao=TODAS", headers=b["headers"])).json() == []
        assert (await client.get(f"/api/v1/payables/{conta['id']}",
                                 headers=b["headers"])).status_code == 404
        vizinho = await client.post(f"/api/v1/payables/{conta['id']}/baixas",
                                    headers={**b["headers"], **_chave()},
                                    json={"amount": "1.00", "version": conta["version"]})
        assert vizinho.status_code == 404, vizinho.text


# ---------------------------------------------------------------------------
# Os três pontos da revisão de 08/09/2026. Cada um reproduz o caso concreto,
# e cada um foi verificado desfazendo a correção de propósito.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_corrida_pela_mesma_conta_e_resolvida_pelo_banco():
    """Dez baixas simultâneas do valor inteiro: uma passa, o resto é recusado.

    **Este teste sozinho não prova a garantia do banco.** Ele passa com e sem
    `FOR UPDATE` na pilha local, porque o ambiente acaba escalonando as dez uma
    depois da outra — e um teste que passa nos dois casos mede o escalonador,
    não a regra. Quem prova a garantia é
    `test_a_versao_e_conferida_com_a_linha_travada_no_banco`, logo abaixo, que
    constrói a corrida em vez de torcer por ela.

    O valor deste aqui é outro: ele é a regressão do resultado. Se algum dia o
    total pago virar múltiplo do valor da conta, é aqui que aparece.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        conta = await _lancar(client, h, amount="900.00")
        versao = conta["version"]

        respostas = await asyncio.gather(*[
            client.post(f"/api/v1/payables/{conta['id']}/baixas", headers={**h, **_chave()},
                        json={"amount": "900.00", "version": versao})
            for _ in range(10)
        ])
        aceitas = [r for r in respostas if r.status_code == 201]
        assert len(aceitas) == 1, [r.status_code for r in respostas]
        for recusada in [r for r in respostas if r.status_code != 201]:
            assert recusada.status_code == 409, recusada.text

        final = (await client.get(f"/api/v1/payables/{conta['id']}", headers=h)).json()
        assert reais(final["paid_amount"]) == reais("900.00"), "a conta foi paga mais de uma vez"
        assert reais(final["balance"]) == reais("0.00")
        pagamentos = [e for e in final["ledger"] if e["entry_type"] == "PAYMENT"]
        assert len(pagamentos) == 1, f"ficaram {len(pagamentos)} pagamentos na razão"


@pytest.mark.asyncio
async def test_baixas_parciais_simultaneas_nao_ultrapassam_o_saldo():
    """A corrida perigosa não é a do valor inteiro; é a do valor que **cabe**.

    Cinco pessoas pagando 200 numa conta de 500: sem travar a linha, as cinco
    passam pela conferência de saldo e a conta termina com 1.000 pagos numa
    dívida de 500.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        conta = await _lancar(client, h, amount="500.00")

        respostas = await asyncio.gather(*[
            client.post(f"/api/v1/payables/{conta['id']}/baixas", headers={**h, **_chave()},
                        json={"amount": "200.00", "version": conta["version"]})
            for _ in range(5)
        ])
        assert len([r for r in respostas if r.status_code == 201]) == 1

        final = (await client.get(f"/api/v1/payables/{conta['id']}", headers=h)).json()
        assert reais(final["paid_amount"]) <= reais("500.00"), "pagou mais do que devia"
        assert reais(final["balance"]) >= reais("0.00")
        assert reais(final["paid_amount"]) + reais(final["balance"]) == reais("500.00")


@pytest.mark.asyncio
async def test_a_conta_de_uma_unidade_nao_se_paga_de_dentro_de_outra():
    """A listagem já escondia a conta da outra unidade; a rota de baixa a
    aceitava mesmo assim. Quem soubesse o identificador pagava a conta de uma
    loja estando em outra, e o dinheiro saía do lugar errado."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        sufixo = ctx["sufixo"]
        outra = (await client.post("/api/v1/identity/stores", json={
            "tenant_id": ctx["tenant"]["id"], "name": "Filial", "code": f"F-{sufixo}",
        })).json()
        na_matriz = {"X-Tenant-ID": ctx["tenant"]["id"], "X-Store-ID": ctx["loja"]["id"]}
        na_filial = {"X-Tenant-ID": ctx["tenant"]["id"], "X-Store-ID": outra["id"]}

        da_matriz = await _lancar(client, na_matriz, payee_name="Aluguel da Matriz",
                                  store_id=ctx["loja"]["id"])
        da_empresa = await _lancar(client, na_matriz, payee_name="Energia da Empresa")
        assert da_matriz["store_id"] == ctx["loja"]["id"]
        assert da_empresa["store_id"] is None

        # A lista da filial não mostra a conta da matriz, e mostra a da empresa.
        na_lista = (await client.get("/api/v1/payables?situacao=TODAS", headers=na_filial)).json()
        nomes = [c["payee_name"] for c in na_lista]
        assert "Energia da Empresa" in nomes, "conta sem unidade é da empresa e some da filial"
        assert "Aluguel da Matriz" not in nomes

        # E o que a lista esconde, a rota também recusa — as duas com a mesma regra.
        for caminho, corpo in (
            (f"/api/v1/payables/{da_matriz['id']}", None),
            (f"/api/v1/payables/{da_matriz['id']}/baixas",
             {"amount": "10.00", "version": da_matriz["version"]}),
        ):
            resposta = (await client.get(caminho, headers=na_filial)) if corpo is None else (
                await client.post(caminho, headers={**na_filial, **_chave()}, json=corpo))
            assert resposta.status_code == 404, (caminho, resposta.text)

        # A conta da empresa continua alcançável das duas unidades.
        de_dentro_da_filial = await client.post(
            f"/api/v1/payables/{da_empresa['id']}/baixas", headers={**na_filial, **_chave()},
            json={"amount": "10.00", "version": da_empresa["version"]})
        assert de_dentro_da_filial.status_code == 201, de_dentro_da_filial.text


@pytest.mark.asyncio
async def test_a_mesma_chave_em_outra_conta_nao_devolve_a_resposta_da_primeira():
    """O pior defeito possível neste domínio: perda silenciosa de pagamento.

    Sem vincular a idempotência à conta, a mesma `Idempotency-Key` usada numa
    **segunda** conta batia no registro da primeira e devolvia a resposta dela.
    A segunda baixa não era gravada, e a tela mostrava sucesso.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        primeira = await _lancar(client, h, payee_name="Conta A", amount="100.00")
        segunda = await _lancar(client, h, payee_name="Conta B", amount="100.00")

        chave = _chave()
        em_a = await client.post(f"/api/v1/payables/{primeira['id']}/baixas",
                                 headers={**h, **chave},
                                 json={"amount": "40.00", "version": primeira["version"]})
        assert em_a.status_code == 201, em_a.text

        em_b = await client.post(f"/api/v1/payables/{segunda['id']}/baixas",
                                 headers={**h, **chave},
                                 json={"amount": "40.00", "version": segunda["version"]})
        assert em_b.status_code == 201, em_b.text
        assert em_b.json()["id"] == segunda["id"], "a resposta veio da conta errada"

        # E o dinheiro entrou nas duas: nenhuma baixa se perdeu no caminho.
        a_depois = (await client.get(f"/api/v1/payables/{primeira['id']}", headers=h)).json()
        b_depois = (await client.get(f"/api/v1/payables/{segunda['id']}", headers=h)).json()
        assert reais(a_depois["paid_amount"]) == reais("40.00")
        assert reais(b_depois["paid_amount"]) == reais("40.00")

        # O reenvio na própria conta continua sendo reconhecido.
        de_novo = await client.post(f"/api/v1/payables/{segunda['id']}/baixas",
                                    headers={**h, **chave},
                                    json={"amount": "40.00", "version": segunda["version"]})
        assert de_novo.status_code == 201, de_novo.text
        b_final = (await client.get(f"/api/v1/payables/{segunda['id']}", headers=h)).json()
        assert reais(b_final["paid_amount"]) == reais("40.00"), "o reenvio pagou duas vezes"


@pytest.mark.asyncio
async def test_a_mesma_chave_em_outra_conta_tambem_vale_para_ajuste_e_reversao():
    """A mesma armadilha existia nas outras duas rotas que mexem em dinheiro."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        a = await _lancar(client, h, payee_name="Ajuste A", amount="100.00")
        b = await _lancar(client, h, payee_name="Ajuste B", amount="100.00")

        chave = _chave()
        em_a = await client.post(f"/api/v1/payables/{a['id']}/ajustes", headers={**h, **chave},
                                 json={"amount": "10.00", "reason": "Multa combinada",
                                       "version": a["version"]})
        em_b = await client.post(f"/api/v1/payables/{b['id']}/ajustes", headers={**h, **chave},
                                 json={"amount": "10.00", "reason": "Multa combinada",
                                       "version": b["version"]})
        assert em_a.status_code == 201 and em_b.status_code == 201, (em_a.text, em_b.text)
        assert em_b.json()["id"] == b["id"], "o ajuste respondeu pela conta errada"
        assert reais(em_a.json()["balance"]) == reais("110.00")
        assert reais(em_b.json()["balance"]) == reais("110.00")

        pago_a = (await client.post(f"/api/v1/payables/{a['id']}/baixas", headers={**h, **_chave()},
                                    json={"amount": "50.00", "version": em_a.json()["version"]})).json()
        pago_b = (await client.post(f"/api/v1/payables/{b['id']}/baixas", headers={**h, **_chave()},
                                    json={"amount": "50.00", "version": em_b.json()["version"]})).json()
        alvo_a = next(e for e in pago_a["ledger"] if e["entry_type"] == "PAYMENT")
        alvo_b = next(e for e in pago_b["ledger"] if e["entry_type"] == "PAYMENT")

        chave_reversao = _chave()
        rev_a = await client.post(f"/api/v1/payables/{a['id']}/reversoes",
                                  headers={**h, **chave_reversao},
                                  json={"entry_id": alvo_a["id"], "reason": "Errei a conta",
                                        "version": pago_a["version"]})
        rev_b = await client.post(f"/api/v1/payables/{b['id']}/reversoes",
                                  headers={**h, **chave_reversao},
                                  json={"entry_id": alvo_b["id"], "reason": "Errei a conta",
                                        "version": pago_b["version"]})
        assert rev_a.status_code == 201 and rev_b.status_code == 201, (rev_a.text, rev_b.text)
        assert rev_b.json()["id"] == b["id"], "a reversão respondeu pela conta errada"
        assert reais(rev_a.json()["paid_amount"]) == reais("0.00")
        assert reais(rev_b.json()["paid_amount"]) == reais("0.00")


@pytest.mark.asyncio
async def test_a_versao_e_conferida_com_a_linha_travada_no_banco():
    """A prova que distingue conferir em Python de garantir no banco.

    As dez baixas simultâneas do teste acima passam **com ou sem** `FOR UPDATE`
    na pilha local, porque o ambiente as escalona uma depois da outra por
    acidente. Um teste que passa nos dois casos não prova a garantia — prova o
    escalonador.

    Aqui a corrida é construída, não torcida. Este teste abre a sua própria
    transação no banco, trava a linha da conta e **segura**. Enquanto ela
    segura:

    * com `FOR UPDATE` na rota, a baixa fica esperando a linha — e quando ela
      finalmente lê, a versão já mudou, e a recusa é correta;
    * sem `FOR UPDATE`, a rota lê a versão **antiga** já comprometida, passa
      pela conferência e paga uma conta cujo estado mudou debaixo dela.

    A diferença aparece no relógio: a requisição bloqueada não responde
    enquanto a trava é segurada.
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL não está no ambiente: sem ele não há como segurar a linha.")
    engine = create_engine(url, poolclass=NullPool)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        conta = await _lancar(client, h, amount="900.00")

        def segurar_e_mudar(solta: threading.Event, pronta: threading.Event) -> None:
            with engine.connect() as conexao:
                # O SQLAlchemy 2.0 abre a transação no primeiro `execute`; é
                # dela que a trava depende, e ela vai até o `commit` lá embaixo.
                # A política de isolamento é forçada até para o dono da tabela.
                conexao.execute(text("SET app.platform_access = 'true'"))
                travadas = conexao.execute(
                    text("SELECT id FROM payables WHERE id = :id FOR UPDATE"),
                    {"id": conta["id"]},
                ).all()
                # Se a política de isolamento escondesse a linha, o SELECT
                # travaria **nada** e o teste passaria a medir o vazio.
                assert len(travadas) == 1, "a linha da conta não foi travada"
                pronta.set()
                solta.wait(timeout=30)
                # Mexe na conta e libera: a rota bloqueada vai reler isto.
                conexao.execute(
                    text("UPDATE payables SET version = version + 1 WHERE id = :id"),
                    {"id": conta["id"]},
                )
                conexao.commit()

        solta, pronta = threading.Event(), threading.Event()
        segurando = asyncio.create_task(asyncio.to_thread(segurar_e_mudar, solta, pronta))
        await asyncio.to_thread(pronta.wait, 15)

        baixa = asyncio.create_task(client.post(
            f"/api/v1/payables/{conta['id']}/baixas", headers={**h, **_chave()},
            json={"amount": "900.00", "version": conta["version"]},
        ))
        # Nos dois casos a requisição fica pendurada: ou ela espera a linha no
        # `SELECT`, ou ela decide sobre leitura velha e só trava depois, na
        # gravação. **Não é aqui que a diferença aparece** — este `sleep` só
        # garante que a corrida aconteceu antes de a trava ser solta.
        await asyncio.sleep(2.0)
        assert not baixa.done(), "a corrida não chegou a acontecer"

        solta.set()
        await segurando

        # **Aqui** está a diferença. Com a trava na rota, a leitura só acontece
        # depois da liberação, já com a versão nova, e a baixa é recusada. Sem
        # ela, a decisão foi tomada lá atrás sobre a versão antiga: a rota
        # apenas esperou para gravar, e gravou — pagando uma conta cujo estado
        # mudou debaixo dela, e apagando a alteração de quem chegou antes.
        resposta = await baixa
        assert resposta.status_code == 409, resposta.text
        assert "saldo" in resposta.json()["detail"]

        final = (await client.get(f"/api/v1/payables/{conta['id']}", headers=h)).json()
        assert reais(final["paid_amount"]) == reais("0.00"), "pagou sobre um estado que mudou"

    engine.dispose()

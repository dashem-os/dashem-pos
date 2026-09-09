"""Fornecedores: cadastro, busca, contatos, isolamento e o retry que não duplica.

O inventário da UX-09 não achou nada — nem tabela, nem rota, nem tela. Sendo
domínio novo, o que estes testes fixam é tanto o que ele faz quanto o que ele
**não** faz: não há pedido de compra em lugar nenhum, e nenhuma rota finge que
há.

As provas falam HTTP porque é aí que o contrato vive: o cabeçalho
`Idempotency-Key` e o isolamento por tenant só existem de verdade na borda.
"""

import asyncio
import os
import uuid

import httpx
import pytest

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _tenant(client: httpx.AsyncClient) -> dict:
    sufixo = uuid.uuid4().hex[:8]
    tenant = (await client.post("/api/v1/identity/tenants", json={
        "name": f"Fornecimento {sufixo}", "slug": f"fornecimento-{sufixo}",
    })).json()
    loja = (await client.post("/api/v1/identity/stores", json={
        "tenant_id": tenant["id"], "name": "Matriz", "code": f"M-{sufixo}",
    })).json()
    return {"headers": {"X-Tenant-ID": tenant["id"], "X-Store-ID": loja["id"]},
            "tenant": tenant, "loja": loja, "sufixo": sufixo}


@pytest.mark.asyncio
async def test_cadastrar_localizar_e_editar():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]

        criado = await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Distribuidora Aurora", "legal_name": "Aurora Comércio de Alimentos LTDA",
            "document": "12.345.678/0001-90",
        })
        assert criado.status_code == 201, criado.text
        fornecedor = criado.json()
        # O documento é guardado sem máscara: a comparação é de dígitos.
        assert fornecedor["document"] == "12345678000190"
        assert fornecedor["recebimentos"] == 0

        por_nome = (await client.get("/api/v1/suppliers?busca=aurora", headers=h)).json()
        assert [item["id"] for item in por_nome] == [fornecedor["id"]]

        # Buscar pelo documento com máscara acha o mesmo cadastro.
        por_documento = (await client.get("/api/v1/suppliers?busca=12.345.678", headers=h)).json()
        assert [item["id"] for item in por_documento] == [fornecedor["id"]]

        editado = await client.patch(f"/api/v1/suppliers/{fornecedor['id']}", headers=h, json={
            "name": "Distribuidora Aurora Matriz",
        })
        assert editado.status_code == 200, editado.text
        assert editado.json()["name"] == "Distribuidora Aurora Matriz"


@pytest.mark.asyncio
async def test_o_reenvio_do_cadastro_nao_cria_dois_fornecedores():
    """O aceite pede cadastrar sem duplicação no retry."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        chave = str(uuid.uuid4())
        corpo = {"name": "Hortifruti do Bairro"}

        primeira = await client.post("/api/v1/suppliers", headers={**h, "Idempotency-Key": chave}, json=corpo)
        segunda = await client.post("/api/v1/suppliers", headers={**h, "Idempotency-Key": chave}, json=corpo)
        assert primeira.status_code == 201, primeira.text
        assert segunda.json()["id"] == primeira.json()["id"]

        lista = (await client.get("/api/v1/suppliers", headers=h)).json()
        assert len(lista) == 1, f"o retry criou {len(lista)} fornecedores"


@pytest.mark.asyncio
async def test_o_mesmo_documento_duas_vezes_e_o_mesmo_fornecedor_digitado_duas_vezes():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Padaria Central", "document": "98765432000155",
        })
        repetido = await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Padaria Central Filial", "document": "98.765.432/0001-55",
        })
        assert repetido.status_code == 409, repetido.text
        assert "Padaria Central" in repetido.json()["detail"]


@pytest.mark.asyncio
async def test_fornecedor_sem_documento_e_permitido_e_nao_colide():
    """Compra de bairro não tem CNPJ no cadastro, e exigir um inventaria
    burocracia que a operação real não tem."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        um = await client.post("/api/v1/suppliers", headers=h, json={"name": "Seu Zé das Verduras"})
        outro = await client.post("/api/v1/suppliers", headers=h, json={"name": "Dona Maria dos Ovos"})
        assert um.status_code == 201 and outro.status_code == 201, (um.text, outro.text)
        assert um.json()["document"] is None and outro.json()["document"] is None


@pytest.mark.asyncio
async def test_contatos_e_o_principal_que_e_um_so():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        fornecedor = (await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Atacado Bom Preço"})).json()

        await client.post(f"/api/v1/suppliers/{fornecedor['id']}/contatos", headers=h, json={
            "name": "Cláudia", "role": "Vendedora", "phone": "11999990000", "is_primary": True})
        com_dois = (await client.post(f"/api/v1/suppliers/{fornecedor['id']}/contatos", headers=h, json={
            "name": "Roberto", "role": "Financeiro", "email": "financeiro@bompreco.test",
            "is_primary": True})).json()

        principais = [c for c in com_dois["contacts"] if c["is_primary"]]
        assert len(principais) == 1, "dois principais não dizem a quem ligar"
        assert principais[0]["name"] == "Roberto"

        contato = com_dois["contacts"][0]
        depois = await client.delete(
            f"/api/v1/suppliers/{fornecedor['id']}/contatos/{contato['id']}", headers=h)
        assert depois.status_code == 200, depois.text
        assert len(depois.json()["contacts"]) == 1


@pytest.mark.asyncio
async def test_o_fornecedor_de_um_tenant_nao_aparece_no_outro():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        a = await _tenant(client)
        b = await _tenant(client)
        criado = (await client.post("/api/v1/suppliers", headers=a["headers"], json={
            "name": "Exclusivo do Tenant A"})).json()

        assert (await client.get("/api/v1/suppliers", headers=b["headers"])).json() == []
        atravessando = await client.get("/api/v1/suppliers", headers=a["headers"])
        assert [item["id"] for item in atravessando.json()] == [criado["id"]]

        # E nem editando pelo identificador: o vizinho não existe para ele.
        recusa = await client.patch(f"/api/v1/suppliers/{criado['id']}", headers=b["headers"],
                                    json={"name": "Tentativa do vizinho"})
        assert recusa.status_code == 404, recusa.text


@pytest.mark.asyncio
async def test_o_recebimento_diz_de_quem_veio_a_mercadoria():
    """O vínculo que o enunciado pede — e nada além dele."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, loja, sufixo = ctx["headers"], ctx["loja"], ctx["sufixo"]
        fornecedor = (await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Distribuidora do Vale"})).json()
        produto = (await client.post("/api/v1/catalog/products", headers=h, json={
            "name": "Cabo 10mm", "sku": f"CAB-{sufixo}", "item_type": "PRODUCT"})).json()

        entrada = await client.post("/api/v1/inventory/adjust", headers=h, json={
            "store_id": loja["id"], "product_id": produto["id"], "actor_id": str(uuid.uuid4()),
            "movement_type": "PURCHASE", "quantity": 12.0, "supplier_id": fornecedor["id"],
        })
        assert entrada.status_code == 200, entrada.text

        depois = (await client.get("/api/v1/suppliers", headers=h)).json()
        assert depois[0]["recebimentos"] == 1, "o recebimento não ficou ligado ao fornecedor"


@pytest.mark.asyncio
async def test_nao_existe_pedido_de_compra():
    """O enunciado proíbe inventá-lo como entregue; nada aqui finge que existe."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        for caminho in ("/api/v1/suppliers/purchase-orders", "/api/v1/purchase-orders"):
            resposta = await client.get(caminho, headers={"X-Tenant-ID": str(uuid.uuid4())})
            assert resposta.status_code in (404, 405, 422), (caminho, resposta.status_code)


# ---------------------------------------------------------------------------
# As cinco correções pedidas na revisão de 8/9/2026. Cada uma nasceu de um
# defeito real encontrado lendo o código, e cada teste abaixo falha se o
# defeito voltar.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_o_cnpj_alfanumerico_nao_perde_as_letras():
    """O CNPJ alfanumérico está em operação desde julho de 2026.

    A normalização guardava só dígitos. Um documento com letras chegava,
    perdia metade dos caracteres e era gravado como outro documento — sem erro,
    sem aviso, e ainda parecendo um número. É corrupção silenciosa de cadastro.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]

        criado = await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Fornecedora Alfanumérica", "document": "12.ABC.345/01DE-35",
        })
        assert criado.status_code == 201, criado.text
        # Sem a máscara, com as letras, em maiúsculas.
        assert criado.json()["document"] == "12ABC34501DE35"

        # E ele é encontrável pelo que a pessoa digita: com máscara e minúsculas.
        achado = (await client.get("/api/v1/suppliers?busca=12.abc.345", headers=h)).json()
        assert [item["id"] for item in achado] == [criado.json()["id"]]

        # O mesmo documento em caixa baixa é o mesmo documento.
        repetido = await client.post("/api/v1/suppliers", headers=h, json={
            "name": "A mesma, digitada de novo", "document": "12abc34501de35",
        })
        assert repetido.status_code == 409, repetido.text

        # E o CPF continua passando pelo mesmo caminho.
        cpf = await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Seu Ze MEI", "document": "123.456.789-09",
        })
        assert cpf.status_code == 201, cpf.text
        assert cpf.json()["document"] == "12345678909"


@pytest.mark.asyncio
async def test_apagar_o_documento_na_edicao_limpa_o_cadastro():
    """Apagar o campo na tela tem de apagar o campo no cadastro.

    A tela enviava `undefined`, que some do JSON; o servidor lia "não mexeu
    neste campo" e mantinha o valor antigo. O lojista apagava o CNPJ errado,
    salvava, e ele voltava.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        fornecedor = (await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Cadastro Completo", "document": "11222333000181",
            "legal_name": "Cadastro Completo LTDA", "notes": "Entrega às terças.",
        })).json()

        limpo = await client.patch(f"/api/v1/suppliers/{fornecedor['id']}", headers=h, json={
            "document": None, "legal_name": None, "notes": None,
        })
        assert limpo.status_code == 200, limpo.text
        assert limpo.json()["document"] is None
        assert limpo.json()["legal_name"] is None
        assert limpo.json()["notes"] is None

        # String vazia é a mesma intenção: "não tenho".
        de_novo = (await client.patch(f"/api/v1/suppliers/{fornecedor['id']}", headers=h, json={
            "legal_name": "Voltou LTDA"})).json()
        assert de_novo["legal_name"] == "Voltou LTDA"
        vazio = await client.patch(f"/api/v1/suppliers/{fornecedor['id']}", headers=h, json={
            "legal_name": "   "})
        assert vazio.json()["legal_name"] is None, "espaço em branco não é razão social"

        # E o que não foi enviado continua onde estava.
        assert vazio.json()["name"] == "Cadastro Completo"


@pytest.mark.asyncio
async def test_editar_para_o_documento_de_outro_recebe_a_mesma_recusa_do_cadastro():
    """Cadastrar checava duplicidade; editar não checava nada.

    Trocar o documento de um fornecedor para o de outro passava direto até o
    banco recusar, e a tela recebia um erro que não sabia explicar.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        primeiro = (await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Atacadão do Norte", "document": "55666777000188"})).json()
        segundo = (await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Mercearia do Sul", "document": "99888777000166"})).json()
        assert primeiro["document"] == "55666777000188"

        conflito = await client.patch(f"/api/v1/suppliers/{segundo['id']}", headers=h, json={
            "document": "55.666.777/0001-88"})
        assert conflito.status_code == 409, conflito.text
        assert "Atacadão do Norte" in conflito.json()["detail"]

        # O cadastro do segundo não foi tocado pela tentativa recusada.
        atual = (await client.get("/api/v1/suppliers", headers=h)).json()
        por_id = {item["id"]: item for item in atual}
        assert por_id[segundo["id"]]["document"] == "99888777000166"

        # Regravar o próprio documento não é conflito consigo mesmo.
        proprio = await client.patch(f"/api/v1/suppliers/{segundo['id']}", headers=h, json={
            "document": "99.888.777/0001-66"})
        assert proprio.status_code == 200, proprio.text


@pytest.mark.asyncio
async def test_dois_principais_ao_mesmo_tempo_nao_gravam_dois_principais():
    """A rota desmarcava os anteriores antes de inserir, e isso basta em fila
    única. Em duas requisições simultâneas as duas leem, as duas desmarcam e as
    duas inserem — e o fornecedor fica com dois principais, o que é o mesmo que
    ficar sem nenhum: a tela deixa de responder a quem ligar."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h = ctx["headers"]
        fornecedor = (await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Distribuidora Simultânea"})).json()
        rota = f"/api/v1/suppliers/{fornecedor['id']}/contatos"

        respostas = await asyncio.gather(*[
            client.post(rota, headers=h, json={"name": nome, "is_primary": True})
            for nome in ("Ana Principal", "Bruno Principal", "Célia Principal")
        ])

        # Quem perde a corrida ouve o motivo. Ninguém recebe 500.
        for resposta in respostas:
            assert resposta.status_code in (201, 409), resposta.text

        final = (await client.get("/api/v1/suppliers", headers=h)).json()[0]
        principais = [c for c in final["contacts"] if c["is_primary"]]
        assert len(principais) <= 1, f"ficaram {len(principais)} contatos principais"


@pytest.mark.asyncio
async def test_o_historico_do_estoque_carrega_de_quem_veio():
    """Guardar o vínculo sem devolvê-lo é o mesmo que não guardar.

    A tela precisa reler no histórico de quem veio cada entrada, e para isso o
    movimento tem de trazer o fornecedor de volta na listagem.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ctx = await _tenant(client)
        h, loja, sufixo = ctx["headers"], ctx["loja"], ctx["sufixo"]
        fornecedor = (await client.post("/api/v1/suppliers", headers=h, json={
            "name": "Transportadora Régia"})).json()
        produto = (await client.post("/api/v1/catalog/products", headers=h, json={
            "name": "Parafuso 5mm", "sku": f"PAR-{sufixo}", "item_type": "PRODUCT"})).json()

        await client.post("/api/v1/inventory/adjust", headers=h, json={
            "store_id": loja["id"], "product_id": produto["id"], "actor_id": str(uuid.uuid4()),
            "movement_type": "PURCHASE", "quantity": 30.0, "supplier_id": fornecedor["id"],
        })
        # E uma perda, que não vem de fornecedor nenhum.
        await client.post("/api/v1/inventory/adjust", headers=h, json={
            "store_id": loja["id"], "product_id": produto["id"], "actor_id": str(uuid.uuid4()),
            "movement_type": "LOSS", "quantity": 2.0, "reason": "Caixa amassada",
        })

        movimentos = (await client.get(
            f"/api/v1/inventory/movements?store_id={loja['id']}&product_id={produto['id']}",
            headers=h)).json()
        por_tipo = {m["movement_type"]: m for m in movimentos}
        assert por_tipo["PURCHASE"]["supplier_id"] == fornecedor["id"]
        assert por_tipo["LOSS"]["supplier_id"] is None, "perda não vem de fornecedor"

"""A grade do balcão quando o acervo é grande.

Medido na homologação de catálogo volumoso (09/09/2026), com 1.203 produtos
vendáveis num tenant e 40 mil na tabela: a página da grade custava **4.563ms**.
Sem a junção externa de `inventory_balances`, a mesma página custava **36ms** —
o plano descartava 723.003 linhas num laço aninhado com filtro de junção.

A causa não é falta de índice: `ix_inventory_balances_product_id` existe. É a
política de RLS da tabela, que carrega um `EXISTS` sobre `stores`. Um predicado
assim não é *leakproof*, então o PostgreSQL o aplica antes das condições de
junção — e a junção deixa de usar o índice.

O saldo saiu da consulta paginada e passou a ser buscado depois do `LIMIT`, para
as linhas da página, como as reservas e as imagens já faziam ali. Estes testes
guardam as duas metades disso: o número continua certo, e a junção não volta.
"""
import os
import re
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.platform import TenantCapability, EntitlementStatusEnum

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")
SERVICO = Path(__file__).resolve().parents[1] / "app" / "services" / "catalog_service.py"


def _corpo_de(nome: str) -> str:
    """O texto de uma função, do `def` até o próximo `def` de mesma indentação."""
    fonte = SERVICO.read_text(encoding="utf-8")
    inicio = fonte.index(f"def {nome}(")
    resto = fonte[inicio:]
    seguinte = re.search(r"\n(?=def |@)", resto)
    return resto[: seguinte.start()] if seguinte else resto


def test_a_pagina_da_grade_nao_junta_a_tabela_de_saldos():
    """O saldo não volta para dentro da consulta paginada.

    Isto guarda uma decisão medida, não um gosto: com a junção, a página do
    balcão custava 4,5 segundos com mil produtos — fila parada. A prova é
    estrutural de propósito. Cronometrar no CI mediria a máquina do dia, e uma
    prova que oscila com a máquina não acusa regressão nenhuma.
    """
    corpo = _corpo_de("list_sellable_products")
    assert "InventoryBalance" not in corpo, (
        "a junção de saldos voltou para a consulta paginada da grade; ela custava "
        "4.563ms contra 36ms sem ela — busque os saldos depois do LIMIT, como "
        "`_balances_by_product` faz"
    )
    # O caminho correto continua no lugar, e é chamado.
    assert "_balances_by_product(" in corpo
    assert "_reserved_by_product(" in corpo


@pytest.mark.asyncio
async def test_o_saldo_da_grade_sobrevive_a_saida_da_juncao():
    """Três produtos, três situações de prateleira, uma página da grade.

    Sem linha de saldo o produto vale zero — nunca foi contado nesta unidade,
    e não é estoque negativo. Com saldo abaixo do mínimo ele é apontado. Era o
    que a junção externa entregava, e é o que a busca separada tem de entregar.
    """
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={
            "name": f"Grade {suffix}", "slug": f"grade-{suffix}"})).json()
        store = (await client.post("/api/v1/identity/stores", json={
            "tenant_id": tenant["id"], "name": "Matriz", "code": f"GR-{suffix}"})).json()
        with Session(engine) as db:
            set_platform_db_context(db)
            db.add(TenantCapability(tenant_id=uuid.UUID(tenant["id"]), key="counter_order",
                                    enabled=True, status=EntitlementStatusEnum.ACTIVE))
            db.add(TenantCapability(tenant_id=uuid.UUID(tenant["id"]), key="inventory",
                                    enabled=True, status=EntitlementStatusEnum.ACTIVE))
            db.commit()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}

        criados = {}
        for apelido, nome in (("sem_saldo", "Alfa Sem Contagem"),
                              ("abaixo", "Beta Abaixo do Mínimo"),
                              ("folgado", "Gama Com Folga")):
            resposta = await client.post("/api/v1/catalog/products", headers=headers, json={
                "name": nome, "sku": f"{apelido.upper()}-{suffix}", "unit": "UN",
            })
            assert resposta.status_code == 200, resposta.text
            criados[apelido] = resposta.json()
            preco = await client.post("/api/v1/catalog/prices", headers=headers, json={
                "product_id": criados[apelido]["id"], "store_id": store["id"],
                "cost_price": 5.0, "sale_price": 10.0,
            })
            assert preco.status_code == 200, preco.text

        # Só dois produtos são contados; o primeiro nunca chega à prateleira.
        for apelido, quantidade, minimo in (("abaixo", 2, 10), ("folgado", 50, 10)):
            ajuste = await client.post("/api/v1/inventory/adjust", headers=headers, json={
                "store_id": store["id"], "product_id": criados[apelido]["id"],
                "actor_id": str(uuid.uuid4()), "movement_type": "PURCHASE",
                "quantity": quantidade, "reason": "Semeadura da prova",
            })
            assert ajuste.status_code == 200, ajuste.text
            minimos = await client.put("/api/v1/inventory/minimum", headers=headers, json={
                "store_id": store["id"], "product_id": criados[apelido]["id"],
                "minimum_stock": minimo,
            })
            assert minimos.status_code == 200, minimos.text

        # A grade lê o sortimento, não a tabela de produtos: sem isto os três
        # produtos existem e nenhum é vendável.
        sortimento = await client.post("/api/v1/catalog/assortments", headers=headers, json={
            "code": f"GRADE-{suffix}", "name": "Sortimento da prova",
            "scopes": [{"store_id": store["id"], "sales_context": "COUNTER"}],
            "product_ids": [criados[a]["id"] for a in ("sem_saldo", "abaixo", "folgado")],
        })
        assert sortimento.status_code == 201, sortimento.text

        pagina = await client.get("/api/v1/catalog/sellable-products", headers=headers,
                                  params={"sales_context": "COUNTER", "page_size": 50})
        assert pagina.status_code == 200, pagina.text
        por_nome = {item["name"]: item for item in pagina.json()["items"]}

        sem_contagem = por_nome["Alfa Sem Contagem"]
        assert Decimal(str(sem_contagem["quantity"])) == 0, (
            "produto que nunca foi contado precisa valer zero, não sumir nem ficar nulo"
        )
        assert Decimal(str(sem_contagem["available"])) == 0

        abaixo = por_nome["Beta Abaixo do Mínimo"]
        assert Decimal(str(abaixo["quantity"])) == 2
        assert Decimal(str(abaixo["available"])) == 2

        assert abaixo["is_low_stock"] is True, (
            "2 na prateleira com mínimo 10 é estoque baixo, e a grade tem de apontar"
        )

        folgado = por_nome["Gama Com Folga"]
        assert Decimal(str(folgado["quantity"])) == 50
        assert folgado["is_low_stock"] is False

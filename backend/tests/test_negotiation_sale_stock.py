"""Mesa e comanda também tiram mercadoria do estoque.

A finalização da negociação cria a `Sale` já paga e, até esta correção, nunca
encostava no estoque. Quem vendia pelo balcão baixava; quem vendia pela mesa não
— e o saldo do salão inteiro ficava parado enquanto a mercadoria saía pela porta.

A fronteira do ADR-001 continua onde estava: quem move estoque é a **venda**, não
o `OrderItem`. É a `Sale` criada na finalização que registra a saída, com item de
venda, ator e motivo, pelo mesmo serviço que a venda de balcão usa. Nenhum
consumo é atribuído ao item de pedido.

Os cenários que o caminho precisa responder estão aqui: mesa, comanda, serviço
sem saldo físico, repetição da finalização, crediário, falha no meio da operação
composta, e a retomada depois de resolvida a falta. Todos pelos endpoints
autenticados, e o que ficou gravado é sempre lido por uma sessão nova.

Uma precisão sobre a falha: **o que não sobrevive é a transação da finalização**,
e só ela. O dinheiro recebido antes é fato anterior e consumado — a intenção de
pagamento confirmada e o movimento de caixa que ela gerou continuam de pé, como
têm de continuar. Desfazer recebimento por causa de falta de estoque seria
apagar dinheiro que entrou.
"""

import os
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlmodel import Session, select

from activity_fixtures import declare_food_service
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.catalog import InventoryBalance, InventoryMovement, MovementTypeEnum
from app.models.negotiation import (
    CheckoutNegotiation, CheckoutNegotiationStatusEnum, PaymentIntent,
    PaymentIntentStatusEnum,
)
from app.models.payment import CashMovement, CashMovementTypeEnum, Payment
from app.models.order import Order, OrderStatusEnum
from app.models.platform import EntitlementStatusEnum, TenantCapability
from app.models.sale import Sale, SaleStatusEnum


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _tenant(client: httpx.AsyncClient, prefix: str):
    """Tenant de food service com mesa, caixa aberto e nada mais."""
    suffix = uuid.uuid4().hex[:8]
    actor = str(uuid.uuid4())
    tenant = (await client.post("/api/v1/identity/tenants", json={
        "name": f"{prefix} {suffix}", "slug": f"{prefix.lower()}-{suffix}",
    })).json()
    store = (await client.post("/api/v1/identity/stores", json={
        "tenant_id": tenant["id"], "name": "Matriz", "code": f"{prefix[:3].upper()}-{suffix}",
    })).json()
    with Session(engine) as db:
        set_platform_db_context(db)
        declare_food_service(db, tenant["id"])
        for key in ("counter_order", "table_service", "receivables"):
            db.add(TenantCapability(
                tenant_id=uuid.UUID(tenant["id"]), key=key, enabled=True,
                status=EntitlementStatusEnum.ACTIVE,
            ))
        db.commit()
    headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}
    register = (await client.post("/api/v1/cash/registers", headers=headers, json={
        "store_id": store["id"], "name": "Caixa", "code": f"CX-{suffix}",
    })).json()
    cash = (await client.post("/api/v1/cash/sessions/open", headers=headers, json={
        "store_id": store["id"], "register_id": register["id"],
        "operator_id": actor, "opening_balance": 100,
    })).json()
    # Sem sortimento publicado o item nem entra no pedido: a mercadoria precisa
    # estar autorizada no contexto antes de haver o que baixar.
    assortment = (await client.post("/api/v1/catalog/assortments", headers=headers, json={
        "code": f"ASSORT-{suffix}", "name": "Sortimento do salão",
        "scopes": [
            {"store_id": store["id"], "sales_context": "TABLE"},
            {"store_id": store["id"], "sales_context": "COUNTER"},
        ],
        "product_ids": [],
    })).json()
    return tenant, store, headers, actor, cash, suffix, assortment


async def _publish(client, headers, assortment, product, version):
    response = await client.post(
        f"/api/v1/catalog/assortments/{assortment['id']}/products", headers=headers,
        json={"expected_version": version, "product_ids": [product["id"]]},
    )
    assert response.status_code == 200, response.text


async def _stocked_product(client, headers, store, suffix, index, *, stock,
                           price=10, assortment=None):
    """Mercadoria controlada, publicada no salão e com saldo recebido."""
    product = (await client.post("/api/v1/catalog/products", headers=headers, json={
        "name": f"Mercadoria {index}", "sku": f"NEG-{suffix}-{index}",
        "unit": "UN", "tracks_inventory": True,
    })).json()
    await client.post("/api/v1/catalog/prices", headers=headers, json={
        "product_id": product["id"], "store_id": store["id"],
        "cost_price": 1, "sale_price": price,
    })
    if assortment is not None:
        await _publish(client, headers, assortment, product, index)
    if stock:
        received = await client.post("/api/v1/inventory/adjust", headers=headers, json={
            "store_id": store["id"], "product_id": product["id"],
            "actor_id": str(uuid.uuid4()), "movement_type": "PURCHASE",
            "quantity": stock, "reason": "Recebimento inicial",
        })
        assert received.status_code == 200, received.text
    return product


async def _table_order(client, headers, store, actor, suffix):
    table = (await client.post("/api/v1/tables", headers={
        **headers, "Idempotency-Key": f"table-{suffix}",
    }, json={
        "store_id": store["id"], "code": "M-01", "name": "Mesa 01",
        "capacity": 4, "actor_id": actor,
    })).json()
    table_session = (await client.post("/api/v1/tables/sessions", headers={
        **headers, "Idempotency-Key": f"session-{suffix}",
    }, json={
        "store_id": store["id"], "service_table_id": table["id"], "actor_id": actor,
    })).json()
    return table_session, table_session["orders"][0]["id"]


async def _counter_order(client, headers, store, actor, suffix):
    """A comanda de balcão: pedido sem mesa, mesmo caminho de finalização."""
    response = await client.post("/api/v1/orders", headers={
        **headers, "Idempotency-Key": f"order-{suffix}",
    }, json={"store_id": store["id"], "actor_id": actor})
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _launch(client, headers, order_id, product, quantity, actor, key):
    response = await client.post(f"/api/v1/orders/{order_id}/items", headers={
        **headers, "Idempotency-Key": key,
    }, json={"product_id": product["id"], "quantity": quantity, "actor_id": actor})
    assert response.status_code == 200, response.text
    return response.json()


async def _cover_with_cash(client, headers, negotiation, actor, cash, amount):
    projection = (await client.post(
        f"/api/v1/negotiations/{negotiation['id']}/intents",
        headers={**headers, "Idempotency-Key": f"intent-{uuid.uuid4()}"},
        json={"method": "CASH", "amount": amount, "cash_session_id": cash["id"],
              "tendered_amount": amount, "actor_id": actor},
    )).json()
    intent = projection["intents"][-1]
    confirmed = await client.post(
        f"/api/v1/negotiations/intents/{intent['id']}/confirm",
        headers={**headers, "Idempotency-Key": f"confirm-{uuid.uuid4()}"},
        json={"actor_id": actor},
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def _balance(tenant_id, store_id, product_id) -> Decimal:
    with Session(engine) as session:
        set_tenant_db_context(session, uuid.UUID(tenant_id), uuid.UUID(store_id), None)
        row = session.exec(select(InventoryBalance).where(
            InventoryBalance.product_id == uuid.UUID(product_id),
        )).first()
        return Decimal("0") if row is None else Decimal(str(row.quantity))


def _sale_movements(tenant_id, store_id, product_id) -> list:
    with Session(engine) as session:
        set_tenant_db_context(session, uuid.UUID(tenant_id), uuid.UUID(store_id), None)
        return session.exec(select(InventoryMovement).where(
            InventoryMovement.product_id == uuid.UUID(product_id),
            InventoryMovement.movement_type == MovementTypeEnum.SALE,
        )).all()


@pytest.mark.asyncio
async def test_a_table_that_closes_takes_the_goods_out_of_the_stock():
    """O caminho que não baixava: mesa fechada pela negociação."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        tenant, store, headers, actor, cash, suffix, assortment = await _tenant(client, "Mesa")
        product = await _stocked_product(client, headers, store, suffix, 1, stock=10, assortment=assortment)
        _, order_id = await _table_order(client, headers, store, actor, suffix)
        await _launch(client, headers, order_id, product, 2, actor, f"item-{suffix}")

        negotiation = (await client.post("/api/v1/negotiations", headers={
            **headers, "Idempotency-Key": f"neg-{suffix}",
        }, json={"store_id": store["id"], "order_ids": [order_id], "actor_id": actor})).json()
        covered = await _cover_with_cash(
            client, headers, negotiation, actor, cash, float(negotiation["total_due"]),
        )
        finalized = await client.post(
            f"/api/v1/negotiations/{negotiation['id']}/finalize",
            headers={**headers, "Idempotency-Key": f"final-{suffix}"},
            json={"expected_version": covered["version"], "actor_id": actor},
        )
        assert finalized.status_code == 200, finalized.text

    assert _balance(tenant["id"], store["id"], product["id"]) == Decimal("8.0000")
    movements = _sale_movements(tenant["id"], store["id"], product["id"])
    assert len(movements) == 1
    assert movements[0].quantity == Decimal("-2.0000")
    assert movements[0].previous_balance + movements[0].quantity == movements[0].new_balance


@pytest.mark.asyncio
async def test_a_counter_tab_takes_the_goods_out_of_the_stock():
    """Comanda de balcão, sem mesa: mesma finalização, mesma baixa."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        tenant, store, headers, actor, cash, suffix, assortment = await _tenant(client, "Comanda")
        product = await _stocked_product(client, headers, store, suffix, 1, stock=6, assortment=assortment)
        order_id = await _counter_order(client, headers, store, actor, suffix)
        await _launch(client, headers, order_id, product, 3, actor, f"item-{suffix}")

        negotiation = (await client.post("/api/v1/negotiations", headers={
            **headers, "Idempotency-Key": f"neg-{suffix}",
        }, json={"store_id": store["id"], "order_ids": [order_id], "actor_id": actor})).json()
        covered = await _cover_with_cash(
            client, headers, negotiation, actor, cash, float(negotiation["total_due"]),
        )
        finalized = await client.post(
            f"/api/v1/negotiations/{negotiation['id']}/finalize",
            headers={**headers, "Idempotency-Key": f"final-{suffix}"},
            json={"expected_version": covered["version"], "actor_id": actor},
        )
        assert finalized.status_code == 200, finalized.text

    assert _balance(tenant["id"], store["id"], product["id"]) == Decimal("3.0000")


@pytest.mark.asyncio
async def test_repeating_the_finalization_does_not_take_the_goods_out_twice():
    """Duplo clique e retry de rede não podem baixar duas vezes."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        tenant, store, headers, actor, cash, suffix, assortment = await _tenant(client, "Repete")
        product = await _stocked_product(client, headers, store, suffix, 1, stock=10, assortment=assortment)
        _, order_id = await _table_order(client, headers, store, actor, suffix)
        await _launch(client, headers, order_id, product, 4, actor, f"item-{suffix}")

        negotiation = (await client.post("/api/v1/negotiations", headers={
            **headers, "Idempotency-Key": f"neg-{suffix}",
        }, json={"store_id": store["id"], "order_ids": [order_id], "actor_id": actor})).json()
        covered = await _cover_with_cash(
            client, headers, negotiation, actor, cash, float(negotiation["total_due"]),
        )
        key = f"final-{suffix}"
        body = {"expected_version": covered["version"], "actor_id": actor}
        first = await client.post(
            f"/api/v1/negotiations/{negotiation['id']}/finalize",
            headers={**headers, "Idempotency-Key": key}, json=body,
        )
        second = await client.post(
            f"/api/v1/negotiations/{negotiation['id']}/finalize",
            headers={**headers, "Idempotency-Key": key}, json=body,
        )
        assert first.status_code == 200 and second.status_code == 200, second.text
        assert first.json()["sale_id"] == second.json()["sale_id"]

    assert _balance(tenant["id"], store["id"], product["id"]) == Decimal("6.0000")
    assert len(_sale_movements(tenant["id"], store["id"], product["id"])) == 1


@pytest.mark.asyncio
async def test_a_missing_balance_on_the_second_item_undoes_the_whole_finalization():
    """A operação composta é uma só: ou fecha inteira, ou não fecha.

    Sem estoque no segundo item, o esperado é que nada sobreviva: nem venda, nem
    baixa do primeiro item, nem pedido fechado, nem negociação finalizada. Lido
    por sessão nova, porque é o que ficou gravado que importa.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        tenant, store, headers, actor, cash, suffix, assortment = await _tenant(client, "Falha")
        disponivel = await _stocked_product(client, headers, store, suffix, 1, stock=10, assortment=assortment)
        vazio = await _stocked_product(client, headers, store, suffix, 2, stock=0, assortment=assortment)
        _, order_id = await _table_order(client, headers, store, actor, suffix)
        await _launch(client, headers, order_id, disponivel, 2, actor, f"item-a-{suffix}")
        await _launch(client, headers, order_id, vazio, 1, actor, f"item-b-{suffix}")

        negotiation = (await client.post("/api/v1/negotiations", headers={
            **headers, "Idempotency-Key": f"neg-{suffix}",
        }, json={"store_id": store["id"], "order_ids": [order_id], "actor_id": actor})).json()
        covered = await _cover_with_cash(
            client, headers, negotiation, actor, cash, float(negotiation["total_due"]),
        )
        refused = await client.post(
            f"/api/v1/negotiations/{negotiation['id']}/finalize",
            headers={**headers, "Idempotency-Key": f"final-{suffix}"},
            json={"expected_version": covered["version"], "actor_id": actor},
        )
        assert refused.status_code == 400, refused.text
        assert "Saldo insuficiente" in refused.text

    assert _balance(tenant["id"], store["id"], disponivel["id"]) == Decimal("10.0000"), (
        "o primeiro item ficou baixado depois de a finalização ter sido recusada"
    )
    assert _sale_movements(tenant["id"], store["id"], disponivel["id"]) == []

    with Session(engine) as session:
        set_tenant_db_context(
            session, uuid.UUID(tenant["id"]), uuid.UUID(store["id"]), None,
        )
        assert session.exec(select(Sale).where(
            Sale.tenant_id == uuid.UUID(tenant["id"]),
        )).all() == [], "sobrou uma venda de uma finalização que falhou"
        order = session.get(Order, uuid.UUID(order_id))
        assert order.status != OrderStatusEnum.CLOSED, "o pedido foi fechado mesmo assim"
        negotiacao = session.get(CheckoutNegotiation, uuid.UUID(negotiation["id"]))
        assert negotiacao.status != CheckoutNegotiationStatusEnum.FINALIZED


@pytest.mark.asyncio
async def test_a_sale_on_credit_still_takes_the_goods_out_of_the_stock():
    """Crediário muda quando o dinheiro entra, não se a mercadoria saiu.

    A venda a prazo sai como `COMPLETED` em vez de `PAID`. Deixar de baixar por
    causa do prazo seria permitir saída física sem controle.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        tenant, store, headers, actor, _cash, suffix, assortment = await _tenant(client, "Crediario")
        product = await _stocked_product(client, headers, store, suffix, 1, stock=10, assortment=assortment)
        _, order_id = await _table_order(client, headers, store, actor, suffix)
        await _launch(client, headers, order_id, product, 5, actor, f"item-{suffix}")

        customer = (await client.post("/api/v1/sales/customers", headers=headers, json={
            "name": "Cliente do fiado", "document": f"DOC-{suffix}",
        })).json()
        policy = await client.put(
            f"/api/v1/receivables/customers/{customer['id']}/policy",
            headers=headers,
            json={"credit_limit": 1000, "terms_days": 30, "actor_id": actor},
        )
        assert policy.status_code == 200, policy.text

        negotiation = (await client.post("/api/v1/negotiations", headers={
            **headers, "Idempotency-Key": f"neg-{suffix}",
        }, json={"store_id": store["id"], "order_ids": [order_id], "actor_id": actor})).json()
        issued = await client.post(
            f"/api/v1/receivables/negotiations/{negotiation['id']}/issue",
            headers={**headers, "Idempotency-Key": f"issue-{suffix}"},
            json={"customer_id": customer["id"], "expected_version": negotiation["version"],
                  "actor_id": actor, "reason": "Venda a prazo"},
        )
        assert issued.status_code == 200, issued.text
        # `issue_and_finalize` já finaliza a negociação: emitir o título é o que
        # cobre a conta, e a venda a prazo se fecha ali mesmo.

    assert _balance(tenant["id"], store["id"], product["id"]) == Decimal("5.0000")
    with Session(engine) as session:
        set_tenant_db_context(
            session, uuid.UUID(tenant["id"]), uuid.UUID(store["id"]), None,
        )
        sale = session.exec(select(Sale).where(
            Sale.tenant_id == uuid.UUID(tenant["id"]),
        )).one()
        assert sale.status == SaleStatusEnum.COMPLETED


@pytest.mark.asyncio
async def test_a_service_sold_at_the_table_moves_no_stock():
    """Serviço não tem saldo físico, e a finalização não inventa um."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        tenant, store, headers, actor, cash, suffix, assortment = await _tenant(client, "Servico")
        service = (await client.post("/api/v1/catalog/products", headers=headers, json={
            "name": "Couvert artístico", "sku": f"SRV-{suffix}",
            "item_type": "SERVICE", "tracks_inventory": False,
        })).json()
        await client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": service["id"], "store_id": store["id"],
            "cost_price": 0, "sale_price": 15,
        })
        await _publish(client, headers, assortment, service, 1)
        _, order_id = await _table_order(client, headers, store, actor, suffix)
        await _launch(client, headers, order_id, service, 1, actor, f"item-{suffix}")

        negotiation = (await client.post("/api/v1/negotiations", headers={
            **headers, "Idempotency-Key": f"neg-{suffix}",
        }, json={"store_id": store["id"], "order_ids": [order_id], "actor_id": actor})).json()
        covered = await _cover_with_cash(
            client, headers, negotiation, actor, cash, float(negotiation["total_due"]),
        )
        finalized = await client.post(
            f"/api/v1/negotiations/{negotiation['id']}/finalize",
            headers={**headers, "Idempotency-Key": f"final-{suffix}"},
            json={"expected_version": covered["version"], "actor_id": actor},
        )
        assert finalized.status_code == 200, finalized.text

    assert _sale_movements(tenant["id"], store["id"], service["id"]) == []


def _rows(model, tenant_id, store_id, **where):
    with Session(engine) as session:
        set_tenant_db_context(session, uuid.UUID(tenant_id), uuid.UUID(store_id), None)
        query = select(model).where(model.tenant_id == uuid.UUID(tenant_id))
        for field, value in where.items():
            query = query.where(getattr(model, field) == value)
        return session.exec(query).all()


@pytest.mark.asyncio
async def test_money_already_received_survives_a_failed_finalization():
    """Falta de estoque desfaz a finalização, nunca o recebimento anterior.

    O pagamento foi confirmado antes, em transação própria: a intenção ficou
    `CONFIRMED` e o caixa registrou a entrada. Se a finalização falhar por falta
    de mercadoria, é ela que volta atrás. Apagar o recebimento junto seria fazer
    sumir dinheiro que entrou no caixa, e o cliente pagou.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        tenant, store, headers, actor, cash, suffix, assortment = await _tenant(client, "Retoma")
        disponivel = await _stocked_product(
            client, headers, store, suffix, 1, stock=10, assortment=assortment,
        )
        vazio = await _stocked_product(
            client, headers, store, suffix, 2, stock=0, assortment=assortment,
        )
        _, order_id = await _table_order(client, headers, store, actor, suffix)
        await _launch(client, headers, order_id, disponivel, 2, actor, f"item-a-{suffix}")
        await _launch(client, headers, order_id, vazio, 1, actor, f"item-b-{suffix}")

        negotiation = (await client.post("/api/v1/negotiations", headers={
            **headers, "Idempotency-Key": f"neg-{suffix}",
        }, json={"store_id": store["id"], "order_ids": [order_id], "actor_id": actor})).json()
        covered = await _cover_with_cash(
            client, headers, negotiation, actor, cash, float(negotiation["total_due"]),
        )

        refused = await client.post(
            f"/api/v1/negotiations/{negotiation['id']}/finalize",
            headers={**headers, "Idempotency-Key": f"final-{suffix}"},
            json={"expected_version": covered["version"], "actor_id": actor},
        )
        assert refused.status_code == 400, refused.text

        # O recebimento continua de pé: intenção confirmada e caixa com a entrada.
        intents = _rows(PaymentIntent, tenant["id"], store["id"])
        confirmados = [i for i in intents if i.status == PaymentIntentStatusEnum.CONFIRMED]
        assert len(confirmados) == 1, "a recusa desfez o pagamento já confirmado"
        entradas = [
            m for m in _rows(CashMovement, tenant["id"], store["id"])
            if m.movement_type == CashMovementTypeEnum.SALE_PAYMENT
        ]
        assert len(entradas) == 1, "a entrada de caixa sumiu ou foi duplicada"

        # A finalização, essa sim, não deixou nada.
        assert _rows(Sale, tenant["id"], store["id"]) == []
        assert _rows(Payment, tenant["id"], store["id"]) == []
        assert _balance(tenant["id"], store["id"], disponivel["id"]) == Decimal("10.0000")

        # Resolvida a falta, a conta fecha — e fecha uma vez só.
        reposto = await client.post("/api/v1/inventory/adjust", headers=headers, json={
            "store_id": store["id"], "product_id": vazio["id"], "actor_id": actor,
            "movement_type": "PURCHASE", "quantity": 5,
            "reason": "Reposição para concluir a conta",
        })
        assert reposto.status_code == 200, reposto.text

        atual = (await client.get(
            f"/api/v1/negotiations/{negotiation['id']}", headers=headers,
        )).json()
        assert atual["status"] == "COVERED", atual["status"]
        finalizada = await client.post(
            f"/api/v1/negotiations/{negotiation['id']}/finalize",
            headers={**headers, "Idempotency-Key": f"final-2-{suffix}"},
            json={"expected_version": atual["version"], "actor_id": actor},
        )
        assert finalizada.status_code == 200, finalizada.text

    # Uma venda, um pagamento registrado, uma entrada de caixa, uma baixa de cada item.
    assert len(_rows(Sale, tenant["id"], store["id"])) == 1
    assert len(_rows(Payment, tenant["id"], store["id"])) == 1, "o cliente foi cobrado duas vezes"
    entradas = [
        m for m in _rows(CashMovement, tenant["id"], store["id"])
        if m.movement_type == CashMovementTypeEnum.SALE_PAYMENT
    ]
    assert len(entradas) == 1, "a entrada de caixa foi contada duas vezes"
    assert len(_sale_movements(tenant["id"], store["id"], disponivel["id"])) == 1
    assert len(_sale_movements(tenant["id"], store["id"], vazio["id"])) == 1
    assert _balance(tenant["id"], store["id"], disponivel["id"]) == Decimal("8.0000")
    assert _balance(tenant["id"], store["id"], vazio["id"]) == Decimal("4.0000")

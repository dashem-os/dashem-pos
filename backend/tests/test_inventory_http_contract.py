"""Contagem e devolução pelo HTTP autenticado, com permissão de verdade.

Chamar a função da rota com uma sessão real prova o serviço e o formato da
resposta. Não prova a rota: fora do caminho HTTP não passam a autenticação, a
resolução de permissão por caminho, a validação do corpo pelo Pydantic, nem o
cabeçalho de idempotência exigido pela assinatura. Essas quatro coisas só
aparecem quando a requisição atravessa o servidor.

Aqui elas atravessam. O servidor roda em `AUTH_MODE=test` — o modo isolado que a
CI já usa —, os tokens são assinados com `AUTH_TEST_SECRET`, e cada papel recebe
o seu: quem tem `inventory.count` conta, quem não tem é recusado com `403` pelo
motor de permissão, e não por uma checagem escrita dentro do teste.

Sem `AUTH_TEST_SECRET` e sem um servidor nesse modo, estes testes são pulados em
vez de fingir cobertura. Para rodar localmente:

    docker run --rm -e AUTH_MODE=test -e AUTH_TEST_SECRET=... -e ENVIRONMENT=test \\
      -e DATABASE_URL=... -p 8004:8000 <imagem> uvicorn app.main:app --host 0.0.0.0
    TEST_AUTH_BASE_URL=http://127.0.0.1:8004 AUTH_TEST_SECRET=... pytest tests/test_inventory_http_contract.py
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import jwt
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.context import TenantContext
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.catalog import InventoryBalance, MovementTypeEnum, Product
from app.models.identity import (
    AuthIdentity, Membership, MembershipStatusEnum, RoleEnum, Store, Tenant,
    TenantStatusEnum, User,
)
from app.models.payment import Payment, PaymentMethodEnum, PaymentStatusEnum
from app.models.platform import EntitlementStatusEnum, TenantCapability
from app.models.sale import Sale, SaleItem, SaleStatusEnum
from app.services import inventory_service, payment_service


BASE_URL = os.getenv("TEST_AUTH_BASE_URL", "")
SECRET = os.getenv("AUTH_TEST_SECRET", "")

pytestmark = pytest.mark.skipif(
    not (BASE_URL and SECRET),
    reason="exige um servidor em AUTH_MODE=test e o segredo de assinatura",
)


def _token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": subject, "aud": "authenticated", "iat": now, "exp": now + timedelta(minutes=10)},
        SECRET, algorithm="HS256",
    )


def _tenant_with(role: RoleEnum, *, stock: str = "10"):
    """Tenant, unidade, identidade com papel, e uma mercadoria com saldo."""
    suffix = uuid.uuid4().hex[:8]
    subject = str(uuid.uuid4())
    with Session(engine, expire_on_commit=False) as session:
        set_platform_db_context(session)
        tenant = Tenant(
            name=f"HTTP {suffix}", slug=f"http-{suffix}", status=TenantStatusEnum.ACTIVE,
        )
        session.add(tenant)
        session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"HTT-{suffix}")
        session.add(store)
        user = User(email=f"{role.value.lower()}-{suffix}@example.test", full_name="Pessoa")
        session.add(user)
        session.flush()
        session.add(AuthIdentity(
            user_id=user.id, provider="supabase", provider_subject=subject,
        ))
        session.add(Membership(
            user_id=user.id, tenant_id=tenant.id, store_id=None,
            role=role, status=MembershipStatusEnum.ACTIVE,
        ))
        for key in ("catalog", "inventory", "payments"):
            session.add(TenantCapability(
                tenant_id=tenant.id, key=key, enabled=True,
                status=EntitlementStatusEnum.ACTIVE,
            ))
        session.commit()

        context = TenantContext(
            tenant_id=tenant.id, store_id=store.id, user_id=user.id,
            auth_subject=subject,
        )
        set_tenant_db_context(session, tenant.id, store.id, user.id)
        product = Product(
            tenant_id=tenant.id, name=f"Mercadoria {suffix}", sku=f"HTT-{suffix}",
        )
        session.add(product)
        session.commit()
        if stock:
            inventory_service.adjust_stock(
                session=session, context=context, store_id=store.id,
                product_id=product.id, actor_id=user.id,
                movement_type=MovementTypeEnum.PURCHASE, quantity=Decimal(stock),
                reason="Recebimento",
            )
            session.commit()
        return {
            "tenant_id": str(tenant.id), "store_id": str(store.id),
            "user_id": str(user.id), "product_id": str(product.id),
            "context": context, "token": _token(subject),
        }


def _client(fixture) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE_URL, timeout=30, headers={
        "X-Tenant-ID": fixture["tenant_id"],
        "X-Store-ID": fixture["store_id"],
        "Authorization": f"Bearer {fixture['token']}",
    })


def _balance(fixture) -> Decimal:
    with Session(engine) as session:
        set_tenant_db_context(
            session, uuid.UUID(fixture["tenant_id"]), uuid.UUID(fixture["store_id"]), None,
        )
        row = session.exec(select(InventoryBalance).where(
            InventoryBalance.product_id == uuid.UUID(fixture["product_id"]),
        )).first()
        return Decimal("0") if row is None else Decimal(str(row.quantity))


def _version(fixture) -> int:
    with Session(engine) as session:
        set_tenant_db_context(
            session, uuid.UUID(fixture["tenant_id"]), uuid.UUID(fixture["store_id"]), None,
        )
        row = session.exec(select(InventoryBalance).where(
            InventoryBalance.product_id == uuid.UUID(fixture["product_id"]),
        )).first()
        return 0 if row is None else row.version


# ------------------------------------------------------------------ contagem

@pytest.mark.asyncio
async def test_a_manager_counts_the_shelf_over_http():
    fixture = _tenant_with(RoleEnum.MANAGER, stock="10")
    async with _client(fixture) as client:
        response = await client.post(
            "/api/v1/inventory/count",
            headers={"Idempotency-Key": f"count-{uuid.uuid4().hex[:10]}"},
            json={
                "store_id": fixture["store_id"], "product_id": fixture["product_id"],
                "actor_id": fixture["user_id"], "counted_quantity": 8,
                "expected_version": _version(fixture), "reason": "Conferência do dia",
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(str(body["balance"]["quantity"])) == Decimal("8.0000")
    assert Decimal(str(body["count"]["difference"])) == Decimal("-2.0000")
    assert _balance(fixture) == Decimal("8.0000")


@pytest.mark.asyncio
async def test_a_cashier_is_refused_by_the_permission_engine_over_http():
    """A recusa vem do motor de permissão, não de um `if` dentro do teste."""
    fixture = _tenant_with(RoleEnum.CASHIER, stock="10")
    async with _client(fixture) as client:
        response = await client.post(
            "/api/v1/inventory/count",
            headers={"Idempotency-Key": f"count-{uuid.uuid4().hex[:10]}"},
            json={
                "store_id": fixture["store_id"], "product_id": fixture["product_id"],
                "actor_id": fixture["user_id"], "counted_quantity": 8,
                "expected_version": _version(fixture),
            },
        )
    assert response.status_code == 403, response.text
    assert _balance(fixture) == Decimal("10.0000")


@pytest.mark.asyncio
async def test_without_a_token_the_route_answers_401():
    fixture = _tenant_with(RoleEnum.MANAGER, stock="10")
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        response = await client.post(
            "/api/v1/inventory/count",
            headers={
                "X-Tenant-ID": fixture["tenant_id"], "X-Store-ID": fixture["store_id"],
                "Idempotency-Key": f"count-{uuid.uuid4().hex[:10]}",
            },
            json={
                "store_id": fixture["store_id"], "product_id": fixture["product_id"],
                "actor_id": fixture["user_id"], "counted_quantity": 8,
                "expected_version": 1,
            },
        )
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_the_route_requires_the_idempotency_header():
    """A assinatura exige a chave; sem ela é o servidor que recusa, não o serviço."""
    fixture = _tenant_with(RoleEnum.MANAGER, stock="10")
    async with _client(fixture) as client:
        response = await client.post(
            "/api/v1/inventory/count",
            json={
                "store_id": fixture["store_id"], "product_id": fixture["product_id"],
                "actor_id": fixture["user_id"], "counted_quantity": 8,
                "expected_version": _version(fixture),
            },
        )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_a_negative_count_is_refused_by_the_body_validation():
    """`counted_quantity` não negativo é contrato da rota, e o Pydantic o aplica."""
    fixture = _tenant_with(RoleEnum.MANAGER, stock="10")
    async with _client(fixture) as client:
        response = await client.post(
            "/api/v1/inventory/count",
            headers={"Idempotency-Key": f"count-{uuid.uuid4().hex[:10]}"},
            json={
                "store_id": fixture["store_id"], "product_id": fixture["product_id"],
                "actor_id": fixture["user_id"], "counted_quantity": -1,
                "expected_version": _version(fixture),
            },
        )
    assert response.status_code == 422, response.text
    assert _balance(fixture) == Decimal("10.0000")


@pytest.mark.asyncio
async def test_a_stale_version_conflicts_over_http_and_carries_the_current_state():
    fixture = _tenant_with(RoleEnum.MANAGER, stock="10")
    version = _version(fixture)
    async with _client(fixture) as client:
        entrada = await client.post(
            "/api/v1/inventory/adjust",
            json={
                "store_id": fixture["store_id"], "product_id": fixture["product_id"],
                "actor_id": fixture["user_id"], "movement_type": "PURCHASE",
                "quantity": 3, "reason": "Entrou durante a contagem",
            },
        )
        assert entrada.status_code == 200, entrada.text

        response = await client.post(
            "/api/v1/inventory/count",
            headers={"Idempotency-Key": f"count-{uuid.uuid4().hex[:10]}"},
            json={
                "store_id": fixture["store_id"], "product_id": fixture["product_id"],
                "actor_id": fixture["user_id"], "counted_quantity": 10,
                "expected_version": version,
            },
        )
    assert response.status_code == 409, response.text
    detalhe = response.json()["detail"]
    assert detalhe["current_version"] == version + 1
    assert detalhe["current_quantity"] == "13.0000"
    assert _balance(fixture) == Decimal("13.0000")


@pytest.mark.asyncio
async def test_resending_the_same_count_over_http_moves_the_stock_once():
    fixture = _tenant_with(RoleEnum.MANAGER, stock="10")
    key = f"count-{uuid.uuid4().hex[:10]}"
    corpo = {
        "store_id": fixture["store_id"], "product_id": fixture["product_id"],
        "actor_id": fixture["user_id"], "counted_quantity": 7,
        "expected_version": _version(fixture),
    }
    async with _client(fixture) as client:
        primeira = await client.post(
            "/api/v1/inventory/count", headers={"Idempotency-Key": key}, json=corpo,
        )
        segunda = await client.post(
            "/api/v1/inventory/count", headers={"Idempotency-Key": key}, json=corpo,
        )
    assert primeira.status_code == 200 and segunda.status_code == 200, segunda.text
    assert primeira.json()["count"]["id"] == segunda.json()["count"]["id"]
    assert _balance(fixture) == Decimal("7.0000")


# ------------------------------------------------------------------- acervo

@pytest.mark.asyncio
async def test_the_holdings_route_lists_goods_nobody_published():
    """O acervo é físico: publicação decide onde vende, não se existe."""
    fixture = _tenant_with(RoleEnum.MANAGER, stock="4")
    async with _client(fixture) as client:
        response = await client.get(
            f"/api/v1/inventory/holdings?store_id={fixture['store_id']}",
        )
    assert response.status_code == 200, response.text
    linhas = response.json()
    achado = [linha for linha in linhas if linha["product_id"] == fixture["product_id"]]
    assert len(achado) == 1, "mercadoria com saldo sumiu do acervo por não estar publicada"
    assert Decimal(str(achado[0]["quantity"])) == Decimal("4.0000")
    assert achado[0]["has_minimum"] is False


# ----------------------------------------------------------------- devolução

def _sale_for(fixture, quantity: str = "3"):
    """Uma venda quitada nesta unidade, com a baixa registrada."""
    context = fixture["context"]
    with Session(engine, expire_on_commit=False) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
        total = Decimal(quantity)
        sale = Sale(
            tenant_id=context.tenant_id, store_id=context.store_id,
            status=SaleStatusEnum.AWAITING_PAYMENT, seller_id=context.user_id,
            gross_total=total, net_total=total,
        )
        session.add(sale)
        session.flush()
        item = SaleItem(
            tenant_id=context.tenant_id, sale_id=sale.id,
            product_id=uuid.UUID(fixture["product_id"]),
            product_name="Mercadoria", sku="HTT", tracks_inventory_snapshot=True,
            unit_price=Decimal("1"), quantity=total, gross_total=total, net_total=total,
        )
        session.add(item)
        payment = Payment(
            tenant_id=context.tenant_id, store_id=context.store_id, sale_id=sale.id,
            method=PaymentMethodEnum.PIX, status=PaymentStatusEnum.PENDING, amount=total,
        )
        session.add(payment)
        session.commit()
        payment_service.confirm_payment(
            session=session, context=context, payment_id=payment.id,
            actor_id=context.user_id,
        )
        return str(item.id)


@pytest.mark.asyncio
async def test_a_return_over_http_puts_the_goods_back():
    fixture = _tenant_with(RoleEnum.MANAGER, stock="10")
    sale_item_id = _sale_for(fixture, "3")
    async with _client(fixture) as client:
        response = await client.post(
            "/api/v1/sales/returns",
            headers={"Idempotency-Key": f"return-{uuid.uuid4().hex[:10]}"},
            json={
                "sale_item_id": sale_item_id, "actor_id": fixture["user_id"],
                "quantity": 2, "condition": "RESALEABLE",
                "destination": "SELLABLE_STOCK", "reason": "Cliente devolveu",
            },
        )
    assert response.status_code == 200, response.text
    assert _balance(fixture) == Decimal("9.0000")


@pytest.mark.asyncio
async def test_a_return_over_http_respects_the_ceiling():
    fixture = _tenant_with(RoleEnum.MANAGER, stock="10")
    sale_item_id = _sale_for(fixture, "3")
    async with _client(fixture) as client:
        response = await client.post(
            "/api/v1/sales/returns",
            headers={"Idempotency-Key": f"return-{uuid.uuid4().hex[:10]}"},
            json={
                "sale_item_id": sale_item_id, "actor_id": fixture["user_id"],
                "quantity": 4, "condition": "RESALEABLE",
                "destination": "SELLABLE_STOCK",
            },
        )
    assert response.status_code == 400, response.text
    assert "acima do vendido" in response.json()["detail"]
    assert _balance(fixture) == Decimal("7.0000")


@pytest.mark.asyncio
async def test_an_incoherent_condition_is_refused_over_http():
    fixture = _tenant_with(RoleEnum.MANAGER, stock="10")
    sale_item_id = _sale_for(fixture, "3")
    async with _client(fixture) as client:
        response = await client.post(
            "/api/v1/sales/returns",
            headers={"Idempotency-Key": f"return-{uuid.uuid4().hex[:10]}"},
            json={
                "sale_item_id": sale_item_id, "actor_id": fixture["user_id"],
                "quantity": 1, "condition": "UNFIT", "destination": "SELLABLE_STOCK",
            },
        )
    assert response.status_code == 400, response.text
    assert _balance(fixture) == Decimal("7.0000")


@pytest.mark.asyncio
async def test_a_cashier_cannot_return_over_http():
    fixture = _tenant_with(RoleEnum.CASHIER, stock="10")
    sale_item_id = _sale_for(fixture, "2")
    async with _client(fixture) as client:
        response = await client.post(
            "/api/v1/sales/returns",
            headers={"Idempotency-Key": f"return-{uuid.uuid4().hex[:10]}"},
            json={
                "sale_item_id": sale_item_id, "actor_id": fixture["user_id"],
                "quantity": 1, "condition": "RESALEABLE",
                "destination": "SELLABLE_STOCK",
            },
        )
    assert response.status_code == 403, response.text
    assert _balance(fixture) == Decimal("8.0000")


@pytest.mark.asyncio
async def test_a_forged_actor_is_refused_over_http():
    """O ator vem do token; alegar outro é recusado pelo servidor."""
    fixture = _tenant_with(RoleEnum.MANAGER, stock="10")
    sale_item_id = _sale_for(fixture, "2")
    async with _client(fixture) as client:
        response = await client.post(
            "/api/v1/sales/returns",
            headers={"Idempotency-Key": f"return-{uuid.uuid4().hex[:10]}"},
            json={
                "sale_item_id": sale_item_id, "actor_id": str(uuid.uuid4()),
                "quantity": 1, "condition": "RESALEABLE",
                "destination": "SELLABLE_STOCK",
            },
        )
    assert response.status_code == 403, response.text
    assert _balance(fixture) == Decimal("8.0000")

"""Travessia autenticada de execuo e retomada de publicao de catlogo (S13.2).

Valida os requisitos da fatia delimitada:
1. Conexo do executor s aes de executar e retomar publicao pela API.
2. Autorizao rigorosa por papis e permisses:
   - Gestora autorizada (MANAGER com channel.catalog.manage) executa e retoma.
   - Leitora sem permisso de ao (DENY em channel.catalog.manage) tem leitura liberada (GET /catalog)
     mas  estritamente recusada com 403 em qualquer ao de mutao (POST /publications,
     POST /publications/{id}/execute, POST /publications/{id}/resume, etc.), sem vazamento do nome da permisso.
3. A interface e a API refletem estados confirmados, pendncias e erros sem afirmar
   publicao antes da confirmao do conector.
4. Tratamento de falhas parciais e retomada monotnica sob conector de referncia.
5. Preservao da venda local no PDV durante indisponibilidade / queda do conector externo
   (zero travamentos, zero conexes retidas no pool).
6. Preservao dos trs nichos: alimentao (FOOD_SERVICE), varejo (RETAIL) e revenda de beleza (BEAUTY_RESELLER)
   sem imposio de dependncias de cozinha/mesas para varejo e beleza.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import re
import threading
import time
import uuid
from typing import Optional

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.main import app
from app.models.catalog import Product, ProductPrice, SalesChannel, SalesChannelTypeEnum
from app.models.channel_catalog import (
    CatalogEntityTypeEnum,
    ChannelCatalogMapping,
    ChannelCatalogOffer,
    ChannelPublicationBatch,
    ChannelPublicationItem,
    PublicationItemStatusEnum,
    PublicationStatusEnum,
)
from app.models.channel_hub import MerchantConnection, MerchantConnectionStatusEnum
from app.models.identity import (
    AuthIdentity,
    Membership,
    MembershipStatusEnum,
    PermissionGrant,
    PermissionGrantEffectEnum,
    RoleEnum,
    Store,
    Tenant,
    TenantStatusEnum,
    User,
)
from app.models.platform import EntitlementStatusEnum, TenantCapability
from app.models.reliability import AuditEvent, OutboxEvent
from app.models.sale import SaleOperationModeEnum, SaleStatusEnum
from app.modules.channels.adapters.reference import ReferenceChannelAdapter
from app.modules.channels.contracts import CatalogPublicationItemResult
from app.services import inventory_service
from tests.activity_fixtures import (
    BEAUTY_RESELLER, FOOD_SERVICE, RETAIL, declare_contract_activities,
)

AUTH_SECRET = "walkthrough-secret-key-32-chars-minimum-test!!"


@pytest.fixture(autouse=True)
def configure_auth_and_connector(monkeypatch):
    """Configura o ambiente para autenticao Supabase JWT de teste e isolamento do conector."""
    monkeypatch.setattr(settings, "AUTH_MODE", "test")
    monkeypatch.setattr(settings, "AUTH_TEST_SECRET", AUTH_SECRET)
    ReferenceChannelAdapter.reset_registry()
    yield
    ReferenceChannelAdapter.reset_registry()


def _mint_jwt(subject: str, email: str) -> str:
    """Gera um JWT de teste assinado com AUTH_TEST_SECRET compatvel com o motor de autenticao."""
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": subject,
            "email": email,
            "aud": "authenticated",
            "iat": now,
            "exp": now + timedelta(hours=2),
            "aal": "aal1",
            "app_metadata": {"provider": "supabase"},
        },
        AUTH_SECRET,
        algorithm="HS256",
    )


def _assert_recusa_de_autoridade(detail: str, operacao: str, chave_proibida: str) -> None:
    """Garante que a recusa 403 seja amigável em português e não vaze a chave da permissão."""
    assert chave_proibida not in detail
    assert not re.search(r"[a-z]+\.[a-z]+", detail), f"chave de permissão vazou no detalhe: {detail}"
    assert "Peça a quem tem" in detail or "autorização" in detail or "autorizacao" in detail or "não tem" in detail


def _setup_walkthrough_environment():
    """Inicializa um tenant multiactividade com suporte aos 3 nichos e dois usurios: Gestora e Leitora."""
    suffix = uuid.uuid4().hex[:8]
    gestora_subject = f"sub-gestora-{suffix}"
    leitora_subject = f"sub-leitora-{suffix}"

    with Session(engine) as session:
        set_platform_db_context(session)

        # 1. Tenant ativo com os trs nichos de negcio contratados
        tenant = Tenant(
            name=f"Hub Walkthrough {suffix}",
            slug=f"hub-{suffix}",
            status=TenantStatusEnum.ACTIVE,
        )
        session.add(tenant)
        session.flush()

        # Usuria 1: Gestora autorizada (MANAGER com permisses normais)
        gestora_user = User(
            email=f"gestora-{suffix}@empresa.test",
            full_name="Gestora de Operaes",
            is_active=True,
        )
        session.add(gestora_user)
        session.flush()

        from app.models.platform import TenantContract
        session.add(TenantContract(
            tenant_id=tenant.id,
            version=1,
            status="ACTIVE",
            schema_version=4,
            capability_keys=["catalog", "delivery_orders", "counter_order", "inventory", "payments"],
            activity_keys=[FOOD_SERVICE, RETAIL, BEAUTY_RESELLER],
            limits={},
            limit_entitlements={},
            created_by=gestora_user.id,
            reason="Contrato de homologacao com 3 nichos e delivery_orders",
        ))

        # Loja Matriz
        store = Store(
            tenant_id=tenant.id,
            name="Loja Matriz Centro",
            code=f"MTZ-{suffix}",
            is_headquarters=True,
            is_active=True,
        )
        session.add(store)
        session.flush()

        session.add(AuthIdentity(
            user_id=gestora_user.id,
            provider="supabase",
            provider_subject=gestora_subject,
        ))
        gestora_mem = Membership(
            user_id=gestora_user.id,
            tenant_id=tenant.id,
            store_id=None,
            role=RoleEnum.MANAGER,
            status=MembershipStatusEnum.ACTIVE,
        )
        session.add(gestora_mem)

        # 5. Usuria 2: Leitora de Catlogo (MANAGER com DENY explcito em channel.catalog.manage)
        leitora_user = User(
            email=f"leitora-{suffix}@empresa.test",
            full_name="Leitora de Auditoria",
            is_active=True,
        )
        session.add(leitora_user)
        session.flush()
        session.add(AuthIdentity(
            user_id=leitora_user.id,
            provider="supabase",
            provider_subject=leitora_subject,
        ))
        leitora_mem = Membership(
            user_id=leitora_user.id,
            tenant_id=tenant.id,
            store_id=None,
            role=RoleEnum.MANAGER,
            status=MembershipStatusEnum.ACTIVE,
        )
        session.add(leitora_mem)
        session.flush()

        # Deny explcito na ao de gesto de catlogo do canal para a leitora
        session.add(PermissionGrant(
            tenant_id=tenant.id,
            membership_id=leitora_mem.id,
            permission_key="channel.catalog.manage",
            effect=PermissionGrantEffectEnum.DENY,
            reason="Papel restrito a auditoria e consulta do catlogo",
        ))

        # 6. Conexo do Channel Hub (Reference Channel - CONTRACT_TEST)
        sales_channel = SalesChannel(
            tenant_id=tenant.id,
            store_id=store.id,
            code=f"CH-REF-{suffix}",
            name="Canal de Homologao Referncia",
            channel_type=SalesChannelTypeEnum.MARKETPLACE,
        )
        session.add(sales_channel)
        session.flush()

        conn = MerchantConnection(
            tenant_id=tenant.id,
            store_id=store.id,
            channel_id=sales_channel.id,
            provider_code="CONTRACT_TEST",
            merchant_external_id=f"merch-{suffix}",
            status=MerchantConnectionStatusEnum.CONNECTED,
            service_actor_id=gestora_user.id,
            configured_by=gestora_user.id,
            idempotency_key=f"conn-{suffix}",
            request_hash=f"hash-{suffix}",
        )
        session.add(conn)
        session.flush()

        # 7. Produtos cobrindo os trs nichos de negcio
        # Nicho A: Alimentao (Food Service)
        prod_food = Product(tenant_id=tenant.id, name="Hambrguer Artesanal Duplo", sku=f"FOOD-{suffix}", unit="UN")
        # Nicho B: Varejo (Retail)
        prod_retail = Product(tenant_id=tenant.id, name="Furadeira de Impacto 500W", sku=f"RET-{suffix}", unit="UN")
        # Nicho C: Revenda de Beleza (Beauty Reseller)
        prod_beauty = Product(tenant_id=tenant.id, name="Batom Matte Longa Durao", sku=f"BEA-{suffix}", unit="UN")
        session.add_all([prod_food, prod_retail, prod_beauty])
        session.flush()

        # Preos de venda e custo
        for prod, price in ((prod_food, Decimal("45.00")), (prod_retail, Decimal("189.90")), (prod_beauty, Decimal("39.90"))):
            session.add(ProductPrice(
                tenant_id=tenant.id,
                store_id=store.id,
                product_id=prod.id,
                cost_price=price / Decimal("2"),
                sale_price=price,
            ))

        # Ofertas de catlogo para o canal
        offer_food = ChannelCatalogOffer(
            tenant_id=tenant.id, store_id=store.id, merchant_connection_id=conn.id,
            product_id=prod_food.id, price=Decimal("45.00"), available=True, stock_quantity=Decimal("30"),
            desired_version=1, published_version=0, last_publication_status=PublicationItemStatusEnum.PENDING,
        )
        offer_retail = ChannelCatalogOffer(
            tenant_id=tenant.id, store_id=store.id, merchant_connection_id=conn.id,
            product_id=prod_retail.id, price=Decimal("189.90"), available=True, stock_quantity=Decimal("15"),
            desired_version=1, published_version=0, last_publication_status=PublicationItemStatusEnum.PENDING,
        )
        offer_beauty = ChannelCatalogOffer(
            tenant_id=tenant.id, store_id=store.id, merchant_connection_id=conn.id,
            product_id=prod_beauty.id, price=Decimal("39.90"), available=True, stock_quantity=Decimal("50"),
            desired_version=1, published_version=0, last_publication_status=PublicationItemStatusEnum.PENDING,
        )
        session.add_all([offer_food, offer_retail, offer_beauty])

        # Mapeamentos externos
        for prod, ext in ((prod_food, f"EXT-FOOD-{suffix}"), (prod_retail, f"EXT-RET-{suffix}"), (prod_beauty, f"EXT-BEA-{suffix}")):
            session.add(ChannelCatalogMapping(
                tenant_id=tenant.id, store_id=store.id, merchant_connection_id=conn.id,
                entity_type=CatalogEntityTypeEnum.PRODUCT, internal_id=prod.id, external_id=ext,
            ))

        # Caixa e Sessão de Caixa aberta para operações de PDV local
        from app.models.identity import Register
        from app.models.payment import CashSession, CashSessionStatusEnum
        register = Register(
            tenant_id=tenant.id,
            store_id=store.id,
            name="Caixa 01 Balcão",
            code=f"CX1-{suffix}",
            is_active=True,
        )
        session.add(register)
        session.flush()

        cash_session = CashSession(
            tenant_id=tenant.id,
            store_id=store.id,
            register_id=register.id,
            operator_id=gestora_user.id,
            opened_at=datetime.utcnow(),
            opening_balance=Decimal("100.00"),
            status=CashSessionStatusEnum.OPEN,
        )
        session.add(cash_session)
        session.flush()

        session.commit()

        # Alimenta estoque inicial para garantir que venda local possa ocorrer
        set_tenant_db_context(session, tenant.id, store.id, gestora_user.id)
        from app.core.context import TenantContext
        ctx = TenantContext(tenant_id=tenant.id, store_id=store.id, user_id=gestora_user.id)
        from app.models.catalog import MovementTypeEnum
        for prod in (prod_food, prod_retail, prod_beauty):
            inventory_service.adjust_stock(
                session, ctx, store.id, prod.id, gestora_user.id,
                MovementTypeEnum.PURCHASE, Decimal("100"), reason="Estoque inicial de homologao"
            )
        session.commit()

        return {
            "tenant_id": tenant.id,
            "store_id": store.id,
            "connection_id": conn.id,
            "gestora_user_id": gestora_user.id,
            "leitora_user_id": leitora_user.id,
            "gestora_token": _mint_jwt(gestora_subject, gestora_user.email),
            "leitora_token": _mint_jwt(leitora_subject, leitora_user.email),
            "food_offer_id": offer_food.id,
            "retail_offer_id": offer_retail.id,
            "beauty_offer_id": offer_beauty.id,
            "prod_food_id": prod_food.id,
            "prod_retail_id": prod_retail.id,
            "prod_beauty_id": prod_beauty.id,
            "register_id": register.id,
            "cash_session_id": cash_session.id,
        }


def test_leitora_tem_leitura_livre_mas_mutacoes_sao_recusadas_com_403():
    """Valida que usuria leitora acessa a vitrine de catlogo, porm  barrada em todas as mutaes da API."""
    env = _setup_walkthrough_environment()
    client = TestClient(app)

    leitora_headers = {
        "Authorization": f"Bearer {env['leitora_token']}",
        "X-Tenant-ID": str(env["tenant_id"]),
        "X-Store-ID": str(env["store_id"]),
    }

    # 1. Leitora pode consultar o catlogo normalmente (GET /catalog -> 200)
    cat_res = client.get("/api/v1/channel-catalog/catalog", headers=leitora_headers)
    assert cat_res.status_code == 200, cat_res.text
    cat_data = cat_res.json()
    assert len(cat_data["offers"]) == 3
    offer_names = {o["product_name"] for o in cat_data["offers"]}
    assert "Hambrguer Artesanal Duplo" in offer_names
    assert "Furadeira de Impacto 500W" in offer_names
    assert "Batom Matte Longa Durao" in offer_names

    # 2. Leitora tenta criar mapeamento -> 403 Forbidden
    map_res = client.post(
        "/api/v1/channel-catalog/mappings",
        headers={**leitora_headers, "Idempotency-Key": f"map-deny-{uuid.uuid4()}"},
        json={
            "connection_id": str(env["connection_id"]),
            "entity_type": "PRODUCT",
            "internal_id": str(env["prod_food_id"]),
            "external_id": "EXT-PROIBIDO",
        },
    )
    assert map_res.status_code == 403, map_res.text
    _assert_recusa_de_autoridade(map_res.json()["detail"], "administrar catlogo", "channel.catalog.manage")

    # 3. Leitora tenta criar oferta -> 403 Forbidden
    offer_res = client.post(
        "/api/v1/channel-catalog/offers",
        headers={**leitora_headers, "Idempotency-Key": f"off-deny-{uuid.uuid4()}"},
        json={
            "connection_id": str(env["connection_id"]),
            "product_id": str(env["prod_food_id"]),
            "price": "50.00",
            "available": True,
        },
    )
    assert offer_res.status_code == 403
    _assert_recusa_de_autoridade(offer_res.json()["detail"], "administrar catlogo", "channel.catalog.manage")

    # 4. Leitora tenta criar lote de publicao -> 403 Forbidden
    batch_res = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**leitora_headers, "Idempotency-Key": f"pub-deny-{uuid.uuid4()}"},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["food_offer_id"])],
        },
    )
    assert batch_res.status_code == 403
    _assert_recusa_de_autoridade(batch_res.json()["detail"], "administrar catlogo", "channel.catalog.manage")

    # 5. Leitora tenta chamar endpoint de execuo diretamente -> 403 Forbidden
    fake_batch_id = uuid.uuid4()
    exec_res = client.post(
        f"/api/v1/channel-catalog/publications/{fake_batch_id}/execute",
        headers=leitora_headers,
        json={},
    )
    assert exec_res.status_code == 403
    _assert_recusa_de_autoridade(exec_res.json()["detail"], "administrar catlogo", "channel.catalog.manage")

    # 6. Leitora tenta chamar endpoint de retomada diretamente -> 403 Forbidden
    resume_res = client.post(
        f"/api/v1/channel-catalog/publications/{fake_batch_id}/resume",
        headers=leitora_headers,
        json={},
    )
    assert resume_res.status_code == 403
    _assert_recusa_de_autoridade(resume_res.json()["detail"], "administrar catlogo", "channel.catalog.manage")


def test_gestora_executa_publicacao_completa_e_confirma_estado_succeeded():
    """Valida fluxo da gestora autorizada: cria lote com os 3 nichos, executa na API e alcana SUCCEEDED."""
    env = _setup_walkthrough_environment()
    client = TestClient(app)

    gestora_headers = {
        "Authorization": f"Bearer {env['gestora_token']}",
        "X-Tenant-ID": str(env["tenant_id"]),
        "X-Store-ID": str(env["store_id"]),
    }

    # 1. Gestora cria lote com as 3 ofertas (Alimentao, Varejo, Beleza)
    batch_key = f"batch-walkthrough-{uuid.uuid4().hex[:8]}"
    create_res = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [
                str(env["food_offer_id"]),
                str(env["retail_offer_id"]),
                str(env["beauty_offer_id"]),
            ],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res.status_code == 200, create_res.text
    batch_data = create_res.json()
    batch_id = batch_data["batch"]["id"]
    assert batch_data["batch"]["status"] == "PENDING"
    assert len(batch_data["items"]) == 3
    assert all(it["status"] == "PENDING" for it in batch_data["items"])

    # 2. Gestora executa a publicao via API (POST /publications/{batch_id}/execute)
    exec_res = client.post(
        f"/api/v1/channel-catalog/publications/{batch_id}/execute",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert exec_res.status_code == 200, exec_res.text
    exec_data = exec_res.json()
    assert exec_data["batch"]["status"] == "SUCCEEDED"
    assert len(exec_data["items"]) == 3
    for it in exec_data["items"]:
        assert it["status"] == "SUCCEEDED"
        assert it["provider_result_ref"] is not None
        assert it["provider_result_ref"].startswith("ref-")

    # 3. Leitora e Gestora verificam que a vitrine reflete confirmao sem antecipao indevida
    for token in (env["gestora_token"], env["leitora_token"]):
        view_res = client.get(
            "/api/v1/channel-catalog/catalog",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Tenant-ID": str(env["tenant_id"]),
                "X-Store-ID": str(env["store_id"]),
            },
        )
        assert view_res.status_code == 200
        view_data = view_res.json()
        assert len(view_data["batches"]) >= 1
        published_batch = next(b for b in view_data["batches"] if b["id"] == batch_id)
        assert published_batch["status"] == "SUCCEEDED"
        for off in view_data["offers"]:
            assert off["published_version"] == 1
            assert off["last_publication_status"] == "SUCCEEDED"


def test_falha_parcial_exibe_erros_leitora_e_gestora_retoma_com_sucesso():
    """Valida cenrio de falha parcial no conector, exibio dos erros e retomada bem-sucedida pela gestora."""
    env = _setup_walkthrough_environment()
    client = TestClient(app)

    gestora_headers = {
        "Authorization": f"Bearer {env['gestora_token']}",
        "X-Tenant-ID": str(env["tenant_id"]),
        "X-Store-ID": str(env["store_id"]),
    }
    leitora_headers = {
        "Authorization": f"Bearer {env['leitora_token']}",
        "X-Tenant-ID": str(env["tenant_id"]),
        "X-Store-ID": str(env["store_id"]),
    }

    # 1. Gestora cria lote com Alimentao e Varejo
    batch_key = f"batch-partial-{uuid.uuid4().hex[:8]}"
    create_res = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["food_offer_id"]), str(env["retail_offer_id"])],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res.status_code == 200
    batch_data = create_res.json()
    batch_id = batch_data["batch"]["id"]
    items = batch_data["items"]

    # Identifica a chave de operao do item de varejo para simular falha
    retail_item = next(it for it in items if it["offer_id"] == str(env["retail_offer_id"]))
    food_item = next(it for it in items if it["offer_id"] == str(env["food_offer_id"]))

    ReferenceChannelAdapter.simulate_failure(
        operation_key=retail_item["provider_operation_key"],
        error_code="INVALID_RETAIL_CATEGORY",
        error_message="Categoria de ferramentas requer certificao no conector",
    )

    # 2. Gestora executa a publicao: resulta em PARTIAL
    exec_res = client.post(
        f"/api/v1/channel-catalog/publications/{batch_id}/execute",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert exec_res.status_code == 200
    exec_data = exec_res.json()
    assert exec_data["batch"]["status"] == "PARTIAL"

    statuses = {it["offer_id"]: it["status"] for it in exec_data["items"]}
    assert statuses[str(env["food_offer_id"])] == "SUCCEEDED"
    assert statuses[str(env["retail_offer_id"])] == "FAILED"

    # 3. Leitora consulta a interface: v status PARTIAL e os cdigos/mensagens de erro
    view_res = client.get("/api/v1/channel-catalog/catalog", headers=leitora_headers)
    assert view_res.status_code == 200
    view_batch = next(b for b in view_res.json()["batches"] if b["id"] == batch_id)
    assert view_batch["status"] == "PARTIAL"
    failed_item = next(it for it in view_batch["items"] if it["status"] == "FAILED")
    assert failed_item["error_code"] == "INVALID_RETAIL_CATEGORY"
    assert "certifica" in failed_item["error_message"]

    # 4. Leitora tenta retomar o lote -> 403 Forbidden
    resume_deny = client.post(
        f"/api/v1/channel-catalog/publications/{batch_id}/resume",
        headers=leitora_headers,
        json={},
    )
    assert resume_deny.status_code == 403
    _assert_recusa_de_autoridade(resume_deny.json()["detail"], "administrar catlogo", "channel.catalog.manage")

    # 5. Condio sanada no canal: limpa o erro simulado
    ReferenceChannelAdapter.reset_registry()

    # 6. Gestora executa a retomada (POST /publications/{batch_id}/resume)
    resume_ok = client.post(
        f"/api/v1/channel-catalog/publications/{batch_id}/resume",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert resume_ok.status_code == 200, resume_ok.text
    resumed_data = resume_ok.json()
    assert resumed_data["batch"]["status"] == "SUCCEEDED"
    assert all(it["status"] == "SUCCEEDED" for it in resumed_data["items"])

    # 7. Monotonicidade preservada: o item de alimentao j confirmado no sofreu regresso
    final_catalog = client.get("/api/v1/channel-catalog/catalog", headers=gestora_headers).json()
    food_off = next(o for o in final_catalog["offers"] if o["id"] == str(env["food_offer_id"]))
    retail_off = next(o for o in final_catalog["offers"] if o["id"] == str(env["retail_offer_id"]))
    assert food_off["last_publication_status"] == "SUCCEEDED"
    assert retail_off["last_publication_status"] == "SUCCEEDED"


def test_checkedout_zero_na_entrada_do_conector_em_execute_e_resume(monkeypatch):
    """Garante que chamadas HTTP autenticadas de execute e resume liberam a sessão da requisição,
    observando checkedout == 0 na entrada isolada dos métodos externos publish_catalog e check_catalog_status."""
    env = _setup_walkthrough_environment()
    client = TestClient(app)

    gestora_headers = {
        "Authorization": f"Bearer {env['gestora_token']}",
        "X-Tenant-ID": str(env["tenant_id"]),
        "X-Store-ID": str(env["store_id"]),
    }

    # 1. Teste de POST /publications/{id}/execute
    batch_key_exec = f"batch-chk-exec-{uuid.uuid4().hex[:8]}"
    create_res = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key_exec},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["food_offer_id"])],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res.status_code == 200
    batch_exec_id = create_res.json()["batch"]["id"]

    checkedout_at_publish = None
    orig_publish = ReferenceChannelAdapter.publish_catalog

    def _spy_publish(adapter_self, payload):
        nonlocal checkedout_at_publish
        checkedout_at_publish = engine.pool.checkedout()
        return orig_publish(adapter_self, payload)

    monkeypatch.setattr(ReferenceChannelAdapter, "publish_catalog", _spy_publish)

    exec_res = client.post(
        f"/api/v1/channel-catalog/publications/{batch_exec_id}/execute",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert exec_res.status_code == 200, exec_res.text
    assert checkedout_at_publish is not None
    assert checkedout_at_publish == 0, f"Pool reteve conexão na entrada de publish_catalog: checkedout={checkedout_at_publish}"

    # 2. Teste de POST /publications/{id}/resume
    batch_key_res = f"batch-chk-resume-{uuid.uuid4().hex[:8]}"
    create_res2 = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key_res},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["retail_offer_id"])],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res2.status_code == 200
    batch_resume_id = create_res2.json()["batch"]["id"]

    # Simula falha na primeira execução para deixar o lote em PARTIAL
    retail_op_key = create_res2.json()["items"][0]["provider_operation_key"]
    ReferenceChannelAdapter.simulate_failure(
        operation_key=retail_op_key,
        error_code="TRANSIENT_ERR",
        error_message="Erro temporário",
    )
    client.post(
        f"/api/v1/channel-catalog/publications/{batch_resume_id}/execute",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )

    # Restaura o conector
    ReferenceChannelAdapter.reset_registry()

    checkedout_at_check = None
    orig_check = ReferenceChannelAdapter.check_catalog_status

    def _spy_check(adapter_self, merchant_ext_id, op_keys):
        nonlocal checkedout_at_check
        checkedout_at_check = engine.pool.checkedout()
        return orig_check(adapter_self, merchant_ext_id, op_keys)

    monkeypatch.setattr(ReferenceChannelAdapter, "check_catalog_status", _spy_check)

    resume_res = client.post(
        f"/api/v1/channel-catalog/publications/{batch_resume_id}/resume",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert resume_res.status_code == 200, resume_res.text
    assert checkedout_at_check is not None
    assert checkedout_at_check == 0, f"Pool reteve conexão na entrada de check_catalog_status: checkedout={checkedout_at_check}"


def test_negativas_conexao_inativa_ou_sem_capacidade_preservam_estado_e_sem_chamada_externa(monkeypatch):
    """Valida que conexão não-CONNECTED ou adaptador sem CATALOG_PUBLICATION gera recusa HTTP 400 controlada,
    sem nenhum despacho externo, sem incremento de tentativas e sem concessão/PROCESSING pendente."""
    env = _setup_walkthrough_environment()
    client = TestClient(app)

    gestora_headers = {
        "Authorization": f"Bearer {env['gestora_token']}",
        "X-Tenant-ID": str(env["tenant_id"]),
        "X-Store-ID": str(env["store_id"]),
    }

    # Espiona chamadas externas
    publish_calls = 0
    orig_publish = ReferenceChannelAdapter.publish_catalog
    def _spy_publish(adapter_self, payload):
        nonlocal publish_calls
        publish_calls += 1
        return orig_publish(adapter_self, payload)
    monkeypatch.setattr(ReferenceChannelAdapter, "publish_catalog", _spy_publish)

    check_calls = 0
    orig_check = ReferenceChannelAdapter.check_catalog_status
    def _spy_check(adapter_self, merchant_ext_id, op_keys):
        nonlocal check_calls
        check_calls += 1
        return orig_check(adapter_self, merchant_ext_id, op_keys)
    monkeypatch.setattr(ReferenceChannelAdapter, "check_catalog_status", _spy_check)

    # 1. Conexão SUSPENDED
    with Session(engine) as session:
        set_platform_db_context(session)
        conn = session.get(MerchantConnection, env["connection_id"])
        conn.status = MerchantConnectionStatusEnum.SUSPENDED
        session.add(conn)
        session.commit()

    # Cria lote
    batch_key = f"batch-suspended-{uuid.uuid4().hex[:8]}"
    create_res = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["food_offer_id"])],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res.status_code == 200
    batch_id = create_res.json()["batch"]["id"]

    # Tentativa de executar com conexão SUSPENDED -> HTTP 400
    exec_res = client.post(
        f"/api/v1/channel-catalog/publications/{batch_id}/execute",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert exec_res.status_code == 400, exec_res.text
    assert "Conexão de canal não está ativa" in exec_res.json()["detail"]
    assert "SUSPENDED" in exec_res.json()["detail"]
    assert publish_calls == 0

    # Verifica no banco: lote permanece PENDING, sem lease, tentativa zerada
    with Session(engine) as session:
        set_platform_db_context(session)
        b = session.get(ChannelPublicationBatch, batch_id)
        assert b.status == PublicationStatusEnum.PENDING
        assert b.lease_token is None
        assert b.lease_expires_at is None
        it = session.exec(select(ChannelPublicationItem).where(ChannelPublicationItem.batch_id == batch_id)).first()
        assert it.attempt_count == 0

    # Tentativa de retomar com conexão SUSPENDED -> HTTP 400
    resume_res = client.post(
        f"/api/v1/channel-catalog/publications/{batch_id}/resume",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert resume_res.status_code == 400
    assert check_calls == 0
    assert publish_calls == 0

    # 2. Conexão reativada mas com provedor indisponível / sem capacidade CATALOG_PUBLICATION
    with Session(engine) as session:
        set_platform_db_context(session)
        conn = session.get(MerchantConnection, env["connection_id"])
        conn.status = MerchantConnectionStatusEnum.CONNECTED
        conn.provider_code = "INEXISTENT_OR_UNAVAILABLE"
        session.add(conn)
        session.commit()

    exec_res2 = client.post(
        f"/api/v1/channel-catalog/publications/{batch_id}/execute",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert exec_res2.status_code == 400, exec_res2.text
    assert "sem capacidade de catálogo" in exec_res2.json()["detail"] or "indisponível" in exec_res2.json()["detail"]
    assert publish_calls == 0

    resume_res2 = client.post(
        f"/api/v1/channel-catalog/publications/{batch_id}/resume",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert resume_res2.status_code == 400
    assert check_calls == 0
    assert publish_calls == 0

    # Estado no banco permaneceu imutável
    with Session(engine) as session:
        set_platform_db_context(session)
        b = session.get(ChannelPublicationBatch, batch_id)
        assert b.status == PublicationStatusEnum.PENDING
        assert b.lease_token is None
        assert b.lease_expires_at is None


def test_auditoria_e_outbox_transacionais_com_alteracoes_locais(monkeypatch):
    """Garante escrita atômica de intenção (Fase 1) e desfecho (Fase 3):
    - Intenção gravada antes do despacho; falha na intenção não despacha.
    - Desfecho gravado com os resultados monotônicos; falha no desfecho não persiste sucesso local;
      a retomada recupera a confirmação sem despachos extras."""
    env = _setup_walkthrough_environment()
    client = TestClient(app)

    gestora_headers = {
        "Authorization": f"Bearer {env['gestora_token']}",
        "X-Tenant-ID": str(env["tenant_id"]),
        "X-Store-ID": str(env["store_id"]),
    }

    # Cenário A: Execução normal grava intenção e desfecho no AuditEvent e OutboxEvent
    batch_key_a = f"batch-audit-a-{uuid.uuid4().hex[:8]}"
    create_res = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key_a},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["food_offer_id"])],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res.status_code == 200
    batch_a_id = uuid.UUID(create_res.json()["batch"]["id"])

    exec_res = client.post(
        f"/api/v1/channel-catalog/publications/{batch_a_id}/execute",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert exec_res.status_code == 200

    with Session(engine) as session:
        set_platform_db_context(session)
        # Intenção
        intent_audit = session.exec(select(AuditEvent).where(
            AuditEvent.action == "channel.catalog.execute",
        )).all()
        intent_for_batch = [a for a in intent_audit if str(batch_a_id) in a.payload]
        assert len(intent_for_batch) >= 1

        intent_outbox = session.exec(select(OutboxEvent).where(
            OutboxEvent.event_type == "channel.publication.intent_dispatched",
            OutboxEvent.aggregate_id == str(batch_a_id),
        )).all()
        assert len(intent_outbox) >= 1

        # Desfecho
        outcome_audit = session.exec(select(AuditEvent).where(
            AuditEvent.action == "channel.catalog.executed",
        )).all()
        outcome_for_batch = [a for a in outcome_audit if str(batch_a_id) in a.payload]
        assert len(outcome_for_batch) >= 1

        outcome_outbox = session.exec(select(OutboxEvent).where(
            OutboxEvent.event_type == "channel.publication.executed",
            OutboxEvent.aggregate_id == str(batch_a_id),
        )).all()
        assert len(outcome_outbox) >= 1

    # Cenário B: Falha na intenção não despacha ao canal
    batch_key_b = f"batch-audit-b-{uuid.uuid4().hex[:8]}"
    create_res_b = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key_b},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["retail_offer_id"])],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res_b.status_code == 200
    batch_b_id = uuid.UUID(create_res_b.json()["batch"]["id"])

    publish_called = False
    orig_publish = ReferenceChannelAdapter.publish_catalog
    def _spy_publish_b(adapter_self, payload):
        nonlocal publish_called
        publish_called = True
        return orig_publish(adapter_self, payload)
    monkeypatch.setattr(ReferenceChannelAdapter, "publish_catalog", _spy_publish_b)

    from app.services import reliability_service
    orig_write_audit = reliability_service.write_audit_and_outbox
    def _failing_intent_audit(*args, **kwargs):
        action = kwargs.get("action") or (args[4] if len(args) > 4 else None)
        if action == "channel.catalog.execute":
            raise RuntimeError("Falha proposital de banco na escrita da auditoria de intenção")
        return orig_write_audit(*args, **kwargs)
    monkeypatch.setattr(reliability_service, "write_audit_and_outbox", _failing_intent_audit)

    with pytest.raises(Exception):
        client.post(
            f"/api/v1/channel-catalog/publications/{batch_b_id}/execute",
            headers=gestora_headers,
            json={"actor_id": str(env["gestora_user_id"])},
        )
    # Prova: despacho NÃO ocorreu
    assert not publish_called

    with Session(engine) as session:
        set_platform_db_context(session)
        b = session.get(ChannelPublicationBatch, batch_b_id)
        assert b.status == PublicationStatusEnum.PENDING
        assert b.lease_token is None

    # Cenário C: Falha na auditoria do desfecho (channel.catalog.executed) após aplicação em memória
    # provoca rollback atômico: nem lote, nem itens, nem ofertas persistem sucesso local sem a trilha transacional.
    # Em seguida, a retomada recupera a confirmação sem despacho duplicado.
    monkeypatch.setattr(reliability_service, "write_audit_and_outbox", orig_write_audit)
    batch_key_c = f"batch-audit-c-{uuid.uuid4().hex[:8]}"
    create_res_c = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key_c},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["beauty_offer_id"])],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res_c.status_code == 200
    batch_c_id = uuid.UUID(create_res_c.json()["batch"]["id"])

    phase1_lease_token = None
    phase1_lease_expires_at = None
    publish_count_initial = 0
    def _count_initial_publish(adapter_self, payload):
        nonlocal publish_count_initial, phase1_lease_token, phase1_lease_expires_at
        publish_count_initial += 1
        with Session(engine) as s_spy:
            set_platform_db_context(s_spy)
            b_spy = s_spy.get(ChannelPublicationBatch, batch_c_id)
            phase1_lease_token = b_spy.lease_token
            phase1_lease_expires_at = b_spy.lease_expires_at
        return orig_publish(adapter_self, payload)
    monkeypatch.setattr(ReferenceChannelAdapter, "publish_catalog", _count_initial_publish)

    def _failing_executed_audit(*args, **kwargs):
        action = kwargs.get("action") or (args[4] if len(args) > 4 else None)
        if action == "channel.catalog.executed":
            raise RuntimeError("Falha proposital de banco na escrita da auditoria de desfecho da execução")
        return orig_write_audit(*args, **kwargs)
    monkeypatch.setattr(reliability_service, "write_audit_and_outbox", _failing_executed_audit)

    with pytest.raises(Exception) as exc_c:
        client.post(
            f"/api/v1/channel-catalog/publications/{batch_c_id}/execute",
            headers=gestora_headers,
            json={"actor_id": str(env["gestora_user_id"])},
        )
    assert "Falha proposital de banco na escrita da auditoria de desfecho da execução" in str(exc_c.value)
    assert publish_count_initial == 1, "Exatamente um despacho inicial deve ter ocorrido antes da falha da Fase 3"

    # Restaura write_audit_and_outbox original
    monkeypatch.setattr(reliability_service, "write_audit_and_outbox", orig_write_audit)

    # Verifica no banco: rollback atômico na Fase 3!
    # Lote permanece em PROCESSING (com lease da Fase 1), item permanece PENDING, oferta não avança versão
    with Session(engine) as session:
        set_platform_db_context(session)
        b = session.get(ChannelPublicationBatch, batch_c_id)
        assert b.status == PublicationStatusEnum.PROCESSING
        # A falha na Fase 3 desfaz sua tentativa de liberação do lease;
        # o lease concedido e persistido na Fase 1 permanece ativo no banco!
        assert b.lease_token is not None
        assert b.lease_token == phase1_lease_token, "O lease gravado na Fase 1 foi preservado após o rollback da Fase 3"
        assert b.lease_expires_at == phase1_lease_expires_at, "A expiração da Fase 1 foi preservada após o rollback da Fase 3"
        item_c = session.exec(select(ChannelPublicationItem).where(ChannelPublicationItem.batch_id == batch_c_id)).one()
        assert item_c.status == PublicationItemStatusEnum.PENDING
        offer_c = session.get(ChannelCatalogOffer, env["beauty_offer_id"])
        assert offer_c.published_version == 0
        outcome_audit = session.exec(select(AuditEvent).where(
            AuditEvent.action == "channel.catalog.executed",
        )).all()
        assert not any(str(batch_c_id) in a.payload for a in outcome_audit)
        outcome_outbox = session.exec(select(OutboxEvent).where(
            OutboxEvent.event_type == "channel.publication.executed",
            OutboxEvent.aggregate_id == str(batch_c_id),
        )).all()
        assert len(outcome_outbox) == 0

        # Expira o lease deixado pela Fase 1 para permitir retomada
        b.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        session.add(b)
        session.commit()

    # Conta chamadas a publish_catalog durante a retomada: DEVE SER 0 (recupera via check_catalog_status)
    publish_during_resume = 0
    def _count_publish(adapter_self, payload):
        nonlocal publish_during_resume
        publish_during_resume += 1
        return orig_publish(adapter_self, payload)
    monkeypatch.setattr(ReferenceChannelAdapter, "publish_catalog", _count_publish)

    resume_res = client.post(
        f"/api/v1/channel-catalog/publications/{batch_c_id}/resume",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert resume_res.status_code == 200, resume_res.text
    assert resume_res.json()["batch"]["status"] == "SUCCEEDED"
    assert publish_during_resume == 0, "Retomada não deve disparar novo envio quando o provedor já confirma"
    assert publish_count_initial + publish_during_resume == 1, "Exatamente um despacho inicial e zero adicionais"

    with Session(engine) as session:
        set_platform_db_context(session)
        resumed_outbox = session.exec(select(OutboxEvent).where(
            OutboxEvent.event_type == "channel.publication.resumed",
            OutboxEvent.aggregate_id == str(batch_c_id),
        )).all()
        assert len(resumed_outbox) >= 1
        offer_c_final = session.get(ChannelCatalogOffer, env["beauty_offer_id"])
        assert offer_c_final.published_version == 1

    # Cenário D: Falha na auditoria de desfecho da retomada (channel.catalog.resumed) provoca rollback;
    # confirmações recuperadas não são persistidas sem auditoria.
    batch_key_d = f"batch-audit-d-{uuid.uuid4().hex[:8]}"
    create_res_d = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key_d},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["retail_offer_id"])],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res_d.status_code == 200
    batch_d_id = uuid.UUID(create_res_d.json()["batch"]["id"])

    # Executa com simulação de erro no envio para deixar o lote em PARTIAL
    def _timeout_publish(adapter_self, payload):
        raise TimeoutError("Simulação de timeout no conector")
    monkeypatch.setattr(ReferenceChannelAdapter, "publish_catalog", _timeout_publish)

    client.post(
        f"/api/v1/channel-catalog/publications/{batch_d_id}/execute",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )

    # Restaura conector para permitir recuperação
    monkeypatch.setattr(ReferenceChannelAdapter, "publish_catalog", orig_publish)

    with Session(engine) as session:
        set_platform_db_context(session)
        item_d = session.exec(select(ChannelPublicationItem).where(ChannelPublicationItem.batch_id == batch_d_id)).one()
        op_key_d = item_d.provider_operation_key
        b_d = session.get(ChannelPublicationBatch, batch_d_id)
        b_d.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        session.add(b_d)
        session.commit()

    monkeypatch.setattr(
        ReferenceChannelAdapter,
        "check_catalog_status",
        lambda self, m_id, keys: tuple(
            CatalogPublicationItemResult(operation_key=k, status="SUCCEEDED", provider_result_ref=f"ref-d-{k}")
            for k in keys
        ),
    )

    # Injeta falha na auditoria de desfecho da retomada (channel.catalog.resumed)
    def _failing_resumed_audit(*args, **kwargs):
        action = kwargs.get("action") or (args[4] if len(args) > 4 else None)
        if action == "channel.catalog.resumed":
            raise RuntimeError("Falha proposital na escrita da auditoria do desfecho da retomada")
        return orig_write_audit(*args, **kwargs)
    monkeypatch.setattr(reliability_service, "write_audit_and_outbox", _failing_resumed_audit)

    with pytest.raises(Exception) as exc_d:
        client.post(
            f"/api/v1/channel-catalog/publications/{batch_d_id}/resume",
            headers=gestora_headers,
            json={"actor_id": str(env["gestora_user_id"])},
        )
    assert "Falha proposital na escrita da auditoria do desfecho da retomada" in str(exc_d.value)

    # Restaura write_audit_and_outbox original
    monkeypatch.setattr(reliability_service, "write_audit_and_outbox", orig_write_audit)

    # Verifica no banco: rollback atômico! Nem lote nem oferta foram confirmados
    with Session(engine) as session:
        set_platform_db_context(session)
        b_d_check = session.get(ChannelPublicationBatch, batch_d_id)
        assert b_d_check.status == PublicationStatusEnum.PROCESSING
        assert b_d_check.lease_token is not None
        item_d_check = session.exec(select(ChannelPublicationItem).where(ChannelPublicationItem.batch_id == batch_d_id)).one()
        assert item_d_check.status == PublicationItemStatusEnum.PENDING
        assert item_d_check.attempt_count == 1
        offer_d_check = session.get(ChannelCatalogOffer, env["retail_offer_id"])
        assert offer_d_check.published_version == 0
        outcome_audit_d = session.exec(select(AuditEvent).where(
            AuditEvent.action == "channel.catalog.resumed",
        )).all()
        assert not any(str(batch_d_id) in a.payload for a in outcome_audit_d), "Nenhum AuditEvent channel.catalog.resumed deve persistir após rollback"
        outcome_outbox_d = session.exec(select(OutboxEvent).where(
            OutboxEvent.event_type == "channel.publication.resumed",
            OutboxEvent.aggregate_id == str(batch_d_id),
        )).all()
        assert len(outcome_outbox_d) == 0, "Nenhum OutboxEvent channel.publication.resumed deve persistir após rollback"

        # Expira lease da retomada falhada para nova tentativa
        b_d_check.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        session.add(b_d_check)
        session.commit()

    # Agora retoma sem falha: confirma SUCCEEDED e grava auditoria
    resume_d_ok = client.post(
        f"/api/v1/channel-catalog/publications/{batch_d_id}/resume",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert resume_d_ok.status_code == 200
    assert resume_d_ok.json()["batch"]["status"] == "SUCCEEDED"

    with Session(engine) as session:
        set_platform_db_context(session)
        offer_d_final = session.get(ChannelCatalogOffer, env["retail_offer_id"])
        assert offer_d_final.published_version == 1
        resumed_audits_d = session.exec(select(AuditEvent).where(
            AuditEvent.action == "channel.catalog.resumed",
        )).all()
        assert any(str(batch_d_id) in a.payload for a in resumed_audits_d)

    # Cenário E (Achado 1 da revisão): Recuperação parcial confirma primeiro item com
    # auditoria/outbox do resultado antes do reenvio dos itens restantes; se o reenvio
    # posterior falhar, o item recuperado permanece SUCCEEDED e sua trilha de auditoria
    # existe de forma verificável.
    suffix_e = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        prod_e1 = Product(tenant_id=env["tenant_id"], name="Produto E1 Cenario", sku=f"E1-{suffix_e}", unit="UN")
        prod_e2 = Product(tenant_id=env["tenant_id"], name="Produto E2 Cenario", sku=f"E2-{suffix_e}", unit="UN")
        session.add_all([prod_e1, prod_e2])
        session.flush()

        session.add(ProductPrice(
            tenant_id=env["tenant_id"], store_id=env["store_id"], product_id=prod_e1.id,
            cost_price=Decimal("10.00"), sale_price=Decimal("20.00"),
        ))
        session.add(ProductPrice(
            tenant_id=env["tenant_id"], store_id=env["store_id"], product_id=prod_e2.id,
            cost_price=Decimal("15.00"), sale_price=Decimal("30.00"),
        ))
        session.add(ChannelCatalogMapping(
            tenant_id=env["tenant_id"], store_id=env["store_id"], merchant_connection_id=env["connection_id"],
            entity_type=CatalogEntityTypeEnum.PRODUCT, internal_id=prod_e1.id, external_id=f"EXT-E1-{suffix_e}",
        ))
        session.add(ChannelCatalogMapping(
            tenant_id=env["tenant_id"], store_id=env["store_id"], merchant_connection_id=env["connection_id"],
            entity_type=CatalogEntityTypeEnum.PRODUCT, internal_id=prod_e2.id, external_id=f"EXT-E2-{suffix_e}",
        ))
        offer_e1 = ChannelCatalogOffer(
            tenant_id=env["tenant_id"], store_id=env["store_id"], merchant_connection_id=env["connection_id"],
            product_id=prod_e1.id, price=Decimal("20.00"), available=True, stock_quantity=Decimal("10"),
            desired_version=1, published_version=0, last_publication_status=PublicationItemStatusEnum.PENDING,
        )
        offer_e2 = ChannelCatalogOffer(
            tenant_id=env["tenant_id"], store_id=env["store_id"], merchant_connection_id=env["connection_id"],
            product_id=prod_e2.id, price=Decimal("30.00"), available=True, stock_quantity=Decimal("10"),
            desired_version=1, published_version=0, last_publication_status=PublicationItemStatusEnum.PENDING,
        )
        session.add_all([offer_e1, offer_e2])
        session.commit()
        offer_e1_id = offer_e1.id
        offer_e2_id = offer_e2.id

    batch_key_e = f"batch-audit-e-{suffix_e}"
    create_res_e = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key_e},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(offer_e1_id), str(offer_e2_id)],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res_e.status_code == 200
    batch_e_id = uuid.UUID(create_res_e.json()["batch"]["id"])
    batch_e_items = create_res_e.json()["items"]
    e1_item = next(it for it in batch_e_items if it["offer_id"] == str(offer_e1_id))
    e2_item = next(it for it in batch_e_items if it["offer_id"] == str(offer_e2_id))

    # Deixa o lote em PARTIAL
    with Session(engine) as session:
        set_platform_db_context(session)
        b_e = session.get(ChannelPublicationBatch, batch_e_id)
        b_e.status = PublicationStatusEnum.PARTIAL
        session.add(b_e)
        session.commit()

    # O conector confirma o item E1, mas NÃO resolve o E2
    monkeypatch.setattr(
        ReferenceChannelAdapter,
        "check_catalog_status",
        lambda self, m_id, keys: tuple(
            [CatalogPublicationItemResult(operation_key=e1_item["provider_operation_key"], status="SUCCEEDED", provider_result_ref=f"ref-e1-recov-{suffix_e}")]
        ),
    )

    # Injeta falha na auditoria de intenção do reenvio (quando execute_publication for chamado na Etapa 4)
    def _fail_followup_execute_intent(*args, **kwargs):
        action = kwargs.get("action") or (args[4] if len(args) > 4 else None)
        if action == "channel.catalog.execute":
            raise RuntimeError("Falha controlada na auditoria do reenvio")
        return orig_write_audit(*args, **kwargs)
    monkeypatch.setattr(reliability_service, "write_audit_and_outbox", _fail_followup_execute_intent)

    with pytest.raises(Exception) as exc_e:
        client.post(
            f"/api/v1/channel-catalog/publications/{batch_e_id}/resume",
            headers=gestora_headers,
            json={"actor_id": str(env["gestora_user_id"])},
        )
    assert "Falha controlada na auditoria do reenvio" in str(exc_e.value)

    # Restaura write_audit_and_outbox original
    monkeypatch.setattr(reliability_service, "write_audit_and_outbox", orig_write_audit)

    # Prova do Achado 1:
    # O primeiro item foi recuperado como SUCCEEDED, a oferta avançou para version 1,
    # E a trilha de auditoria/outbox (channel.catalog.resumed / channel.publication.resumed)
    # FOI GRAVADA na mesma transação da recuperação parcial!
    with Session(engine) as session:
        set_platform_db_context(session)
        e1_item_db = session.get(ChannelPublicationItem, uuid.UUID(e1_item["id"]))
        e2_item_db = session.get(ChannelPublicationItem, uuid.UUID(e2_item["id"]))
        offer_e1_db = session.get(ChannelCatalogOffer, offer_e1_id)
        offer_e2_db = session.get(ChannelCatalogOffer, offer_e2_id)

        assert e1_item_db.status == PublicationItemStatusEnum.SUCCEEDED
        assert e2_item_db.status == PublicationItemStatusEnum.PENDING
        assert offer_e1_db.published_version == 1, "Oferta E1 avança estritamente de 0 para 1"
        assert offer_e2_db.published_version == 0, "Oferta E2 não recuperada permanece na versão 0"

        outbox_events_e = session.exec(select(OutboxEvent).where(
            OutboxEvent.aggregate_id == str(batch_e_id),
        )).all()
        audit_events_e = session.exec(select(AuditEvent).where(
            AuditEvent.tenant_id == env["tenant_id"],
        )).all()

        assert any(ev.event_type == "channel.publication.intent_resumed" for ev in outbox_events_e)
        resumed_outbox = [ev for ev in outbox_events_e if ev.event_type == "channel.publication.resumed"]
        assert len(resumed_outbox) == 1, "Exatamente um evento outbox de desfecho da recuperação parcial"
        ob_payload = json.loads(resumed_outbox[0].payload) if isinstance(resumed_outbox[0].payload, str) else resumed_outbox[0].payload
        assert ob_payload["batch_id"] == str(batch_e_id)
        assert ob_payload["conclusive_count"] == 1
        assert ob_payload["remaining_pending_count"] == 1
        assert ob_payload["status"] == "PARTIAL"

        assert any(aud.action == "channel.catalog.resume" and str(batch_e_id) in aud.payload for aud in audit_events_e)
        resumed_audits = [aud for aud in audit_events_e if aud.action == "channel.catalog.resumed" and str(batch_e_id) in aud.payload]
        assert len(resumed_audits) == 1, "Exatamente um evento de auditoria de desfecho da recuperação parcial"
        aud_payload = json.loads(resumed_audits[0].payload) if isinstance(resumed_audits[0].payload, str) else resumed_audits[0].payload
        assert aud_payload["batch_id"] == str(batch_e_id)
        assert aud_payload["conclusive_count"] == 1
        assert aud_payload["remaining_pending_count"] == 1
        assert aud_payload["status"] == "PARTIAL"


def test_retomada_de_processing_com_lease_ativo_retorna_409_e_expirado_prossegue():
    """Valida controle de concorrência na retomada:
    - Lote em PROCESSING com lease ativo recusa com 409 e mensagem clara.
    - Lote em PROCESSING com lease expirado assume nova concessão e prossegue normalmente."""
    env = _setup_walkthrough_environment()
    client = TestClient(app)

    gestora_headers = {
        "Authorization": f"Bearer {env['gestora_token']}",
        "X-Tenant-ID": str(env["tenant_id"]),
        "X-Store-ID": str(env["store_id"]),
    }

    # 1. Cria lote de publicação
    batch_key = f"batch-lease-test-{uuid.uuid4().hex[:8]}"
    create_res = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["food_offer_id"])],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res.status_code == 200
    batch_id = uuid.UUID(create_res.json()["batch"]["id"])

    # Registra item no conector de referência
    with Session(engine) as session:
        set_platform_db_context(session)
        it = session.exec(select(ChannelPublicationItem).where(ChannelPublicationItem.batch_id == batch_id)).first()
        op_key = it.provider_operation_key
        adapter = ReferenceChannelAdapter()
        from app.modules.channels.contracts import CatalogPublicationPayload, CatalogPublicationItemPayload
        adapter.publish_catalog(CatalogPublicationPayload(
            batch_id=str(batch_id),
            snapshot_version=1,
            merchant_external_id=f"merch-{env['tenant_id'].hex[:8]}",
            items=(CatalogPublicationItemPayload(
                operation_key=op_key,
                offer_id=str(env["food_offer_id"]),
                product_id=str(env["prod_food_id"]),
                desired_version=1,
                price=Decimal("45.00"),
                available=True,
                stock_quantity=Decimal("30"),
                sku="FOOD-SKU",
                title="Hamburguer",
            ),),
        ))

        # Coloca o lote em PROCESSING com concessão ativa
        b = session.get(ChannelPublicationBatch, batch_id)
        b.status = PublicationStatusEnum.PROCESSING
        b.lease_token = "active-external-lease-token"
        b.lease_expires_at = datetime.utcnow() + timedelta(minutes=5)
        session.add(b)
        session.commit()

    # 2. Retomada com lease ativo -> HTTP 409
    active_resume_res = client.post(
        f"/api/v1/channel-catalog/publications/{batch_id}/resume",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert active_resume_res.status_code == 409, active_resume_res.text
    assert "concessão ativa" in active_resume_res.json()["detail"] or "sendo executado" in active_resume_res.json()["detail"]

    # 3. Expira a concessão no banco de teste
    with Session(engine) as session:
        set_platform_db_context(session)
        b = session.get(ChannelPublicationBatch, batch_id)
        b.lease_expires_at = datetime.utcnow() - timedelta(seconds=10)
        session.add(b)
        session.commit()

    # 4. Retomada com lease expirado -> prossegue e conclui com SUCCEEDED
    expired_resume_res = client.post(
        f"/api/v1/channel-catalog/publications/{batch_id}/resume",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert expired_resume_res.status_code == 200, expired_resume_res.text
    assert expired_resume_res.json()["batch"]["status"] == "SUCCEEDED"


def test_venda_local_funciona_normalmente_durante_bloqueio_do_conector_externo(monkeypatch):
    """Substitui prova sequencial por concorrência real:
    - Bloqueia a chamada externa do conector via threading.Event;
    - Verifica checkedout == 0 na entrada do método externo;
    - Durante o bloqueio, conclui no PDV uma venda local completa de balcão (5 etapas:
      abertura de venda, itens de nichos variados, checkout, registro de pagamento e confirmação PAID),
      medindo a latência sob estrito limite temporal;
    - Libera o bloqueio e conclui a requisição externa."""
    env = _setup_walkthrough_environment()
    client = TestClient(app)

    gestora_headers = {
        "Authorization": f"Bearer {env['gestora_token']}",
        "X-Tenant-ID": str(env["tenant_id"]),
        "X-Store-ID": str(env["store_id"]),
    }

    # 1. Cria lote de publicação de catálogo
    batch_key = f"batch-concurrent-{uuid.uuid4().hex[:8]}"
    create_res = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["beauty_offer_id"])],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res.status_code == 200
    batch_id = create_res.json()["batch"]["id"]

    entered_event = threading.Event()
    release_event = threading.Event()
    checkedout_at_entry = None
    exec_holder = {}

    orig_publish = ReferenceChannelAdapter.publish_catalog

    def _blocking_publish(adapter_self, payload):
        nonlocal checkedout_at_entry
        # Conexão do pool deve estar em 0 na entrada do conector externo
        checkedout_at_entry = engine.pool.checkedout()
        entered_event.set()
        # Segura a execução externa até que a venda local seja concluída
        released = release_event.wait(timeout=10.0)
        if not released:
            raise TimeoutError("release_event expirou aguardando a venda local")
        return orig_publish(adapter_self, payload)

    monkeypatch.setattr(ReferenceChannelAdapter, "publish_catalog", _blocking_publish)

    # 2. Dispara a execução de catálogo em thread separada
    def _run_execute():
        try:
            res = client.post(
                f"/api/v1/channel-catalog/publications/{batch_id}/execute",
                headers=gestora_headers,
                json={"actor_id": str(env["gestora_user_id"])},
            )
            exec_holder["response"] = res
        except Exception as exc:
            exec_holder["error"] = exc

    t = threading.Thread(target=_run_execute)
    t.start()

    # 3. Aguarda o conector externo ser alcançado
    entered = entered_event.wait(timeout=5.0)
    assert entered, "Executor não atingiu a chamada externa dentro do prazo"
    assert checkedout_at_entry == 0, f"Pool reteve conexão na chamada externa: checkedout={checkedout_at_entry}"

    # 4. Durante o bloqueio do canal externo, executa o ciclo completo de venda no PDV local (5 etapas)
    t0 = time.perf_counter()

    # Etapa 1: Abertura da venda no balcão (COUNTER)
    sale_res = client.post(
        "/api/v1/sales",
        headers=gestora_headers,
        json={
            "store_id": str(env["store_id"]),
            "register_id": str(env["register_id"]),
            "operation_mode": "COUNTER",
        },
    )
    assert sale_res.status_code == 200, sale_res.text
    sale_id = sale_res.json()["id"]
    assert sale_res.json()["status"] == "DRAFT"

    # Etapa 2: Adição de itens de nichos variados (Varejo + Beleza)
    it1_res = client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=gestora_headers,
        json={"product_id": str(env["prod_retail_id"]), "quantity": 1.0},
    )
    assert it1_res.status_code == 200

    it2_res = client.post(
        f"/api/v1/sales/{sale_id}/items",
        headers=gestora_headers,
        json={"product_id": str(env["prod_beauty_id"]), "quantity": 2.0},
    )
    assert it2_res.status_code == 200

    # Etapa 3: Fechamento / Checkout da venda local
    checkout_res = client.post(
        f"/api/v1/sales/{sale_id}/checkout",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert checkout_res.status_code == 200, checkout_res.text
    checked_sale = checkout_res.json()
    assert checked_sale["status"] == "AWAITING_PAYMENT"
    net_total = float(checked_sale["net_total"])
    assert net_total == 269.70

    # Etapa 4: Registro do pagamento em dinheiro
    pay_res = client.post(
        "/api/v1/payments",
        headers={**gestora_headers, "Idempotency-Key": f"pay-conc-{uuid.uuid4()}"},
        json={
            "sale_id": sale_id,
            "method": "CASH",
            "amount": net_total,
            "cash_session_id": str(env["cash_session_id"]),
            "tendered_amount": 300.00,
            "provider": "MANUAL_OPERATOR",
        },
    )
    assert pay_res.status_code == 200, pay_res.text
    payment_id = pay_res.json()["id"]

    # Etapa 5: Confirmação do pagamento e transição atômica para PAID
    confirm_res = client.post(
        f"/api/v1/payments/{payment_id}/confirm",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert confirm_res.status_code == 200, confirm_res.text
    assert confirm_res.json()["sale_status"] == "PAID"

    # Confirmação no endpoint da venda
    sale_final = client.get(f"/api/v1/sales/{sale_id}", headers=gestora_headers).json()
    assert sale_final["status"] == "PAID"

    elapsed = time.perf_counter() - t0
    # Latência das 5 etapas do PDV local deve ser imediata (< 2.0 segundos), comprovando ausência de contenção
    assert elapsed < 2.0, f"Venda local demorou excessivamente sob conector bloqueado: {elapsed:.3f}s"

    # 5. Libera o conector externo para concluir sua requisição
    release_event.set()
    t.join(timeout=5.0)
    assert not t.is_alive(), "Thread de publicação não finalizou após release"
    assert "error" not in exec_holder, f"Erro inesperado na thread de publicação: {exec_holder.get('error')}"
    assert exec_holder["response"].status_code == 200
    assert exec_holder["response"].json()["batch"]["status"] == "SUCCEEDED"


def test_tres_nichos_sem_imposicao_de_cozinha_ou_mesas():
    """Valida que varejo e revenda de beleza operam sem dependncia de roteamento de cozinha ou mesas."""
    env = _setup_walkthrough_environment()
    client = TestClient(app)

    gestora_headers = {
        "Authorization": f"Bearer {env['gestora_token']}",
        "X-Tenant-ID": str(env["tenant_id"]),
        "X-Store-ID": str(env["store_id"]),
    }

    # 1. Verifica propriedades estruturais dos produtos de varejo e beleza no banco
    with Session(engine) as session:
        retail_prod = session.get(Product, env["prod_retail_id"])
        beauty_prod = session.get(Product, env["prod_beauty_id"])
        food_prod = session.get(Product, env["prod_food_id"])

        # Produtos de varejo e beleza no exigem cozinha/ponto de produo
        assert not hasattr(retail_prod, "production_destination") or retail_prod.production_destination is None
        assert not hasattr(beauty_prod, "production_destination") or beauty_prod.production_destination is None

    # 2. Publicao isolada de lote exclusivamente de revenda de beleza
    beauty_key = f"batch-beauty-{uuid.uuid4().hex[:8]}"
    pub_res = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": beauty_key},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["beauty_offer_id"])],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert pub_res.status_code == 200
    batch_id = pub_res.json()["batch"]["id"]

    exec_res = client.post(
        f"/api/v1/channel-catalog/publications/{batch_id}/execute",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert exec_res.status_code == 200
    assert exec_res.json()["batch"]["status"] == "SUCCEEDED"
    assert exec_res.json()["items"][0]["status"] == "SUCCEEDED"


def test_retomada_sem_itens_pendentes_finaliza_com_desfecho_atomico_e_reverte_na_falha(monkeypatch):
    """Valida que quando um lote a retomar já não possui itens pendentes:
    - Finaliza o lote como SUCCEEDED e registra o desfecho atomicamente na Fase 1, sem chamadas externas.
    - Falha na escrita do desfecho reverte a transação (rollback atômico).
    - Nova tentativa bem-sucedida finaliza o lote com auditoria e outbox corretos."""
    env = _setup_walkthrough_environment()
    client = TestClient(app)

    gestora_headers = {
        "Authorization": f"Bearer {env['gestora_token']}",
        "X-Tenant-ID": str(env["tenant_id"]),
        "X-Store-ID": str(env["store_id"]),
    }

    # 1. Cria lote de publicação
    batch_key = f"batch-no-pending-{uuid.uuid4().hex[:8]}"
    create_res = client.post(
        "/api/v1/channel-catalog/publications",
        headers={**gestora_headers, "Idempotency-Key": batch_key},
        json={
            "connection_id": str(env["connection_id"]),
            "offer_ids": [str(env["retail_offer_id"])],
            "actor_id": str(env["gestora_user_id"]),
        },
    )
    assert create_res.status_code == 200
    batch_id = uuid.UUID(create_res.json()["batch"]["id"])

    # Simula estado onde todos os itens já estão SUCCEEDED, mas o lote está PARTIAL com lease expirado
    with Session(engine) as session:
        set_platform_db_context(session)
        b = session.get(ChannelPublicationBatch, batch_id)
        b.status = PublicationStatusEnum.PARTIAL
        b.lease_token = None
        b.lease_expires_at = None
        session.add(b)
        it = session.exec(select(ChannelPublicationItem).where(ChannelPublicationItem.batch_id == batch_id)).one()
        it.status = PublicationItemStatusEnum.SUCCEEDED
        session.add(it)
        session.commit()

    # Espiona chamadas externas: nenhuma deve ocorrer neste ramo
    publish_calls = 0
    orig_publish = ReferenceChannelAdapter.publish_catalog
    def _spy_publish(adapter_self, payload):
        nonlocal publish_calls
        publish_calls += 1
        return orig_publish(adapter_self, payload)
    monkeypatch.setattr(ReferenceChannelAdapter, "publish_catalog", _spy_publish)

    check_calls = 0
    orig_check = ReferenceChannelAdapter.check_catalog_status
    def _spy_check(adapter_self, merchant_ext_id, op_keys):
        nonlocal check_calls
        check_calls += 1
        return orig_check(adapter_self, merchant_ext_id, op_keys)
    monkeypatch.setattr(ReferenceChannelAdapter, "check_catalog_status", _spy_check)

    from app.services import reliability_service
    orig_write_audit = reliability_service.write_audit_and_outbox

    # Injeta falha na gravação do desfecho
    def _failing_no_pending_audit(*args, **kwargs):
        action = kwargs.get("action") or (args[4] if len(args) > 4 else None)
        if action == "channel.catalog.resumed":
            raise RuntimeError("Falha proposital na auditoria do ramo sem itens pendentes")
        return orig_write_audit(*args, **kwargs)
    monkeypatch.setattr(reliability_service, "write_audit_and_outbox", _failing_no_pending_audit)

    with pytest.raises(Exception) as exc:
        client.post(
            f"/api/v1/channel-catalog/publications/{batch_id}/resume",
            headers=gestora_headers,
            json={"actor_id": str(env["gestora_user_id"])},
        )
    assert "Falha proposital na auditoria do ramo sem itens pendentes" in str(exc.value)
    assert publish_calls == 0
    assert check_calls == 0

    # Verifica no banco: rollback atômico! O lote continua PARTIAL e não SUCCEEDED
    with Session(engine) as session:
        set_platform_db_context(session)
        b_check = session.get(ChannelPublicationBatch, batch_id)
        assert b_check.status == PublicationStatusEnum.PARTIAL
        outcome_audits = session.exec(select(AuditEvent).where(
            AuditEvent.action == "channel.catalog.resumed",
        )).all()
        assert not any(str(batch_id) in a.payload for a in outcome_audits)

    # Restaura write_audit_and_outbox original
    monkeypatch.setattr(reliability_service, "write_audit_and_outbox", orig_write_audit)

    # Retoma com sucesso: finaliza atomicamente
    resume_ok = client.post(
        f"/api/v1/channel-catalog/publications/{batch_id}/resume",
        headers=gestora_headers,
        json={"actor_id": str(env["gestora_user_id"])},
    )
    assert resume_ok.status_code == 200
    assert resume_ok.json()["batch"]["status"] == "SUCCEEDED"
    assert publish_calls == 0, "Nenhum despacho externo no ramo sem itens pendentes"
    assert check_calls == 0, "Nenhuma consulta externa no ramo sem itens pendentes"

    with Session(engine) as session:
        set_platform_db_context(session)
        b_final = session.get(ChannelPublicationBatch, batch_id)
        assert b_final.status == PublicationStatusEnum.SUCCEEDED
        assert b_final.lease_token is None

        outbox_events = session.exec(select(OutboxEvent).where(
            OutboxEvent.aggregate_id == str(batch_id),
            OutboxEvent.event_type == "channel.publication.resumed",
        )).all()
        assert len(outbox_events) == 1
        ob_payload = json.loads(outbox_events[0].payload) if isinstance(outbox_events[0].payload, str) else outbox_events[0].payload
        assert ob_payload["batch_id"] == str(batch_id)
        assert ob_payload["conclusive_count"] == 0
        assert ob_payload["remaining_pending_count"] == 0
        assert ob_payload["status"] == "SUCCEEDED"

        audit_events = session.exec(select(AuditEvent).where(
            AuditEvent.action == "channel.catalog.resumed",
        )).all()
        batch_audits = [a for a in audit_events if str(batch_id) in a.payload]
        assert len(batch_audits) == 1
        aud_payload = json.loads(batch_audits[0].payload) if isinstance(batch_audits[0].payload, str) else batch_audits[0].payload
        assert aud_payload["batch_id"] == str(batch_id)
        assert aud_payload["conclusive_count"] == 0
        assert aud_payload["remaining_pending_count"] == 0
        assert aud_payload["status"] == "SUCCEEDED"

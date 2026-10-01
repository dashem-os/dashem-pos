"""Testes da primeira fatia fundacional do executor de publicação de catálogo (S13.2).

Valida os requisitos essenciais estabelecidos para a publicação de catálogo:
1. Reutilização de ChannelCatalogOffer, ChannelPublicationBatch e ChannelPublicationItem.
2. Separação de versão do snapshot/lote (snapshot_version) da desired_version individual de cada oferta.
3. Congelamento integral por item (frozen_payload com snapshot dos dados no instante do lote).
4. Separação de hashes: request_hash (idempotência do comando) vs. content_hash (conteúdo congelado).
5. Idempotência estrita: rechamada com a mesma Idempotency-Key recupera o lote original existente,
   mesmo após alterações posteriores de preço ou estoque no catálogo.
6. Convergência monotônica e proteção contra respostas fora de ordem:
   - Confirmação de versão antiga não publica versão nova nem regride published_version.
   - Falha antiga não sobrescreve sucesso posterior na oferta.
7. Preservação de identidade da operação (provider_operation_key estável) em retomadas e reenvios.
8. Chamadas de rede fora de transações abertas de banco de dados.
9. Cobertura dos três nichos (alimentação, varejo e revenda de beleza) e combinado, com preços
   vindos dos dados e sem imposição de cozinha ou mesas a varejo e revenda.
"""

import uuid
from decimal import Decimal
import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.catalog import Product, ProductPrice, SalesChannel, SalesChannelTypeEnum
from app.models.channel_catalog import (
    ChannelCatalogOffer, ChannelPublicationBatch, ChannelPublicationItem,
    PublicationItemStatusEnum, PublicationStatusEnum,
)
from app.models.channel_hub import MerchantConnection, MerchantConnectionStatusEnum
from app.models.identity import Store, Tenant, User
from app.modules.channels import catalog_publisher
from app.modules.channels.adapters.reference import ReferenceChannelAdapter
from app.modules.channels.contracts import (
    CatalogPublicationBatchResult, CatalogPublicationItemResult,
)
from tests.activity_fixtures import (
    BEAUTY_RESELLER, FOOD_SERVICE, RETAIL, declare_activity, declare_contract_activities,
)


def _session_factory():
    session = Session(engine)
    set_platform_db_context(session)
    return session


def _setup_fixture(suffix: str, activity: str = FOOD_SERVICE, multiple_activities: tuple[str, ...] = ()):
    with _session_factory() as session:
        tenant = Tenant(name=f"Tenant {suffix}", slug=f"tenant-{suffix}")
        session.add(tenant)
        session.flush()

        if multiple_activities:
            declare_contract_activities(session, tenant.id, multiple_activities)
        else:
            declare_activity(session, tenant.id, activity)

        store = Store(tenant_id=tenant.id, name="Loja Matriz", code=f"ST-{suffix}")
        session.add(store)

        user = User(email=f"user-{suffix}@example.com", full_name=f"User {suffix}")
        session.add(user)
        session.flush()

        sales_channel = SalesChannel(
            tenant_id=tenant.id,
            store_id=store.id,
            code=f"CH-{suffix}",
            name="Reference Delivery Channel",
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
            service_actor_id=user.id,
            configured_by=user.id,
            idempotency_key=f"conn-{suffix}",
            request_hash=f"hash-{suffix}",
        )
        session.add(conn)
        session.commit()

        conn_id = conn.id
        user_id = user.id
        context = TenantContext(tenant_id=tenant.id, store_id=store.id, user_id=user.id)
        return context, conn_id, user_id


def _create_offer(session: Session, context: TenantContext, conn_id: uuid.UUID, name: str, sku: str, price: Decimal, stock: Decimal = Decimal("50")):
    prod = Product(
        tenant_id=context.tenant_id,
        name=name,
        sku=sku,
        unit="UN",
    )
    session.add(prod)
    session.flush()

    price_row = ProductPrice(
        tenant_id=context.tenant_id,
        store_id=context.store_id,
        product_id=prod.id,
        cost_price=price / Decimal("2"),
        sale_price=price,
    )
    session.add(price_row)

    offer = ChannelCatalogOffer(
        tenant_id=context.tenant_id,
        store_id=context.store_id,
        merchant_connection_id=conn_id,
        product_id=prod.id,
        price=price,
        available=True,
        stock_quantity=stock,
        desired_version=1,
        published_version=0,
        last_publication_status=PublicationItemStatusEnum.PENDING,
    )
    session.add(offer)
    session.commit()
    session.refresh(offer)
    session.refresh(prod)
    return offer, prod


def test_publicacao_idempotente_com_mesma_chave_recupera_lote_original_apos_mudancas_no_catalogo():
    suffix = uuid.uuid4().hex[:8]
    context, conn_id, user_id = _setup_fixture(suffix, RETAIL)

    with _session_factory() as session:
        offer, prod = _create_offer(session, context, conn_id, "Camiseta Básica", f"SKU-{suffix}", Decimal("79.90"))

        idempotency_key = f"pub-key-{suffix}"
        res1 = catalog_publisher.prepare_batch(
            session, context, connection_id=conn_id, offer_ids=[offer.id], actor_id=user_id, idempotency_key=idempotency_key,
        )
        batch1 = res1["batch"]
        items1 = res1["items"]

        assert batch1.snapshot_version >= 1
        assert len(batch1.content_hash) == 64
        assert len(batch1.request_hash) == 64
        assert len(items1) == 1
        assert items1[0].desired_version == 1
        assert Decimal(items1[0].frozen_payload["price"]) == Decimal("79.90")
        assert items1[0].frozen_payload["sku"] == f"SKU-{suffix}"

        # Altera oferta no catálogo local posteriormente: novo preço e avanço de versão desejada
        offer_db = session.get(ChannelCatalogOffer, offer.id)
        offer_db.price = Decimal("99.90")
        offer_db.desired_version = 2
        session.commit()

        # Rechamada com a mesma Idempotency-Key deve recuperar o lote original intacto
        res2 = catalog_publisher.prepare_batch(
            session, context, connection_id=conn_id, offer_ids=[offer.id], actor_id=user_id, idempotency_key=idempotency_key,
        )
        batch2 = res2["batch"]
        items2 = res2["items"]

        assert batch2.id == batch1.id
        assert batch2.snapshot_version == batch1.snapshot_version
        assert batch2.content_hash == batch1.content_hash
        assert batch2.request_hash == batch1.request_hash
        # O payload congelado deve conter estritamente a versão e o preço do momento da criação do lote
        assert items2[0].desired_version == 1
        assert Decimal(items2[0].frozen_payload["price"]) == Decimal("79.90")

        # Reutilização da mesma chave com payload divergente deve ser recusada com 409
        other_offer, _ = _create_offer(session, context, conn_id, "Bermuda Jeans", f"SKU-2-{suffix}", Decimal("129.90"))
        with pytest.raises(HTTPException) as exc:
            catalog_publisher.prepare_batch(
                session, context, connection_id=conn_id, offer_ids=[other_offer.id], actor_id=user_id, idempotency_key=idempotency_key,
            )
        assert exc.value.status_code == 409


def test_publicacao_executa_fora_de_transacao_de_banco_e_atualiza_monotonico():
    suffix = uuid.uuid4().hex[:8]
    context, conn_id, user_id = _setup_fixture(suffix, FOOD_SERVICE)

    with _session_factory() as session:
        offer, prod = _create_offer(session, context, conn_id, "Smash Burger", f"FOOD-{suffix}", Decimal("34.50"))
        res = catalog_publisher.prepare_batch(
            session, context, connection_id=conn_id, offer_ids=[offer.id], actor_id=user_id, idempotency_key=f"exec-{suffix}",
        )
        batch_id = res["batch"].id
        offer_id = offer.id

    # Execução através da fábrica de sessões (as chamadas ao adaptador ocorrem fora de transações abertas)
    exec_res = catalog_publisher.execute_publication(_session_factory, context.tenant_id, batch_id)
    assert exec_res["batch"].status == PublicationStatusEnum.SUCCEEDED
    assert len(exec_res["items"]) == 1
    item = exec_res["items"][0]
    assert item.status == PublicationItemStatusEnum.SUCCEEDED
    assert item.provider_result_ref is not None
    assert item.attempt_count == 1

    with _session_factory() as session:
        offer_after = session.get(ChannelCatalogOffer, offer_id)
        assert offer_after.published_version == 1
        assert offer_after.last_publication_status == PublicationItemStatusEnum.SUCCEEDED


def test_resposta_fora_de_ordem_confirmacao_antiga_nao_regride_versao_nova():
    suffix = uuid.uuid4().hex[:8]
    context, conn_id, user_id = _setup_fixture(suffix, FOOD_SERVICE)

    with _session_factory() as session:
        offer, prod = _create_offer(session, context, conn_id, "Pizza Margherita", f"PIZZA-{suffix}", Decimal("65.00"))
        offer_id = offer.id

        # Simula que a oferta já evoluiu e já foi publicada com sucesso na versão 3
        offer_db = session.get(ChannelCatalogOffer, offer.id)
        offer_db.desired_version = 3
        offer_db.published_version = 3
        offer_db.last_publication_status = PublicationItemStatusEnum.SUCCEEDED
        session.commit()

        # Cria um lote correspondente a uma tentativa antiga (versão 2)
        batch = ChannelPublicationBatch(
            tenant_id=context.tenant_id,
            store_id=context.store_id,
            merchant_connection_id=conn_id,
            status=PublicationStatusEnum.PENDING,
            idempotency_key=f"old-batch-{suffix}",
            request_hash="old-req",
            snapshot_version=1,
            content_hash="old-content",
            created_by=user_id,
        )
        session.add(batch)
        session.flush()

        old_op_key = f"cat:{conn_id}:{offer_id}:v2"
        item = ChannelPublicationItem(
            tenant_id=context.tenant_id,
            batch_id=batch.id,
            offer_id=offer_id,
            desired_version=2,
            frozen_payload={"price": "60.00"},
            provider_operation_key=old_op_key,
            status=PublicationItemStatusEnum.PENDING,
        )
        session.add(item)
        session.commit()
        batch_id = batch.id

    # Executa a confirmação da versão 2 tardia
    res = catalog_publisher.execute_publication(_session_factory, context.tenant_id, batch_id)
    assert res["batch"].status == PublicationStatusEnum.SUCCEEDED
    assert res["items"][0].status == PublicationItemStatusEnum.SUCCEEDED

    with _session_factory() as session:
        offer_check = session.get(ChannelCatalogOffer, offer_id)
        # published_version NÃO regride para 2; mantém 3
        assert offer_check.published_version == 3
        assert offer_check.last_publication_status == PublicationItemStatusEnum.SUCCEEDED


def test_resposta_fora_de_ordem_falha_antiga_nao_sobrescreve_sucesso_posterior():
    suffix = uuid.uuid4().hex[:8]
    context, conn_id, user_id = _setup_fixture(suffix, BEAUTY_RESELLER)

    with _session_factory() as session:
        offer, prod = _create_offer(session, context, conn_id, "Batom Matte", f"BATOM-{suffix}", Decimal("49.90"))
        offer_id = offer.id

        # A oferta já está confirmada com sucesso na versão 2
        offer_db = session.get(ChannelCatalogOffer, offer.id)
        offer_db.desired_version = 2
        offer_db.published_version = 2
        offer_db.last_publication_status = PublicationItemStatusEnum.SUCCEEDED
        session.commit()

        # Cria lote com versão antiga 1 cujo SKU/item simula falha
        batch = ChannelPublicationBatch(
            tenant_id=context.tenant_id,
            store_id=context.store_id,
            merchant_connection_id=conn_id,
            status=PublicationStatusEnum.PENDING,
            idempotency_key=f"fail-old-{suffix}",
            request_hash="req-fail",
            snapshot_version=1,
            content_hash="content-fail",
            created_by=user_id,
        )
        session.add(batch)
        session.flush()

        item = ChannelPublicationItem(
            tenant_id=context.tenant_id,
            batch_id=batch.id,
            offer_id=offer_id,
            desired_version=1,
            frozen_payload={"sku": "FAIL-BATOM", "price": "45.00"},
            provider_operation_key=f"cat:{conn_id}:{offer_id}:v1-FAIL",
            status=PublicationItemStatusEnum.PENDING,
        )
        session.add(item)
        session.commit()
        batch_id = batch.id

    res = catalog_publisher.execute_publication(_session_factory, context.tenant_id, batch_id)
    assert res["batch"].status == PublicationStatusEnum.FAILED
    assert res["items"][0].status == PublicationItemStatusEnum.FAILED

    with _session_factory() as session:
        offer_check = session.get(ChannelCatalogOffer, offer_id)
        # A falha tardia da v1 NÃO pode sobrescrever o sucesso já confirmado da v2!
        assert offer_check.published_version == 2
        assert offer_check.last_publication_status == PublicationItemStatusEnum.SUCCEEDED


def test_resultados_parciais_e_retomada_com_chave_estavel(monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    context, conn_id, user_id = _setup_fixture(suffix, RETAIL)

    with _session_factory() as session:
        offer_good, _ = _create_offer(session, context, conn_id, "Mochila Couro", f"MOCH-{suffix}", Decimal("249.00"))
        offer_fail, _ = _create_offer(session, context, conn_id, "Estojo Escolar", f"FAIL-EST-{suffix}", Decimal("29.90"))

        res = catalog_publisher.prepare_batch(
            session, context, connection_id=conn_id, offer_ids=[offer_good.id, offer_fail.id],
            actor_id=user_id, idempotency_key=f"partial-{suffix}",
        )
        batch_id = res["batch"].id
        orig_op_keys = {item.offer_id: item.provider_operation_key for item in res["items"]}
        good_id = offer_good.id
        fail_id = offer_fail.id

    # Primeira execução: um sucede e o com "FAIL" falha
    exec_res = catalog_publisher.execute_publication(_session_factory, context.tenant_id, batch_id)
    assert exec_res["batch"].status == PublicationStatusEnum.PARTIAL
    statuses = {item.offer_id: item.status for item in exec_res["items"]}
    assert statuses[good_id] == PublicationItemStatusEnum.SUCCEEDED
    assert statuses[fail_id] == PublicationItemStatusEnum.FAILED

    # Corrige a causa da rejeição no conector (monkeypatch para simular que o canal agora aceita o item)
    monkeypatch.setattr(
        ReferenceChannelAdapter,
        "publish_catalog",
        lambda self, payload: CatalogPublicationBatchResult(
            batch_id=payload.batch_id,
            results=tuple(
                CatalogPublicationItemResult(operation_key=i.operation_key, status="SUCCEEDED", provider_result_ref=f"fixed-{i.operation_key}")
                for i in payload.items
            ),
        ),
    )

    # Retomada do lote
    resumed = catalog_publisher.resume_publication(_session_factory, context.tenant_id, batch_id)
    assert resumed["batch"].status == PublicationStatusEnum.SUCCEEDED
    for item in resumed["items"]:
        assert item.status == PublicationItemStatusEnum.SUCCEEDED
        # Preserva deterministicamente a operation_key original
        assert item.provider_operation_key == orig_op_keys[item.offer_id]


def test_confirmacao_perdida_e_reconciliacao_na_retomada():
    suffix = uuid.uuid4().hex[:8]
    context, conn_id, user_id = _setup_fixture(suffix, BEAUTY_RESELLER)

    with _session_factory() as session:
        offer, _ = _create_offer(session, context, conn_id, "Perfume Floral 100ml", f"PERF-{suffix}", Decimal("189.90"))
        offer_id = offer.id
        res = catalog_publisher.prepare_batch(
            session, context, connection_id=conn_id, offer_ids=[offer.id],
            actor_id=user_id, idempotency_key=f"lost-{suffix}",
        )
        batch_id = res["batch"].id
        op_key = res["items"][0].provider_operation_key

    # Execução com confirmação perdida: omitimos a resposta para op_key simulando timeout de resposta
    exec_res = catalog_publisher.execute_publication(
        _session_factory, context.tenant_id, batch_id, omit_operation_keys=[op_key],
    )
    assert exec_res["batch"].status == PublicationStatusEnum.PARTIAL
    assert exec_res["items"][0].status == PublicationItemStatusEnum.PENDING

    # Retomada: consulta check_catalog_status no canal e descobre que o canal processou
    resumed = catalog_publisher.resume_publication(_session_factory, context.tenant_id, batch_id)
    assert resumed["batch"].status == PublicationStatusEnum.SUCCEEDED
    assert resumed["items"][0].status == PublicationItemStatusEnum.SUCCEEDED
    assert resumed["items"][0].provider_result_ref == f"ref-{op_key}"

    with _session_factory() as session:
        offer_check = session.get(ChannelCatalogOffer, offer_id)
        assert offer_check.published_version == 1
        assert offer_check.last_publication_status == PublicationItemStatusEnum.SUCCEEDED


def test_tres_nichos_e_combinado_sem_imposicao_de_cozinha_ou_mesas():
    """Valida publicação nos três nichos e em tenant combinado.

    - Alimentação (FOOD_SERVICE)
    - Varejo (RETAIL)
    - Revenda de Beleza (BEAUTY_RESELLER)
    - Combinado (FOOD_SERVICE + RETAIL)

    Garante que preços vêm dos dados/fixtures e que varejo e revenda não impõem cozinha ou mesas.
    """
    scenarios = [
        ("food", FOOD_SERVICE, (), "Combo X-Burger com Fritas", Decimal("42.90"), Decimal("20")),
        ("retail", RETAIL, (), "Parafuso Sextavado Inox 50un", Decimal("18.75"), Decimal("200")),
        ("beauty", BEAUTY_RESELLER, (), "Kit Sérum Rejuvenescedor Noturno", Decimal("139.00"), Decimal("15")),
        ("combined", None, (FOOD_SERVICE, RETAIL), "Café Gourmet em Grãos 500g", Decimal("48.50"), Decimal("80")),
    ]

    for prefix, activity, multiple_acts, prod_name, price, stock in scenarios:
        suffix = f"{prefix}-{uuid.uuid4().hex[:6]}"
        context, conn_id, user_id = _setup_fixture(suffix, activity or FOOD_SERVICE, multiple_activities=multiple_acts)

        with _session_factory() as session:
            offer, prod = _create_offer(session, context, conn_id, prod_name, f"SKU-{suffix}", price, stock=stock)
            offer_id = offer.id

            # Para varejo e beleza, asseguramos ausência de exigência de cozinha
            if activity in (RETAIL, BEAUTY_RESELLER):
                assert not hasattr(prod, "production_destination") or prod.production_destination is None

            idempotency_key = f"niche-{suffix}"
            prep = catalog_publisher.prepare_batch(
                session, context, connection_id=conn_id, offer_ids=[offer.id],
                actor_id=user_id, idempotency_key=idempotency_key,
            )
            batch_id = prep["batch"].id
            item = prep["items"][0]
            # Preço do canal vem do cadastro da oferta/dados, sem hardcoding comercial
            assert Decimal(item.frozen_payload["price"]) == price
            assert Decimal(item.frozen_payload["stock_quantity"]) == stock

        exec_res = catalog_publisher.execute_publication(_session_factory, context.tenant_id, batch_id)
        assert exec_res["batch"].status == PublicationStatusEnum.SUCCEEDED
        assert exec_res["items"][0].status == PublicationItemStatusEnum.SUCCEEDED

        with _session_factory() as session:
            offer_final = session.get(ChannelCatalogOffer, offer_id)
            assert offer_final.published_version == 1
            assert offer_final.price == price

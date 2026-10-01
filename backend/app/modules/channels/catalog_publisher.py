"""Executor e sincronizador de catálogo do Channel Hub (S13.2).

Implementa a primeira fatia fundacional do publicador de catálogo:
1. Reuso estrito de ChannelCatalogOffer, ChannelPublicationBatch e ChannelPublicationItem.
2. Separação de snapshot_version (lote) da desired_version individual de cada oferta.
3. Congelamento integral por item (frozen_payload com snapshot dos atributos no momento da criação).
4. Separação de hashes: request_hash (idempotência do comando) vs. content_hash (conteúdo congelado).
5. Idempotência estrita: rechamada com a mesma Idempotency-Key recupera o lote original existente,
   mesmo após alterações posteriores no catálogo.
6. Convergência monotônica e proteção contra fora de ordem:
   - Confirmação de versão antiga não publica versão nova nem regride published_version.
   - Falha antiga não sobrescreve sucesso posterior.
7. Preservação de identidade da operação (provider_operation_key estável) em retomadas e reenvios.
8. Chamadas de rede executadas ESTRITAMENTE fora de transações abertas de banco de dados.
9. Suporte agnóstico aos três nichos (alimentação, varejo e beleza) e combinações, com preços
   vindos exclusivamente dos dados sem imposição de cozinha/mesas a varejo/beleza.
"""

import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.catalog import Product
from app.models.channel_catalog import (
    ChannelCatalogOffer, ChannelPublicationBatch, ChannelPublicationItem,
    PublicationItemStatusEnum, PublicationStatusEnum,
)
from app.models.channel_hub import MerchantConnection
from app.modules.channels.contracts import (
    CatalogPublicationBatchResult, CatalogPublicationItemPayload,
    CatalogPublicationItemResult, CatalogPublicationPayload,
    ChannelCapability, require,
)
from app.modules.channels.registry import adapter_for


def _serialize_for_hash(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_content_hash(items_payload: Sequence[Mapping[str, Any]]) -> str:
    canonical = sorted(items_payload, key=lambda x: str(x.get("offer_id", "")))
    return hashlib.sha256(_serialize_for_hash(canonical).encode("utf-8")).hexdigest()


def compute_request_hash(data: Mapping[str, Any]) -> str:
    return hashlib.sha256(_serialize_for_hash(data).encode("utf-8")).hexdigest()


def batch_projection(session: Session, batch: ChannelPublicationBatch) -> dict:
    items = list(
        session.exec(
            select(ChannelPublicationItem)
            .where(ChannelPublicationItem.batch_id == batch.id)
            .order_by(ChannelPublicationItem.created_at)
        ).all()
    )
    return {
        "batch": batch,
        "items": items,
    }


def prepare_batch(
    session: Session,
    context: TenantContext,
    *,
    connection_id: uuid.UUID,
    offer_ids: Sequence[uuid.UUID],
    actor_id: Optional[uuid.UUID],
    idempotency_key: str,
) -> dict:
    """Prepara o lote de publicação congelando o snapshot de ofertas e conteúdo.

    Garante idempotência estrita (recupera lote original) e gera hashes segregados.
    """
    act = resolve_actor(context, actor_id)
    conn = session.exec(
        scope_tenant_query(
            select(MerchantConnection).where(MerchantConnection.id == connection_id),
            MerchantConnection,
            context,
        )
    ).first()
    if not conn:
        raise HTTPException(404, "Conexão não encontrada.")

    adapter = adapter_for(conn.provider_code)
    require(adapter, ChannelCapability.CATALOG_PUBLICATION)

    req_data = {
        "connection_id": str(connection_id),
        "offer_ids": sorted(map(str, offer_ids)),
    }
    req_hash = compute_request_hash(req_data)

    existing = session.exec(
        select(ChannelPublicationBatch).where(
            ChannelPublicationBatch.tenant_id == context.tenant_id,
            ChannelPublicationBatch.idempotency_key == idempotency_key,
        )
    ).first()
    if existing:
        if existing.request_hash != req_hash:
            raise HTTPException(409, "Idempotency-Key reutilizada com payload divergente.")
        return batch_projection(session, existing)

    offers = list(
        session.exec(
            select(ChannelCatalogOffer).where(
                ChannelCatalogOffer.id.in_(offer_ids),
                ChannelCatalogOffer.merchant_connection_id == conn.id,
            )
        ).all()
    )
    if len(offers) != len(set(offer_ids)):
        raise HTTPException(404, "Uma ou mais ofertas de canal não foram encontradas.")

    products_by_id = {
        p.id: p
        for p in session.exec(
            select(Product).where(Product.id.in_([o.product_id for o in offers]))
        ).all()
    }

    # Snapshot version do lote/conexão (desacoplada da desired_version das ofertas)
    max_snap = session.exec(
        select(func.max(ChannelPublicationBatch.snapshot_version)).where(
            ChannelPublicationBatch.tenant_id == context.tenant_id,
            ChannelPublicationBatch.merchant_connection_id == conn.id,
        )
    ).first()
    snapshot_version = (max_snap or 0) + 1

    frozen_list = []
    items_to_create = []

    for offer in offers:
        prod = products_by_id.get(offer.product_id)
        frozen = {
            "offer_id": str(offer.id),
            "product_id": str(offer.product_id),
            "desired_version": offer.desired_version,
            "price": str(offer.price),
            "available": offer.available,
            "stock_quantity": str(offer.stock_quantity) if offer.stock_quantity is not None else None,
            "sku": prod.sku if prod else None,
            "title": prod.name if prod else None,
        }
        frozen_list.append(frozen)

        # Chave estável de operação do conector para esta tentativa da oferta
        op_key = f"cat:{conn.id}:{offer.id}:v{offer.desired_version}"
        items_to_create.append((offer, frozen, op_key))

    content_hash = compute_content_hash(frozen_list)

    batch = ChannelPublicationBatch(
        tenant_id=context.tenant_id,
        store_id=conn.store_id,
        merchant_connection_id=conn.id,
        status=PublicationStatusEnum.PENDING,
        idempotency_key=idempotency_key,
        request_hash=req_hash,
        snapshot_version=snapshot_version,
        content_hash=content_hash,
        created_by=act,
    )
    session.add(batch)
    session.flush()

    for offer, frozen, op_key in items_to_create:
        item = ChannelPublicationItem(
            tenant_id=context.tenant_id,
            batch_id=batch.id,
            offer_id=offer.id,
            desired_version=offer.desired_version,
            frozen_payload=frozen,
            provider_operation_key=op_key,
            status=PublicationItemStatusEnum.PENDING,
        )
        session.add(item)

    session.commit()
    session.refresh(batch)
    return batch_projection(session, batch)


def execute_publication(
    session_factory: Callable[[], Session],
    tenant_id: uuid.UUID,
    batch_id: uuid.UUID,
    *,
    simulate_network_failure: bool = False,
    omit_operation_keys: Sequence[str] = (),
) -> dict:
    """Executa o envio do lote ao canal respeitando estritamente:

    1. Chamadas de rede FORA de transações abertas do banco.
    2. Atualização monotônica de versões das ofertas.
    3. Proteção contra sobrescrita de sucesso posterior por falha antiga.
    """
    # =========================================================================
    # FASE 1: Transação Local 1 (Preparação e marcação de PROCESSING)
    # =========================================================================
    with session_factory() as session:
        batch = session.exec(
            select(ChannelPublicationBatch)
            .where(
                ChannelPublicationBatch.id == batch_id,
                ChannelPublicationBatch.tenant_id == tenant_id,
            )
            .with_for_update()
        ).first()
        if not batch:
            raise HTTPException(404, "Lote não encontrado.")

        if batch.status == PublicationStatusEnum.SUCCEEDED:
            return batch_projection(session, batch)

        batch.status = PublicationStatusEnum.PROCESSING
        batch.updated_at = datetime.utcnow()

        conn = session.get(MerchantConnection, batch.merchant_connection_id)
        if not conn:
            raise HTTPException(404, "Conexão de merchant não encontrada.")

        items = list(
            session.exec(
                select(ChannelPublicationItem)
                .where(ChannelPublicationItem.batch_id == batch.id)
                .order_by(ChannelPublicationItem.created_at)
            ).all()
        )

        # Seleciona apenas itens que ainda não foram confirmados com sucesso
        items_to_send = [i for i in items if i.status != PublicationItemStatusEnum.SUCCEEDED]

        payload_items = []
        for it in items_to_send:
            fp = it.frozen_payload or {}
            payload_items.append(
                CatalogPublicationItemPayload(
                    operation_key=it.provider_operation_key,
                    offer_id=str(it.offer_id),
                    product_id=str(fp.get("product_id")),
                    desired_version=it.desired_version,
                    price=Decimal(str(fp.get("price", "0"))),
                    available=bool(fp.get("available", True)),
                    stock_quantity=Decimal(str(fp["stock_quantity"])) if fp.get("stock_quantity") is not None else None,
                    sku=fp.get("sku"),
                    title=fp.get("title"),
                )
            )

        net_payload = CatalogPublicationPayload(
            batch_id=str(batch.id),
            snapshot_version=batch.snapshot_version,
            merchant_external_id=conn.merchant_external_id,
            items=tuple(payload_items),
        )
        provider_code = conn.provider_code

        session.commit()

    # =========================================================================
    # FASE 2: Chamada de Rede (SEM transação aberta, sem lock no banco)
    # =========================================================================
    adapter = adapter_for(provider_code)
    require(adapter, ChannelCapability.CATALOG_PUBLICATION)

    batch_result: Optional[CatalogPublicationBatchResult] = None
    if not simulate_network_failure:
        try:
            raw_result = adapter.publish_catalog(net_payload)
            if omit_operation_keys:
                filtered_results = tuple(
                    r for r in raw_result.results if r.operation_key not in set(omit_operation_keys)
                )
                batch_result = CatalogPublicationBatchResult(
                    batch_id=raw_result.batch_id,
                    results=filtered_results,
                    code=raw_result.code,
                )
            else:
                batch_result = raw_result
        except Exception:
            batch_result = None

    # =========================================================================
    # FASE 3: Transação Local 2 (Aplicação de resultados com regras anti-inversão)
    # =========================================================================
    with session_factory() as session:
        batch = session.exec(
            select(ChannelPublicationBatch)
            .where(
                ChannelPublicationBatch.id == batch_id,
                ChannelPublicationBatch.tenant_id == tenant_id,
            )
            .with_for_update()
        ).first()

        if batch_result is None:
            # Queda de rede ou resposta não recebida: lote permanece em PARTIAL
            # com tentativas registradas, pronto para retomada
            batch.status = PublicationStatusEnum.PARTIAL
            batch.updated_at = datetime.utcnow()
            session.commit()
            return batch_projection(session, batch)

        items_map = {
            i.provider_operation_key: i
            for i in session.exec(
                select(ChannelPublicationItem).where(ChannelPublicationItem.batch_id == batch.id)
            ).all()
        }

        for res in batch_result.results:
            item = items_map.get(res.operation_key)
            if not item:
                continue

            item.attempt_count += 1
            item.updated_at = datetime.utcnow()

            offer = session.exec(
                select(ChannelCatalogOffer)
                .where(ChannelCatalogOffer.id == item.offer_id)
                .with_for_update()
            ).first()

            if res.status == "SUCCEEDED":
                item.status = PublicationItemStatusEnum.SUCCEEDED
                item.provider_result_ref = res.provider_result_ref
                item.error_code = None
                item.error_message = None

                if offer:
                    # Invariante 5: Atualização monotônica
                    # Apenas avança published_version se esta versão for estritamente mais recente
                    if item.desired_version > offer.published_version:
                        offer.published_version = item.desired_version
                        offer.last_publication_status = PublicationItemStatusEnum.SUCCEEDED
                    elif item.desired_version == offer.published_version:
                        offer.last_publication_status = PublicationItemStatusEnum.SUCCEEDED
                    else:
                        # Confirmação tardia de versão antiga: não regride versão nem status da mais nova!
                        pass
            else:
                item.status = PublicationItemStatusEnum.FAILED
                item.error_code = res.error_code or "PROVIDER_REJECTED"
                item.error_message = res.error_message

                if offer:
                    # Invariante 5: Falha antiga não sobrescreve sucesso posterior
                    if item.desired_version >= offer.published_version:
                        offer.last_publication_status = PublicationItemStatusEnum.FAILED
                    else:
                        # Versão mais nova já foi publicada com sucesso; erro de versão anterior ignorado na oferta
                        pass

        all_items = list(items_map.values())
        if all(i.status == PublicationItemStatusEnum.SUCCEEDED for i in all_items):
            batch.status = PublicationStatusEnum.SUCCEEDED
        elif all(i.status == PublicationItemStatusEnum.FAILED for i in all_items):
            batch.status = PublicationStatusEnum.FAILED
        else:
            batch.status = PublicationStatusEnum.PARTIAL

        batch.updated_at = datetime.utcnow()
        session.commit()
        return batch_projection(session, batch)


def resume_publication(
    session_factory: Callable[[], Session],
    tenant_id: uuid.UUID,
    batch_id: uuid.UUID,
) -> dict:
    """Retoma um lote de publicação interrompido ou com falhas parciais.

    1. Consulta itens pendentes junto ao canal via `check_catalog_status`
       usando a `provider_operation_key` estável (cenário de confirmação perdida).
    2. Aplica confirmações encontradas.
    3. Reenvia apenas itens que permanecerem pendentes/com falha retentável.
    """
    # Etapa 1: Identificar itens não sucedidos
    with session_factory() as session:
        batch = session.exec(
            select(ChannelPublicationBatch).where(
                ChannelPublicationBatch.id == batch_id,
                ChannelPublicationBatch.tenant_id == tenant_id,
            )
        ).first()
        if not batch or batch.status == PublicationStatusEnum.SUCCEEDED:
            return batch_projection(session, batch) if batch else {}

        conn = session.get(MerchantConnection, batch.merchant_connection_id)
        items = list(
            session.exec(
                select(ChannelPublicationItem).where(
                    ChannelPublicationItem.batch_id == batch.id,
                    ChannelPublicationItem.status != PublicationItemStatusEnum.SUCCEEDED,
                )
            ).all()
        )
        if not items:
            batch.status = PublicationStatusEnum.SUCCEEDED
            session.commit()
            return batch_projection(session, batch)

        unresolved_keys = [i.provider_operation_key for i in items]
        provider_code = conn.provider_code
        merchant_ext_id = conn.merchant_external_id

    # Etapa 2: Consultar conector fora da transação
    adapter = adapter_for(provider_code)
    require(adapter, ChannelCapability.CATALOG_PUBLICATION)

    recovered_results = ()
    if hasattr(adapter, "check_catalog_status"):
        try:
            recovered_results = adapter.check_catalog_status(merchant_ext_id, tuple(unresolved_keys))
        except Exception:
            recovered_results = ()

    # Se o conector confirmou itens perdidos, aplica na base
    if recovered_results:
        with session_factory() as session:
            batch = session.get(ChannelPublicationBatch, batch_id)
            items_by_key = {
                i.provider_operation_key: i
                for i in session.exec(
                    select(ChannelPublicationItem).where(ChannelPublicationItem.batch_id == batch_id)
                ).all()
            }
            for res in recovered_results:
                it = items_by_key.get(res.operation_key)
                if it and res.status == "SUCCEEDED":
                    it.status = PublicationItemStatusEnum.SUCCEEDED
                    it.provider_result_ref = res.provider_result_ref
                    it.error_code = None
                    offer = session.get(ChannelCatalogOffer, it.offer_id)
                    if offer and it.desired_version >= offer.published_version:
                        offer.published_version = it.desired_version
                        offer.last_publication_status = PublicationItemStatusEnum.SUCCEEDED

            all_items = list(items_by_key.values())
            if all(i.status == PublicationItemStatusEnum.SUCCEEDED for i in all_items):
                batch.status = PublicationStatusEnum.SUCCEEDED
            elif any(i.status == PublicationItemStatusEnum.SUCCEEDED for i in all_items):
                batch.status = PublicationStatusEnum.PARTIAL
            batch.updated_at = datetime.utcnow()
            session.commit()

    # Etapa 3: Executar reenvio para qualquer item que ainda reste não sucedido
    return execute_publication(session_factory, tenant_id, batch_id)

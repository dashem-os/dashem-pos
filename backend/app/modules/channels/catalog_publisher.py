"""Executor e sincronizador de catálogo do Channel Hub (S13.2).

Implementa a primeira fatia fundacional do publicador de catálogo:
1. Reuso estrito de ChannelCatalogOffer, ChannelPublicationBatch e ChannelPublicationItem.
2. Separação de snapshot_version (lote) da desired_version individual de cada oferta.
3. Atribuição sequencial de snapshot_version serializada por conexão via bloqueio transacional.
4. Congelamento integral por item (frozen_payload com snapshot dos atributos no momento da criação).
   Validação estrita antes do envio: lotes legados sem snapshot permanecem não publicáveis (422).
5. Separação de hashes: request_hash (idempotência do comando) vs. content_hash (conteúdo congelado).
   Reconhecimento do algoritmo legado de request_hash para compatibilidade com lotes existentes.
6. Uma chave de operação, um conteúdo:
   - Mudanças de produto (título/SKU) e oferta (preço/disponibilidade) avançam a desired_version.
   - Identidade operacional atrelada ao conteúdo; proibida mesma chave com hashes divergentes.
   - Reenvios preservam a identidade estável e o conteúdo originais.
7. Convergência monotônica e proteção contra respostas fora de ordem:
   - Regras unificadas em apply_item_results_to_offers para execute, resume e apply_results.
   - Bloqueio ordenado de ofertas (ORDER BY id FOR UPDATE) sem I/O de rede durante os locks.
   - Confirmação de versão antiga não sobrescreve versão nova já confirmada.
   - Falha tardia não desfaz sucesso confirmado.
8. Aquisição durável de execução (durable lease):
   - Evita despachos simultâneos locais por dois executores.
   - Registro de tentativas persistido antes de qualquer chamada de rede.
   - NOTA: Concessão local não substitui desduplicação externa do canal (idempotência do provedor).
9. Chamadas de rede executadas ESTRITAMENTE fora de transações abertas de banco de dados (zero conexões retidas).
10. Suporte agnóstico aos três nichos (alimentação, varejo e beleza) e combinações.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
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
from app.services import reliability_service

logger = logging.getLogger("dashem.channel_catalog")


def _serialize_for_hash(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_content_hash(items_payload: Sequence[Mapping[str, Any]]) -> str:
    canonical = sorted(items_payload, key=lambda x: str(x.get("offer_id", "")))
    return hashlib.sha256(_serialize_for_hash(canonical).encode("utf-8")).hexdigest()


def compute_request_hash(data: Mapping[str, Any]) -> str:
    return hashlib.sha256(_serialize_for_hash(data).encode("utf-8")).hexdigest()


def _matches_request_hash(stored_hash: str, req_data: Mapping[str, Any]) -> bool:
    """Verifica correspondência com o hash canônico atual ou com o algoritmo legado do reliability_service."""
    current_digest = compute_request_hash(req_data)
    if stored_hash == current_digest:
        return True
    legacy_digest = reliability_service.compute_request_hash(req_data)
    if stored_hash == legacy_digest:
        return True
    return False


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


def validate_frozen_payload(item: ChannelPublicationItem) -> Mapping[str, Any]:
    """Valida o conteúdo congelado antes do envio.

    Rejeita lotes legados sem snapshot ou payloads incompletos, sem recorrer
    a defaults que distorçam dados (como preço zero, produto None ou disponibilidade True).
    """
    fp = item.frozen_payload
    if not fp or not isinstance(fp, dict):
        raise HTTPException(
            422,
            f"Lote sem snapshot congelado válido para o item da oferta {item.offer_id}. "
            "Lotes legados sem snapshot não são publicáveis; crie um novo lote de publicação com snapshot explícito."
        )

    price_raw = fp.get("price")
    if price_raw is None:
        raise HTTPException(422, f"Snapshot do item {item.offer_id} sem campo 'price' obrigatório.")
    try:
        price = Decimal(str(price_raw))
        if not price.is_finite() or price < 0:
            raise ValueError()
    except Exception:
        raise HTTPException(422, f"Snapshot do item {item.offer_id} com 'price' inválido: {price_raw}.")

    prod_id = fp.get("product_id")
    if not prod_id or str(prod_id).strip() == "" or str(prod_id).lower() == "none":
        raise HTTPException(422, f"Snapshot do item {item.offer_id} sem 'product_id' canônico válido.")

    avail = fp.get("available")
    if not isinstance(avail, bool):
        raise HTTPException(422, f"Snapshot do item {item.offer_id} com 'available' ausente ou não booleano.")

    stock_raw = fp.get("stock_quantity")
    stock_qty = None
    if stock_raw is not None:
        try:
            stock_qty = Decimal(str(stock_raw))
            if not stock_qty.is_finite() or stock_qty < 0:
                raise ValueError()
        except Exception:
            raise HTTPException(422, f"Snapshot do item {item.offer_id} com 'stock_quantity' inválido: {stock_raw}.")

    return {
        "price": price,
        "product_id": str(prod_id),
        "available": avail,
        "stock_quantity": stock_qty,
        "sku": fp.get("sku"),
        "title": fp.get("title"),
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

    Garante:
    - Atribuição sequencial protegida de snapshot_version por conexão (bloqueio ordenado da conexão).
    - Idempotência estrita: rechamada concorrente ou sequencial com mesma Idempotency-Key e payload
      recupera o lote existente sem expor IntegrityError; divergência real resulta em 409.
    - Reconhecimento do algoritmo anterior de request_hash para lotes legados.
    - Uma chave de operação, um conteúdo: alterações em título/SKU, preço ou disponibilidade avançam
      a versão desejada da oferta; mesma chave não é permitida com hashes de conteúdo divergentes.
    """
    act = resolve_actor(context, actor_id)

    # 1. Bloqueia a linha da conexão no banco para serializar a versão sequencial do snapshot
    conn = session.exec(
        scope_tenant_query(
            select(MerchantConnection).where(MerchantConnection.id == connection_id).with_for_update(),
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

    # 2. Verificação prévia de idempotência
    existing = session.exec(
        select(ChannelPublicationBatch).where(
            ChannelPublicationBatch.tenant_id == context.tenant_id,
            ChannelPublicationBatch.idempotency_key == idempotency_key,
        )
    ).first()
    if existing:
        if not _matches_request_hash(existing.request_hash, req_data):
            raise HTTPException(409, "Idempotency-Key reutilizada com payload divergente.")
        return batch_projection(session, existing)

    # 3. Carregar e bloquear ofertas ordenadamente (ORDER BY id)
    sorted_unique_ids = sorted(list(set(offer_ids)))
    offers = list(
        session.exec(
            select(ChannelCatalogOffer).where(
                ChannelCatalogOffer.id.in_(sorted_unique_ids),
                ChannelCatalogOffer.merchant_connection_id == conn.id,
            ).order_by(ChannelCatalogOffer.id).with_for_update()
        ).all()
    )
    if len(offers) != len(sorted_unique_ids):
        raise HTTPException(404, "Uma ou mais ofertas de canal não foram encontradas.")

    products_by_id = {
        p.id: p
        for p in session.exec(
            select(Product).where(Product.id.in_([o.product_id for o in offers]))
        ).all()
    }

    # 4. Versão sequencial do snapshot serializada pela transação da conexão
    max_snap = session.exec(
        select(func.max(ChannelPublicationBatch.snapshot_version)).where(
            ChannelPublicationBatch.tenant_id == context.tenant_id,
            ChannelPublicationBatch.merchant_connection_id == conn.id,
        )
    ).first()
    snapshot_version = (max_snap or 0) + 1

    frozen_list = []
    items_to_create = []

    # 5. Processamento dos itens e amarração de chave a conteúdo
    for offer in offers:
        prod = products_by_id.get(offer.product_id)
        if not prod:
            raise HTTPException(404, f"Produto canônico da oferta {offer.id} não encontrado.")

        # Verifica se o item anterior possuía conteúdo diferente (título, SKU, preço, disponibilidade, estoque)
        latest_item = session.exec(
            select(ChannelPublicationItem)
            .where(ChannelPublicationItem.offer_id == offer.id)
            .order_by(ChannelPublicationItem.created_at.desc())
        ).first()

        if latest_item and latest_item.frozen_payload:
            prev_fp = latest_item.frozen_payload
            content_changed = (
                prev_fp.get("title") != prod.name
                or prev_fp.get("sku") != prod.sku
                or prev_fp.get("price") != str(offer.price)
                or prev_fp.get("available") != offer.available
                or prev_fp.get("stock_quantity") != (str(offer.stock_quantity) if offer.stock_quantity is not None else None)
            )
            # Se o conteúdo mudou mas desired_version ainda não avançou, incrementa a versão da oferta
            if content_changed and offer.desired_version <= latest_item.desired_version:
                offer.desired_version = latest_item.desired_version + 1
                offer.last_publication_status = PublicationItemStatusEnum.PENDING
                offer.updated_at = datetime.utcnow()
                session.add(offer)

        frozen = {
            "offer_id": str(offer.id),
            "product_id": str(offer.product_id),
            "desired_version": offer.desired_version,
            "price": str(offer.price),
            "available": offer.available,
            "stock_quantity": str(offer.stock_quantity) if offer.stock_quantity is not None else None,
            "sku": prod.sku,
            "title": prod.name,
        }
        frozen_list.append(frozen)

        # Chave de operação unívoca atrelada ao conteúdo e à versão
        item_content_hash = compute_content_hash([frozen])[:10]
        op_key = f"pub:{conn.id}:{offer.id}:v{offer.desired_version}:{item_content_hash}"

        # Validação estrita: não permitir a mesma chave com hashes de conteúdo divergentes
        prior_items_with_key = session.exec(
            select(ChannelPublicationItem).where(ChannelPublicationItem.provider_operation_key == op_key)
        ).all()
        for prior_item in prior_items_with_key:
            if prior_item and prior_item.frozen_payload:
                prior_hash = compute_content_hash([prior_item.frozen_payload])[:10]
                if prior_hash != item_content_hash:
                    raise HTTPException(409, f"A chave de operação '{op_key}' já foi utilizada com conteúdo divergente.")

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

    try:
        session.flush()
    except IntegrityError:
        # Colisão concorrente na chave de idempotência do lote
        session.rollback()
        existing = session.exec(
            select(ChannelPublicationBatch).where(
                ChannelPublicationBatch.tenant_id == context.tenant_id,
                ChannelPublicationBatch.idempotency_key == idempotency_key,
            )
        ).first()
        if existing:
            if not _matches_request_hash(existing.request_hash, req_data):
                raise HTTPException(409, "Idempotency-Key reutilizada com payload divergente.")
            return batch_projection(session, existing)
        raise

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

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(ChannelPublicationBatch).where(
                ChannelPublicationBatch.tenant_id == context.tenant_id,
                ChannelPublicationBatch.idempotency_key == idempotency_key,
            )
        ).first()
        if existing:
            if not _matches_request_hash(existing.request_hash, req_data):
                raise HTTPException(409, "Idempotency-Key reutilizada com payload divergente.")
            return batch_projection(session, existing)
        raise

    session.refresh(batch)
    return batch_projection(session, batch)


def apply_item_results_to_offers(
    session: Session,
    batch: ChannelPublicationBatch,
    items_map: Mapping[str, ChannelPublicationItem],
    results: Sequence[CatalogPublicationItemResult],
) -> None:
    """Aplica monotonicamente os resultados do conector sobre ofertas e itens do lote.

    Regras canônicas unificadas (execute_publication, resume_publication, apply_results):
    1. Valida correspondência de cada resultado a um item existente do lote.
    2. Adquire locks ordenados sobre as ofertas envolvidas (ORDER BY id FOR UPDATE),
       atualizando o identity map da sessão (populate_existing=True).
    3. Atualização estritamente monotônica:
       - Confirmação de versão antiga não sobrescreve versão nova já confirmada.
       - Falha antiga não sobrescreve status de sucesso já confirmado para versão igual ou posterior.
       - Falha tardia não rebaixa item ou lote já confirmado com SUCCEEDED.
       - Apenas versão estritamente mais recente ou versão igual atualizam published_version e status.
    4. Recalcula o status do lote (preservando SUCCEEDED caso já confirmado).
    """
    now = datetime.utcnow()

    # 1. Validar identidade dos resultados
    matched_entries = []
    for res in results:
        item = items_map.get(res.operation_key)
        if not item:
            # Resultado para chave não pertencente a este lote é ignorado
            continue
        matched_entries.append((item, res))

    if matched_entries:
        # 2. Bloqueio ordenado das ofertas envolvidas com recarga do identity map
        distinct_offer_ids = sorted(list({item.offer_id for item, _ in matched_entries}))
        offers = list(
            session.exec(
                select(ChannelCatalogOffer)
                .where(ChannelCatalogOffer.id.in_(distinct_offer_ids))
                .order_by(ChannelCatalogOffer.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        offers_by_id = {o.id: o for o in offers}

        # 3. Aplicação monotônica
        for item, res in matched_entries:
            item.updated_at = now
            offer = offers_by_id.get(item.offer_id)

            if res.status == "SUCCEEDED":
                item.status = PublicationItemStatusEnum.SUCCEEDED
                item.provider_result_ref = res.provider_result_ref
                item.error_code = None
                item.error_message = None

                if offer:
                    if item.desired_version > offer.published_version:
                        offer.published_version = item.desired_version
                        offer.last_publication_status = PublicationItemStatusEnum.SUCCEEDED
                        offer.updated_at = now
                        session.add(offer)
                    elif item.desired_version == offer.published_version:
                        offer.last_publication_status = PublicationItemStatusEnum.SUCCEEDED
                        offer.updated_at = now
                        session.add(offer)
                    else:
                        # Confirmação atrasada de versão antiga: não regride versão nem sucesso atual!
                        pass
            elif res.status == "FAILED":
                # Proteção estrita: sucesso confirmado não é revertido por falha tardia!
                if item.status == PublicationItemStatusEnum.SUCCEEDED:
                    logger.warning(
                        "Falha tardia ignorada para item %s (chave: %s) já confirmado com sucesso na versão %s.",
                        item.id, item.provider_operation_key, item.desired_version,
                    )
                    continue

                item.status = PublicationItemStatusEnum.FAILED
                item.error_code = res.error_code or "PROVIDER_REJECTED"
                item.error_message = res.error_message

                if offer:
                    if item.desired_version > offer.published_version:
                        offer.last_publication_status = PublicationItemStatusEnum.FAILED
                        offer.updated_at = now
                        session.add(offer)
                    elif item.desired_version == offer.published_version:
                        # Se a oferta já alcançou SUCCEEDED para esta versão, falha atrasada não desfaz o sucesso!
                        if offer.last_publication_status != PublicationItemStatusEnum.SUCCEEDED:
                            offer.last_publication_status = PublicationItemStatusEnum.FAILED
                            offer.updated_at = now
                            session.add(offer)
                    else:
                        # Falha de versão anterior ignorada na oferta pois versão posterior já está vigente
                        pass

    # 4. Recalcular status do lote (preservando SUCCEEDED se já confirmado)
    if batch.status == PublicationStatusEnum.SUCCEEDED:
        # Lote já confirmado com sucesso: falha tardia não desfaz o status do lote!
        pass
    else:
        all_items = list(items_map.values())
        if all(i.status == PublicationItemStatusEnum.SUCCEEDED for i in all_items):
            batch.status = PublicationStatusEnum.SUCCEEDED
        elif all(i.status == PublicationItemStatusEnum.FAILED for i in all_items):
            batch.status = PublicationStatusEnum.FAILED
        else:
            batch.status = PublicationStatusEnum.PARTIAL

    batch.updated_at = now


def execute_publication(
    session_factory: Callable[[], Session],
    tenant_id: uuid.UUID,
    batch_id: uuid.UUID,
    *,
    lease_token: Optional[str] = None,
    simulate_network_failure: bool = False,
    omit_operation_keys: Sequence[str] = (),
    simulate_crash_before_confirmation: bool = False,
    on_before_phase3: Optional[Callable[[], None]] = None,
) -> dict:
    """Executa o envio do lote ao canal respeitando estritamente:

    1. Aquisição durável de execução (lease com expiração e token) impedindo múltiplos executores simultâneos.
    2. Verificação do lease_token sob bloqueio antes de qualquer alteração de estado ou liberação.
    3. Registro de tentativa gravado no banco ANTES de qualquer chamada de rede.
    4. Validação estrita do snapshot congelado (lotes legados sem snapshot rejeitados com 422).
    5. Chamadas de rede executadas FORA de transações abertas do banco (zero conexões retidas no pool).
    6. Preservação de operation_keys já armazenadas no banco (inclusive prefixos legados).
    7. Atualização monotônica com bloqueios ordenados e populate_existing=True via apply_item_results_to_offers.

    NOTA DE ARQUITETURA:
    O lease durável protege contra corridas concorrentes locais no Dashem POS. Contudo,
    a deduplicação externa no provedor permanece mandatória pela chave estável de operação e seu conteúdo,
    uma vez que quedas de rede e timeouts podem levar a tentativas repetidas de entrega junto ao canal.
    """
    # =========================================================================
    # FASE 1: Transação Local 1 (Lease durável, validação de payload e registro de tentativa)
    # =========================================================================
    with session_factory() as session:
        batch = session.exec(
            select(ChannelPublicationBatch)
            .where(
                ChannelPublicationBatch.id == batch_id,
                ChannelPublicationBatch.tenant_id == tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if not batch:
            raise HTTPException(404, "Lote não encontrado.")

        if batch.status == PublicationStatusEnum.SUCCEEDED:
            return batch_projection(session, batch)

        now = datetime.utcnow()

        # Proteção de lease durável contra executores concorrentes
        if batch.lease_expires_at and batch.lease_expires_at > now:
            if lease_token and batch.lease_token == lease_token:
                # Mesmo executor autorizado (ex.: continuação pela retomada)
                pass
            else:
                raise HTTPException(409, "Lote já está sendo executado por outro processo.")

        active_token = lease_token or uuid.uuid4().hex
        batch.lease_token = active_token
        batch.lease_expires_at = now + timedelta(seconds=60)
        batch.status = PublicationStatusEnum.PROCESSING
        batch.updated_at = now

        conn = session.get(MerchantConnection, batch.merchant_connection_id)
        if not conn:
            raise HTTPException(404, "Conexão de merchant não encontrada.")

        items = list(
            session.exec(
                select(ChannelPublicationItem)
                .where(ChannelPublicationItem.batch_id == batch.id)
                .order_by(ChannelPublicationItem.created_at)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )

        # Seleciona apenas itens que ainda não foram confirmados com sucesso
        items_to_send = [i for i in items if i.status != PublicationItemStatusEnum.SUCCEEDED]

        payload_items = []
        for it in items_to_send:
            # Validação estrita do payload congelado (rejeita lotes legados ou incompletos com 422)
            valid_fp = validate_frozen_payload(it)

            # Registra tentativa ANTES de qualquer I/O de rede
            it.attempt_count += 1
            it.updated_at = now

            payload_items.append(
                CatalogPublicationItemPayload(
                    operation_key=it.provider_operation_key,
                    offer_id=str(it.offer_id),
                    product_id=valid_fp["product_id"],
                    desired_version=it.desired_version,
                    price=valid_fp["price"],
                    available=valid_fp["available"],
                    stock_quantity=valid_fp["stock_quantity"],
                    sku=valid_fp["sku"],
                    title=valid_fp["title"],
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

    if on_before_phase3:
        on_before_phase3()

    if simulate_crash_before_confirmation:
        # Simula crash do executor após o envio ao canal e antes de gravar a confirmação no banco
        raise RuntimeError("Crash simulado do executor antes da gravação da confirmação.")

    # =========================================================================
    # FASE 3: Transação Local 2 (Aplicação monotônica e liberação do lease sob conferência)
    # =========================================================================
    with session_factory() as session:
        batch = session.exec(
            select(ChannelPublicationBatch)
            .where(
                ChannelPublicationBatch.id == batch_id,
                ChannelPublicationBatch.tenant_id == tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if not batch:
            raise HTTPException(404, "Lote não encontrado.")

        # VERIFICAÇÃO ESTRITA DO LEASE:
        # Se o lease_token atual difere do active_token deste executor,
        # a concessão expirou e outro executor assumiu.
        # Este executor atrasado NÃO pode apagar a concessão de outro nem sobrescrever o lote!
        if batch.lease_token != active_token:
            logger.warning(
                "Executor atrasado perdeu concessão do lote %s (esperado: %s, atual: %s).",
                batch.id, active_token, batch.lease_token,
            )
            session.rollback()
            raise HTTPException(409, "A concessão de execução deste lote expirou e foi assumida por outro executor.")

        # Libera o lease durável após conclusão da tentativa sob titularidade comprovada
        batch.lease_token = None
        batch.lease_expires_at = None

        if batch_result is None:
            # Queda de rede ou resposta não recebida: lote permanece em PARTIAL,
            # com tentativas registradas antes do I/O, pronto para recuperação
            batch.status = PublicationStatusEnum.PARTIAL
            batch.updated_at = datetime.utcnow()
            session.commit()
            return batch_projection(session, batch)

        items_map = {
            i.provider_operation_key: i
            for i in session.exec(
                select(ChannelPublicationItem)
                .where(ChannelPublicationItem.batch_id == batch.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        }

        apply_item_results_to_offers(session, batch, items_map, batch_result.results)
        session.commit()
        return batch_projection(session, batch)


def resume_publication(
    session_factory: Callable[[], Session],
    tenant_id: uuid.UUID,
    batch_id: uuid.UUID,
) -> dict:
    """Retoma um lote de publicação interrompido ou com falhas parciais.

    1. Bloqueia o lote e verifica se outro executor mantém concessão ativa (409 se ativo).
    2. Adquire concessão durável para a retomada (impede múltiplos executores concorrentes).
    3. Consulta itens pendentes junto ao conector via `check_catalog_status`
       usando a `provider_operation_key` estável (cenário de confirmação perdida).
    4. Aplica confirmações registradas via `apply_item_results_to_offers` com bloqueios ordenados
       e populate_existing=True.
    5. Se todos os itens foram solucionados, conclui como SUCCEEDED sem reenvio ao conector.
    6. Se restarem itens não resolvidos/pendentes, executa reenvio com `execute_publication`
       preservando a concessão adquirida.
    """
    # Etapa 1: Identificar itens não sucedidos e adquirir concessão da retomada sob lock
    with session_factory() as session:
        batch = session.exec(
            select(ChannelPublicationBatch).where(
                ChannelPublicationBatch.id == batch_id,
                ChannelPublicationBatch.tenant_id == tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if not batch:
            raise HTTPException(404, "Lote não encontrado.")

        if batch.status == PublicationStatusEnum.SUCCEEDED:
            return batch_projection(session, batch)

        now = datetime.utcnow()
        # A retomada não pode habilitar reenvio enquanto outro executor mantém concessão válida ativa
        if batch.lease_expires_at and batch.lease_expires_at > now:
            raise HTTPException(409, "Lote já está sendo executado por outro processo (concessão ativa).")

        conn = session.get(MerchantConnection, batch.merchant_connection_id)
        items = list(
            session.exec(
                select(ChannelPublicationItem).where(
                    ChannelPublicationItem.batch_id == batch.id,
                    ChannelPublicationItem.status != PublicationItemStatusEnum.SUCCEEDED,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        if not items:
            batch.status = PublicationStatusEnum.SUCCEEDED
            batch.lease_token = None
            batch.lease_expires_at = None
            session.commit()
            return batch_projection(session, batch)

        # Adquire concessão para a retomada protegendo contra novos despachos concorrentes
        resume_token = uuid.uuid4().hex
        batch.lease_token = resume_token
        batch.lease_expires_at = now + timedelta(seconds=60)
        batch.status = PublicationStatusEnum.PROCESSING
        batch.updated_at = now

        unresolved_keys = [i.provider_operation_key for i in items]
        provider_code = conn.provider_code
        merchant_ext_id = conn.merchant_external_id
        session.commit()

    # Etapa 2: Consultar conector FORA de transação aberta
    adapter = adapter_for(provider_code)
    require(adapter, ChannelCapability.CATALOG_PUBLICATION)

    recovered_results = ()
    if hasattr(adapter, "check_catalog_status"):
        try:
            recovered_results = adapter.check_catalog_status(merchant_ext_id, tuple(unresolved_keys))
        except Exception:
            recovered_results = ()

    # Etapa 3: Aplicar confirmações efetivamente registradas (ignora UNKNOWN / não encontradas)
    conclusive_results = [r for r in recovered_results if r.status in ("SUCCEEDED", "FAILED")]
    with session_factory() as session:
        batch = session.exec(
            select(ChannelPublicationBatch).where(
                ChannelPublicationBatch.id == batch_id,
                ChannelPublicationBatch.tenant_id == tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if not batch:
            raise HTTPException(404, "Lote não encontrado.")

        # Confere se a concessão da retomada ainda pertence a esta execução
        if batch.lease_token != resume_token:
            session.rollback()
            raise HTTPException(409, "A concessão da retomada expirou e foi assumida por outro executor.")

        if conclusive_results:
            items_map = {
                i.provider_operation_key: i
                for i in session.exec(
                    select(ChannelPublicationItem).where(ChannelPublicationItem.batch_id == batch_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                ).all()
            }
            apply_item_results_to_offers(session, batch, items_map, conclusive_results)

        # Checa se todos os itens foram concluídos com sucesso após a aplicação da consulta
        all_items = list(
            session.exec(
                select(ChannelPublicationItem).where(ChannelPublicationItem.batch_id == batch_id)
                .execution_options(populate_existing=True)
            ).all()
        )
        if all(it.status == PublicationItemStatusEnum.SUCCEEDED for it in all_items):
            batch.status = PublicationStatusEnum.SUCCEEDED
            batch.lease_token = None
            batch.lease_expires_at = None
            session.commit()
            return batch_projection(session, batch)

        session.commit()

    # Etapa 4: Se restarem itens pendentes, executa reenvio preservando o token da concessão
    return execute_publication(session_factory, tenant_id, batch_id, lease_token=resume_token)

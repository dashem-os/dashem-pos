import hashlib
import hmac
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.core.tenancy import set_tenant_db_context
from app.models.catalog import SalesChannel, SalesChannelTypeEnum, Product, ProductPrice
from app.models.channel_hub import (
    ChannelInboxEvent, ChannelInboxStatusEnum, ChannelOutboundMessage,
    ExternalOrderMapping, MerchantConnection, MerchantConnectionStatusEnum,
)
from app.models.order import OrderFulfillmentEnum, OrderOriginEnum
from app.modules.capabilities.service import effective_capabilities
from app.providers.channel_adapter import resolve_channel_adapter
from app.services import order_service, reliability_service


def _actor(context: TenantContext, actor_id: Optional[uuid.UUID]) -> uuid.UUID:
    return resolve_actor(context, actor_id)


def _hash(payload: object) -> str:
    return reliability_service.compute_request_hash(payload)


def _webhook_secret(tenant_id: uuid.UUID, idempotency_key: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), f"channel-webhook:{tenant_id}:{idempotency_key}".encode(), hashlib.sha256,
    ).hexdigest()


def create_connection(
    session: Session, context: TenantContext, *, store_id: uuid.UUID,
    provider_code: str, merchant_external_id: str, channel_name: str,
    credentials_ref: Optional[str], actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> tuple[MerchantConnection, str]:
    if context.store_id and context.store_id != store_id:
        raise HTTPException(status_code=403, detail="Conexão fora da unidade ativa.")
    actor = _actor(context, actor_id)
    code = provider_code.strip().upper()
    if code == "CONTRACT_TEST" and settings.ENVIRONMENT.lower() not in {"test", "development"}:
        raise HTTPException(status_code=422, detail="Adapter de contrato existe somente em testes.")
    payload = {
        "store_id": str(store_id), "provider_code": code,
        "merchant_external_id": merchant_external_id, "channel_name": channel_name,
        "credentials_ref": credentials_ref,
    }
    request_hash = _hash(payload)
    existing = session.exec(select(MerchantConnection).where(
        MerchantConnection.tenant_id == context.tenant_id,
        MerchantConnection.idempotency_key == idempotency_key,
    )).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency-Key reutilizada com outro conteúdo.")
        return existing, _webhook_secret(context.tenant_id, idempotency_key)
    try:
        adapter = resolve_channel_adapter(code)
    except LookupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    channel = SalesChannel(
        tenant_id=context.tenant_id, store_id=store_id,
        code=f"{code}-{merchant_external_id}"[:120], name=channel_name,
        channel_type=SalesChannelTypeEnum.MARKETPLACE,
        external_account_id=merchant_external_id, is_active=True,
        configuration={"provider_code": code, "adapter_version": adapter.version},
    )
    session.add(channel); session.flush()
    secret = _webhook_secret(context.tenant_id, idempotency_key)
    connection = MerchantConnection(
        tenant_id=context.tenant_id, store_id=store_id, channel_id=channel.id,
        provider_code=code, adapter_version=adapter.version,
        merchant_external_id=merchant_external_id,
        credentials_ref=credentials_ref, webhook_secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        service_actor_id=uuid.uuid4(), idempotency_key=idempotency_key,
        request_hash=request_hash, configured_by=actor,
    )
    session.add(connection)
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=store_id, actor_id=actor,
        action="channel.connection.created", target=f"MERCHANT-CONNECTION-{connection.id}",
        audit_payload={"provider_code": code, "merchant_external_id": merchant_external_id},
        aggregate_type="merchant_connection", aggregate_id=str(connection.id),
        event_type="channel.connection.created",
        outbox_payload={"provider_code": code, "merchant_external_id": merchant_external_id},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Merchant já configurado neste tenant.") from exc
    session.refresh(connection)
    return connection, secret


def validate_connection(
    session: Session, context: TenantContext, connection_id: uuid.UUID,
    actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> MerchantConnection:
    actor = _actor(context, actor_id)
    payload = {"connection_id": str(connection_id)}
    cached, _, body = reliability_service.check_idempotency(
        session, context.tenant_id, actor, "channel.connection.validate",
        idempotency_key, payload,
    )
    if cached and body:
        cached_connection = session.exec(scope_tenant_query(select(MerchantConnection).where(
            MerchantConnection.id == uuid.UUID(body["connection_id"]),
        ), MerchantConnection, context)).first()
        if not cached_connection:
            raise HTTPException(status_code=409, detail="Resultado anterior da validação não está mais disponível.")
        return cached_connection
    connection = session.exec(scope_tenant_query(select(MerchantConnection).where(
        MerchantConnection.id == connection_id,
    ).with_for_update(), MerchantConnection, context)).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Conexão não encontrada.")
    adapter = resolve_channel_adapter(connection.provider_code)
    connection.status = MerchantConnectionStatusEnum.VALIDATING
    ok, error = adapter.validate_connection(connection.merchant_external_id, connection.credentials_ref)
    connection.last_validated_at = datetime.utcnow()
    connection.updated_at = datetime.utcnow()
    connection.status = MerchantConnectionStatusEnum.CONNECTED if ok else MerchantConnectionStatusEnum.NOT_CONNECTED
    connection.last_error_code = error
    connection.last_error_message = "Validação externa indisponível ou recusada." if error else None
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=connection.store_id, actor_id=actor,
        action="channel.connection.validated", target=f"MERCHANT-CONNECTION-{connection.id}",
        audit_payload={"connected": ok, "error_code": error}, aggregate_type="merchant_connection",
        aggregate_id=str(connection.id), event_type="channel.connection.validated",
        outbox_payload={"status": connection.status.value, "error_code": error},
    )
    session.commit(); session.refresh(connection)
    reliability_service.save_idempotency_record(
        session, context.tenant_id, actor, "channel.connection.validate",
        idempotency_key, payload, 200, {"connection_id": str(connection.id)},
    )
    session.commit()
    return connection


def list_connections(session: Session, context: TenantContext) -> list[MerchantConnection]:
    return list(session.exec(scope_tenant_query(
        select(MerchantConnection).order_by(MerchantConnection.created_at.desc()), MerchantConnection, context,
    )).all())


def list_inbox(session: Session, context: TenantContext, limit: int = 100) -> list[ChannelInboxEvent]:
    return list(session.exec(scope_tenant_query(
        select(ChannelInboxEvent).order_by(ChannelInboxEvent.received_at.desc()).limit(limit), ChannelInboxEvent, context,
    )).all())


def _verify_signature(connection: MerchantConnection, payload: dict, signature: str) -> None:
    secret = _webhook_secret(connection.tenant_id, connection.idempotency_key)
    expected = hmac.new(
        secret.encode(), json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(), hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Assinatura do webhook inválida.")


def receive_event(
    session: Session, *, tenant_id: uuid.UUID, store_id: uuid.UUID,
    connection_id: uuid.UUID, provider_event_id: str, event_type: str,
    payload: dict, signature: str,
) -> ChannelInboxEvent:
    set_tenant_db_context(session, tenant_id, store_id, None)
    connection = session.exec(select(MerchantConnection).where(
        MerchantConnection.id == connection_id,
        MerchantConnection.tenant_id == tenant_id,
        MerchantConnection.store_id == store_id,
    )).first()
    if not connection or connection.status != MerchantConnectionStatusEnum.CONNECTED:
        raise HTTPException(status_code=409, detail="Canal não está conectado e validado.")
    _verify_signature(connection, payload, signature)
    payload_hash = _hash(payload)
    existing = session.exec(select(ChannelInboxEvent).where(
        ChannelInboxEvent.merchant_connection_id == connection.id,
        ChannelInboxEvent.provider_event_id == provider_event_id,
    )).first()
    if existing:
        if existing.payload_hash != payload_hash:
            raise HTTPException(status_code=409, detail="Evento externo reutilizado com payload divergente.")
        return existing
    external_order_id = str(payload.get("external_order_id") or f"unresolved:{provider_event_id}")
    event = ChannelInboxEvent(
        tenant_id=tenant_id, store_id=store_id, merchant_connection_id=connection.id,
        provider_event_id=provider_event_id, external_order_id=external_order_id,
        event_type=event_type, payload_hash=payload_hash, raw_payload=payload,
    )
    session.add(event); session.commit(); session.refresh(event)
    # Acknowledgment is only recorded after the inbox row is durable.
    event.acknowledged_at = datetime.utcnow(); session.commit(); session.refresh(event)
    # The provider identity is server-issued and cannot be selected by the
    # webhook payload.  Downstream services therefore see the persisted
    # service principal as their authoritative context actor.
    effective = effective_capabilities(session, tenant_id, store_id)
    context = TenantContext(
        tenant_id=tenant_id, store_id=store_id,
        user_id=connection.service_actor_id,
        auth_subject=f"service:channel:{connection.id}",
        capabilities=tuple(effective.keys()),
    )
    mapping = session.exec(select(ExternalOrderMapping).where(
        ExternalOrderMapping.merchant_connection_id == connection.id,
        ExternalOrderMapping.external_order_id == external_order_id,
    )).first()
    if mapping:
        event.status = ChannelInboxStatusEnum.DUPLICATE
        event.order_id = mapping.order_id
        event.processed_at = datetime.utcnow(); session.commit(); session.refresh(event)
        return event
    try:
        normalized = resolve_channel_adapter(connection.provider_code).normalize(payload)
        # Validate the whole payload before creating any canonical aggregate.
        prepared = []
        for raw in normalized.items:
            product_id = uuid.UUID(raw.product_id)
            product = session.exec(select(Product).where(
                Product.id == product_id, Product.tenant_id == tenant_id,
                Product.is_active.is_(True), Product.available_for_sale.is_(True),
            )).first()
            price = session.exec(select(ProductPrice).where(
                ProductPrice.tenant_id == tenant_id, ProductPrice.product_id == product_id,
                ProductPrice.store_id == store_id,
            )).first()
            modifier_ids = [uuid.UUID(item) for item in raw.modifier_ids]
            if not product or not price:
                raise ValueError(f"Produto {product_id} sem cadastro/preço efetivo.")
            order_service._modifiers(session, context, product_id, modifier_ids)
            prepared.append((product_id, Decimal(raw.quantity), modifier_ids, raw.notes))
        event.status = ChannelInboxStatusEnum.NORMALIZED; session.commit()
        order = order_service.create_order(
            session, context, store_id=store_id,
            idempotency_key=f"channel:{connection.id}:{normalized.external_order_id}",
            actor_id=connection.service_actor_id, register_id=None, customer_id=None,
            table_id=None, table_session_id=None, sale_id=None, channel_id=connection.channel_id,
            origin=OrderOriginEnum.SALES_CHANNEL,
            fulfillment=OrderFulfillmentEnum(normalized.fulfillment),
            external_reference=normalized.external_order_id,
            notes=normalized.notes or (f"Cliente: {normalized.customer_name}" if normalized.customer_name else None),
        )
        for index, (product_id, quantity, modifier_ids, notes) in enumerate(prepared):
            order_service.add_item(
                session, context, order.id, product_id=product_id, quantity=quantity,
                modifier_ids=modifier_ids, notes=notes,
                idempotency_key=f"channel-item:{event.id}:{index}", actor_id=connection.service_actor_id,
            )
        mapping = ExternalOrderMapping(
            tenant_id=tenant_id, store_id=store_id, merchant_connection_id=connection.id,
            external_order_id=normalized.external_order_id, order_id=order.id,
            payment_origin=normalized.payment_origin,
        )
        session.add(mapping)
        event.order_id = order.id
        event.status = ChannelInboxStatusEnum.PROCESSED
        event.processed_at = datetime.utcnow()
        connection.last_event_at = event.processed_at
        reliability_service.write_audit_and_outbox(
            session=session, tenant_id=tenant_id, store_id=store_id,
            actor_id=connection.service_actor_id, action="channel.inbox.processed",
            target=f"CHANNEL-INBOX-{event.id}", audit_payload={
                "provider_event_id": provider_event_id, "external_order_id": normalized.external_order_id,
                "order_id": str(order.id), "payment_origin": normalized.payment_origin,
            }, aggregate_type="channel_inbox", aggregate_id=str(event.id),
            event_type="channel.inbox.processed", outbox_payload={
                "order_id": str(order.id), "merchant_connection_id": str(connection.id),
                "external_order_id": normalized.external_order_id,
            },
        )
        session.commit(); session.refresh(event)
        return event
    except (ValueError, HTTPException) as exc:
        session.rollback()
        event = session.get(ChannelInboxEvent, event.id)
        event.status = ChannelInboxStatusEnum.QUARANTINED
        event.quarantine_code = "INVALID_EXTERNAL_ORDER"
        event.quarantine_reason = str(exc.detail if isinstance(exc, HTTPException) else exc)[:500]
        event.processed_at = datetime.utcnow()
        session.commit(); session.refresh(event)
        return event


def queue_outbound(
    session: Session, context: TenantContext, order_id: uuid.UUID, *,
    message_type: str, payload: dict, actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> ChannelOutboundMessage:
    actor = _actor(context, actor_id)
    existing = session.exec(select(ChannelOutboundMessage).where(
        ChannelOutboundMessage.tenant_id == context.tenant_id,
        ChannelOutboundMessage.idempotency_key == idempotency_key,
    )).first()
    request_hash = _hash({"order_id": str(order_id), "message_type": message_type, "payload": payload})
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency-Key reutilizada com outro outbound.")
        return existing
    mapping = session.exec(select(ExternalOrderMapping).where(
        ExternalOrderMapping.tenant_id == context.tenant_id,
        ExternalOrderMapping.order_id == order_id,
    )).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Order não possui origem externa.")
    message = ChannelOutboundMessage(
        tenant_id=context.tenant_id, store_id=mapping.store_id,
        merchant_connection_id=mapping.merchant_connection_id, order_id=order_id,
        message_type=message_type, payload=payload, idempotency_key=idempotency_key,
        request_hash=request_hash, created_by=actor,
    )
    session.add(message)
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=mapping.store_id, actor_id=actor,
        action="channel.outbound.queued", target=f"CHANNEL-OUTBOUND-{message.id}",
        audit_payload={"order_id": str(order_id), "message_type": message_type},
        aggregate_type="channel_outbound", aggregate_id=str(message.id),
        event_type="channel.outbound.queued", outbox_payload={
            "merchant_connection_id": str(mapping.merchant_connection_id),
            "order_id": str(order_id), "message_type": message_type, "payload": payload,
        },
    )
    session.commit(); session.refresh(message)
    return message

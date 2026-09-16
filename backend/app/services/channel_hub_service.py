import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.catalog import SalesChannel, SalesChannelTypeEnum
from app.models.channel_hub import (
    ChannelInboxEvent, ChannelOutboundMessage,
    ExternalOrderMapping, MerchantConnection, MerchantConnectionStatusEnum,
)
from app.modules.channels import registry as channel_registry
from app.modules.channels.contracts import ChannelCapability
from app.services import reliability_service


def _actor(context: TenantContext, actor_id: Optional[uuid.UUID]) -> uuid.UUID:
    return resolve_actor(context, actor_id)


def _hash(payload: object) -> str:
    return reliability_service.compute_request_hash(payload)


def create_connection(
    session: Session, context: TenantContext, *, store_id: uuid.UUID,
    provider_code: str, merchant_external_id: str, channel_name: str,
    credentials_ref: Optional[str], actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> MerchantConnection:
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
        return existing
    # Um provedor sem adaptador pode ser cadastrado: a conexão fica sem nenhuma
    # capacidade, e a tela diz isso (H11). Cadastrar não é conectar.
    adapter = channel_registry.adapter_for(code)
    channel = SalesChannel(
        tenant_id=context.tenant_id, store_id=store_id,
        code=f"{code}-{merchant_external_id}"[:120], name=channel_name,
        channel_type=SalesChannelTypeEnum.MARKETPLACE,
        external_account_id=merchant_external_id, is_active=True,
        configuration={"provider_code": code, "adapter_version": adapter.parser_version},
    )
    session.add(channel); session.flush()
    connection = MerchantConnection(
        tenant_id=context.tenant_id, store_id=store_id, channel_id=channel.id,
        provider_code=code, adapter_version=adapter.parser_version,
        merchant_external_id=merchant_external_id,
        credentials_ref=credentials_ref,
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
    return connection


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
    adapter = channel_registry.adapter_for(connection.provider_code)
    connection.status = MerchantConnectionStatusEnum.VALIDATING
    if ChannelCapability.CONNECTION_VALIDATION in adapter.capabilities:
        outcome = adapter.validate_connection(connection.merchant_external_id)
        ok, error = outcome.connected, outcome.code
    else:
        ok, error = False, "CAPABILITY_NOT_DECLARED"
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
    try:
        session.commit()
    except IntegrityError:
        # A merchant connected in another tenant (migration 098). The ingress
        # resolves a merchant to one connection; two would make delivery ambiguous.
        session.rollback()
        connection = session.exec(scope_tenant_query(select(MerchantConnection).where(
            MerchantConnection.id == connection_id,
        ).with_for_update(), MerchantConnection, context)).first()
        error = "MERCHANT_CONNECTED_ELSEWHERE"
        connection.status = MerchantConnectionStatusEnum.NOT_CONNECTED
        connection.last_validated_at = datetime.utcnow()
        connection.updated_at = datetime.utcnow()
        connection.last_error_code = error
        connection.last_error_message = "Este merchant já está conectado em outra conta."
        reliability_service.write_audit_and_outbox(
            session=session, tenant_id=context.tenant_id, store_id=connection.store_id, actor_id=actor,
            action="channel.connection.validated", target=f"MERCHANT-CONNECTION-{connection.id}",
            audit_payload={"connected": False, "error_code": error}, aggregate_type="merchant_connection",
            aggregate_id=str(connection.id), event_type="channel.connection.validated",
            outbox_payload={"status": connection.status.value, "error_code": error},
        )
        session.commit()
    session.refresh(connection)
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

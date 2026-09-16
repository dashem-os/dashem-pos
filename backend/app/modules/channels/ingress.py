"""The channel's door: verify, find whose event it is, keep it, confirm.

S10.1, step 2 (§3.3). One route per provider, the URL registered on the
channel's portal. Nothing in the body chooses a tenant (H9): the adapter checks
the signature over the bytes received, splits the body into events, and each
event's merchant resolves — on the server — to the one connected connection that
owns it.

Each event is persisted before it is confirmed (H1), already on its retention
clock (D6), in a transaction of its own under the tenant and unit of its
connection. A body can carry events of different merchants; one failing does not
undo the ones already kept, and the channel resending the whole body finds them
as duplicates.

What this step does not do yet: apply events to orders. They wait in `RECEIVED`
for the resumable inbox of step 3. The S10 route `/channels/webhooks` keeps
processing inline until then.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.channel_hub import (
    ChannelInboxEvent, ChannelInboxStatusEnum, ChannelRetentionBasisEnum,
    MerchantConnection, MerchantConnectionStatusEnum,
)
from app.modules.channels import registry, retention
from app.modules.channels.contracts import (
    ChannelAdapter, ChannelCapability, IngressEnvelope, PayloadRejected, SignatureRejected,
)
from app.services import reliability_service

logger = logging.getLogger("dashem_pos.channels.ingress")


class IngressOutcomeEnum:
    RECEIVED = "RECEIVED"
    DUPLICATE = "DUPLICATE"
    DIVERGENT = "DIVERGENT"
    MERCHANT_NOT_CONNECTED = "MERCHANT_NOT_CONNECTED"


@dataclass(frozen=True)
class IngressOutcome:
    provider_event_id: str
    outcome: str


@dataclass(frozen=True)
class _ConnectionScope:
    connection_id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    service_actor_id: uuid.UUID


def receive(provider_code: str, headers: Mapping[str, str], body: bytes) -> list[IngressOutcome]:
    adapter = registry.adapter_for(provider_code)
    if ChannelCapability.ORDER_INGRESS not in adapter.capabilities:
        # A platform that cannot talk to this provider has no door for it.
        raise HTTPException(status_code=404, detail={"code": "PROVIDER_NOT_AVAILABLE"})
    try:
        adapter.verify_signature(headers, body)
    except SignatureRejected as rejection:
        raise HTTPException(status_code=401, detail={"code": rejection.code}) from None
    try:
        envelopes = adapter.envelopes(body)
    except PayloadRejected as rejection:
        raise HTTPException(status_code=400, detail={"code": rejection.code}) from None
    return [_keep(adapter, envelope) for envelope in envelopes]


def _connection_scope(provider_code: str, merchant_external_id: str) -> Optional[_ConnectionScope]:
    """Whose merchant this is — a lookup that cannot be tenant-scoped, because the tenant is the answer.

    Like the TEF bridge credential, it reads with platform visibility in a
    session of its own that answers this one question and closes. Only a
    `CONNECTED` connection owns a merchant, and there is at most one (migration 098).
    """
    with Session(engine) as session:
        set_platform_db_context(session)
        connection = session.exec(select(MerchantConnection).where(
            MerchantConnection.provider_code == provider_code,
            MerchantConnection.merchant_external_id == merchant_external_id,
            MerchantConnection.status == MerchantConnectionStatusEnum.CONNECTED,
        )).first()
        if connection is None:
            return None
        return _ConnectionScope(connection.id, connection.tenant_id, connection.store_id, connection.service_actor_id)


def _keep(adapter: ChannelAdapter, envelope: IngressEnvelope) -> IngressOutcome:
    scope = _connection_scope(adapter.provider_code, envelope.merchant_external_id)
    if scope is None:
        # Recusado com registro técnico mínimo: identificadores, sem payload.
        logger.warning(
            "channel ingress refused: merchant not connected provider=%s event=%s",
            adapter.provider_code, envelope.provider_event_id,
        )
        return IngressOutcome(envelope.provider_event_id, IngressOutcomeEnum.MERCHANT_NOT_CONNECTED)

    payload = dict(envelope.payload)
    payload_hash = reliability_service.compute_request_hash(payload)
    with Session(engine) as session:
        set_tenant_db_context(session, scope.tenant_id, scope.store_id, None)
        known = _known(session, scope, envelope.provider_event_id, payload_hash)
        if known is not None:
            return known
        now = datetime.utcnow()
        session.add(ChannelInboxEvent(
            tenant_id=scope.tenant_id, store_id=scope.store_id,
            merchant_connection_id=scope.connection_id,
            provider_event_id=envelope.provider_event_id,
            external_order_id=envelope.external_order_id or f"unresolved:{envelope.provider_event_id}",
            event_type=envelope.event_type, payload_hash=payload_hash, raw_payload=payload,
            status=ChannelInboxStatusEnum.RECEIVED,
            received_at=now,
            # The confirmation is the response to this request, and it only goes
            # out if this commit does.
            acknowledged_at=now,
            retention_basis=ChannelRetentionBasisEnum.RECEPCAO,
            retention_until=retention.raw_payload_deadline_from_reception(now),
        ))
        try:
            session.commit()
        except IntegrityError:
            # The same event arriving twice at the same instant: the database
            # kept one, and this one is whatever that one was.
            session.rollback()
            set_tenant_db_context(session, scope.tenant_id, scope.store_id, None)
            known = _known(session, scope, envelope.provider_event_id, payload_hash)
            if known is not None:
                return known
            raise
    return IngressOutcome(envelope.provider_event_id, IngressOutcomeEnum.RECEIVED)


def _known(
    session: Session, scope: _ConnectionScope, provider_event_id: str, payload_hash: str,
) -> Optional[IngressOutcome]:
    existing = session.exec(select(ChannelInboxEvent).where(
        ChannelInboxEvent.merchant_connection_id == scope.connection_id,
        ChannelInboxEvent.provider_event_id == provider_event_id,
    )).first()
    if existing is None:
        return None
    if existing.payload_hash == payload_hash:
        return IngressOutcome(provider_event_id, IngressOutcomeEnum.DUPLICATE)
    # Same identifier, different content. Confirmed so the channel stops resending,
    # recorded with hashes only, and not applied (§3.3).
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=scope.tenant_id, store_id=scope.store_id,
        actor_id=scope.service_actor_id, action="channel.ingress.divergent_event",
        target=f"CHANNEL-INBOX-{existing.id}",
        audit_payload={
            "provider_event_id": provider_event_id,
            "stored_payload_hash": existing.payload_hash, "received_payload_hash": payload_hash,
        },
        aggregate_type="channel_inbox", aggregate_id=str(existing.id),
        event_type="channel.ingress.divergent_event",
        outbox_payload={"provider_event_id": provider_event_id, "inbox_event_id": str(existing.id)},
    )
    session.commit()
    return IngressOutcome(provider_event_id, IngressOutcomeEnum.DIVERGENT)

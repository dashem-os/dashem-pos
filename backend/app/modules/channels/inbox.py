"""The resumable inbox: take an event, apply it once, and say plainly when it cannot be.

S10.1, §3.4. An event waits in `RECEIVED` until one processor claims it with a
lease; the claim and the application are separate transactions, so a processor
that dies after claiming leaves an event another one takes when the lease runs
out, and a processor that dies while applying leaves nothing half-done — the
application is one transaction (H2).

The same `process_event` answers every trigger (§3.4, D4):

(a) right after the ingress confirms, as a task after the response;
(b) the worker sweep, which only takes events older than a grace window so it
    does not race the inline trigger;
(c) "Retomar" on the screen, under `channel.manage`;
(d) any new event of a connection retakes that connection's pending ones.

On Render free there is no hosted worker (ADR-027): (b) runs only where a worker
runs, and an event that stops with no further traffic waits for (c). That is a
limitation, stated on the screen, not hidden.

Quarantine and review record a **code** and a fixed text from this module — never
an exception message, never content (H17). An event whose payload deadline has
passed is never claimed: it becomes `EXPIRED`, definitively (D6).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlmodel import Session, select

from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.channel_hub import (
    ChannelInboxEvent, ChannelInboxStatusEnum, ExternalOrderMapping,
    ExternalOrderTerminalStateEnum, MerchantConnection, MerchantConnectionStatusEnum,
)
from app.models.order import Order, OrderStatusEnum
from app.modules.capabilities.service import effective_capabilities
from app.modules.channels import orders, registry, retention
from app.modules.channels.contracts import ChannelCapability
from app.services import reliability_service

logger = logging.getLogger("dashem_pos.channels.inbox")

LEASE_SECONDS = 60
MAX_ATTEMPTS = 5
SWEEP_GRACE_SECONDS = 120

QUARANTINE_TEXT = {
    "ITEM_NOT_MAPPED": "Item do canal sem código correspondente no catálogo desta conexão.",
    "MODIFIER_NOT_MAPPED": "Complemento do canal sem código correspondente no catálogo desta conexão.",
    "ORDER_NOT_YET_RECEIVED": "O canal mandou uma mudança antes do pedido; ela é retomada quando o pedido chegar.",
    "ORDER_ENGINE_REFUSED": "O pedido não pôde ser aberto nesta unidade: produto indisponível, sem preço ou jornada não contratada.",
    "CONNECTION_NOT_CONNECTED": "A conexão com o canal não está ativa.",
    "CAPABILITY_NOT_DECLARED": "A plataforma não sabe processar pedidos deste canal.",
    "PROCESSING_FAILED": "O processamento falhou repetidas vezes; verifique e retome.",
    "PAYLOAD_PURGED": "O conteúdo do evento já foi removido.",
}
PAYLOAD_TEXT = "O canal enviou um evento que não pôde ser lido."
REVIEW_TEXT = {
    "PREPARATION_STARTED": "O canal pediu mudança ou cancelamento de um pedido que já está em preparo; uma pessoa decide.",
}
RESUMABLE = {ChannelInboxStatusEnum.QUARANTINED, ChannelInboxStatusEnum.NEEDS_REVIEW}
OVERDUE_ELIGIBLE = {
    ChannelInboxStatusEnum.RECEIVED, ChannelInboxStatusEnum.PROCESSING,
    ChannelInboxStatusEnum.QUARANTINED, ChannelInboxStatusEnum.NEEDS_REVIEW,
}


@dataclass(frozen=True)
class _Claim:
    event_id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    attempts: int


def _claimable(now: datetime):
    return (
        or_(
            ChannelInboxEvent.status == ChannelInboxStatusEnum.RECEIVED,
            (ChannelInboxEvent.status == ChannelInboxStatusEnum.PROCESSING)
            & (ChannelInboxEvent.lease_expires_at < now),
        ),
        or_(ChannelInboxEvent.retention_until.is_(None), ChannelInboxEvent.retention_until > now),
    )


def claim(event_id: uuid.UUID, *, now: Optional[datetime] = None) -> Optional[_Claim]:
    """Take one event with a lease, or nothing if someone else has it or it is not claimable."""
    observed = now or datetime.utcnow()
    with Session(engine) as session:
        set_platform_db_context(session)
        row = session.exec(select(ChannelInboxEvent).where(
            ChannelInboxEvent.id == event_id, *_claimable(observed),
        ).with_for_update(skip_locked=True)).first()
        if row is None:
            return None
        row.status = ChannelInboxStatusEnum.PROCESSING
        row.lease_expires_at = observed + timedelta(seconds=LEASE_SECONDS)
        row.attempts += 1
        session.add(row)
        taken = _Claim(row.id, row.tenant_id, row.store_id, row.attempts)
        session.commit()
        return taken


def _context(session: Session, connection: MerchantConnection) -> TenantContext:
    effective = effective_capabilities(session, connection.tenant_id, connection.store_id)
    return TenantContext(
        tenant_id=connection.tenant_id, store_id=connection.store_id,
        user_id=connection.service_actor_id,
        auth_subject=f"service:channel:{connection.id}",
        capabilities=tuple(effective.keys()),
    )


def process_event(event_id: uuid.UUID, *, now: Optional[datetime] = None) -> Optional[ChannelInboxStatusEnum]:
    """Claim and apply one event. Returns the state it ended in, or None if it was not claimed."""
    taken = claim(event_id, now=now)
    if taken is None:
        return None
    observed = now or datetime.utcnow()
    with Session(engine) as session:
        set_tenant_db_context(session, taken.tenant_id, taken.store_id, None)
        row = session.get(ChannelInboxEvent, taken.event_id)
        connection = session.get(MerchantConnection, row.merchant_connection_id)
        try:
            if connection is None or connection.status != MerchantConnectionStatusEnum.CONNECTED:
                raise orders.Quarantine("CONNECTION_NOT_CONNECTED")
            adapter = registry.adapter_for(connection.provider_code)
            if ChannelCapability.ORDER_INGRESS not in adapter.capabilities:
                raise orders.Quarantine("CAPABILITY_NOT_DECLARED")
            event = orders.normalize(adapter, connection, row)
            status, mapping = orders.apply(session, _context(session, connection), connection, row, event, observed)
            row.status = status
            row.order_id = mapping.order_id if mapping else row.order_id
            row.processed_at = observed
            row.lease_expires_at = None
            row.last_error_code = None
            row.quarantine_code = None
            row.quarantine_reason = None
            if mapping is not None:
                retention.settle_applied_event(row, mapping)
            connection.last_event_at = observed
            session.add(row)
            session.add(connection)
            reliability_service.write_audit_and_outbox(
                session=session, tenant_id=row.tenant_id, store_id=row.store_id,
                actor_id=connection.service_actor_id, action=f"channel.inbox.{status.value.lower()}",
                target=f"CHANNEL-INBOX-{row.id}",
                audit_payload={"provider_event_id": row.provider_event_id, "order_id": str(row.order_id) if row.order_id else None},
                aggregate_type="channel_inbox", aggregate_id=str(row.id),
                event_type=f"channel.inbox.{status.value.lower()}",
                outbox_payload={"inbox_event_id": str(row.id), "order_id": str(row.order_id) if row.order_id else None},
            )
            connection_id, external_order_id = row.merchant_connection_id, row.external_order_id
            session.commit()
        except orders.Quarantine as quarantine:
            session.rollback()
            return _settle_refusal(taken, ChannelInboxStatusEnum.QUARANTINED, quarantine.code, None, observed)
        except orders.NeedsReview as review:
            session.rollback()
            return _settle_refusal(taken, ChannelInboxStatusEnum.NEEDS_REVIEW, review.code, review.order_id, observed)
        except Exception as failure:  # noqa: BLE001 — any other failure is retried, never lost
            session.rollback()
            # Only the exception's class: its message can carry what arrived.
            logger.warning(
                "channel inbox processing failed event=%s attempt=%s error=%s",
                taken.event_id, taken.attempts, type(failure).__name__,
            )
            return _release(taken, observed)
    if status == ChannelInboxStatusEnum.APPLIED:
        _retake_waiting(taken, connection_id, external_order_id)
    return status


def _settle_refusal(
    taken: _Claim, status: ChannelInboxStatusEnum, code: str,
    order_id: Optional[uuid.UUID], now: datetime,
) -> ChannelInboxStatusEnum:
    with Session(engine) as session:
        set_tenant_db_context(session, taken.tenant_id, taken.store_id, None)
        row = session.get(ChannelInboxEvent, taken.event_id)
        row.status = status
        row.quarantine_code = code
        row.quarantine_reason = (
            REVIEW_TEXT.get(code) if status == ChannelInboxStatusEnum.NEEDS_REVIEW
            else QUARANTINE_TEXT.get(code, PAYLOAD_TEXT)
        )
        if row.first_quarantined_at is None:
            # Held back — quarantine or review. From here on the payload stays on
            # its reception clock, even if a person resumes it later (D6).
            row.first_quarantined_at = now
        if order_id is not None:
            row.order_id = order_id
        row.lease_expires_at = None
        row.processed_at = now
        session.add(row)
        session.commit()
    return status


def _release(taken: _Claim, now: datetime) -> ChannelInboxStatusEnum:
    if taken.attempts >= MAX_ATTEMPTS:
        return _settle_refusal(taken, ChannelInboxStatusEnum.QUARANTINED, "PROCESSING_FAILED", None, now)
    with Session(engine) as session:
        set_tenant_db_context(session, taken.tenant_id, taken.store_id, None)
        row = session.get(ChannelInboxEvent, taken.event_id)
        row.status = ChannelInboxStatusEnum.RECEIVED
        row.lease_expires_at = None
        row.last_error_code = "PROCESSING_FAILED_RETRYING"
        session.add(row)
        session.commit()
    return ChannelInboxStatusEnum.RECEIVED


def _retake_waiting(taken: _Claim, connection_id: uuid.UUID, external_order_id: str) -> None:
    """The order arrived: changes that came before it go back to the queue and run, in order."""
    with Session(engine) as session:
        set_tenant_db_context(session, taken.tenant_id, taken.store_id, None)
        waiting = session.exec(select(ChannelInboxEvent).where(
            ChannelInboxEvent.merchant_connection_id == connection_id,
            ChannelInboxEvent.external_order_id == external_order_id,
            ChannelInboxEvent.status == ChannelInboxStatusEnum.QUARANTINED,
            ChannelInboxEvent.quarantine_code == "ORDER_NOT_YET_RECEIVED",
        ).order_by(ChannelInboxEvent.order_key, ChannelInboxEvent.received_at)).all()
        ids = [row.id for row in waiting]
        for row in waiting:
            row.status = ChannelInboxStatusEnum.RECEIVED
            session.add(row)
        session.commit()
    for event_id in ids:
        process_event(event_id)


def expire_overdue(*, now: Optional[datetime] = None, limit: int = 200) -> int:
    """Events whose payload deadline passed before they were applied become `EXPIRED` (D6)."""
    observed = now or datetime.utcnow()
    with Session(engine) as session:
        set_platform_db_context(session)
        overdue = session.exec(select(ChannelInboxEvent).where(
            ChannelInboxEvent.status.in_(list(OVERDUE_ELIGIBLE)),
            ChannelInboxEvent.retention_until.is_not(None),
            ChannelInboxEvent.retention_until <= observed,
        ).limit(limit).with_for_update(skip_locked=True)).all()
        for row in overdue:
            if row.status == ChannelInboxStatusEnum.PROCESSING and row.lease_expires_at and row.lease_expires_at > observed:
                continue
            row.status = ChannelInboxStatusEnum.EXPIRED
            row.lease_expires_at = None
            row.processed_at = observed
            session.add(row)
        session.commit()
        return len(overdue)


def anchor_locally_terminal(*, limit: int = 200) -> int:
    """An external order closed or cancelled by a path other than the channel still starts its clocks."""
    with Session(engine) as session:
        set_platform_db_context(session)
        rows = session.exec(select(ExternalOrderMapping, Order).join(
            Order, Order.id == ExternalOrderMapping.order_id,
        ).where(
            ExternalOrderMapping.terminal_at.is_(None),
            Order.status.in_([OrderStatusEnum.CLOSED, OrderStatusEnum.CANCELED]),
        ).limit(limit)).all()
        anchored = 0
        for mapping, order in rows:
            state = (
                ExternalOrderTerminalStateEnum.CANCELED if order.status == OrderStatusEnum.CANCELED
                else ExternalOrderTerminalStateEnum.CONCLUDED
            )
            anchored += int(retention.anchor_terminal(session, mapping, state, order.updated_at))
        session.commit()
        return anchored


def pending_ids(
    *, connection_ids: Optional[Iterable[uuid.UUID]] = None, older_than: Optional[datetime] = None,
    now: Optional[datetime] = None, limit: int = 50,
) -> list[uuid.UUID]:
    observed = now or datetime.utcnow()
    with Session(engine) as session:
        set_platform_db_context(session)
        query = select(ChannelInboxEvent.id).where(*_claimable(observed))
        if connection_ids is not None:
            query = query.where(ChannelInboxEvent.merchant_connection_id.in_(list(connection_ids)))
        if older_than is not None:
            query = query.where(ChannelInboxEvent.received_at <= older_than)
        return list(session.exec(query.order_by(
            ChannelInboxEvent.received_at, ChannelInboxEvent.order_key,
        ).limit(limit)).all())


def process_connections(connection_ids: Iterable[uuid.UUID]) -> int:
    """Triggers (a) and (d): what is pending on these connections, now."""
    processed = 0
    for event_id in pending_ids(connection_ids=list(connection_ids)):
        processed += int(process_event(event_id) is not None)
    return processed


def sweep(*, now: Optional[datetime] = None) -> int:
    """Trigger (b): expire, anchor, and retake what the inline trigger left behind."""
    observed = now or datetime.utcnow()
    expire_overdue(now=observed)
    anchor_locally_terminal()
    processed = 0
    for event_id in pending_ids(older_than=observed - timedelta(seconds=SWEEP_GRACE_SECONDS), now=observed):
        processed += int(process_event(event_id, now=observed) is not None)
    return processed


def resume(session: Session, context: TenantContext, event_id: uuid.UUID, actor_id: uuid.UUID) -> ChannelInboxEvent:
    """Trigger (c): a person retakes a quarantined or reviewed event. The deadline does not move."""
    row = session.exec(select(ChannelInboxEvent).where(
        ChannelInboxEvent.id == event_id, ChannelInboxEvent.tenant_id == context.tenant_id,
    ).with_for_update()).first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "EVENT_NOT_FOUND"})
    now = datetime.utcnow()
    if row.status == ChannelInboxStatusEnum.EXPIRED or (row.retention_until and row.retention_until <= now):
        raise HTTPException(status_code=409, detail={"code": "EVENT_EXPIRED"})
    if row.status not in RESUMABLE:
        raise HTTPException(status_code=409, detail={"code": "EVENT_NOT_RESUMABLE", "status": row.status.value})
    row.status = ChannelInboxStatusEnum.RECEIVED
    row.lease_expires_at = None
    session.add(row)
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=row.tenant_id, store_id=row.store_id, actor_id=actor_id,
        action="channel.inbox.resumed", target=f"CHANNEL-INBOX-{row.id}",
        audit_payload={"provider_event_id": row.provider_event_id, "quarantine_code": row.quarantine_code},
        aggregate_type="channel_inbox", aggregate_id=str(row.id), event_type="channel.inbox.resumed",
        outbox_payload={"inbox_event_id": str(row.id)},
    )
    session.commit()
    process_event(event_id)
    session.refresh(row)
    return row

"""Notices to the channel: queued, sent once at a time, and honest about what came back.

S10.1, §3.6. `ChannelOutboundMessage` is the executor's own queue, as ADR-027
asks: each external adapter keeps its own delivery record, and a published
outbox event is never mistaken for a notice the channel received (H8).

A notice leaves in three steps, and no database transaction is open while the
channel is being called:

1. **claim** — a lease on one message, committed;
2. **call** — the adapter, with nothing held;
3. **record** — the outcome, only if the lease is still this attempt's.

What came back decides the state:

- `DELIVERED` → `DELIVERED`, with the channel's reference;
- `RETRYABLE` → `RETRY` with a growing wait, until attempts run out;
- `PERMANENT`, or attempts exhausted → `DEAD_LETTER`, visible, with "Reenviar"
  under `channel.manage`;
- `AMBIGUOUS` — timed out or broke after it may have arrived — is neither. If the
  channel deduplicates by the notice identity (E4), the same notice is resent. If
  it does not, the notice becomes `UNCONFIRMED` and the channel is **asked**
  before anything is resent (E5). An adapter that raises is treated as ambiguous.

Which order transitions create notices is not decided here (D8): today a notice
exists only when something enqueues it explicitly. Nothing is inventing an
acceptance or a "ready" the business did not choose to send.

Nothing personal enters the queue's audit or the outbox (H17). A notice whose
payload names a person is refused; whatever a real channel needs from the
contact layer is read at send time, under the retention rules, not copied here.

The same triggers as the inbox apply: right after enqueueing, the worker sweep,
and "Reenviar". On Render free there is no hosted worker; a notice waiting for a
retry does not leave by itself, and the screen says so.
"""

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlmodel import Session, select

from app.core.context import TenantContext, resolve_actor
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.channel_hub import (
    ChannelOutboundMessage, ChannelOutboundStatusEnum, ExternalOrderMapping,
    MerchantConnection, MerchantConnectionStatusEnum,
)
from app.modules.channels import registry
from app.modules.channels.contracts import (
    ChannelCapability, DeliveryOutcome, DeliveryResult, OutboundNotice,
)
from app.services import reliability_service

logger = logging.getLogger("dashem_pos.channels.outbound")

LEASE_SECONDS = 60
MAX_ATTEMPTS = 6
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 1800
SWEEP_GRACE_SECONDS = 120

PERSONAL_TOKENS = {
    "name", "nome", "customer", "cliente", "phone", "telefone", "celular", "whatsapp",
    "address", "endereco", "logradouro", "cep", "postal", "contact", "contato",
    "cpf", "email", "instructions",
}
#: A dead letter whose last word was ambiguous may have arrived: resending it
#: starts by asking the channel, never by sending (E5).
AMBIGUOUS_PREFIX = "AMBIGUOUS:"


@dataclass(frozen=True)
class _Claim:
    message_id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    attempt: int
    confirming: bool


def _tokens(name: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", plain)
    return {part.lower() for part in re.split(r"[^A-Za-z0-9]+", spaced) if part}


def _personal_keys(value) -> bool:
    if isinstance(value, dict):
        return any(_tokens(key) & PERSONAL_TOKENS or _personal_keys(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_personal_keys(item) for item in value)
    return False


def backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(BACKOFF_BASE_SECONDS * (2 ** max(attempt - 1, 0)), BACKOFF_MAX_SECONDS))


def enqueue(
    session: Session, context: TenantContext, order_id: uuid.UUID, *,
    message_type: str, payload: dict, actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> ChannelOutboundMessage:
    """Queue one notice for an external order. The outbox hears identifiers, never content."""
    actor = resolve_actor(context, actor_id)
    if _personal_keys(payload):
        raise HTTPException(status_code=422, detail={"code": "NOTICE_PAYLOAD_PERSONAL"})
    request_hash = reliability_service.compute_request_hash({
        "order_id": str(order_id), "message_type": message_type, "payload": payload,
    })
    existing = session.exec(select(ChannelOutboundMessage).where(
        ChannelOutboundMessage.tenant_id == context.tenant_id,
        ChannelOutboundMessage.idempotency_key == idempotency_key,
    )).first()
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
            "outbound_message_id": str(message.id),
            "merchant_connection_id": str(mapping.merchant_connection_id),
            "order_id": str(order_id), "message_type": message_type,
        },
    )
    session.commit()
    session.refresh(message)
    return message


def _claimable(now: datetime):
    return or_(
        ChannelOutboundMessage.status == ChannelOutboundStatusEnum.PENDING,
        (ChannelOutboundMessage.status.in_([ChannelOutboundStatusEnum.RETRY, ChannelOutboundStatusEnum.UNCONFIRMED]))
        & (or_(ChannelOutboundMessage.next_retry_at.is_(None), ChannelOutboundMessage.next_retry_at <= now)),
        (ChannelOutboundMessage.status == ChannelOutboundStatusEnum.SENDING)
        & (ChannelOutboundMessage.lease_expires_at < now),
    )


def claim(message_id: uuid.UUID, *, now: Optional[datetime] = None) -> Optional[_Claim]:
    observed = now or datetime.utcnow()
    with Session(engine) as session:
        set_platform_db_context(session)
        row = session.exec(select(ChannelOutboundMessage).where(
            ChannelOutboundMessage.id == message_id, _claimable(observed),
        ).with_for_update(skip_locked=True)).first()
        if row is None:
            return None
        # UNCONFIRMED, or a lease that ran out mid-call: it may have arrived. Ask first.
        confirming = row.status in {ChannelOutboundStatusEnum.UNCONFIRMED, ChannelOutboundStatusEnum.SENDING}
        row.status = ChannelOutboundStatusEnum.SENDING
        row.lease_expires_at = observed + timedelta(seconds=LEASE_SECONDS)
        row.attempt_count += 1
        row.updated_at = observed
        session.add(row)
        taken = _Claim(row.id, row.tenant_id, row.store_id, row.attempt_count, confirming)
        session.commit()
        return taken


def _notice(taken: _Claim):
    """Everything the call needs, read in a session that closes before the call."""
    with Session(engine) as session:
        set_tenant_db_context(session, taken.tenant_id, taken.store_id, None)
        row = session.get(ChannelOutboundMessage, taken.message_id)
        connection = session.get(MerchantConnection, row.merchant_connection_id)
        mapping = session.exec(select(ExternalOrderMapping).where(
            ExternalOrderMapping.tenant_id == row.tenant_id, ExternalOrderMapping.order_id == row.order_id,
        )).first()
        notice = OutboundNotice(
            notice_id=str(row.id), merchant_external_id=connection.merchant_external_id,
            external_order_id=mapping.external_order_id if mapping else "",
            message_type=row.message_type, payload=dict(row.payload or {}),
        )
        return notice, connection.status, connection.provider_code


def deliver(message_id: uuid.UUID, *, now: Optional[datetime] = None) -> Optional[ChannelOutboundStatusEnum]:
    """Claim, call the channel with nothing held, record. None if the message was not claimable."""
    taken = claim(message_id, now=now)
    if taken is None:
        return None
    notice, connection_status, provider_code = _notice(taken)
    if connection_status != MerchantConnectionStatusEnum.CONNECTED:
        return _record(taken, now, DeliveryOutcome(DeliveryResult.RETRYABLE, code="CONNECTION_NOT_CONNECTED"))
    adapter = registry.adapter_for(provider_code)
    if ChannelCapability.ORDER_STATUS_OUTBOUND not in adapter.capabilities:
        # Never called for what it did not declare (H11).
        return _record(taken, now, DeliveryOutcome(DeliveryResult.PERMANENT, code="CAPABILITY_NOT_DECLARED"))

    if taken.confirming:
        try:
            arrived = adapter.confirm_notice(notice)
        except Exception as failure:  # noqa: BLE001 — cannot confirm is not a failure of the notice
            logger.warning("channel notice confirmation failed notice=%s error=%s", taken.message_id, type(failure).__name__)
            arrived = None
        if arrived is True:
            return _record(taken, now, DeliveryOutcome(DeliveryResult.DELIVERED, code="CONFIRMED_BY_CHANNEL"))
        if arrived is None:
            return _record(taken, now, DeliveryOutcome(DeliveryResult.AMBIGUOUS, code="CHANNEL_CANNOT_CONFIRM"), still_unconfirmed=True)
        # The channel says it never arrived: now it is safe to send again.

    try:
        outcome = adapter.send_notice(notice)
    except Exception as failure:  # noqa: BLE001 — a broken call may still have arrived
        logger.warning("channel notice call failed notice=%s error=%s", taken.message_id, type(failure).__name__)
        outcome = DeliveryOutcome(DeliveryResult.AMBIGUOUS, code="CALL_FAILED")
    if outcome.result == DeliveryResult.AMBIGUOUS and getattr(adapter, "idempotent_delivery", False):
        # E4: the channel drops a repeat of the same identity, so resending is safe.
        outcome = DeliveryOutcome(DeliveryResult.RETRYABLE, code=outcome.code or "AMBIGUOUS_RESENT")
    return _record(taken, now, outcome)


def _record(
    taken: _Claim, now: Optional[datetime], outcome: DeliveryOutcome, *, still_unconfirmed: bool = False,
) -> Optional[ChannelOutboundStatusEnum]:
    # Measured after the call: a slow channel must not shorten the wait before the next attempt.
    now = now or datetime.utcnow()
    with Session(engine) as session:
        set_tenant_db_context(session, taken.tenant_id, taken.store_id, None)
        row = session.exec(select(ChannelOutboundMessage).where(
            ChannelOutboundMessage.id == taken.message_id,
        ).with_for_update()).first()
        if row.status != ChannelOutboundStatusEnum.SENDING or row.attempt_count != taken.attempt:
            # The lease ran out and another attempt took over; this answer is not ours to write.
            logger.warning("channel notice outcome discarded, lease lost notice=%s attempt=%s", taken.message_id, taken.attempt)
            return None
        row.lease_expires_at = None
        row.updated_at = now
        ambiguous = outcome.result == DeliveryResult.AMBIGUOUS or still_unconfirmed
        code = outcome.code or outcome.result.value
        row.last_error_code = (
            None if outcome.result == DeliveryResult.DELIVERED
            else f"{AMBIGUOUS_PREFIX}{code}"[:80] if ambiguous else code[:80]
        )
        exhausted = row.attempt_count >= MAX_ATTEMPTS
        if outcome.result == DeliveryResult.DELIVERED:
            row.status = ChannelOutboundStatusEnum.DELIVERED
            row.delivered_at = now
            row.provider_reference = (outcome.provider_reference or row.provider_reference)
            row.next_retry_at = None
        elif outcome.result == DeliveryResult.PERMANENT or exhausted:
            row.status = ChannelOutboundStatusEnum.DEAD_LETTER
            row.next_retry_at = None
        elif ambiguous:
            row.status = ChannelOutboundStatusEnum.UNCONFIRMED
            row.next_retry_at = now + backoff(row.attempt_count)
        else:
            row.status = ChannelOutboundStatusEnum.RETRY
            row.next_retry_at = now + backoff(row.attempt_count)
        status = row.status
        session.add(row)
        reliability_service.write_audit_and_outbox(
            session=session, tenant_id=row.tenant_id, store_id=row.store_id, actor_id=row.created_by,
            action=f"channel.outbound.{status.value.lower()}", target=f"CHANNEL-OUTBOUND-{row.id}",
            audit_payload={"attempt": row.attempt_count, "code": row.last_error_code},
            aggregate_type="channel_outbound", aggregate_id=str(row.id),
            event_type=f"channel.outbound.{status.value.lower()}",
            outbox_payload={"outbound_message_id": str(row.id), "status": status.value},
        )
        session.commit()
        return status


def resend(session: Session, context: TenantContext, message_id: uuid.UUID, actor_id: uuid.UUID) -> ChannelOutboundMessage:
    """A person sends a dead-lettered notice again, under `channel.manage`. Same identity, fresh attempts."""
    row = session.exec(select(ChannelOutboundMessage).where(
        ChannelOutboundMessage.id == message_id, ChannelOutboundMessage.tenant_id == context.tenant_id,
    ).with_for_update()).first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOTICE_NOT_FOUND"})
    if row.status != ChannelOutboundStatusEnum.DEAD_LETTER:
        raise HTTPException(status_code=409, detail={"code": "NOTICE_NOT_RESENDABLE", "status": row.status.value})
    # Ambiguous last word: it may have arrived, so the channel is asked first.
    row.status = (
        ChannelOutboundStatusEnum.UNCONFIRMED
        if (row.last_error_code or "").startswith(AMBIGUOUS_PREFIX)
        else ChannelOutboundStatusEnum.PENDING
    )
    row.attempt_count = 0
    row.next_retry_at = None
    row.updated_at = datetime.utcnow()
    session.add(row)
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=row.tenant_id, store_id=row.store_id, actor_id=actor_id,
        action="channel.outbound.resent", target=f"CHANNEL-OUTBOUND-{row.id}",
        audit_payload={"last_error_code": row.last_error_code},
        aggregate_type="channel_outbound", aggregate_id=str(row.id), event_type="channel.outbound.resent",
        outbox_payload={"outbound_message_id": str(row.id)},
    )
    session.commit()
    deliver(message_id)
    session.refresh(row)
    return row


def list_messages(
    session: Session, context: TenantContext, limit: int = 100, *, message_id: Optional[uuid.UUID] = None,
) -> list[dict]:
    query = select(ChannelOutboundMessage, ExternalOrderMapping.external_order_id).join(
        ExternalOrderMapping, ExternalOrderMapping.order_id == ChannelOutboundMessage.order_id, isouter=True,
    ).where(ChannelOutboundMessage.tenant_id == context.tenant_id)
    if message_id is not None:
        query = query.where(ChannelOutboundMessage.id == message_id)
    rows = session.exec(query.order_by(
        ChannelOutboundMessage.created_at.desc(),
    ).limit(limit)).all()
    return [{
        "id": message.id, "order_id": message.order_id, "external_order_id": external_order_id,
        "message_type": message.message_type, "status": message.status,
        "attempt_count": message.attempt_count, "last_error_code": message.last_error_code,
        "next_retry_at": message.next_retry_at, "delivered_at": message.delivered_at,
        "created_at": message.created_at,
    } for message, external_order_id in rows]


def pending_ids(*, older_than: Optional[datetime] = None, now: Optional[datetime] = None, limit: int = 50) -> list[uuid.UUID]:
    observed = now or datetime.utcnow()
    with Session(engine) as session:
        set_platform_db_context(session)
        query = select(ChannelOutboundMessage.id).where(_claimable(observed))
        if older_than is not None:
            query = query.where(ChannelOutboundMessage.created_at <= older_than)
        return list(session.exec(query.order_by(ChannelOutboundMessage.created_at).limit(limit)).all())


def deliver_now(message_ids: Iterable[uuid.UUID]) -> int:
    return sum(int(deliver(message_id) is not None) for message_id in message_ids)


def sweep(*, now: Optional[datetime] = None) -> int:
    observed = now or datetime.utcnow()
    return deliver_now(pending_ids(older_than=observed - timedelta(seconds=SWEEP_GRACE_SECONDS), now=observed))

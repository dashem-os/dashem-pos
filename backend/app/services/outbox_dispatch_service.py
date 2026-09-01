"""Reliable publication from the mutable outbox into an immutable event stream."""

import hashlib
import json
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlmodel import Session, select

from app.models.reliability import OutboxEvent, OutboxStatusEnum, PublishedEvent


LEASE_SECONDS = 30
MAX_ATTEMPTS = 8
MAX_BACKOFF_SECONDS = 300


class OutboxDispatchError(RuntimeError):
    pass


class InvalidOutboxEnvelope(OutboxDispatchError):
    pass


def _canonical_envelope(event: OutboxEvent) -> tuple[str, str]:
    try:
        payload = json.loads(event.payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise InvalidOutboxEnvelope("O payload da outbox não é JSON válido.") from exc
    if not isinstance(payload, dict):
        raise InvalidOutboxEnvelope("O payload da outbox deve ser um objeto JSON.")
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    envelope = {
        "outbox_event_id": str(event.id),
        "tenant_id": str(event.tenant_id),
        "store_id": str(event.store_id) if event.store_id else None,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": event.aggregate_id,
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "payload": payload,
        "correlation_id": event.correlation_id,
        "occurred_at": event.occurred_at.isoformat(),
    }
    canonical_envelope = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return canonical_payload, hashlib.sha256(canonical_envelope.encode("utf-8")).hexdigest()


def claim_next_event(
    session: Session,
    *,
    now: datetime | None = None,
    event_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Lease exactly one ready event; abandoned PROCESSING leases are recoverable."""

    observed_at = now or datetime.utcnow()
    event_filter = "AND id = :event_id" if event_id is not None else ""
    row = session.exec(text(f"""
        WITH candidate AS (
            SELECT id
            FROM outbox_events
            WHERE (
                (status = :pending_status AND available_at <= :observed_at)
                OR (status = :processing_status AND available_at <= :observed_at)
            )
            {event_filter}
            ORDER BY created_at ASC, id ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE outbox_events AS event
        SET status = :processing_status,
            attempts = event.attempts + 1,
            available_at = :lease_expires_at,
            last_error = NULL
        FROM candidate
        WHERE event.id = candidate.id
        RETURNING event.id
    """), params={
        "pending_status": OutboxStatusEnum.PENDING.value,
        "processing_status": OutboxStatusEnum.PROCESSING.value,
        "observed_at": observed_at,
        "lease_expires_at": observed_at + timedelta(seconds=LEASE_SECONDS),
        **({"event_id": event_id} if event_id is not None else {}),
    }).first()
    session.commit()
    return uuid.UUID(str(row[0])) if row else None


def publish_claimed_event(
    session: Session, event_id: uuid.UUID, *, now: datetime | None = None,
) -> PublishedEvent:
    """Atomically append the event stream entry and complete its outbox record."""

    published_at = now or datetime.utcnow()
    event = session.get(OutboxEvent, event_id)
    if event is None or event.status != OutboxStatusEnum.PROCESSING:
        raise OutboxDispatchError("O evento não possui um lease ativo para publicação.")
    canonical_payload, content_hash = _canonical_envelope(event)
    published = session.exec(select(PublishedEvent).where(
        PublishedEvent.outbox_event_id == event.id
    )).first()
    if published is not None and published.content_hash != content_hash:
        raise OutboxDispatchError("O recibo existente diverge do envelope da outbox.")
    if published is None:
        published = PublishedEvent(
            outbox_event_id=event.id,
            tenant_id=event.tenant_id,
            store_id=event.store_id,
            actor_id=event.actor_id,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            schema_version=event.schema_version,
            payload=canonical_payload,
            content_hash=content_hash,
            correlation_id=event.correlation_id,
            occurred_at=event.occurred_at,
            published_at=published_at,
        )
        session.add(published)
    event.status = OutboxStatusEnum.PUBLISHED
    event.processed_at = published_at
    event.available_at = published_at
    event.last_error = None
    session.add(event)
    session.commit()
    session.refresh(published)
    return published


def release_claim(
    session: Session,
    event_id: uuid.UUID,
    error: Exception,
    *,
    now: datetime | None = None,
    permanent: bool = False,
) -> None:
    """Return a failed lease with bounded backoff or quarantine a poison event."""

    observed_at = now or datetime.utcnow()
    event = session.get(OutboxEvent, event_id)
    if event is None or event.status != OutboxStatusEnum.PROCESSING:
        session.rollback()
        return
    event.last_error = str(error)[:1000]
    if permanent or event.attempts >= MAX_ATTEMPTS:
        event.status = OutboxStatusEnum.FAILED
        event.available_at = observed_at
    else:
        event.status = OutboxStatusEnum.PENDING
        delay = min(2 ** max(event.attempts, 1), MAX_BACKOFF_SECONDS)
        event.available_at = observed_at + timedelta(seconds=delay)
    session.add(event)
    session.commit()

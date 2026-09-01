import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.reliability import OutboxEvent, OutboxStatusEnum, PublishedEvent
from app.services.outbox_dispatch_service import (
    LEASE_SECONDS,
    InvalidOutboxEnvelope,
    claim_next_event,
    publish_claimed_event,
    release_claim,
)


def _event(*, payload: str = '{"b":2,"a":1}', **changes) -> OutboxEvent:
    values = {
        "tenant_id": uuid.uuid4(),
        "aggregate_type": "contract",
        "aggregate_id": str(uuid.uuid4()),
        "event_type": "contract.updated",
        "schema_version": 1,
        "payload": payload,
        "correlation_id": str(uuid.uuid4()),
    }
    values.update(changes)
    return OutboxEvent(**values)


def _persist(event: OutboxEvent) -> uuid.UUID:
    with Session(engine) as session:
        set_platform_db_context(session)
        session.add(event)
        session.commit()
        return event.id


def test_claim_publishes_canonical_immutable_receipt():
    ready_at = datetime(2099, 9, 1, 15, 0, 0)
    event_id = _persist(_event(available_at=ready_at, occurred_at=ready_at))

    with Session(engine) as session:
        set_platform_db_context(session)
        assert claim_next_event(session, now=ready_at, event_id=event_id) == event_id
        claimed = session.get(OutboxEvent, event_id)
        assert claimed.status == OutboxStatusEnum.PROCESSING
        assert claimed.attempts == 1
        assert claimed.available_at == ready_at + timedelta(seconds=LEASE_SECONDS)

    published_at = ready_at + timedelta(seconds=1)
    with Session(engine) as session:
        set_platform_db_context(session)
        receipt = publish_claimed_event(session, event_id, now=published_at)
        assert receipt.payload == '{"a":1,"b":2}'
        assert len(receipt.content_hash) == 64
        assert receipt.published_at == published_at
        completed = session.get(OutboxEvent, event_id)
        assert completed.status == OutboxStatusEnum.PUBLISHED
        assert completed.processed_at == published_at

        try:
            result = session.exec(text(
                "UPDATE published_events SET payload = '{}' WHERE id = :id"
            ), params={"id": receipt.id})
            session.commit()
            assert result.rowcount == 0
        except DBAPIError as exc:
            session.rollback()
            assert "published events are immutable" in str(exc)
            set_platform_db_context(session)
        unchanged = session.get(PublishedEvent, receipt.id)
        assert unchanged.payload == '{"a":1,"b":2}'


def test_publishing_same_claim_twice_is_idempotent():
    now = datetime(2099, 9, 1, 16, 0, 0)
    event_id = _persist(_event(available_at=now, occurred_at=now))

    with Session(engine) as session:
        set_platform_db_context(session)
        claim_next_event(session, now=now, event_id=event_id)
        first = publish_claimed_event(session, event_id, now=now)
        first_id = first.id
        event = session.get(OutboxEvent, event_id)
        event.status = OutboxStatusEnum.PROCESSING
        session.add(event)
        session.commit()
        second = publish_claimed_event(session, event_id, now=now + timedelta(seconds=1))
        assert second.id == first_id
        receipts = session.exec(select(PublishedEvent).where(
            PublishedEvent.outbox_event_id == event_id
        )).all()
        assert len(receipts) == 1


def test_expired_processing_lease_is_recovered():
    now = datetime(2099, 9, 1, 17, 0, 0)
    event_id = _persist(_event(
        status=OutboxStatusEnum.PROCESSING,
        attempts=2,
        available_at=now - timedelta(seconds=1),
    ))

    with Session(engine) as session:
        set_platform_db_context(session)
        assert claim_next_event(session, now=now, event_id=event_id) == event_id
        recovered = session.get(OutboxEvent, event_id)
        assert recovered.status == OutboxStatusEnum.PROCESSING
        assert recovered.attempts == 3
        assert recovered.available_at == now + timedelta(seconds=LEASE_SECONDS)


def test_failed_publication_returns_to_queue_with_backoff():
    now = datetime(2099, 9, 1, 18, 0, 0)
    event_id = _persist(_event(available_at=now))

    with Session(engine) as session:
        set_platform_db_context(session)
        claim_next_event(session, now=now, event_id=event_id)
        release_claim(session, event_id, RuntimeError("temporary provider failure"), now=now)
        queued = session.get(OutboxEvent, event_id)
        assert queued.status == OutboxStatusEnum.PENDING
        assert queued.available_at == now + timedelta(seconds=2)
        assert queued.last_error == "temporary provider failure"


def test_invalid_payload_is_quarantined_without_receipt():
    now = datetime(2099, 9, 1, 19, 0, 0)
    event_id = _persist(_event(payload="[]", available_at=now))

    with Session(engine) as session:
        set_platform_db_context(session)
        claim_next_event(session, now=now, event_id=event_id)
        with pytest.raises(InvalidOutboxEnvelope):
            publish_claimed_event(session, event_id, now=now)
        session.rollback()
        set_platform_db_context(session)
        release_claim(session, event_id, InvalidOutboxEnvelope("invalid envelope"), now=now, permanent=True)
        failed = session.get(OutboxEvent, event_id)
        assert failed.status == OutboxStatusEnum.FAILED
        assert session.exec(select(PublishedEvent).where(
            PublishedEvent.outbox_event_id == event_id
        )).first() is None

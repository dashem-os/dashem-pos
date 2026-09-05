import time
import logging
from datetime import datetime
from sqlmodel import Session
from app.core.database import engine
from app.models.reliability import ServiceHeartbeat
from app.core.tenancy import set_platform_db_context
from app.services.outbox_dispatch_service import (
    InvalidOutboxEnvelope,
    claim_next_event,
    publish_claimed_event,
    release_claim,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dashem_pos.outbox_worker")


def _heartbeat(session: Session, *, status: str = "HEALTHY", error: str | None = None) -> None:
    now = datetime.utcnow()
    heartbeat = session.get(ServiceHeartbeat, "outbox_worker") or ServiceHeartbeat(
        service_key="outbox_worker"
    )
    heartbeat.status = status
    heartbeat.details = {"last_error": error} if error else {}
    heartbeat.last_seen_at = now
    heartbeat.updated_at = now
    session.add(heartbeat)
    session.commit()

def _record_heartbeat(*, status: str = "HEALTHY", error: str | None = None) -> None:
    with Session(engine) as session:
        set_platform_db_context(session)
        _heartbeat(session, status=status, error=error)


def sweep_expired_reserves() -> int:
    """Take back payment reserves the server can prove were never sent.

    Only a parcel with no provider transaction at all is expired here. One that
    reached a provider is left for reconciliation to query, because a lost
    answer is not a lost charge — S25.1.
    """
    from app.services.negotiation_service import expire_abandoned_reserves

    with Session(engine) as session:
        set_platform_db_context(session)
        expired = expire_abandoned_reserves(session)
    if expired:
        logger.info("Expired %s abandoned payment reserves", len(expired))
    return len(expired)


def process_one_event() -> bool:
    """Publish one leased outbox event and persist an immutable receipt."""

    with Session(engine) as claim_session:
        set_platform_db_context(claim_session)
        event_id = claim_next_event(claim_session)
    if event_id is None:
        return False

    try:
        with Session(engine) as publish_session:
            set_platform_db_context(publish_session)
            published = publish_claimed_event(publish_session, event_id)
        logger.info(
            "Published outbox event id=%s receipt=%s hash=%s",
            event_id,
            published.id,
            published.content_hash,
        )
    except InvalidOutboxEnvelope as exc:
        logger.error("Quarantining invalid outbox event id=%s: %s", event_id, exc)
        with Session(engine) as release_session:
            set_platform_db_context(release_session)
            release_claim(release_session, event_id, exc, permanent=True)
    except Exception as exc:
        logger.exception("Publication failed for outbox event id=%s", event_id)
        with Session(engine) as release_session:
            set_platform_db_context(release_session)
            release_claim(release_session, event_id, exc)
    return True


def process_outbox_events():
    logger.info("Starting Dashem POS Outbox Worker...")
    last_heartbeat_at = 0.0
    last_sweep_at = 0.0
    while True:
        try:
            if time.monotonic() - last_heartbeat_at >= 10:
                _record_heartbeat()
                last_heartbeat_at = time.monotonic()
            # The reserve sweep is cheap and indexed; once a minute is enough,
            # and it survives a restart because it reads the clock from the row.
            if time.monotonic() - last_sweep_at >= 60:
                sweep_expired_reserves()
                last_sweep_at = time.monotonic()
            if not process_one_event():
                time.sleep(1.0)
        except Exception as e:
            logger.exception("Outbox worker loop failed")
            try:
                _record_heartbeat(status="DEGRADED", error=str(e)[:500])
            except Exception:
                logger.exception("Could not persist worker heartbeat failure")
            time.sleep(2.0)

if __name__ == "__main__":
    process_outbox_events()

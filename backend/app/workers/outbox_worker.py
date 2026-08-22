import time
import logging
import json
from datetime import datetime
from sqlmodel import Session, select, text
from app.core.database import engine
from app.models.reliability import OutboxEvent, OutboxStatusEnum
from app.core.tenancy import set_platform_db_context

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dashem_pos.outbox_worker")

def process_outbox_events():
    logger.info("Starting Dashem POS Outbox Worker...")
    
    while True:
        try:
            with Session(engine) as session:
                # This is an internal platform worker, not a tenant request.
                set_platform_db_context(session)
                # Concurrency-safe claim using FOR UPDATE SKIP LOCKED
                query = text("""
                    SELECT id FROM outbox_events
                    WHERE status = :pending_status
                      AND available_at <= :now
                    ORDER BY created_at ASC
                    LIMIT 10
                    FOR UPDATE SKIP LOCKED
                """)
                
                result = session.exec(query, params={
                    "pending_status": OutboxStatusEnum.PENDING.value,
                    "now": datetime.utcnow()
                }).all()
                
                if not result:
                    time.sleep(1.0)
                    continue
                
                event_ids = [row[0] for row in result]
                
                for event_id in event_ids:
                    event = session.get(OutboxEvent, event_id)
                    if not event:
                        continue
                    
                    event.status = OutboxStatusEnum.PROCESSING
                    event.attempts += 1
                    session.add(event)
                    session.commit()
                    
                    logger.info(
                        f"[Outbox Worker] Processing event: id={event.id}, type={event.event_type}, aggregate={event.aggregate_type}/{event.aggregate_id}, correlation_id={event.correlation_id}"
                    )
                    
                    try:
                        # Process / dispatch event to Read Models or Harness Event Bus
                        # In POS-0, we log and mark as PUBLISHED
                        event.status = OutboxStatusEnum.PROCESSED
                        event.processed_at = datetime.utcnow()
                        session.add(event)
                        session.commit()
                        logger.info(f"[Outbox Worker] Event {event.id} successfully PROCESSED.")
                    except Exception as ex:
                        logger.error(f"[Outbox Worker] Failed to process event {event.id}: {ex}")
                        event.status = OutboxStatusEnum.FAILED
                        event.last_error = str(ex)
                        session.add(event)
                        session.commit()
                        
        except Exception as e:
            logger.error(f"[Outbox Worker Loop Error] {e}")
            time.sleep(2.0)

if __name__ == "__main__":
    process_outbox_events()

import uuid
import hashlib
import json
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
from sqlmodel import Session, select
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from app.models.reliability import OutboxEvent, AuditEvent, IdempotencyRecord, OutboxStatusEnum

def compute_request_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

def check_idempotency(
    session: Session,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    operation: str,
    idempotency_key: str,
    request_payload: Any
) -> Tuple[bool, Optional[int], Optional[Dict[str, Any]]]:
    req_hash = compute_request_hash(request_payload)
    query = select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == tenant_id,
        IdempotencyRecord.actor_id == actor_id,
        IdempotencyRecord.operation == operation,
        IdempotencyRecord.idempotency_key == idempotency_key
    )
    record = session.exec(query).first()
    if record:
        if record.request_hash != req_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "IDEMPOTENCY_KEY_REUSED",
                    "message": f"Idempotency key '{idempotency_key}' was previously used with a different request payload."
                }
            )
        body = json.loads(record.response_body) if record.response_body else None
        return True, record.response_status, body
    return False, None, None

def save_idempotency_record(
    session: Session,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    operation: str,
    idempotency_key: str,
    request_payload: Any,
    response_status: int,
    response_body: Dict[str, Any]
) -> Dict[str, Any]:
    req_hash = compute_request_hash(request_payload)
    record = IdempotencyRecord(
        tenant_id=tenant_id,
        actor_id=actor_id,
        operation=operation,
        idempotency_key=idempotency_key,
        request_hash=req_hash,
        response_status=response_status,
        response_body=json.dumps(response_body, default=str)
    )
    try:
        with session.begin_nested():
            session.add(record)
            session.flush()
        return response_body
    except IntegrityError:
        existing = session.exec(
            select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id,
                IdempotencyRecord.actor_id == actor_id,
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.idempotency_key == idempotency_key
            )
        ).first()
        if existing:
            if existing.request_hash != req_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "IDEMPOTENCY_KEY_REUSED",
                        "message": f"Idempotency key '{idempotency_key}' was previously used with a different request payload."
                    }
                )
            return json.loads(existing.response_body) if existing.response_body else response_body
        return response_body

def write_audit_and_outbox(
    session: Session,
    tenant_id: uuid.UUID,
    store_id: Optional[uuid.UUID],
    actor_id: uuid.UUID,
    action: str,
    target: str,
    audit_payload: Dict[str, Any],
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    outbox_payload: Dict[str, Any],
    correlation_id: Optional[str] = None
) -> Tuple[AuditEvent, OutboxEvent]:
    audit = AuditEvent(
        tenant_id=tenant_id,
        store_id=store_id,
        actor_id=actor_id,
        action=action,
        target=target,
        payload=json.dumps(audit_payload, default=str),
        correlation_id=correlation_id
    )
    session.add(audit)

    outbox = OutboxEvent(
        tenant_id=tenant_id,
        store_id=store_id,
        actor_id=actor_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=json.dumps(outbox_payload, default=str),
        status=OutboxStatusEnum.PENDING,
        correlation_id=correlation_id
    )
    session.add(outbox)

    return audit, outbox

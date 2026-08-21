import uuid
from datetime import datetime
from enum import Enum
from typing import Optional
from sqlmodel import SQLModel, Field, UniqueConstraint

class OutboxStatusEnum(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"

class OutboxEvent(SQLModel, table=True):
    __tablename__ = "outbox_events"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    aggregate_type: str = Field(index=True)
    aggregate_id: str = Field(index=True)
    event_type: str = Field(index=True)
    payload: str  # JSON string
    status: OutboxStatusEnum = Field(default=OutboxStatusEnum.PENDING, index=True)
    attempts: int = Field(default=0)
    available_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    processed_at: Optional[datetime] = None
    last_error: Optional[str] = None
    correlation_id: Optional[str] = Field(default=None, index=True)

class AuditEvent(SQLModel, table=True):
    __tablename__ = "audit_events"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    actor_id: uuid.UUID = Field(index=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: uuid.UUID = Field(index=True)
    action: str = Field(index=True)
    target: str = Field(index=True)
    payload: str  # JSON string
    correlation_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class IdempotencyRecord(SQLModel, table=True):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "actor_id", "operation", "idempotency_key", name="uq_tenant_actor_op_key"),
    )
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    actor_id: uuid.UUID = Field(index=True)
    operation: str = Field(index=True)
    idempotency_key: str = Field(index=True)
    request_hash: str = Field(index=True)  # SHA256 of request payload
    response_status: int
    response_body: str  # JSON string
    created_at: datetime = Field(default_factory=datetime.utcnow)

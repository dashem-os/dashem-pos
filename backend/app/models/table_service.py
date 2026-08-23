import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, CheckConstraint, Column, Index, Text, text
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


class ServiceTableStatusEnum(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    RESERVED = "RESERVED"
    BLOCKED = "BLOCKED"


class TableSessionKindEnum(str, Enum):
    TABLE = "TABLE"
    INDIVIDUAL_TAB = "INDIVIDUAL_TAB"


class TableSessionStatusEnum(str, Enum):
    OPEN = "OPEN"
    IN_SERVICE = "IN_SERVICE"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    CANCELED = "CANCELED"


class ServiceTable(SQLModel, table=True):
    __tablename__ = "service_tables"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", "code", name="uq_service_table_store_code"),
        UniqueConstraint("tenant_id", "creation_idempotency_key", name="uq_service_table_creation_key"),
        CheckConstraint("capacity > 0", name="ck_service_table_capacity_positive"),
        CheckConstraint("version > 0", name="ck_service_table_version_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    code: str = Field(max_length=40, index=True)
    name: str = Field(max_length=120, index=True)
    capacity: int = Field(default=1, ge=1)
    area: Optional[str] = Field(default=None, max_length=80, index=True)
    status: ServiceTableStatusEnum = Field(
        default=ServiceTableStatusEnum.AVAILABLE,
        sa_column=Column(EnumString(ServiceTableStatusEnum), nullable=False, index=True),
    )
    version: int = Field(default=1, ge=1)
    is_active: bool = Field(default=True, index=True)
    creation_idempotency_key: str = Field(max_length=160, index=True)
    creation_request_hash: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TableSession(SQLModel, table=True):
    __tablename__ = "table_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "open_idempotency_key", name="uq_table_session_open_key"),
        CheckConstraint("version > 0", name="ck_table_session_version_positive"),
        CheckConstraint(
            "(kind = 'TABLE' AND service_table_id IS NOT NULL) OR "
            "(kind = 'INDIVIDUAL_TAB' AND service_table_id IS NULL)",
            name="ck_table_session_kind_resource",
        ),
        Index(
            "uq_active_table_session", "tenant_id", "store_id", "service_table_id",
            unique=True,
            postgresql_where=text(
                "service_table_id IS NOT NULL AND status IN "
                "('OPEN', 'IN_SERVICE', 'PARTIALLY_PAID', 'CLOSING')"
            ),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    service_table_id: Optional[uuid.UUID] = Field(default=None, foreign_key="service_tables.id", index=True)
    kind: TableSessionKindEnum = Field(sa_column=Column(EnumString(TableSessionKindEnum), nullable=False, index=True))
    status: TableSessionStatusEnum = Field(
        default=TableSessionStatusEnum.OPEN,
        sa_column=Column(EnumString(TableSessionStatusEnum), nullable=False, index=True),
    )
    display_label: str = Field(max_length=120, index=True)
    customer_id: Optional[uuid.UUID] = Field(default=None, foreign_key="customers.id", index=True)
    attendant_id: uuid.UUID = Field(index=True)
    opened_by: uuid.UUID = Field(index=True)
    closed_by: Optional[uuid.UUID] = Field(default=None, index=True)
    close_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    version: int = Field(default=1, ge=1)
    open_idempotency_key: str = Field(max_length=160, index=True)
    open_request_hash: str = Field(max_length=64)
    opened_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = Field(default=None, index=True)


class TableSessionEvent(SQLModel, table=True):
    __tablename__ = "table_session_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    table_session_id: uuid.UUID = Field(foreign_key="table_sessions.id", ondelete="CASCADE", index=True)
    event_type: str = Field(max_length=80, index=True)
    actor_id: uuid.UUID = Field(index=True)
    from_status: Optional[str] = Field(default=None, max_length=40)
    to_status: Optional[str] = Field(default=None, max_length=40)
    reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class TableSessionCommand(SQLModel, table=True):
    __tablename__ = "table_session_commands"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_table_session_command_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    table_session_id: uuid.UUID = Field(foreign_key="table_sessions.id", ondelete="CASCADE", index=True)
    idempotency_key: str = Field(max_length=160, index=True)
    command_type: str = Field(max_length=80, index=True)
    request_hash: str = Field(max_length=64)
    result_entity_id: uuid.UUID = Field(index=True)
    actor_id: uuid.UUID = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

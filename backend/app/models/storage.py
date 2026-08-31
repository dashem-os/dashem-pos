"""Persistence for provider-backed storage metering and quota reservations."""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, CheckConstraint, Column, JSON, String, Text
from sqlmodel import Field, SQLModel, UniqueConstraint


class StorageMeterSource(SQLModel, table=True):
    """Physical namespace that a trusted meter must inventory exhaustively."""

    __tablename__ = "storage_meter_sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_key", name="uq_storage_meter_source_tenant_key"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_storage_meter_source_status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    source_key: str = Field(sa_column=Column(String(80), nullable=False, index=True))
    provider: str = Field(sa_column=Column(String(60), nullable=False, index=True))
    locator_reference: str = Field(sa_column=Column(String(240), nullable=False))
    status: str = Field(default="ACTIVE", sa_column=Column(String(16), nullable=False, index=True))
    created_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StorageMeasurement(SQLModel, table=True):
    """Append-only aggregate emitted by a trusted inventory adapter."""

    __tablename__ = "storage_measurements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_fingerprint", name="uq_storage_measurement_fingerprint"),
        CheckConstraint(
            "status IN ('PARTIAL', 'RECONCILED', 'DIVERGENT', 'UNAVAILABLE')",
            name="ck_storage_measurement_status",
        ),
        CheckConstraint("used_bytes IS NULL OR used_bytes >= 0", name="ck_storage_measurement_used_bytes"),
        CheckConstraint("object_count IS NULL OR object_count >= 0", name="ck_storage_measurement_object_count"),
        CheckConstraint(
            "status <> 'RECONCILED' OR (used_bytes IS NOT NULL AND object_count IS NOT NULL)",
            name="ck_storage_measurement_reconciled_values",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    status: str = Field(sa_column=Column(String(20), nullable=False, index=True))
    used_bytes: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    object_count: Optional[int] = Field(default=None)
    source_keys: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, default=list)
    )
    watermark: str = Field(sa_column=Column(String(240), nullable=False))
    source_fingerprint: str = Field(sa_column=Column(String(128), nullable=False, index=True))
    evidence: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )
    measured_at: datetime = Field(index=True)
    recorded_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    recorded_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class StorageReservation(SQLModel, table=True):
    """Capacity held before a storage-producing operation commits its object."""

    __tablename__ = "storage_reservations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "operation_key", name="uq_storage_reservation_operation"),
        CheckConstraint("requested_bytes > 0", name="ck_storage_reservation_requested_bytes"),
        CheckConstraint(
            "status IN ('ACTIVE', 'COMMITTED', 'RELEASED', 'EXPIRED')",
            name="ck_storage_reservation_status",
        ),
        CheckConstraint("contract_version >= 1", name="ck_storage_reservation_contract_version"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    operation_key: str = Field(sa_column=Column(String(160), nullable=False))
    requested_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    status: str = Field(default="ACTIVE", sa_column=Column(String(20), nullable=False, index=True))
    contract_id: uuid.UUID = Field(foreign_key="tenant_contracts.id", index=True)
    contract_version: int = Field(ge=1)
    measurement_id: uuid.UUID = Field(foreign_key="storage_measurements.id", index=True)
    created_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    finalized_at: Optional[datetime] = Field(default=None, index=True)
    final_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

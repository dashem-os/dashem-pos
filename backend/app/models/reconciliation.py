import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import CheckConstraint, Column, Numeric, Text
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


class ReconciliationStatusEnum(str, Enum):
    MATCHED = "MATCHED"
    DIFFERENCE = "DIFFERENCE"


class FinancialReconciliation(SQLModel, table=True):
    __tablename__ = "financial_reconciliations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sale_id", name="uq_tenant_sale_reconciliation"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    sale_id: uuid.UUID = Field(foreign_key="sales.id", index=True)
    negotiation_id: Optional[uuid.UUID] = Field(default=None, foreign_key="checkout_negotiations.id", index=True)
    fiscal_document_id: Optional[uuid.UUID] = Field(default=None, foreign_key="fiscal_documents.id", index=True)
    cash_session_id: Optional[uuid.UUID] = Field(default=None, foreign_key="cash_sessions.id", index=True)
    expected_amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    payment_total: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    receivable_total: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    provider_reported_total: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    difference: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    status: ReconciliationStatusEnum = Field(sa_column=Column(EnumString(ReconciliationStatusEnum), nullable=False, index=True))
    provider: Optional[str] = Field(default=None, index=True)
    provider_reference: Optional[str] = Field(default=None, index=True)
    version: int = Field(default=1)
    actor_id: uuid.UUID = Field(index=True)
    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    checked_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReconciliationEvent(SQLModel, table=True):
    __tablename__ = "reconciliation_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    reconciliation_id: uuid.UUID = Field(foreign_key="financial_reconciliations.id", index=True)
    actor_id: uuid.UUID = Field(index=True)
    status: ReconciliationStatusEnum = Field(sa_column=Column(EnumString(ReconciliationStatusEnum), nullable=False, index=True))
    expected_amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    observed_amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    difference: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    provider: Optional[str] = None
    provider_reference: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class PaymentRefund(SQLModel, table=True):
    __tablename__ = "payment_refunds"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_payment_refund_key"),
        CheckConstraint("amount > 0", name="ck_payment_refund_amount_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    payment_id: uuid.UUID = Field(foreign_key="payments.id", index=True)
    cash_session_id: Optional[uuid.UUID] = Field(default=None, foreign_key="cash_sessions.id", index=True)
    cash_movement_id: Optional[uuid.UUID] = Field(default=None, foreign_key="cash_movements.id", unique=True)
    amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    provider_reference: Optional[str] = Field(default=None, index=True)
    idempotency_key: str = Field(index=True)
    actor_id: uuid.UUID = Field(index=True)
    reason: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

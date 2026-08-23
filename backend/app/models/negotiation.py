import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import CheckConstraint, Column, Index, JSON, Numeric, Text, text
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString
from app.models.payment import PaymentMethodEnum


class CheckoutNegotiationStatusEnum(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_COVERED = "PARTIALLY_COVERED"
    COVERED = "COVERED"
    INVALIDATED = "INVALIDATED"
    FINALIZED = "FINALIZED"
    CANCELED = "CANCELED"


class PaymentIntentStatusEnum(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class CheckoutNegotiation(SQLModel, table=True):
    __tablename__ = "checkout_negotiations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "open_idempotency_key", name="uq_tenant_negotiation_open_key"),
        CheckConstraint("version > 0", name="ck_negotiation_version_positive"),
        CheckConstraint("total_due >= 0", name="ck_negotiation_total_nonnegative"),
        Index(
            "uq_active_negotiation_scope", "tenant_id", "store_id", "scope_key",
            unique=True,
            postgresql_where=text("status IN ('OPEN', 'PARTIALLY_COVERED', 'COVERED')"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    table_session_id: Optional[uuid.UUID] = Field(default=None, foreign_key="table_sessions.id", index=True)
    sale_id: Optional[uuid.UUID] = Field(default=None, foreign_key="sales.id", index=True)
    scope_key: str = Field(max_length=160, index=True)
    status: CheckoutNegotiationStatusEnum = Field(
        default=CheckoutNegotiationStatusEnum.OPEN,
        sa_column=Column(EnumString(CheckoutNegotiationStatusEnum), nullable=False, index=True),
    )
    subtotal: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    discount_total: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    surcharge_total: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    tax_total: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    total_due: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    source_version: int = Field(ge=1)
    version: int = Field(default=1, ge=1)
    opened_by: uuid.UUID = Field(index=True)
    finalized_by: Optional[uuid.UUID] = Field(default=None, index=True)
    open_idempotency_key: str = Field(max_length=160, index=True)
    open_request_hash: str = Field(max_length=64)
    finalize_idempotency_key: Optional[str] = Field(default=None, max_length=160, index=True)
    finalize_request_hash: Optional[str] = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    finalized_at: Optional[datetime] = Field(default=None, index=True)


class NegotiationOrder(SQLModel, table=True):
    __tablename__ = "negotiation_orders"
    __table_args__ = (
        UniqueConstraint("negotiation_id", "order_id", name="uq_negotiation_order"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    negotiation_id: uuid.UUID = Field(foreign_key="checkout_negotiations.id", ondelete="CASCADE", index=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", index=True)
    amount_snapshot: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class PaymentIntent(SQLModel, table=True):
    __tablename__ = "payment_intents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_payment_intent_key"),
        CheckConstraint("amount > 0", name="ck_payment_intent_amount_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    negotiation_id: uuid.UUID = Field(foreign_key="checkout_negotiations.id", ondelete="CASCADE", index=True)
    cash_session_id: Optional[uuid.UUID] = Field(default=None, foreign_key="cash_sessions.id", index=True)
    cash_movement_id: Optional[uuid.UUID] = Field(default=None, foreign_key="cash_movements.id", unique=True)
    method: PaymentMethodEnum = Field(sa_column=Column(EnumString(PaymentMethodEnum), nullable=False, index=True))
    status: PaymentIntentStatusEnum = Field(
        default=PaymentIntentStatusEnum.PENDING,
        sa_column=Column(EnumString(PaymentIntentStatusEnum), nullable=False, index=True),
    )
    amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    tendered_amount: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    change_amount: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    provider: str = Field(default="MANUAL", max_length=80, index=True)
    failure_code: Optional[str] = Field(default=None, max_length=80)
    failure_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    idempotency_key: str = Field(max_length=160, index=True)
    request_hash: str = Field(max_length=64)
    confirm_idempotency_key: Optional[str] = Field(default=None, max_length=160, index=True)
    confirm_request_hash: Optional[str] = Field(default=None, max_length=64)
    failure_idempotency_key: Optional[str] = Field(default=None, max_length=160, index=True)
    failure_request_hash: Optional[str] = Field(default=None, max_length=64)
    created_by: uuid.UUID = Field(index=True)
    confirmed_by: Optional[uuid.UUID] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    confirmed_at: Optional[datetime] = Field(default=None, index=True)
    failed_at: Optional[datetime] = Field(default=None, index=True)


class PaymentAllocation(SQLModel, table=True):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_allocation_amount_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    negotiation_id: uuid.UUID = Field(foreign_key="checkout_negotiations.id", ondelete="CASCADE", index=True)
    payment_intent_id: uuid.UUID = Field(foreign_key="payment_intents.id", ondelete="CASCADE", index=True)
    order_id: Optional[uuid.UUID] = Field(default=None, foreign_key="orders.id", index=True)
    order_item_id: Optional[uuid.UUID] = Field(default=None, foreign_key="order_items.id", index=True)
    amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class NegotiationEvent(SQLModel, table=True):
    __tablename__ = "negotiation_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    negotiation_id: uuid.UUID = Field(foreign_key="checkout_negotiations.id", ondelete="CASCADE", index=True)
    event_type: str = Field(max_length=80, index=True)
    actor_id: uuid.UUID = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

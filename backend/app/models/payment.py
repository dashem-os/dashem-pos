import uuid
from decimal import Decimal
from datetime import datetime
from enum import Enum
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint, Column, Numeric
from sqlalchemy import Text
from app.core.db_types import EnumString

class CashSessionStatusEnum(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"

class CashMovementTypeEnum(str, Enum):
    OPENING = "OPENING"
    SALE_PAYMENT = "SALE_PAYMENT"
    BLEED = "BLEED"
    REINFORCEMENT = "REINFORCEMENT"
    CLOSING = "CLOSING"
    RECEIVABLE_PAYMENT = "RECEIVABLE_PAYMENT"
    REFUND = "REFUND"

class PaymentMethodEnum(str, Enum):
    CASH = "CASH"
    PIX = "PIX"
    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"
    STORE_CREDIT = "STORE_CREDIT"

class PaymentStatusEnum(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"

class Register(SQLModel, table=True):
    __tablename__ = "registers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", "code", name="uq_tenant_store_register_code"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: uuid.UUID = Field(index=True)
    name: str = Field(index=True)
    code: str = Field(index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    sessions: List["CashSession"] = Relationship(back_populates="register")

class CashSession(SQLModel, table=True):
    __tablename__ = "cash_sessions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: uuid.UUID = Field(index=True)
    register_id: uuid.UUID = Field(foreign_key="registers.id", index=True)
    operator_id: uuid.UUID = Field(index=True)
    status: CashSessionStatusEnum = Field(
        default=CashSessionStatusEnum.OPEN,
        sa_column=Column(EnumString(CashSessionStatusEnum), nullable=False, index=True),
    )
    opening_balance: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 4), nullable=False, default=0.0))
    closing_balance: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    expected_balance: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    variance: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    version: int = Field(default=1)
    blind_count: bool = Field(default=False)
    closing_started_at: Optional[datetime] = Field(default=None)
    closing_started_by: Optional[uuid.UUID] = Field(default=None, index=True)
    divergence_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    opened_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    closed_at: Optional[datetime] = Field(default=None)

    register: Optional["Register"] = Relationship(back_populates="sessions")
    movements: List["CashMovement"] = Relationship(back_populates="cash_session")
    payments: List["Payment"] = Relationship(back_populates="cash_session")

class CashMovement(SQLModel, table=True):
    __tablename__ = "cash_movements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_cash_movement_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: uuid.UUID = Field(index=True)
    cash_session_id: uuid.UUID = Field(foreign_key="cash_sessions.id", index=True)
    actor_id: uuid.UUID = Field(index=True)
    movement_type: CashMovementTypeEnum = Field(sa_column=Column(EnumString(CashMovementTypeEnum), nullable=False, index=True))
    amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    notes: Optional[str] = None
    source_type: Optional[str] = Field(default=None, index=True)
    source_id: Optional[str] = Field(default=None, index=True)
    idempotency_key: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    cash_session: Optional["CashSession"] = Relationship(back_populates="movements")

class Payment(SQLModel, table=True):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "provider_event_id", name="uq_tenant_provider_event_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: uuid.UUID = Field(index=True)
    sale_id: uuid.UUID = Field(foreign_key="sales.id", index=True)
    cash_session_id: Optional[uuid.UUID] = Field(default=None, foreign_key="cash_sessions.id", index=True)
    method: PaymentMethodEnum = Field(sa_column=Column(EnumString(PaymentMethodEnum), nullable=False, index=True))
    status: PaymentStatusEnum = Field(
        default=PaymentStatusEnum.PENDING,
        sa_column=Column(EnumString(PaymentStatusEnum), nullable=False, index=True),
    )
    amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    tendered_amount: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    change_amount: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 4), nullable=True))
    provider: str = Field(default="MANUAL_OPERATOR", index=True)
    provider_event_id: Optional[str] = Field(default=None, index=True)
    transaction_ref: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    confirmed_at: Optional[datetime] = Field(default=None)

    cash_session: Optional["CashSession"] = Relationship(back_populates="payments")

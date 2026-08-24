import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import CheckConstraint, Column, JSON, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


class CreditPolicyStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class ReceivableStatusEnum(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    REVERSED = "REVERSED"
    RENEGOTIATED = "RENEGOTIATED"


class ReceivableEntryTypeEnum(str, Enum):
    ISSUE = "ISSUE"
    PAYMENT = "PAYMENT"
    ADJUSTMENT = "ADJUSTMENT"
    REVERSAL = "REVERSAL"
    AGREEMENT = "AGREEMENT"


class CustomerCreditPolicy(SQLModel, table=True):
    __tablename__ = "customer_credit_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_id", name="uq_tenant_customer_credit_policy"),
        CheckConstraint("credit_limit >= 0", name="ck_credit_policy_limit_nonnegative"),
        CheckConstraint("terms_days BETWEEN 0 AND 3650", name="ck_credit_policy_terms_range"),
        CheckConstraint("version > 0", name="ck_credit_policy_version_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    customer_id: uuid.UUID = Field(foreign_key="customers.id", index=True)
    status: CreditPolicyStatusEnum = Field(
        default=CreditPolicyStatusEnum.ACTIVE,
        sa_column=Column(EnumString(CreditPolicyStatusEnum), nullable=False, index=True),
    )
    credit_limit: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    terms_days: int = Field(default=30)
    allow_overdue: bool = Field(default=False)
    version: int = Field(default=1)
    updated_by: uuid.UUID = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Receivable(SQLModel, table=True):
    __tablename__ = "receivables"
    __table_args__ = (
        UniqueConstraint("tenant_id", "issue_idempotency_key", name="uq_tenant_receivable_issue_key"),
        CheckConstraint("principal_amount > 0", name="ck_receivable_principal_positive"),
        CheckConstraint("paid_amount >= 0", name="ck_receivable_paid_nonnegative"),
        CheckConstraint("balance >= 0", name="ck_receivable_balance_nonnegative"),
        CheckConstraint("version > 0", name="ck_receivable_version_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    customer_id: uuid.UUID = Field(foreign_key="customers.id", index=True)
    negotiation_id: uuid.UUID = Field(foreign_key="checkout_negotiations.id", index=True)
    sale_id: Optional[uuid.UUID] = Field(default=None, foreign_key="sales.id", index=True)
    status: ReceivableStatusEnum = Field(
        default=ReceivableStatusEnum.OPEN,
        sa_column=Column(EnumString(ReceivableStatusEnum), nullable=False, index=True),
    )
    principal_amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    paid_amount: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    balance: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    issued_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    due_at: datetime = Field(index=True)
    version: int = Field(default=1)
    issue_idempotency_key: str = Field(max_length=160, index=True)
    issue_request_hash: str = Field(max_length=64)
    reversed_at: Optional[datetime] = Field(default=None, index=True)
    created_by: uuid.UUID = Field(index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ReceivableAllocation(SQLModel, table=True):
    __tablename__ = "receivable_allocations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "negotiation_id", name="uq_tenant_negotiation_receivable_allocation"),
        CheckConstraint("amount > 0", name="ck_receivable_allocation_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    negotiation_id: uuid.UUID = Field(foreign_key="checkout_negotiations.id", index=True)
    receivable_id: uuid.UUID = Field(foreign_key="receivables.id", ondelete="CASCADE", index=True)
    amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class ReceivableLedgerEntry(SQLModel, table=True):
    __tablename__ = "receivable_ledger_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_receivable_ledger_key"),
        CheckConstraint("amount <> 0", name="ck_receivable_ledger_amount_nonzero"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    receivable_id: uuid.UUID = Field(foreign_key="receivables.id", ondelete="RESTRICT", index=True)
    entry_type: ReceivableEntryTypeEnum = Field(
        sa_column=Column(EnumString(ReceivableEntryTypeEnum), nullable=False, index=True)
    )
    amount: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    balance_after: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    actor_id: uuid.UUID = Field(index=True)
    reason: str = Field(sa_column=Column(Text, nullable=False))
    idempotency_key: str = Field(max_length=160, index=True)
    metadata_payload: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import CheckConstraint, Column, Index, Numeric, String, Text
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


class SaasInvoiceStatusEnum(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    VOID = "VOID"
    UNCOLLECTIBLE = "UNCOLLECTIBLE"


class SaasInvoiceLineTypeEnum(str, Enum):
    PLAN = "PLAN"
    CAPABILITY = "CAPABILITY"
    ADD_ON = "ADD_ON"
    DISCOUNT = "DISCOUNT"
    CREDIT = "CREDIT"
    TAX = "TAX"
    ADJUSTMENT = "ADJUSTMENT"


class SaasPaymentStatusEnum(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class SaasCollectionEventTypeEnum(str, Enum):
    OVERDUE_MARKED = "OVERDUE_MARKED"
    CONTACT_ATTEMPT = "CONTACT_ATTEMPT"
    PROMISE_TO_PAY = "PROMISE_TO_PAY"
    MANUAL_NOTE = "MANUAL_NOTE"


class SaasMrrMovementTypeEnum(str, Enum):
    BASELINE = "BASELINE"
    NONE = "NONE"
    NEW = "NEW"
    EXPANSION = "EXPANSION"
    CONTRACTION = "CONTRACTION"
    CHURN = "CHURN"


class SaasBillingAccount(SQLModel, table=True):
    """Platform-owned billing identity for a Dashem SaaS customer.

    This record contains only the data needed for Dashem to bill its customer.
    It must never be populated from sales, cash, staff, or other tenant
    operating data.
    """

    __tablename__ = "saas_billing_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_saas_billing_accounts_tenant"),
        CheckConstraint(
            "version >= 1",
            name="ck_saas_billing_accounts_version_positive",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    legal_name: Optional[str] = Field(default=None, max_length=200)
    tax_id: Optional[str] = Field(default=None, max_length=14)
    contact_name: Optional[str] = Field(default=None, max_length=160)
    contact_email: Optional[str] = Field(default=None, max_length=254)
    contact_phone: Optional[str] = Field(default=None, max_length=32)
    currency: str = Field(default="BRL", max_length=3)
    provider_customer_reference: Optional[str] = Field(default=None, max_length=180)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SaasInvoice(SQLModel, table=True):
    """Platform-owned invoice for the Dashem subscription, never tenant sales."""

    __tablename__ = "saas_invoices"
    __table_args__ = (
        UniqueConstraint("public_number", name="uq_saas_invoices_public_number"),
        UniqueConstraint("generation_key", name="uq_saas_invoices_generation_key"),
        UniqueConstraint("issue_idempotency_key", name="uq_saas_invoices_issue_idempotency"),
        UniqueConstraint("void_idempotency_key", name="uq_saas_invoices_void_idempotency"),
        UniqueConstraint(
            "subscription_id", "period_start", "generation_revision",
            name="uq_saas_invoice_subscription_period_revision",
        ),
        CheckConstraint("tenant_id = subscription_id", name="ck_saas_invoice_subscription_tenant"),
        CheckConstraint(
            "period_start = date_trunc('month', period_start)::date",
            name="ck_saas_invoice_period_start",
        ),
        CheckConstraint(
            "period_end = (date_trunc('month', period_start) + interval '1 month - 1 day')::date",
            name="ck_saas_invoice_period_end",
        ),
        CheckConstraint("subtotal >= 0", name="ck_saas_invoice_subtotal_nonnegative"),
        CheckConstraint("discount_amount >= 0", name="ck_saas_invoice_discount_nonnegative"),
        CheckConstraint("tax_amount >= 0", name="ck_saas_invoice_tax_nonnegative"),
        CheckConstraint("total_amount >= 0", name="ck_saas_invoice_total_nonnegative"),
        CheckConstraint("balance_amount >= 0 AND balance_amount <= total_amount", name="ck_saas_invoice_balance"),
        CheckConstraint(
            "total_amount = subtotal - discount_amount + tax_amount",
            name="ck_saas_invoice_total_formula",
        ),
        CheckConstraint("version >= 1", name="ck_saas_invoice_version_positive"),
        CheckConstraint("generation_revision >= 1", name="ck_saas_invoice_generation_revision_positive"),
        Index("ix_saas_invoices_period_status", "period_start", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    public_number: str = Field(max_length=40, index=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    billing_account_id: uuid.UUID = Field(foreign_key="saas_billing_accounts.id", index=True)
    subscription_id: uuid.UUID = Field(foreign_key="tenant_subscriptions.tenant_id", index=True)
    contract_id: uuid.UUID = Field(foreign_key="tenant_contracts.id", index=True)
    plan_id: uuid.UUID = Field(foreign_key="service_plans.id", index=True)
    period_start: date = Field(index=True)
    period_end: date = Field(index=True)
    due_date: date = Field(index=True)
    currency: str = Field(default="BRL", max_length=3)
    subtotal: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    discount_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 2), nullable=False, default=0))
    tax_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(14, 2), nullable=False, default=0))
    total_amount: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    balance_amount: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    status: SaasInvoiceStatusEnum = Field(
        default=SaasInvoiceStatusEnum.DRAFT,
        sa_column=Column(EnumString(SaasInvoiceStatusEnum), nullable=False, index=True),
    )
    generation_key: str = Field(max_length=64)
    generation_revision: int = Field(default=1)
    contract_version: int
    plan_code_snapshot: str = Field(max_length=60)
    plan_name_snapshot: str = Field(max_length=120)
    description_snapshot: str = Field(max_length=240)
    billing_legal_name_snapshot: str = Field(max_length=200)
    billing_tax_id_snapshot: str = Field(max_length=14)
    billing_contact_email_snapshot: str = Field(max_length=254)
    fiscal_reference: Optional[str] = Field(default=None, max_length=180)
    provider_reference: Optional[str] = Field(default=None, max_length=180)
    issued_at: Optional[datetime] = Field(default=None, index=True)
    issued_by: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    issue_idempotency_key: Optional[str] = Field(default=None, max_length=160)
    issue_request_hash: Optional[str] = Field(default=None, max_length=64)
    voided_at: Optional[datetime] = Field(default=None, index=True)
    voided_by: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    void_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    void_idempotency_key: Optional[str] = Field(default=None, max_length=160)
    void_request_hash: Optional[str] = Field(default=None, max_length=64)
    paid_at: Optional[datetime] = Field(default=None, index=True)
    created_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    version: int = Field(default=1)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SaasInvoiceLine(SQLModel, table=True):
    __tablename__ = "saas_invoice_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_saas_invoice_line_quantity_positive"),
        CheckConstraint("total_amount = quantity * unit_amount", name="ck_saas_invoice_line_total_formula"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    invoice_id: uuid.UUID = Field(
        foreign_key="saas_invoices.id", ondelete="CASCADE", index=True
    )
    line_type: SaasInvoiceLineTypeEnum = Field(
        sa_column=Column(EnumString(SaasInvoiceLineTypeEnum), nullable=False, index=True)
    )
    description: str = Field(max_length=240)
    quantity: Decimal = Field(sa_column=Column(Numeric(14, 4), nullable=False))
    unit_amount: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    total_amount: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    contract_version: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SaasPayment(SQLModel, table=True):
    """Money received by Dashem for its SaaS invoices, never tenant payments."""

    __tablename__ = "saas_payments"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_saas_payments_idempotency_key"),
        UniqueConstraint(
            "reconcile_idempotency_key", name="uq_saas_payments_reconcile_idempotency"
        ),
        UniqueConstraint(
            "provider", "provider_payment_reference",
            name="uq_saas_payments_provider_reference",
        ),
        CheckConstraint("amount > 0", name="ck_saas_payments_amount_positive"),
        CheckConstraint("version >= 1", name="ck_saas_payments_version_positive"),
        Index("ix_saas_payments_received_status", "received_at", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    billing_account_id: uuid.UUID = Field(foreign_key="saas_billing_accounts.id", index=True)
    provider: str = Field(max_length=60, index=True)
    provider_payment_reference: Optional[str] = Field(default=None, max_length=180, index=True)
    external_event_id: Optional[str] = Field(default=None, max_length=180, index=True)
    idempotency_key: str = Field(max_length=160)
    request_hash: str = Field(max_length=64)
    reconcile_idempotency_key: Optional[str] = Field(default=None, max_length=160)
    reconcile_request_hash: Optional[str] = Field(default=None, max_length=64)
    status: SaasPaymentStatusEnum = Field(
        sa_column=Column(EnumString(SaasPaymentStatusEnum), nullable=False, index=True)
    )
    currency: str = Field(default="BRL", max_length=3)
    amount: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    payment_method_summary: Optional[str] = Field(default=None, max_length=80)
    failure_code: Optional[str] = Field(default=None, max_length=80)
    evidence_reference: str = Field(max_length=240)
    received_at: datetime = Field(index=True)
    succeeded_at: Optional[datetime] = Field(default=None, index=True)
    created_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    version: int = Field(default=1)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SaasPaymentAllocation(SQLModel, table=True):
    __tablename__ = "saas_payment_allocations"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_saas_payment_allocations_idempotency_key"),
        CheckConstraint("amount > 0", name="ck_saas_payment_allocations_amount_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    payment_id: uuid.UUID = Field(foreign_key="saas_payments.id", index=True)
    invoice_id: uuid.UUID = Field(foreign_key="saas_invoices.id", index=True)
    amount: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    idempotency_key: str = Field(max_length=160)
    allocated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class SaasRefund(SQLModel, table=True):
    __tablename__ = "saas_refunds"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_saas_refunds_idempotency_key"),
        CheckConstraint("amount > 0", name="ck_saas_refunds_amount_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    payment_id: uuid.UUID = Field(foreign_key="saas_payments.id", index=True)
    invoice_id: uuid.UUID = Field(foreign_key="saas_invoices.id", index=True)
    amount: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    reason: str = Field(sa_column=Column(Text, nullable=False))
    evidence_reference: str = Field(max_length=240)
    idempotency_key: str = Field(max_length=160)
    refunded_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SaasCollectionEvent(SQLModel, table=True):
    __tablename__ = "saas_collection_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_saas_collection_events_idempotency_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    invoice_id: uuid.UUID = Field(foreign_key="saas_invoices.id", index=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    event_type: SaasCollectionEventTypeEnum = Field(
        sa_column=Column(EnumString(SaasCollectionEventTypeEnum), nullable=False, index=True)
    )
    channel: str = Field(max_length=40)
    outcome: str = Field(max_length=80)
    recipient_masked: Optional[str] = Field(default=None, max_length=160)
    detail: str = Field(sa_column=Column(Text, nullable=False))
    evidence_reference: Optional[str] = Field(default=None, max_length=240)
    idempotency_key: str = Field(max_length=160)
    actor_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    occurred_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SaasFinanceDailyMetric(SQLModel, table=True):
    """Rebuildable daily projection sourced only from platform SaaS facts."""

    __tablename__ = "saas_finance_daily_metrics"
    __table_args__ = (
        UniqueConstraint("metric_date", name="uq_saas_finance_daily_metrics_date"),
        UniqueConstraint(
            "rebuild_idempotency_key",
            name="uq_saas_finance_daily_metrics_rebuild_idempotency",
        ),
        CheckConstraint("version >= 1", name="ck_saas_finance_daily_metrics_version_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    metric_date: date = Field(index=True)
    formula_version: str = Field(max_length=40, index=True)
    watermark: datetime = Field(index=True)
    source_fingerprint: str = Field(max_length=64)
    rebuild_idempotency_key: str = Field(max_length=160)
    rebuild_request_hash: str = Field(max_length=64)
    active_subscriptions: int = Field(default=0, ge=0)
    excluded_subscriptions: int = Field(default=0, ge=0)
    contracted_mrr: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    projected_arr: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    new_mrr: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 2), nullable=True))
    expansion_mrr: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 2), nullable=True))
    contraction_mrr: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 2), nullable=True))
    churned_mrr: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 2), nullable=True))
    net_new_mrr: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 2), nullable=True))
    logo_churn_rate: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(9, 6), nullable=True))
    invoiced_total: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    received_total: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    refunded_total: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    open_balance: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    overdue_balance: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    collection_rate: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(9, 6), nullable=True))
    delinquency_rate: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(9, 6), nullable=True))
    invoice_count: int = Field(default=0, ge=0)
    paid_invoice_count: int = Field(default=0, ge=0)
    overdue_invoice_count: int = Field(default=0, ge=0)
    version: int = Field(default=1, ge=1)
    calculated_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    calculated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SaasFinanceSubscriptionSnapshot(SQLModel, table=True):
    """Tenant-level drill-down captured with a daily financial projection."""

    __tablename__ = "saas_finance_subscription_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "metric_id", "tenant_id",
            name="uq_saas_finance_subscription_snapshot_metric_tenant",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    metric_id: uuid.UUID = Field(
        foreign_key="saas_finance_daily_metrics.id", ondelete="CASCADE", index=True
    )
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    subscription_version: int = Field(ge=1)
    subscription_status: str = Field(max_length=32, index=True)
    contract_id: Optional[uuid.UUID] = Field(default=None, foreign_key="tenant_contracts.id")
    contract_version: Optional[int] = None
    included_in_mrr: bool = Field(default=False, index=True)
    exclusion_reason: Optional[str] = Field(default=None, max_length=80)
    previous_mrr: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 2), nullable=True))
    current_mrr: Decimal = Field(sa_column=Column(Numeric(14, 2), nullable=False))
    movement_type: SaasMrrMovementTypeEnum = Field(
        sa_column=Column(EnumString(SaasMrrMovementTypeEnum), nullable=False, index=True)
    )
    movement_amount: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(14, 2), nullable=True))
    captured_at: datetime = Field(default_factory=datetime.utcnow)

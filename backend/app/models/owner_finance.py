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

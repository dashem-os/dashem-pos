import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class SaasBillingAccount(SQLModel, table=True):
    """Platform-owned billing identity for a Dashem SaaS customer.

    This record contains only the data needed for Dashem to bill its customer.
    It must never be populated from sales, cash, staff, or other tenant
    operating data.
    """

    __tablename__ = "saas_billing_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_saas_billing_accounts_tenant"),
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

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import Column, Numeric, Text
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


class BiFactScopeEnum(str, Enum):
    SALES = "SALES"
    OPERATIONS = "OPERATIONS"


class BiDailyFact(SQLModel, table=True):
    __tablename__ = "bi_daily_facts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", "competence_date", "scope", "register_key", "operator_key", "channel_key", name="uq_bi_daily_fact_dimension"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    competence_date: date = Field(index=True)
    scope: BiFactScopeEnum = Field(sa_column=Column(EnumString(BiFactScopeEnum), nullable=False, index=True))
    register_key: str = Field(default="ALL", max_length=40, index=True)
    operator_key: str = Field(default="ALL", max_length=40, index=True)
    channel_key: str = Field(default="ALL", max_length=40, index=True)
    gross_revenue: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    net_revenue: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    discount_total: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    refunds_total: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    sales_count: int = Field(default=0)
    confirmed_receipts: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    cash_receipts: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    pix_receipts: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    card_receipts: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    receivables_issued: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    receivables_settled: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    marketplace_settled: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(14, 4), nullable=False))
    table_sessions_closed: int = Field(default=0)
    table_service_seconds: int = Field(default=0)
    production_tickets_completed: int = Field(default=0)
    production_seconds: int = Field(default=0)
    transfers_count: int = Field(default=0)
    stockout_products: int = Field(default=0)
    projected_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class BiProjectionState(SQLModel, table=True):
    __tablename__ = "bi_projection_states"
    __table_args__ = (UniqueConstraint("tenant_id", "store_id", "projection_key", name="uq_bi_projection_state"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    projection_key: str = Field(default="BI_V1_DAILY", max_length=80, index=True)
    last_competence: Optional[date] = Field(default=None, index=True)
    source_watermark: Optional[datetime] = Field(default=None)
    projected_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    version: int = Field(default=1)
    status: str = Field(default="READY", max_length=40, index=True)
    last_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

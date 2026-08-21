import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint

class FiscalStatusEnum(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    CONTINGENCY = "CONTINGENCY"
    CANCELED = "CANCELED"

class FiscalDocumentTypeEnum(str, Enum):
    NFCE = "NFCE"
    NFE = "NFE"
    SAT = "SAT"
    NONE = "NONE"

class FiscalEventTypeEnum(str, Enum):
    ISSUANCE_REQUESTED = "ISSUANCE_REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    CONTINGENCY_REGISTERED = "CONTINGENCY_REGISTERED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELED = "CANCELED"

class FiscalDocument(SQLModel, table=True):
    __tablename__ = "fiscal_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "access_key", name="uq_tenant_fiscal_access_key"),
        UniqueConstraint("tenant_id", "sale_id", name="uq_tenant_sale_fiscal_document"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: uuid.UUID = Field(index=True)
    sale_id: uuid.UUID = Field(foreign_key="sales.id", index=True)
    document_type: FiscalDocumentTypeEnum = Field(default=FiscalDocumentTypeEnum.NFCE, index=True)
    status: FiscalStatusEnum = Field(default=FiscalStatusEnum.PENDING, index=True)
    access_key: Optional[str] = Field(default=None, index=True)
    document_number: Optional[int] = Field(default=None)
    series: Optional[int] = Field(default=1)
    xml_content: Optional[str] = None
    pdf_url: Optional[str] = None
    rejection_code: Optional[str] = None
    rejection_reason: Optional[str] = None
    request_hash: Optional[str] = Field(default=None)
    provider: str = Field(default="FAKE_FISCAL_GATEWAY", index=True)
    provider_document_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    issued_at: Optional[datetime] = Field(default=None)
    canceled_at: Optional[datetime] = Field(default=None)

    events: List["FiscalEvent"] = Relationship(back_populates="fiscal_document")

class FiscalEvent(SQLModel, table=True):
    __tablename__ = "fiscal_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    store_id: uuid.UUID = Field(index=True)
    fiscal_document_id: uuid.UUID = Field(foreign_key="fiscal_documents.id", index=True)
    actor_id: uuid.UUID = Field(index=True)
    event_type: FiscalEventTypeEnum = Field(index=True)
    details: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    fiscal_document: Optional["FiscalDocument"] = Relationship(back_populates="events")

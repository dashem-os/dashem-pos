import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.payment import PaymentMethodEnum
from app.models.receivable import (
    CreditPolicyStatusEnum, CustomerCreditPolicy, Receivable, ReceivableStatusEnum,
    ReceivableReceipt, ReceivableReceiptStatusEnum, ReceivableAgreement,
    ReceivableAgreementStatusEnum, ReceivableCollectionEvent,
)
from app.services import receivable_service


router = APIRouter()


class CreditPolicyWrite(BaseModel):
    credit_limit: Decimal = Field(ge=0)
    terms_days: int = Field(default=30, ge=0, le=3650)
    allow_overdue: bool = False
    status: CreditPolicyStatusEnum = CreditPolicyStatusEnum.ACTIVE
    expected_version: Optional[int] = Field(default=None, ge=0)
    actor_id: Optional[uuid.UUID] = None


class CreditPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    customer_id: uuid.UUID
    status: CreditPolicyStatusEnum
    credit_limit: Decimal
    terms_days: int
    allow_overdue: bool
    version: int
    updated_at: datetime


class CreditPolicyProjection(BaseModel):
    policy: CreditPolicyRead
    exposure: Decimal
    available: Decimal


class CreditIssueCommand(BaseModel):
    customer_id: uuid.UUID
    expected_version: int = Field(ge=1)
    due_at: Optional[datetime] = None
    reason: str = Field(min_length=3, max_length=500)
    actor_id: Optional[uuid.UUID] = None


class ReceivableRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    customer_id: uuid.UUID
    negotiation_id: Optional[uuid.UUID]
    sale_id: Optional[uuid.UUID]
    agreement_id: Optional[uuid.UUID]
    agreement_installment_number: Optional[int]
    origin_receivable_id: Optional[uuid.UUID]
    status: ReceivableStatusEnum
    principal_amount: Decimal
    paid_amount: Decimal
    balance: Decimal
    issued_at: datetime
    due_at: datetime
    version: int
    reversed_at: Optional[datetime]


class ReverseCommand(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    actor_id: Optional[uuid.UUID] = None


class SettlementAllocationCommand(BaseModel):
    receivable_id: uuid.UUID
    expected_version: int = Field(ge=1)
    principal_amount: Decimal = Field(gt=0)
    interest_amount: Decimal = Field(default=Decimal("0"), ge=0)
    fine_amount: Decimal = Field(default=Decimal("0"), ge=0)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    abatement_amount: Decimal = Field(default=Decimal("0"), ge=0)


class SettlementCommand(BaseModel):
    allocations: list[SettlementAllocationCommand] = Field(min_length=1)
    method: PaymentMethodEnum
    cash_session_id: Optional[uuid.UUID] = None
    provider_reference: Optional[str] = Field(default=None, max_length=160)
    reason: str = Field(min_length=3, max_length=500)
    actor_id: Optional[uuid.UUID] = None


class ReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    customer_id: uuid.UUID
    status: ReceivableReceiptStatusEnum
    method: str
    amount: Decimal
    cash_session_id: Optional[uuid.UUID]
    cash_movement_id: Optional[uuid.UUID]
    provider: str
    provider_reference: Optional[str]
    reason: str
    confirmed_at: Optional[datetime]
    created_at: datetime


class AgreementCommand(BaseModel):
    receivable_ids: list[uuid.UUID] = Field(min_length=1)
    installment_count: int = Field(ge=1, le=120)
    first_due_at: datetime
    interval_days: int = Field(default=30, ge=1, le=365)
    interest_amount: Decimal = Field(default=Decimal("0"), ge=0)
    fine_amount: Decimal = Field(default=Decimal("0"), ge=0)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    reason: str = Field(min_length=3, max_length=500)
    actor_id: Optional[uuid.UUID] = None


class AgreementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    customer_id: uuid.UUID
    status: ReceivableAgreementStatusEnum
    original_principal: Decimal
    interest_amount: Decimal
    fine_amount: Decimal
    discount_amount: Decimal
    agreement_total: Decimal
    installment_count: int
    version: int
    reason: str
    created_at: datetime


class CollectionEventCommand(BaseModel):
    customer_id: uuid.UUID
    receivable_id: Optional[uuid.UUID] = None
    agreement_id: Optional[uuid.UUID] = None
    event_type: str = Field(min_length=3, max_length=60)
    promised_for: Optional[datetime] = None
    notes: str = Field(min_length=3, max_length=1000)
    actor_id: Optional[uuid.UUID] = None


class CollectionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    customer_id: uuid.UUID
    receivable_id: Optional[uuid.UUID]
    agreement_id: Optional[uuid.UUID]
    event_type: str
    promised_for: Optional[datetime]
    notes: str
    created_at: datetime


@router.put("/customers/{customer_id}/policy", response_model=CreditPolicyProjection)
def put_credit_policy(
    customer_id: uuid.UUID, data: CreditPolicyWrite,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    receivable_service.upsert_policy(
        session, context, customer_id=customer_id, credit_limit=data.credit_limit,
        terms_days=data.terms_days, allow_overdue=data.allow_overdue,
        status=data.status, actor_id=data.actor_id, expected_version=data.expected_version,
    )
    return receivable_service.policy_projection(session, context, customer_id)


@router.get("/customers/{customer_id}/policy", response_model=CreditPolicyProjection)
def get_credit_policy(
    customer_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return receivable_service.policy_projection(session, context, customer_id)


@router.post("/negotiations/{negotiation_id}/issue", response_model=ReceivableRead)
def issue_receivable(
    negotiation_id: uuid.UUID, data: CreditIssueCommand,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return receivable_service.issue_and_finalize(
        session, context, negotiation_id, customer_id=data.customer_id,
        expected_version=data.expected_version, due_at=data.due_at, reason=data.reason,
        actor_id=data.actor_id, idempotency_key=idempotency_key,
    )


@router.get("", response_model=list[ReceivableRead])
def get_receivables(
    customer_id: Optional[uuid.UUID] = None,
    status_filter: Optional[ReceivableStatusEnum] = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return receivable_service.list_receivables(
        session, context, customer_id=customer_id, status_filter=status_filter, limit=limit,
    )


@router.post("/{receivable_id}/reverse", response_model=ReceivableRead)
def reverse_receivable(
    receivable_id: uuid.UUID, data: ReverseCommand,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return receivable_service.reverse(
        session, context, receivable_id, reason=data.reason,
        actor_id=data.actor_id, idempotency_key=idempotency_key,
    )


@router.post("/settlements", response_model=ReceiptRead)
def settle_receivables(
    data: SettlementCommand,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return receivable_service.settle(
        session, context, allocations=[item.model_dump(mode="json") for item in data.allocations],
        method=data.method, cash_session_id=data.cash_session_id,
        provider_reference=data.provider_reference, reason=data.reason,
        actor_id=data.actor_id, idempotency_key=idempotency_key,
    )


@router.post("/agreements", response_model=AgreementRead)
def create_agreement(
    data: AgreementCommand,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return receivable_service.create_agreement(
        session, context, receivable_ids=data.receivable_ids,
        installment_count=data.installment_count, first_due_at=data.first_due_at,
        interval_days=data.interval_days, interest_amount=data.interest_amount,
        fine_amount=data.fine_amount, discount_amount=data.discount_amount,
        reason=data.reason, actor_id=data.actor_id, idempotency_key=idempotency_key,
    )


@router.get("/agreements", response_model=list[AgreementRead])
def get_agreements(
    limit: int = Query(default=100, ge=1, le=500),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return receivable_service.list_agreements(session, context, limit)


@router.post("/collection-events", response_model=CollectionEventRead)
def create_collection_event(
    data: CollectionEventCommand,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return receivable_service.record_collection_event(
        session, context, customer_id=data.customer_id, receivable_id=data.receivable_id,
        agreement_id=data.agreement_id, event_type=data.event_type,
        promised_for=data.promised_for, notes=data.notes, actor_id=data.actor_id,
    )

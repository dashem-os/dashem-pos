import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.receivable import CreditPolicyStatusEnum, CustomerCreditPolicy, Receivable, ReceivableStatusEnum
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
    negotiation_id: uuid.UUID
    sale_id: Optional[uuid.UUID]
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

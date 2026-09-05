import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.negotiation import CheckoutNegotiationStatusEnum, PaymentIntentStatusEnum
from app.models.payment import PaymentMethodEnum
from app.services import negotiation_service


router = APIRouter()


class NegotiationOpenDTO(BaseModel):
    store_id: uuid.UUID
    table_session_id: Optional[uuid.UUID] = None
    order_ids: List[uuid.UUID] = Field(default_factory=list)
    actor_id: Optional[uuid.UUID] = None


class AllocationCreateDTO(BaseModel):
    amount: Decimal = Field(gt=0)
    order_id: Optional[uuid.UUID] = None
    order_item_id: Optional[uuid.UUID] = None


class PaymentIntentCreateDTO(BaseModel):
    method: PaymentMethodEnum
    amount: Decimal = Field(gt=0)
    cash_session_id: Optional[uuid.UUID] = None
    tendered_amount: Optional[Decimal] = Field(default=None, gt=0)
    allocations: List[AllocationCreateDTO] = Field(default_factory=list)
    actor_id: Optional[uuid.UUID] = None
    # Whose money this is. Never required: friends splitting a bill do not
    # register themselves, and an unnamed parcel is honest about being unnamed.
    payer_label: Optional[str] = Field(default=None, max_length=160)
    payer_customer_id: Optional[uuid.UUID] = None


class IntentCommandDTO(BaseModel):
    actor_id: Optional[uuid.UUID] = None


class IntentFailureDTO(IntentCommandDTO):
    failure_code: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=3, max_length=500)


class NegotiationFinalizeDTO(BaseModel):
    expected_version: int = Field(ge=1)
    actor_id: Optional[uuid.UUID] = None


class NegotiationOrderDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    order_id: uuid.UUID
    amount_snapshot: Decimal


class PaymentIntentDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    method: PaymentMethodEnum
    status: PaymentIntentStatusEnum
    amount: Decimal
    tendered_amount: Optional[Decimal]
    change_amount: Decimal
    provider: str
    failure_code: Optional[str]
    failure_reason: Optional[str]
    created_at: datetime
    confirmed_at: Optional[datetime]
    failed_at: Optional[datetime]
    payer_label: Optional[str]
    payer_customer_id: Optional[uuid.UUID]


class PaymentAllocationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    payment_intent_id: uuid.UUID
    order_id: Optional[uuid.UUID]
    order_item_id: Optional[uuid.UUID]
    amount: Decimal


class ItemSettlementDTO(BaseModel):
    """What one item of the account still owes, resolved by the server.

    ``available_amount`` is what a next payer may still take; it is the number
    the screen must obey, because a whisky someone is paying for right now reads
    as unavailable long before the card comes back."""
    model_config = ConfigDict(from_attributes=True)
    order_item_id: uuid.UUID
    order_id: uuid.UUID
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    item_total: Decimal
    settled_amount: Decimal
    reserved_amount: Decimal
    available_amount: Decimal
    is_paid: bool
    settled_by: List[str]
    reserved_by: List[str]


class NegotiationProjectionDTO(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    table_session_id: Optional[uuid.UUID]
    sale_id: Optional[uuid.UUID]
    status: CheckoutNegotiationStatusEnum
    subtotal: Decimal
    discount_total: Decimal
    surcharge_total: Decimal
    tax_total: Decimal
    total_due: Decimal
    confirmed_amount: Decimal
    receivable_amount: Decimal
    processing_amount: Decimal
    failed_amount: Decimal
    remaining_amount: Decimal
    source_version: int
    version: int
    created_at: datetime
    updated_at: datetime
    finalized_at: Optional[datetime]
    orders: List[NegotiationOrderDTO]
    intents: List[PaymentIntentDTO]
    allocations: List[PaymentAllocationDTO]
    item_settlements: List[ItemSettlementDTO]
    unassigned_settled_amount: Decimal
    unassigned_reserved_amount: Decimal


@router.post("", response_model=NegotiationProjectionDTO)
def open_negotiation_endpoint(
    data: NegotiationOpenDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return negotiation_service.open_negotiation(
        session, context, store_id=data.store_id,
        table_session_id=data.table_session_id, order_ids=data.order_ids,
        actor_id=data.actor_id, idempotency_key=idempotency_key,
    )


@router.get("/{negotiation_id}", response_model=NegotiationProjectionDTO)
def get_negotiation_endpoint(
    negotiation_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return negotiation_service.projection(session, context, negotiation_id)


@router.post("/{negotiation_id}/intents", response_model=NegotiationProjectionDTO)
def create_payment_intent_endpoint(
    negotiation_id: uuid.UUID, data: PaymentIntentCreateDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return negotiation_service.create_intent(
        session, context, negotiation_id, method=data.method, amount=data.amount,
        cash_session_id=data.cash_session_id, tendered_amount=data.tendered_amount,
        allocations=[item.model_dump(mode="json") for item in data.allocations],
        actor_id=data.actor_id, idempotency_key=idempotency_key,
        payer_label=data.payer_label, payer_customer_id=data.payer_customer_id,
    )


@router.post("/intents/{intent_id}/confirm", response_model=NegotiationProjectionDTO)
def confirm_payment_intent_endpoint(
    intent_id: uuid.UUID, data: IntentCommandDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return negotiation_service.confirm_intent(
        session, context, intent_id, actor_id=data.actor_id,
        idempotency_key=idempotency_key,
    )


@router.post("/intents/{intent_id}/fail", response_model=NegotiationProjectionDTO)
def fail_payment_intent_endpoint(
    intent_id: uuid.UUID, data: IntentFailureDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return negotiation_service.fail_intent(
        session, context, intent_id, failure_code=data.failure_code,
        reason=data.reason, actor_id=data.actor_id, idempotency_key=idempotency_key,
    )


@router.post("/{negotiation_id}/finalize", response_model=NegotiationProjectionDTO)
def finalize_negotiation_endpoint(
    negotiation_id: uuid.UUID, data: NegotiationFinalizeDTO,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return negotiation_service.finalize_negotiation(
        session, context, negotiation_id, expected_version=data.expected_version,
        actor_id=data.actor_id, idempotency_key=idempotency_key,
    )

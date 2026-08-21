import uuid
from decimal import Decimal
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session
from app.core.database import get_session
from app.core.context import TenantContext, get_tenant_context
from app.models.payment import Payment, PaymentMethodEnum
from app.services import payment_service, reliability_service

router = APIRouter()

class PaymentCreateDTO(BaseModel):
    sale_id: uuid.UUID
    method: PaymentMethodEnum
    amount: float
    cash_session_id: Optional[uuid.UUID] = None
    tendered_amount: Optional[float] = None
    provider: str = "FAKE_PSP"
    provider_event_id: Optional[str] = None

class PaymentConfirmDTO(BaseModel):
    actor_id: uuid.UUID

@router.post("", response_model=Payment)
def create_payment_endpoint(
    data: PaymentCreateDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return payment_service.create_payment(
        session,
        context,
        sale_id=data.sale_id,
        method=data.method,
        amount=Decimal(str(data.amount)),
        cash_session_id=data.cash_session_id,
        tendered_amount=Decimal(str(data.tendered_amount)) if data.tendered_amount else None,
        provider=data.provider,
        provider_event_id=data.provider_event_id
    )

@router.post("/{payment_id}/confirm")
def confirm_payment_endpoint(
    payment_id: uuid.UUID,
    data: PaymentConfirmDTO,
    context: TenantContext = Depends(get_tenant_context),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    session: Session = Depends(get_session)
):
    # Check Idempotency if key header is provided
    if x_idempotency_key:
        is_cached, status_code, body = reliability_service.check_idempotency(
            session=session,
            tenant_id=context.tenant_id,
            actor_id=data.actor_id,
            operation=f"POST /api/v1/payments/{payment_id}/confirm",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict()
        )
        if is_cached and status_code and body:
            return body

    payment, sale, already_confirmed = payment_service.confirm_payment(
        session=session,
        context=context,
        payment_id=payment_id,
        actor_id=data.actor_id,
        correlation_id=x_correlation_id
    )

    response_data = {
        "payment": payment.dict(),
        "sale_status": sale.status.value,
        "already_confirmed": already_confirmed
    }

    # Save Idempotency record if key header was provided
    if x_idempotency_key:
        reliability_service.save_idempotency_record(
            session=session,
            tenant_id=context.tenant_id,
            actor_id=data.actor_id,
            operation=f"POST /api/v1/payments/{payment_id}/confirm",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict(),
            response_status=200,
            response_body=response_data
        )

    session.commit()
    return response_data

@router.get("", response_model=List[Payment])
def list_payments_endpoint(
    sale_id: Optional[uuid.UUID] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return payment_service.list_payments(session, context, sale_id=sale_id)


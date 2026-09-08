import uuid
from decimal import Decimal
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlmodel import Session
from app.core.database import get_session
from app.core.context import TenantContext, get_tenant_context, resolve_actor
from app.models.payment import Payment, PaymentMethodEnum
from app.models.reconciliation import PaymentRefund
from app.services import payment_service, reliability_service

router = APIRouter()

class PaymentCreateDTO(BaseModel):
    sale_id: uuid.UUID
    method: PaymentMethodEnum
    amount: float
    cash_session_id: Optional[uuid.UUID] = None
    tendered_amount: Optional[float] = None
    provider: str = "MANUAL_OPERATOR"
    provider_event_id: Optional[str] = None

class PaymentConfirmDTO(BaseModel):
    actor_id: uuid.UUID

class PaymentRefundDTO(BaseModel):
    actor_id: uuid.UUID
    amount: Decimal
    reason: str
    cash_session_id: Optional[uuid.UUID] = None
    provider_reference: Optional[str] = None

@router.post("", response_model=Payment)
def create_payment_endpoint(
    data: PaymentCreateDTO,
    context: TenantContext = Depends(get_tenant_context),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_session)
):
    """Cria o pagamento — e a mesma intenção, reenviada, não cria um segundo.

    Confirmar já era idempotente por estado: um pagamento CONFIRMED reconfirmado
    devolve ele mesmo. **Criar não era.** Se a criação passa e a confirmação
    estoura no meio — o timeout depois do envio —, a venda continua
    AWAITING_PAYMENT, e repetir a operação criava um segundo pagamento e o
    confirmava, enquanto o primeiro ficava pendente. Se o provedor capturou o
    primeiro, são duas cobranças. Em pagamento dividido é pior: a venda nunca
    chega a PAID entre as parcelas, então nada barra a repetição.

    A chave é da intenção do operador, não da tentativa: reenviar depois de um
    erro de rede devolve o mesmo pagamento em vez de abrir outro.
    """
    actor_id = resolve_actor(context)
    if x_idempotency_key:
        is_cached, status_code, body = reliability_service.check_idempotency(
            session=session,
            tenant_id=context.tenant_id,
            actor_id=actor_id,
            operation="POST /api/v1/payments",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict(),
        )
        if is_cached and status_code and body:
            return body

    payment = payment_service.create_payment(
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

    # O corpo é serializado ANTES do commit e devolvido como corpo, não como
    # instância: depois do commit o SQLModel expira os atributos, e o que a
    # rota devolvia era um objeto vazio — `payment 200 {}`. O caminho do cache
    # já devolve dicionário; os dois passam a devolver a mesma coisa.
    corpo = jsonable_encoder(payment)
    if x_idempotency_key:
        reliability_service.save_idempotency_record(
            session=session,
            tenant_id=context.tenant_id,
            actor_id=actor_id,
            operation="POST /api/v1/payments",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict(),
            response_status=200,
            response_body=corpo,
        )
        session.commit()
    return corpo

@router.post("/{payment_id}/confirm")
def confirm_payment_endpoint(
    payment_id: uuid.UUID,
    data: PaymentConfirmDTO,
    context: TenantContext = Depends(get_tenant_context),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    session: Session = Depends(get_session)
):
    actor_id = resolve_actor(context, data.actor_id)
    # Check Idempotency if key header is provided
    if x_idempotency_key:
        is_cached, status_code, body = reliability_service.check_idempotency(
            session=session,
            tenant_id=context.tenant_id,
            actor_id=actor_id,
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
        actor_id=actor_id,
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
            actor_id=actor_id,
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

@router.post("/{payment_id}/refund", response_model=PaymentRefund)
def refund_payment_endpoint(
    payment_id: uuid.UUID, data: PaymentRefundDTO,
    context: TenantContext = Depends(get_tenant_context),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    session: Session = Depends(get_session),
):
    actor_id = resolve_actor(context, data.actor_id)
    return payment_service.refund_payment(
        session, context, payment_id, actor_id=actor_id, amount=data.amount,
        reason=data.reason, idempotency_key=idempotency_key,
        cash_session_id=data.cash_session_id, provider_reference=data.provider_reference,
    )

import csv
import io
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.access import require_platform_permission
from app.core.config import settings
from app.core.database import get_session
from app.core.security import AuthPrincipal, get_current_principal
from app.core.tenancy import set_platform_db_context
from app.models.identity import Tenant, User
from app.models.owner_finance import (
    SaasInvoice, SaasInvoiceLine, SaasInvoiceStatusEnum,
    SaasCollectionEvent, SaasCollectionEventTypeEnum, SaasPayment,
    SaasPaymentAllocation, SaasPaymentStatusEnum, SaasRefund,
)
from app.services import owner_finance_service


router = APIRouter(dependencies=[Depends(get_current_principal)])
provider_router = APIRouter()
FINANCE_READ = "control.finance.read"
FINANCE_COLLECT = "control.finance.collect"
FINANCE_RECONCILE = "control.finance.reconcile"
FINANCE_REFUND = "control.finance.refund"
FINANCE_EXPORT = "control.finance.export"


class InvoiceGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    competence: date
    tenant_id: Optional[uuid.UUID] = None


class InvoiceCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = PydanticField(ge=1)
    reason: str = PydanticField(min_length=4, max_length=500)


class InvoiceSkip(BaseModel):
    tenant_id: str
    code: str
    detail: str


class InvoiceGenerateResult(BaseModel):
    generated: list[SaasInvoice]
    existing: list[SaasInvoice]
    skipped: list[InvoiceSkip]


class InvoiceListItem(BaseModel):
    invoice: SaasInvoice
    tenant_name: str


class InvoiceListResult(BaseModel):
    items: list[InvoiceListItem]
    total: int
    page: int
    size: int


class InvoiceDetail(BaseModel):
    invoice: SaasInvoice
    tenant_name: str
    lines: list[SaasInvoiceLine]


class PaymentAllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_id: uuid.UUID
    amount: Decimal = PydanticField(gt=0)
    expected_invoice_version: int = PydanticField(ge=1)


class ManualPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal = PydanticField(gt=0)
    currency: str = PydanticField(default="BRL", pattern=r"^BRL$")
    received_at: datetime
    evidence_reference: str = PydanticField(min_length=4, max_length=240)
    payment_method_summary: str = PydanticField(default="TRANSFERENCIA_CONFIRMADA", min_length=3, max_length=80)
    reason: str = PydanticField(min_length=4, max_length=500)
    allocations: list[PaymentAllocationRequest] = PydanticField(min_length=1, max_length=50)


class RefundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_id: uuid.UUID
    amount: Decimal = PydanticField(gt=0)
    expected_invoice_version: int = PydanticField(ge=1)
    reason: str = PydanticField(min_length=4, max_length=500)
    evidence_reference: str = PydanticField(min_length=4, max_length=240)


class ReconcilePaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_id: uuid.UUID
    confirmed_status: SaasPaymentStatusEnum
    expected_invoice_version: int = PydanticField(ge=1)
    evidence_reference: str = PydanticField(min_length=4, max_length=240)
    failure_code: Optional[str] = PydanticField(default=None, max_length=80)


class ProviderWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_event_id: str = PydanticField(min_length=4, max_length=180)
    provider_payment_reference: str = PydanticField(min_length=4, max_length=180)
    invoice_id: uuid.UUID
    status: SaasPaymentStatusEnum
    amount: Decimal = PydanticField(gt=0)
    currency: str = PydanticField(default="BRL", pattern=r"^BRL$")
    occurred_at: datetime
    payment_method_summary: Optional[str] = PydanticField(default=None, max_length=80)
    failure_code: Optional[str] = PydanticField(default=None, max_length=80)


class PaymentListItem(BaseModel):
    payment: SaasPayment
    tenant_name: str
    allocated_amount: Decimal
    refunded_amount: Decimal
    invoice_ids: list[uuid.UUID]


class PaymentListResult(BaseModel):
    items: list[PaymentListItem]
    total: int
    page: int
    size: int


class PaymentDetail(BaseModel):
    payment: SaasPayment
    tenant_name: str
    allocations: list[SaasPaymentAllocation]
    refunds: list[SaasRefund]


class MarkOverdueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: date


class CollectionEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_id: uuid.UUID
    event_type: SaasCollectionEventTypeEnum
    channel: str = PydanticField(min_length=2, max_length=40)
    outcome: str = PydanticField(min_length=2, max_length=80)
    recipient_masked: Optional[str] = PydanticField(default=None, max_length=160)
    detail: str = PydanticField(min_length=4, max_length=1000)
    evidence_reference: Optional[str] = PydanticField(default=None, max_length=240)


def _invoice_query(
    *,
    status: Optional[SaasInvoiceStatusEnum],
    tenant_id: Optional[uuid.UUID],
    period_from: Optional[date],
    period_to: Optional[date],
):
    query = select(SaasInvoice)
    if status is not None:
        query = query.where(SaasInvoice.status == status)
    if tenant_id is not None:
        query = query.where(SaasInvoice.tenant_id == tenant_id)
    if period_from is not None:
        query = query.where(SaasInvoice.period_start >= period_from)
    if period_to is not None:
        query = query.where(SaasInvoice.period_start <= period_to)
    return query


@router.post("/invoices/generate", response_model=InvoiceGenerateResult)
def generate_invoices(
    data: InvoiceGenerateRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_permission(session, principal, FINANCE_COLLECT, require_aal2=True)
    assert actor is not None
    generated, existing, skipped = owner_finance_service.generate_invoices(
        session,
        competence=data.competence,
        tenant_id=data.tenant_id,
        actor_id=actor.id,
        idempotency_key=idempotency_key,
    )
    return InvoiceGenerateResult(generated=generated, existing=existing, skipped=skipped)


@router.get("/invoices", response_model=InvoiceListResult)
def list_invoices(
    status: Optional[SaasInvoiceStatusEnum] = None,
    tenant_id: Optional[uuid.UUID] = None,
    period_from: Optional[date] = None,
    period_to: Optional[date] = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_permission(session, principal, FINANCE_READ)
    query = _invoice_query(
        status=status, tenant_id=tenant_id, period_from=period_from, period_to=period_to
    )
    count_query = select(func.count()).select_from(query.subquery())
    total = int(session.exec(count_query).one())
    invoices = list(session.exec(
        query.order_by(SaasInvoice.created_at.desc()).offset((page - 1) * size).limit(size)
    ).all())
    tenant_ids = {invoice.tenant_id for invoice in invoices}
    tenants = {
        tenant.id: tenant.name for tenant in session.exec(
            select(Tenant).where(Tenant.id.in_(tenant_ids))
        ).all()
    } if tenant_ids else {}
    return InvoiceListResult(
        items=[InvoiceListItem(invoice=invoice, tenant_name=tenants.get(invoice.tenant_id, "Tenant removido")) for invoice in invoices],
        total=total,
        page=page,
        size=size,
    )


@router.get("/invoices/export")
def export_invoices(
    status: Optional[SaasInvoiceStatusEnum] = None,
    tenant_id: Optional[uuid.UUID] = None,
    period_from: Optional[date] = None,
    period_to: Optional[date] = None,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_permission(session, principal, FINANCE_EXPORT)
    invoices = list(session.exec(
        _invoice_query(
            status=status, tenant_id=tenant_id,
            period_from=period_from, period_to=period_to,
        ).order_by(SaasInvoice.period_start, SaasInvoice.public_number)
    ).all())
    tenant_ids = {invoice.tenant_id for invoice in invoices}
    tenants = {
        tenant.id: tenant.name for tenant in session.exec(
            select(Tenant).where(Tenant.id.in_(tenant_ids))
        ).all()
    } if tenant_ids else {}
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "numero", "cliente", "competencia_inicio", "competencia_fim",
        "vencimento", "situacao", "moeda", "total", "saldo",
    ])
    for invoice in invoices:
        writer.writerow([
            invoice.public_number,
            tenants.get(invoice.tenant_id, "Tenant removido"),
            invoice.period_start.isoformat(),
            invoice.period_end.isoformat(),
            invoice.due_date.isoformat(),
            invoice.status.value,
            invoice.currency,
            str(Decimal(invoice.total_amount).quantize(Decimal("0.01"))),
            str(Decimal(invoice.balance_amount).quantize(Decimal("0.01"))),
        ])
    content = "\ufeff" + output.getvalue()
    filename = f"faturas-saas-{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetail)
def get_invoice(
    invoice_id: uuid.UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_permission(session, principal, FINANCE_READ)
    invoice = session.get(SaasInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Fatura SaaS não encontrada.")
    tenant = session.get(Tenant, invoice.tenant_id)
    lines = list(session.exec(select(SaasInvoiceLine).where(
        SaasInvoiceLine.invoice_id == invoice.id
    ).order_by(SaasInvoiceLine.created_at, SaasInvoiceLine.id)).all())
    return InvoiceDetail(
        invoice=invoice,
        tenant_name=tenant.name if tenant else "Tenant removido",
        lines=lines,
    )


@router.post("/invoices/{invoice_id}/issue", response_model=SaasInvoice)
def issue_invoice(
    invoice_id: uuid.UUID,
    data: InvoiceCommandRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_permission(session, principal, FINANCE_COLLECT, require_aal2=True)
    assert actor is not None
    return owner_finance_service.issue_invoice(
        session,
        invoice_id=invoice_id,
        expected_version=data.expected_version,
        reason=data.reason,
        actor_id=actor.id,
        idempotency_key=idempotency_key,
    )


@router.post("/invoices/{invoice_id}/void", response_model=SaasInvoice)
def void_invoice(
    invoice_id: uuid.UUID,
    data: InvoiceCommandRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_permission(session, principal, FINANCE_COLLECT, require_aal2=True)
    assert actor is not None
    return owner_finance_service.void_invoice(
        session,
        invoice_id=invoice_id,
        expected_version=data.expected_version,
        reason=data.reason,
        actor_id=actor.id,
        idempotency_key=idempotency_key,
    )


@router.post("/payments/manual", response_model=SaasPayment)
def record_manual_payment(
    data: ManualPaymentRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_permission(session, principal, FINANCE_COLLECT, require_aal2=True)
    assert actor is not None
    return owner_finance_service.record_succeeded_payment(
        session,
        allocations=[
            (item.invoice_id, item.amount, item.expected_invoice_version)
            for item in data.allocations
        ],
        amount=data.amount,
        currency=data.currency,
        provider="MANUAL",
        provider_payment_reference=None,
        external_event_id=None,
        payment_method_summary=data.payment_method_summary,
        evidence_reference=data.evidence_reference,
        reason=data.reason,
        received_at=data.received_at,
        actor_id=actor.id,
        idempotency_key=idempotency_key,
    )


@router.get("/payments", response_model=PaymentListResult)
def list_payments(
    status: Optional[SaasPaymentStatusEnum] = None,
    tenant_id: Optional[uuid.UUID] = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_permission(session, principal, FINANCE_READ)
    query = select(SaasPayment)
    if status is not None:
        query = query.where(SaasPayment.status == status)
    if tenant_id is not None:
        query = query.where(SaasPayment.tenant_id == tenant_id)
    total = int(session.exec(select(func.count()).select_from(query.subquery())).one())
    payments = list(session.exec(
        query.order_by(SaasPayment.received_at.desc()).offset((page - 1) * size).limit(size)
    ).all())
    tenant_ids = {payment.tenant_id for payment in payments}
    tenants = {item.id: item.name for item in session.exec(
        select(Tenant).where(Tenant.id.in_(tenant_ids))
    ).all()} if tenant_ids else {}
    payment_ids = {payment.id for payment in payments}
    allocations = list(session.exec(select(SaasPaymentAllocation).where(
        SaasPaymentAllocation.payment_id.in_(payment_ids)
    )).all()) if payment_ids else []
    refunds = list(session.exec(select(SaasRefund).where(
        SaasRefund.payment_id.in_(payment_ids)
    )).all()) if payment_ids else []
    return PaymentListResult(
        items=[PaymentListItem(
            payment=payment,
            tenant_name=tenants.get(payment.tenant_id, "Tenant removido"),
            allocated_amount=sum((Decimal(item.amount) for item in allocations if item.payment_id == payment.id), Decimal("0.00")),
            refunded_amount=sum((Decimal(item.amount) for item in refunds if item.payment_id == payment.id), Decimal("0.00")),
            invoice_ids=[item.invoice_id for item in allocations if item.payment_id == payment.id],
        ) for payment in payments],
        total=total, page=page, size=size,
    )


@router.get("/payments/{payment_id}", response_model=PaymentDetail)
def get_payment(
    payment_id: uuid.UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_permission(session, principal, FINANCE_READ)
    payment = session.get(SaasPayment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Pagamento SaaS não encontrado.")
    tenant = session.get(Tenant, payment.tenant_id)
    return PaymentDetail(
        payment=payment,
        tenant_name=tenant.name if tenant else "Tenant removido",
        allocations=list(session.exec(select(SaasPaymentAllocation).where(
            SaasPaymentAllocation.payment_id == payment.id
        ).order_by(SaasPaymentAllocation.allocated_at)).all()),
        refunds=list(session.exec(select(SaasRefund).where(
            SaasRefund.payment_id == payment.id
        ).order_by(SaasRefund.refunded_at)).all()),
    )


@router.post("/payments/{payment_id}/reconcile", response_model=SaasPayment)
def reconcile_payment(
    payment_id: uuid.UUID,
    data: ReconcilePaymentRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_permission(session, principal, FINANCE_RECONCILE, require_aal2=True)
    assert actor is not None
    return owner_finance_service.reconcile_unknown_payment(
        session, payment_id=payment_id, invoice_id=data.invoice_id,
        confirmed_status=data.confirmed_status,
        expected_invoice_version=data.expected_invoice_version,
        evidence_reference=data.evidence_reference, failure_code=data.failure_code,
        actor_id=actor.id, idempotency_key=idempotency_key,
    )


@router.post("/payments/{payment_id}/refunds", response_model=SaasRefund)
def refund_payment(
    payment_id: uuid.UUID,
    data: RefundRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_permission(session, principal, FINANCE_REFUND, require_aal2=True)
    assert actor is not None
    return owner_finance_service.refund_payment(
        session, payment_id=payment_id, invoice_id=data.invoice_id,
        amount=data.amount, expected_invoice_version=data.expected_invoice_version,
        reason=data.reason, evidence_reference=data.evidence_reference,
        actor_id=actor.id, idempotency_key=idempotency_key,
    )


@router.post("/collections/mark-overdue", response_model=list[SaasInvoice])
def mark_overdue(
    data: MarkOverdueRequest,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_permission(session, principal, FINANCE_RECONCILE, require_aal2=True)
    assert actor is not None
    return owner_finance_service.mark_overdue_invoices(
        session, as_of=data.as_of, actor_id=actor.id
    )


@router.post("/collections/events", response_model=SaasCollectionEvent)
def create_collection_event(
    data: CollectionEventRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_permission(session, principal, FINANCE_RECONCILE, require_aal2=True)
    assert actor is not None
    return owner_finance_service.record_collection_event(
        session, invoice_id=data.invoice_id, event_type=data.event_type,
        channel=data.channel, outcome=data.outcome,
        recipient_masked=data.recipient_masked, detail=data.detail,
        evidence_reference=data.evidence_reference, actor_id=actor.id,
        idempotency_key=idempotency_key,
    )


@router.get("/collections/events", response_model=list[SaasCollectionEvent])
def list_collection_events(
    invoice_id: Optional[uuid.UUID] = None,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_permission(session, principal, FINANCE_READ)
    query = select(SaasCollectionEvent)
    if invoice_id is not None:
        query = query.where(SaasCollectionEvent.invoice_id == invoice_id)
    return list(session.exec(
        query.order_by(SaasCollectionEvent.occurred_at.desc()).limit(500)
    ).all())


@provider_router.post("/webhooks/{provider}", response_model=SaasPayment)
async def receive_provider_webhook(
    provider: str,
    request: Request,
    signature: str = Header(alias="X-Dashem-Signature", min_length=16, max_length=256),
    session: Session = Depends(get_session),
):
    if not settings.SAAS_PAYMENT_WEBHOOK_SECRET or not settings.SAAS_PAYMENT_WEBHOOK_ACTOR_ID:
        raise HTTPException(status_code=503, detail="Provider de recebimentos SaaS não configurado.")
    raw_body = await request.body()
    if not owner_finance_service.verify_webhook_signature(
        raw_body, signature, settings.SAAS_PAYMENT_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=401, detail="Assinatura do webhook inválida.")
    try:
        data = ProviderWebhookRequest.model_validate_json(raw_body)
        actor_id = uuid.UUID(settings.SAAS_PAYMENT_WEBHOOK_ACTOR_ID)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Evento de provider inválido.") from exc
    if session.get(User, actor_id) is None:
        raise HTTPException(status_code=503, detail="Identidade técnica do provider não configurada.")
    set_platform_db_context(session, actor_id)
    return owner_finance_service.record_provider_observation(
        session, invoice_id=data.invoice_id, status=data.status,
        amount=data.amount, currency=data.currency, provider=provider,
        provider_payment_reference=data.provider_payment_reference,
        external_event_id=data.external_event_id,
        payment_method_summary=data.payment_method_summary,
        failure_code=data.failure_code, occurred_at=data.occurred_at,
        actor_id=actor_id,
        idempotency_key=f"provider:{provider.lower()}:{data.external_event_id}",
    )

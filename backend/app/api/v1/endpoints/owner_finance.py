import csv
import io
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.access import require_platform_permission
from app.core.database import get_session
from app.core.security import AuthPrincipal, get_current_principal
from app.models.identity import Tenant
from app.models.owner_finance import (
    SaasInvoice, SaasInvoiceLine, SaasInvoiceStatusEnum,
)
from app.services import owner_finance_service


router = APIRouter(dependencies=[Depends(get_current_principal)])
FINANCE_READ = "control.finance.read"
FINANCE_COLLECT = "control.finance.collect"
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

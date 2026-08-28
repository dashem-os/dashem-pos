import hashlib
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.identity import (
    ServicePlan, SubscriptionStatusEnum, Tenant, TenantSubscription,
)
from app.models.owner_finance import (
    SaasBillingAccount, SaasInvoice, SaasInvoiceLine,
    SaasInvoiceLineTypeEnum, SaasInvoiceStatusEnum,
)
from app.models.platform import TenantContract
from app.models.reliability import AuditEvent
from app.services import reliability_service


def invoice_period(competence: date) -> tuple[date, date]:
    start = competence.replace(day=1)
    next_month = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
    return start, next_month - timedelta(days=1)


def billing_account_ready(account: Optional[SaasBillingAccount]) -> bool:
    return bool(
        account and account.legal_name and account.tax_id
        and account.contact_name and account.contact_email
    )


def _audit_invoice(
    session: Session,
    *,
    invoice: SaasInvoice,
    actor_id: uuid.UUID,
    action: str,
    payload: dict,
) -> None:
    audit, _ = reliability_service.write_audit_and_outbox(
        session,
        tenant_id=invoice.tenant_id,
        store_id=None,
        actor_id=actor_id,
        action=action,
        target=f"saas_invoice:{invoice.id}",
        audit_payload=payload,
        aggregate_type="saas_invoice",
        aggregate_id=str(invoice.id),
        event_type=action,
        outbox_payload=payload,
    )
    audit.platform_scope = True
    session.add(audit)


def generate_invoices(
    session: Session,
    *,
    competence: date,
    actor_id: uuid.UUID,
    idempotency_key: str,
    tenant_id: Optional[uuid.UUID] = None,
) -> tuple[list[SaasInvoice], list[SaasInvoice], list[dict[str, str]]]:
    period_start, period_end = invoice_period(competence)
    query = select(TenantSubscription).where(
        TenantSubscription.status == SubscriptionStatusEnum.ACTIVE
    ).order_by(TenantSubscription.tenant_id)
    if tenant_id is not None:
        query = query.where(TenantSubscription.tenant_id == tenant_id)
    subscriptions = list(session.exec(query).all())
    if tenant_id is not None and not subscriptions:
        return [], [], [{
            "tenant_id": str(tenant_id),
            "code": "SUBSCRIPTION_NOT_ACTIVE_OR_MISSING",
            "detail": "A assinatura não existe ou não está ativa.",
        }]

    generated: list[SaasInvoice] = []
    existing: list[SaasInvoice] = []
    skipped: list[dict[str, str]] = []
    for subscription in subscriptions:
        duplicate = session.exec(select(SaasInvoice).where(
            SaasInvoice.subscription_id == subscription.tenant_id,
            SaasInvoice.period_start == period_start,
            SaasInvoice.generation_revision == 1,
        )).first()
        if duplicate is not None:
            existing.append(duplicate)
            continue

        tenant = session.get(Tenant, subscription.tenant_id)
        account = session.exec(select(SaasBillingAccount).where(
            SaasBillingAccount.tenant_id == subscription.tenant_id
        )).first()
        contract = session.exec(select(TenantContract).where(
            TenantContract.tenant_id == subscription.tenant_id,
            TenantContract.status == "ACTIVE",
        ).order_by(TenantContract.version.desc())).first()
        plan = session.get(ServicePlan, subscription.plan_id) if subscription.plan_id else None
        missing: list[str] = []
        if tenant is None:
            missing.append("tenant")
        if not billing_account_ready(account):
            missing.append("billing_account")
        if contract is None:
            missing.append("contract")
        if plan is None:
            missing.append("plan")
        if missing:
            skipped.append({
                "tenant_id": str(subscription.tenant_id),
                "code": "INVOICE_SOURCE_INCOMPLETE",
                "detail": "Fontes obrigatórias ausentes: " + ", ".join(missing) + ".",
            })
            continue
        assert tenant is not None and account is not None and contract is not None and plan is not None

        amount = Decimal(subscription.monthly_amount).quantize(Decimal("0.01"))
        invoice_id = uuid.uuid4()
        generation_key = hashlib.sha256(
            f"{idempotency_key}:{subscription.tenant_id}:{period_start.isoformat()}:1".encode("utf-8")
        ).hexdigest()
        public_number = f"DSH-{period_start:%Y%m}-{invoice_id.hex[:12].upper()}"
        description = f"Assinatura {plan.name} — competência {period_start:%m/%Y}"
        due_date = date(period_start.year, period_start.month, min(max(subscription.billing_day, 1), 28))
        invoice = SaasInvoice(
            id=invoice_id,
            public_number=public_number,
            tenant_id=subscription.tenant_id,
            billing_account_id=account.id,
            subscription_id=subscription.tenant_id,
            contract_id=contract.id,
            plan_id=plan.id,
            period_start=period_start,
            period_end=period_end,
            due_date=due_date,
            currency=account.currency,
            subtotal=amount,
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            total_amount=amount,
            balance_amount=amount,
            status=SaasInvoiceStatusEnum.DRAFT,
            generation_key=generation_key,
            generation_revision=1,
            contract_version=contract.version,
            plan_code_snapshot=plan.code,
            plan_name_snapshot=plan.name,
            description_snapshot=description,
            billing_legal_name_snapshot=account.legal_name,
            billing_tax_id_snapshot=account.tax_id,
            billing_contact_email_snapshot=account.contact_email,
            created_by=actor_id,
        )
        line = SaasInvoiceLine(
            invoice_id=invoice.id,
            line_type=SaasInvoiceLineTypeEnum.PLAN,
            description=description,
            quantity=Decimal("1.0000"),
            unit_amount=amount,
            total_amount=amount,
            contract_version=contract.version,
        )
        try:
            with session.begin_nested():
                session.add(invoice)
                session.flush()
                session.add(line)
                session.flush()
        except IntegrityError:
            duplicate = session.exec(select(SaasInvoice).where(
                SaasInvoice.subscription_id == subscription.tenant_id,
                SaasInvoice.period_start == period_start,
                SaasInvoice.generation_revision == 1,
            )).first()
            if duplicate is None:
                raise
            existing.append(duplicate)
            continue

        _audit_invoice(
            session,
            invoice=invoice,
            actor_id=actor_id,
            action="saas.invoice.generated",
            payload={
                "invoice_id": str(invoice.id),
                "public_number": invoice.public_number,
                "tenant_id": str(invoice.tenant_id),
                "period_start": invoice.period_start.isoformat(),
                "period_end": invoice.period_end.isoformat(),
                "contract_version": invoice.contract_version,
                "total_amount": str(invoice.total_amount),
                "currency": invoice.currency,
            },
        )
        generated.append(invoice)
    session.commit()
    for invoice in generated:
        session.refresh(invoice)
    return generated, existing, skipped


def issue_invoice(
    session: Session,
    *,
    invoice_id: uuid.UUID,
    expected_version: int,
    reason: str,
    actor_id: uuid.UUID,
    idempotency_key: str,
) -> SaasInvoice:
    invoice = session.get(SaasInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Fatura SaaS não encontrada.")
    request_payload = {
        "invoice_id": str(invoice_id),
        "expected_version": expected_version,
        "reason": reason.strip(),
    }
    request_hash = reliability_service.compute_request_hash(request_payload)
    if invoice.issue_idempotency_key == idempotency_key:
        if invoice.issue_request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Chave de idempotência reutilizada com outro conteúdo.")
        return invoice
    if invoice.status != SaasInvoiceStatusEnum.DRAFT:
        raise HTTPException(status_code=409, detail="Somente uma fatura em rascunho pode ser emitida.")
    now = datetime.utcnow()
    try:
        result = session.exec(
            sa_update(SaasInvoice).where(
                SaasInvoice.id == invoice_id,
                SaasInvoice.status == SaasInvoiceStatusEnum.DRAFT,
                SaasInvoice.version == expected_version,
            ).values(
                status=SaasInvoiceStatusEnum.OPEN.value,
                issued_at=now,
                issued_by=actor_id,
                issue_idempotency_key=idempotency_key,
                issue_request_hash=request_hash,
                updated_at=now,
                version=expected_version + 1,
            )
        )
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Chave de idempotência já utilizada em outra emissão.") from exc
    if result.rowcount != 1:
        session.rollback()
        current = session.get(SaasInvoice, invoice_id)
        if current and current.issue_idempotency_key == idempotency_key:
            if current.issue_request_hash != request_hash:
                raise HTTPException(status_code=409, detail="Chave de idempotência reutilizada com outro conteúdo.")
            return current
        raise HTTPException(
            status_code=409,
            detail="A fatura foi alterada por outra sessão. Recarregue antes de emitir.",
        )
    session.expire(invoice)
    session.refresh(invoice)
    _audit_invoice(
        session,
        invoice=invoice,
        actor_id=actor_id,
        action="saas.invoice.issued",
        payload={
            "invoice_id": str(invoice.id),
            "public_number": invoice.public_number,
            "previous_status": SaasInvoiceStatusEnum.DRAFT.value,
            "current_status": invoice.status.value,
            "total_amount": str(invoice.total_amount),
            "reason": reason.strip(),
        },
    )
    session.commit()
    session.refresh(invoice)
    return invoice


def void_invoice(
    session: Session,
    *,
    invoice_id: uuid.UUID,
    expected_version: int,
    reason: str,
    actor_id: uuid.UUID,
    idempotency_key: str,
) -> SaasInvoice:
    invoice = session.get(SaasInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Fatura SaaS não encontrada.")
    request_payload = {
        "invoice_id": str(invoice_id),
        "expected_version": expected_version,
        "reason": reason.strip(),
    }
    request_hash = reliability_service.compute_request_hash(request_payload)
    if invoice.void_idempotency_key == idempotency_key:
        if invoice.void_request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Chave de idempotência reutilizada com outro conteúdo.")
        return invoice
    if invoice.status != SaasInvoiceStatusEnum.OPEN:
        raise HTTPException(status_code=409, detail="Somente uma fatura aberta pode ser anulada.")
    now = datetime.utcnow()
    try:
        result = session.exec(
            sa_update(SaasInvoice).where(
                SaasInvoice.id == invoice_id,
                SaasInvoice.status == SaasInvoiceStatusEnum.OPEN,
                SaasInvoice.version == expected_version,
            ).values(
                status=SaasInvoiceStatusEnum.VOID.value,
                balance_amount=Decimal("0.00"),
                voided_at=now,
                voided_by=actor_id,
                void_reason=reason.strip(),
                void_idempotency_key=idempotency_key,
                void_request_hash=request_hash,
                updated_at=now,
                version=expected_version + 1,
            )
        )
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Chave de idempotência já utilizada em outra anulação.") from exc
    if result.rowcount != 1:
        session.rollback()
        current = session.get(SaasInvoice, invoice_id)
        if current and current.void_idempotency_key == idempotency_key:
            if current.void_request_hash != request_hash:
                raise HTTPException(status_code=409, detail="Chave de idempotência reutilizada com outro conteúdo.")
            return current
        raise HTTPException(
            status_code=409,
            detail="A fatura foi alterada por outra sessão. Recarregue antes de anular.",
        )
    session.expire(invoice)
    session.refresh(invoice)
    _audit_invoice(
        session,
        invoice=invoice,
        actor_id=actor_id,
        action="saas.invoice.voided",
        payload={
            "invoice_id": str(invoice.id),
            "public_number": invoice.public_number,
            "previous_status": SaasInvoiceStatusEnum.OPEN.value,
            "current_status": invoice.status.value,
            "total_amount": str(invoice.total_amount),
            "reason": reason.strip(),
        },
    )
    session.commit()
    session.refresh(invoice)
    return invoice

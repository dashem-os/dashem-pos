import hashlib
import hmac
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
    SaasCollectionEvent, SaasCollectionEventTypeEnum, SaasPayment,
    SaasPaymentAllocation, SaasPaymentStatusEnum, SaasRefund,
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


MONEY = Decimal("0.01")


def verify_webhook_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    supplied = signature.removeprefix("sha256=").strip().lower()
    return hmac.compare_digest(expected, supplied)


def _invoice_status_for_balance(invoice: SaasInvoice, *, as_of: date) -> SaasInvoiceStatusEnum:
    if Decimal(invoice.balance_amount) == Decimal("0.00"):
        return SaasInvoiceStatusEnum.PAID
    if invoice.due_date < as_of:
        return SaasInvoiceStatusEnum.OVERDUE
    if Decimal(invoice.balance_amount) < Decimal(invoice.total_amount):
        return SaasInvoiceStatusEnum.PARTIALLY_PAID
    return SaasInvoiceStatusEnum.OPEN


def _audit_payment(
    session: Session,
    *,
    payment: SaasPayment,
    actor_id: uuid.UUID,
    action: str,
    payload: dict,
) -> None:
    audit, _ = reliability_service.write_audit_and_outbox(
        session,
        tenant_id=payment.tenant_id,
        store_id=None,
        actor_id=actor_id,
        action=action,
        target=f"saas_payment:{payment.id}",
        audit_payload=payload,
        aggregate_type="saas_payment",
        aggregate_id=str(payment.id),
        event_type=action,
        outbox_payload=payload,
    )
    audit.platform_scope = True
    session.add(audit)


def record_succeeded_payment(
    session: Session,
    *,
    allocations: list[tuple[uuid.UUID, Decimal, int]],
    amount: Decimal,
    currency: str,
    provider: str,
    provider_payment_reference: Optional[str],
    external_event_id: Optional[str],
    payment_method_summary: Optional[str],
    evidence_reference: str,
    reason: str,
    received_at: datetime,
    actor_id: uuid.UUID,
    idempotency_key: str,
) -> SaasPayment:
    normalized_amount = Decimal(amount).quantize(MONEY)
    normalized_allocations = [
        (invoice_id, Decimal(value).quantize(MONEY), version)
        for invoice_id, value, version in allocations
    ]
    request_payload = {
        "allocations": [
            {"invoice_id": str(invoice_id), "amount": str(value), "expected_version": version}
            for invoice_id, value, version in normalized_allocations
        ],
        "amount": str(normalized_amount),
        "currency": currency,
        "provider": provider,
        "provider_payment_reference": provider_payment_reference,
        "external_event_id": external_event_id,
        "payment_method_summary": payment_method_summary,
        "evidence_reference": evidence_reference,
        "reason": reason.strip(),
        "received_at": received_at.isoformat(),
    }
    request_hash = reliability_service.compute_request_hash(request_payload)
    existing = session.exec(select(SaasPayment).where(
        SaasPayment.idempotency_key == idempotency_key
    )).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Chave de idempotência reutilizada com outro recebimento.")
        return existing
    if normalized_amount <= 0 or not normalized_allocations:
        raise HTTPException(status_code=422, detail="Recebimento e alocações precisam possuir valor positivo.")
    if len({invoice_id for invoice_id, _, _ in normalized_allocations}) != len(normalized_allocations):
        raise HTTPException(status_code=422, detail="Cada fatura pode aparecer uma única vez no recebimento.")
    if sum((value for _, value, _ in normalized_allocations), Decimal("0.00")) != normalized_amount:
        raise HTTPException(status_code=422, detail="A soma das alocações deve ser igual ao recebimento.")
    if currency != "BRL":
        raise HTTPException(status_code=422, detail="A Fase 3 aceita somente a moeda BRL configurada.")
    if len(evidence_reference.strip()) < 4 or len(reason.strip()) < 4:
        raise HTTPException(status_code=422, detail="Informe motivo e evidência verificável do recebimento.")

    invoice_ids = [invoice_id for invoice_id, _, _ in normalized_allocations]
    invoices = list(session.exec(
        select(SaasInvoice).where(SaasInvoice.id.in_(invoice_ids)).with_for_update()
    ).all())
    by_id = {invoice.id: invoice for invoice in invoices}
    if len(by_id) != len(set(invoice_ids)):
        raise HTTPException(status_code=404, detail="Uma ou mais faturas SaaS não foram encontradas.")
    tenants = {invoice.tenant_id for invoice in invoices}
    accounts = {invoice.billing_account_id for invoice in invoices}
    if len(tenants) != 1 or len(accounts) != 1:
        raise HTTPException(status_code=422, detail="Um recebimento não pode misturar clientes ou contas de cobrança.")
    for invoice_id, allocated, expected_version in normalized_allocations:
        invoice = by_id[invoice_id]
        if invoice.version != expected_version:
            raise HTTPException(status_code=409, detail="Uma fatura foi alterada. Recarregue antes de alocar.")
        if invoice.status not in {
            SaasInvoiceStatusEnum.OPEN,
            SaasInvoiceStatusEnum.PARTIALLY_PAID,
            SaasInvoiceStatusEnum.OVERDUE,
        }:
            raise HTTPException(status_code=409, detail="A fatura não aceita recebimento em seu estado atual.")
        if invoice.currency != currency or allocated <= 0 or allocated > Decimal(invoice.balance_amount):
            raise HTTPException(status_code=422, detail="A alocação excede o saldo ou usa moeda incompatível.")

    now = datetime.utcnow()
    payment = SaasPayment(
        tenant_id=next(iter(tenants)),
        billing_account_id=next(iter(accounts)),
        provider=provider.strip().upper(),
        provider_payment_reference=provider_payment_reference,
        external_event_id=external_event_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status=SaasPaymentStatusEnum.SUCCEEDED,
        currency=currency,
        amount=normalized_amount,
        payment_method_summary=payment_method_summary,
        evidence_reference=evidence_reference.strip(),
        received_at=received_at,
        succeeded_at=received_at,
        created_by=actor_id,
    )
    try:
        session.add(payment)
        session.flush()
        for invoice_id, allocated, _ in normalized_allocations:
            invoice = by_id[invoice_id]
            invoice.balance_amount = (Decimal(invoice.balance_amount) - allocated).quantize(MONEY)
            invoice.status = _invoice_status_for_balance(invoice, as_of=received_at.date())
            invoice.paid_at = received_at if invoice.status == SaasInvoiceStatusEnum.PAID else None
            invoice.version += 1
            invoice.updated_at = now
            session.add(invoice)
            session.add(SaasPaymentAllocation(
                payment_id=payment.id,
                invoice_id=invoice.id,
                amount=allocated,
                idempotency_key=hashlib.sha256(
                    f"{idempotency_key}:{invoice.id}".encode("utf-8")
                ).hexdigest(),
                allocated_at=received_at,
            ))
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        existing = session.exec(select(SaasPayment).where(
            SaasPayment.idempotency_key == idempotency_key
        )).first()
        if existing is not None and existing.request_hash == request_hash:
            return existing
        raise HTTPException(status_code=409, detail="Referência de recebimento já utilizada.") from exc
    _audit_payment(
        session,
        payment=payment,
        actor_id=actor_id,
        action="saas.payment.succeeded",
        payload={
            "payment_id": str(payment.id),
            "tenant_id": str(payment.tenant_id),
            "provider": payment.provider,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "invoice_ids": [str(item) for item in invoice_ids],
            "source": "provider_webhook" if external_event_id else "manual_with_evidence",
            "reason": reason.strip(),
        },
    )
    session.commit()
    session.refresh(payment)
    return payment


def record_provider_observation(
    session: Session,
    *,
    invoice_id: uuid.UUID,
    status: SaasPaymentStatusEnum,
    amount: Decimal,
    currency: str,
    provider: str,
    provider_payment_reference: str,
    external_event_id: str,
    payment_method_summary: Optional[str],
    failure_code: Optional[str],
    occurred_at: datetime,
    actor_id: uuid.UUID,
    idempotency_key: str,
) -> SaasPayment:
    if status == SaasPaymentStatusEnum.SUCCEEDED:
        invoice = session.get(SaasInvoice, invoice_id)
        if invoice is None:
            raise HTTPException(status_code=404, detail="Fatura SaaS não encontrada.")
        return record_succeeded_payment(
            session,
            allocations=[(invoice.id, Decimal(amount), invoice.version)],
            amount=amount,
            currency=currency,
            provider=provider,
            provider_payment_reference=provider_payment_reference,
            external_event_id=external_event_id,
            payment_method_summary=payment_method_summary,
            evidence_reference=f"provider-event:{provider}:{external_event_id}",
            reason="Confirmação autenticada recebida do provider.",
            received_at=occurred_at,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    if status not in {SaasPaymentStatusEnum.UNKNOWN, SaasPaymentStatusEnum.FAILED}:
        raise HTTPException(status_code=422, detail="Status de provider não aceito nesta entrada.")
    invoice = session.get(SaasInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Fatura SaaS não encontrada.")
    normalized = Decimal(amount).quantize(MONEY)
    if normalized <= 0 or currency != "BRL":
        raise HTTPException(status_code=422, detail="Evento de provider exige valor positivo em BRL.")
    payload = {
        "invoice_id": str(invoice_id), "status": status.value,
        "amount": str(normalized), "currency": currency, "provider": provider,
        "provider_payment_reference": provider_payment_reference,
        "external_event_id": external_event_id, "failure_code": failure_code,
        "occurred_at": occurred_at.isoformat(),
    }
    request_hash = reliability_service.compute_request_hash(payload)
    existing = session.exec(select(SaasPayment).where(
        SaasPayment.idempotency_key == idempotency_key
    )).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Evento externo repetido com conteúdo divergente.")
        return existing
    payment = SaasPayment(
        tenant_id=invoice.tenant_id,
        billing_account_id=invoice.billing_account_id,
        provider=provider.strip().upper(),
        provider_payment_reference=provider_payment_reference,
        external_event_id=external_event_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status=status,
        currency=currency,
        amount=normalized,
        payment_method_summary=payment_method_summary,
        failure_code=failure_code,
        evidence_reference=f"provider-event:{provider}:{external_event_id}",
        received_at=occurred_at,
        created_by=actor_id,
    )
    try:
        session.add(payment)
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        existing = session.exec(select(SaasPayment).where(
            SaasPayment.idempotency_key == idempotency_key
        )).first()
        if existing is not None and existing.request_hash == request_hash:
            return existing
        raise HTTPException(status_code=409, detail="Referência externa de pagamento já utilizada.") from exc
    _audit_payment(
        session,
        payment=payment,
        actor_id=actor_id,
        action=("saas.payment.failed" if status == SaasPaymentStatusEnum.FAILED else "saas.payment.unknown"),
        payload={
            "payment_id": str(payment.id), "invoice_id": str(invoice.id),
            "status": status.value, "provider": payment.provider,
            "amount": str(payment.amount), "failure_code": failure_code,
        },
    )
    session.commit()
    session.refresh(payment)
    return payment


def reconcile_unknown_payment(
    session: Session,
    *,
    payment_id: uuid.UUID,
    invoice_id: uuid.UUID,
    confirmed_status: SaasPaymentStatusEnum,
    expected_invoice_version: int,
    evidence_reference: str,
    failure_code: Optional[str],
    actor_id: uuid.UUID,
    idempotency_key: str,
) -> SaasPayment:
    if confirmed_status not in {SaasPaymentStatusEnum.SUCCEEDED, SaasPaymentStatusEnum.FAILED}:
        raise HTTPException(status_code=422, detail="A reconciliação deve confirmar sucesso ou falha.")
    payload = {
        "payment_id": str(payment_id), "invoice_id": str(invoice_id),
        "confirmed_status": confirmed_status.value,
        "expected_invoice_version": expected_invoice_version,
        "evidence_reference": evidence_reference.strip(), "failure_code": failure_code,
    }
    request_hash = reliability_service.compute_request_hash(payload)
    payment = session.exec(select(SaasPayment).where(
        SaasPayment.id == payment_id
    ).with_for_update()).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Pagamento SaaS não encontrado.")
    if payment.reconcile_idempotency_key == idempotency_key:
        if payment.reconcile_request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Chave de reconciliação reutilizada com outro conteúdo.")
        return payment
    if payment.status != SaasPaymentStatusEnum.UNKNOWN:
        raise HTTPException(status_code=409, detail="Somente um pagamento desconhecido pode ser reconciliado.")
    invoice = session.exec(select(SaasInvoice).where(
        SaasInvoice.id == invoice_id
    ).with_for_update()).first()
    if invoice is None or invoice.tenant_id != payment.tenant_id:
        raise HTTPException(status_code=404, detail="Fatura SaaS compatível não encontrada.")
    if invoice.version != expected_invoice_version:
        raise HTTPException(status_code=409, detail="A fatura foi alterada. Recarregue antes de reconciliar.")
    now = datetime.utcnow()
    if confirmed_status == SaasPaymentStatusEnum.SUCCEEDED:
        if invoice.status not in {
            SaasInvoiceStatusEnum.OPEN, SaasInvoiceStatusEnum.PARTIALLY_PAID,
            SaasInvoiceStatusEnum.OVERDUE,
        } or Decimal(payment.amount) > Decimal(invoice.balance_amount):
            raise HTTPException(status_code=422, detail="O pagamento não cabe no saldo atual da fatura.")
        invoice.balance_amount = (Decimal(invoice.balance_amount) - Decimal(payment.amount)).quantize(MONEY)
        invoice.status = _invoice_status_for_balance(invoice, as_of=now.date())
        invoice.paid_at = now if invoice.status == SaasInvoiceStatusEnum.PAID else None
        invoice.version += 1
        invoice.updated_at = now
        session.add(invoice)
        session.add(SaasPaymentAllocation(
            payment_id=payment.id,
            invoice_id=invoice.id,
            amount=payment.amount,
            idempotency_key=hashlib.sha256(
                f"{idempotency_key}:{invoice.id}".encode("utf-8")
            ).hexdigest(),
            allocated_at=now,
        ))
        payment.succeeded_at = now
    payment.status = confirmed_status
    payment.failure_code = failure_code if confirmed_status == SaasPaymentStatusEnum.FAILED else None
    payment.evidence_reference = evidence_reference.strip()
    payment.reconcile_idempotency_key = idempotency_key
    payment.reconcile_request_hash = request_hash
    payment.version += 1
    payment.updated_at = now
    session.add(payment)
    session.flush()
    _audit_payment(
        session,
        payment=payment,
        actor_id=actor_id,
        action=("saas.payment.succeeded" if confirmed_status == SaasPaymentStatusEnum.SUCCEEDED else "saas.payment.failed"),
        payload={
            "payment_id": str(payment.id), "invoice_id": str(invoice.id),
            "previous_status": SaasPaymentStatusEnum.UNKNOWN.value,
            "current_status": confirmed_status.value,
            "evidence_reference": payment.evidence_reference,
        },
    )
    session.commit()
    session.refresh(payment)
    return payment


def refund_payment(
    session: Session,
    *,
    payment_id: uuid.UUID,
    invoice_id: uuid.UUID,
    amount: Decimal,
    expected_invoice_version: int,
    reason: str,
    evidence_reference: str,
    actor_id: uuid.UUID,
    idempotency_key: str,
) -> SaasRefund:
    existing = session.exec(select(SaasRefund).where(
        SaasRefund.idempotency_key == idempotency_key
    )).first()
    normalized = Decimal(amount).quantize(MONEY)
    if existing is not None:
        if (
            existing.payment_id != payment_id or existing.invoice_id != invoice_id
            or Decimal(existing.amount) != normalized or existing.reason != reason.strip()
            or existing.evidence_reference != evidence_reference.strip()
        ):
            raise HTTPException(status_code=409, detail="Chave de idempotência reutilizada com outro estorno.")
        return existing
    if normalized <= 0 or len(reason.strip()) < 4 or len(evidence_reference.strip()) < 4:
        raise HTTPException(status_code=422, detail="Estorno exige valor, motivo e evidência válidos.")
    payment = session.exec(select(SaasPayment).where(
        SaasPayment.id == payment_id
    ).with_for_update()).first()
    invoice = session.exec(select(SaasInvoice).where(
        SaasInvoice.id == invoice_id
    ).with_for_update()).first()
    if payment is None or invoice is None:
        raise HTTPException(status_code=404, detail="Pagamento ou fatura SaaS não encontrado.")
    if payment.status not in {
        SaasPaymentStatusEnum.SUCCEEDED,
        SaasPaymentStatusEnum.PARTIALLY_REFUNDED,
    }:
        raise HTTPException(status_code=409, detail="O pagamento não aceita estorno.")
    if invoice.version != expected_invoice_version:
        raise HTTPException(status_code=409, detail="A fatura foi alterada. Recarregue antes de estornar.")
    allocated = sum((
        Decimal(item.amount) for item in session.exec(select(SaasPaymentAllocation).where(
            SaasPaymentAllocation.payment_id == payment_id,
            SaasPaymentAllocation.invoice_id == invoice_id,
        )).all()
    ), Decimal("0.00"))
    already_refunded = sum((
        Decimal(item.amount) for item in session.exec(select(SaasRefund).where(
            SaasRefund.payment_id == payment_id,
            SaasRefund.invoice_id == invoice_id,
        )).all()
    ), Decimal("0.00"))
    if normalized > allocated - already_refunded:
        raise HTTPException(status_code=422, detail="O estorno excede o valor alocado nesta fatura.")
    refund = SaasRefund(
        payment_id=payment.id,
        invoice_id=invoice.id,
        amount=normalized,
        reason=reason.strip(),
        evidence_reference=evidence_reference.strip(),
        idempotency_key=idempotency_key,
        created_by=actor_id,
    )
    session.add(refund)
    invoice.balance_amount = min(
        Decimal(invoice.total_amount), Decimal(invoice.balance_amount) + normalized
    ).quantize(MONEY)
    invoice.status = _invoice_status_for_balance(invoice, as_of=date.today())
    invoice.paid_at = None
    invoice.version += 1
    invoice.updated_at = datetime.utcnow()
    session.add(invoice)
    total_refunded = sum((
        Decimal(item.amount) for item in session.exec(select(SaasRefund).where(
            SaasRefund.payment_id == payment_id
        )).all()
    ), Decimal("0.00")) + normalized
    payment.status = (
        SaasPaymentStatusEnum.REFUNDED
        if total_refunded == Decimal(payment.amount)
        else SaasPaymentStatusEnum.PARTIALLY_REFUNDED
    )
    payment.version += 1
    payment.updated_at = datetime.utcnow()
    session.add(payment)
    session.flush()
    _audit_payment(
        session,
        payment=payment,
        actor_id=actor_id,
        action="saas.payment.refunded",
        payload={
            "payment_id": str(payment.id), "refund_id": str(refund.id),
            "invoice_id": str(invoice.id), "amount": str(refund.amount),
            "reason": refund.reason,
        },
    )
    session.commit()
    session.refresh(refund)
    return refund


def mark_overdue_invoices(
    session: Session,
    *,
    as_of: date,
    actor_id: uuid.UUID,
) -> list[SaasInvoice]:
    invoices = list(session.exec(select(SaasInvoice).where(
        SaasInvoice.due_date < as_of,
        SaasInvoice.balance_amount > 0,
        SaasInvoice.status.in_([
            SaasInvoiceStatusEnum.OPEN,
            SaasInvoiceStatusEnum.PARTIALLY_PAID,
        ]),
    ).with_for_update()).all())
    changed: list[SaasInvoice] = []
    for invoice in invoices:
        previous = invoice.status
        invoice.status = SaasInvoiceStatusEnum.OVERDUE
        invoice.version += 1
        invoice.updated_at = datetime.utcnow()
        session.add(invoice)
        event_key = f"saas-overdue:{invoice.id}:{as_of.isoformat()}"
        if session.exec(select(SaasCollectionEvent).where(
            SaasCollectionEvent.idempotency_key == event_key
        )).first() is None:
            session.add(SaasCollectionEvent(
                invoice_id=invoice.id,
                tenant_id=invoice.tenant_id,
                event_type=SaasCollectionEventTypeEnum.OVERDUE_MARKED,
                channel="SYSTEM",
                outcome="OVERDUE",
                detail=f"Saldo vencido derivado na data de corte {as_of.isoformat()}.",
                idempotency_key=event_key,
                actor_id=actor_id,
            ))
        _audit_invoice(
            session,
            invoice=invoice,
            actor_id=actor_id,
            action="saas.invoice.overdue",
            payload={
                "invoice_id": str(invoice.id), "as_of": as_of.isoformat(),
                "previous_status": previous.value, "balance_amount": str(invoice.balance_amount),
            },
        )
        changed.append(invoice)
    session.commit()
    for invoice in changed:
        session.refresh(invoice)
    return changed


def record_collection_event(
    session: Session,
    *,
    invoice_id: uuid.UUID,
    event_type: SaasCollectionEventTypeEnum,
    channel: str,
    outcome: str,
    recipient_masked: Optional[str],
    detail: str,
    evidence_reference: Optional[str],
    actor_id: uuid.UUID,
    idempotency_key: str,
) -> SaasCollectionEvent:
    existing = session.exec(select(SaasCollectionEvent).where(
        SaasCollectionEvent.idempotency_key == idempotency_key
    )).first()
    if existing is not None:
        if (
            existing.invoice_id != invoice_id
            or existing.event_type != event_type
            or existing.channel != channel.strip().upper()
            or existing.outcome != outcome.strip().upper()
            or existing.recipient_masked != (recipient_masked.strip() if recipient_masked else None)
            or existing.detail != detail.strip()
            or existing.evidence_reference != (evidence_reference.strip() if evidence_reference else None)
        ):
            raise HTTPException(status_code=409, detail="Chave de idempotência reutilizada com outra ação de cobrança.")
        return existing
    if len(channel.strip()) < 2 or len(outcome.strip()) < 2 or len(detail.strip()) < 4:
        raise HTTPException(status_code=422, detail="A ação de cobrança exige canal, resultado e detalhe válidos.")
    invoice = session.get(SaasInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Fatura SaaS não encontrada.")
    event = SaasCollectionEvent(
        invoice_id=invoice.id,
        tenant_id=invoice.tenant_id,
        event_type=event_type,
        channel=channel.strip().upper(),
        outcome=outcome.strip().upper(),
        recipient_masked=recipient_masked.strip() if recipient_masked else None,
        detail=detail.strip(),
        evidence_reference=evidence_reference.strip() if evidence_reference else None,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
    )
    session.add(event)
    session.flush()
    _audit_invoice(
        session,
        invoice=invoice,
        actor_id=actor_id,
        action="saas.collection.recorded",
        payload={
            "invoice_id": str(invoice.id), "collection_event_id": str(event.id),
            "event_type": event.event_type.value, "channel": event.channel,
            "outcome": event.outcome,
        },
    )
    session.commit()
    session.refresh(event)
    return event

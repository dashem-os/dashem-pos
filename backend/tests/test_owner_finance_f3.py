import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import platform_finance_overview
from app.core.database import engine
from app.core.config import settings
from app.core.tenancy import set_platform_db_context
from app.models.owner_finance import (
    SaasCollectionEvent, SaasInvoice, SaasInvoiceStatusEnum, SaasPayment,
    SaasPaymentAllocation, SaasPaymentStatusEnum, SaasRefund,
    SaasCollectionEventTypeEnum,
)
from app.models.platform import PlatformRoleEnum
from app.services import owner_finance_service
from app.main import app
from tests.test_owner_finance_f2 import _invoice_source, _platform_user


def _issued_invoice(session: Session, actor, competence: date) -> SaasInvoice:
    tenant, _, _, _, _ = _invoice_source(session, actor)
    generated, _, _ = owner_finance_service.generate_invoices(
        session,
        competence=competence,
        actor_id=actor.id,
        idempotency_key=f"f3-generate-{tenant.id}-{competence:%Y-%m}",
        tenant_id=tenant.id,
    )
    invoice = generated[0]
    return owner_finance_service.issue_invoice(
        session,
        invoice_id=invoice.id,
        expected_version=invoice.version,
        reason="Emissão para teste de recebimento real.",
        actor_id=actor.id,
        idempotency_key=f"f3-issue-{invoice.id}",
    )


def test_f3_receipt_refund_and_overdue_are_real_idempotent_facts():
    with Session(engine) as session:
        principal, actor = _platform_user(session, PlatformRoleEnum.PLATFORM_OWNER)
        set_platform_db_context(session, actor.id)
        invoice = _issued_invoice(session, actor, date(2027, 9, 1))
        baseline = platform_finance_overview(principal, session)

        first_key = f"manual-receipt-{invoice.id}-1"
        first = owner_finance_service.record_succeeded_payment(
            session,
            allocations=[(invoice.id, Decimal("100.00"), invoice.version)],
            amount=Decimal("100.00"),
            currency="BRL",
            provider="MANUAL",
            provider_payment_reference=None,
            external_event_id=None,
            payment_method_summary="TRANSFERENCIA_CONFIRMADA",
            evidence_reference="bank-statement:receipt-001",
            reason="Baixa manual conferida no extrato bancário.",
            received_at=datetime(2027, 9, 10, 12, 0, 0),
            actor_id=actor.id,
            idempotency_key=first_key,
        )
        session.refresh(invoice)
        assert first.status == SaasPaymentStatusEnum.SUCCEEDED
        assert invoice.status == SaasInvoiceStatusEnum.PARTIALLY_PAID
        assert invoice.balance_amount == Decimal("149.90")

        replay = owner_finance_service.record_succeeded_payment(
            session,
            allocations=[(invoice.id, Decimal("100.00"), 2)],
            amount=Decimal("100.00"), currency="BRL", provider="MANUAL",
            provider_payment_reference=None, external_event_id=None,
            payment_method_summary="TRANSFERENCIA_CONFIRMADA",
            evidence_reference="bank-statement:receipt-001",
            reason="Baixa manual conferida no extrato bancário.",
            received_at=datetime(2027, 9, 10, 12, 0, 0), actor_id=actor.id,
            idempotency_key=first_key,
        )
        assert replay.id == first.id
        assert len(session.exec(select(SaasPaymentAllocation).where(
            SaasPaymentAllocation.payment_id == first.id
        )).all()) == 1

        second = owner_finance_service.record_succeeded_payment(
            session,
            allocations=[(invoice.id, Decimal("149.90"), invoice.version)],
            amount=Decimal("149.90"), currency="BRL", provider="MANUAL",
            provider_payment_reference=None, external_event_id=None,
            payment_method_summary="PIX_CONFIRMADO",
            evidence_reference="bank-statement:receipt-002",
            reason="PIX identificado e conferido no extrato bancário.",
            received_at=datetime(2027, 9, 11, 12, 0, 0), actor_id=actor.id,
            idempotency_key=f"manual-receipt-{invoice.id}-2",
        )
        session.refresh(invoice)
        assert invoice.status == SaasInvoiceStatusEnum.PAID
        assert invoice.balance_amount == Decimal("0.00") and invoice.paid_at is not None

        refund = owner_finance_service.refund_payment(
            session,
            payment_id=second.id,
            invoice_id=invoice.id,
            amount=Decimal("50.00"),
            expected_invoice_version=invoice.version,
            reason="Estorno confirmado no extrato bancário.",
            evidence_reference="bank-statement:refund-001",
            actor_id=actor.id,
            idempotency_key=f"refund-{second.id}-1",
        )
        session.refresh(invoice); session.refresh(second)
        assert refund.amount == Decimal("50.00")
        assert second.status == SaasPaymentStatusEnum.PARTIALLY_REFUNDED
        assert invoice.balance_amount == Decimal("50.00")
        assert invoice.status == SaasInvoiceStatusEnum.PARTIALLY_PAID

        overdue = owner_finance_service.mark_overdue_invoices(
            session, as_of=date(2027, 10, 1), actor_id=actor.id
        )
        assert [item.id for item in overdue] == [invoice.id]
        assert overdue[0].status == SaasInvoiceStatusEnum.OVERDUE
        repeated = owner_finance_service.mark_overdue_invoices(
            session, as_of=date(2027, 10, 1), actor_id=actor.id
        )
        assert repeated == []
        assert len(session.exec(select(SaasCollectionEvent).where(
            SaasCollectionEvent.invoice_id == invoice.id
        )).all()) == 1

        collection_key = f"collection-contact-{invoice.id}"
        contact = owner_finance_service.record_collection_event(
            session,
            invoice_id=invoice.id,
            event_type=SaasCollectionEventTypeEnum.CONTACT_ATTEMPT,
            channel="email",
            outcome="sent",
            recipient_masked="f***@example.test",
            detail="Contato de cobrança enviado após confirmação do vencimento.",
            evidence_reference="mail-provider:event-001",
            actor_id=actor.id,
            idempotency_key=collection_key,
        )
        replayed_contact = owner_finance_service.record_collection_event(
            session,
            invoice_id=invoice.id,
            event_type=SaasCollectionEventTypeEnum.CONTACT_ATTEMPT,
            channel="email",
            outcome="sent",
            recipient_masked="f***@example.test",
            detail="Contato de cobrança enviado após confirmação do vencimento.",
            evidence_reference="mail-provider:event-001",
            actor_id=actor.id,
            idempotency_key=collection_key,
        )
        assert replayed_contact.id == contact.id

        overview = platform_finance_overview(principal, session)
        assert overview.received_total == baseline.received_total + Decimal("199.90")
        assert overview.refunded_total == baseline.refunded_total + Decimal("50.00")
        assert overview.overdue_invoice_balance == baseline.overdue_invoice_balance + Decimal("50.00")
        assert overview.overdue_invoices == baseline.overdue_invoices + 1

        allocation = session.exec(select(SaasPaymentAllocation).where(
            SaasPaymentAllocation.payment_id == first.id
        )).one()
        with pytest.raises(DBAPIError):
            session.exec(text(
                "UPDATE saas_payment_allocations SET amount = 1 WHERE id = :id"
            ), params={"id": allocation.id})
            session.commit()
        session.rollback()


def test_f3_unknown_provider_result_is_reconciled_before_allocation():
    with Session(engine) as session:
        _, actor = _platform_user(session, PlatformRoleEnum.PLATFORM_OWNER)
        set_platform_db_context(session, actor.id)
        invoice = _issued_invoice(session, actor, date(2027, 11, 1))
        unknown = owner_finance_service.record_provider_observation(
            session,
            invoice_id=invoice.id,
            status=SaasPaymentStatusEnum.UNKNOWN,
            amount=invoice.total_amount,
            currency="BRL",
            provider="TEST_PROVIDER",
            provider_payment_reference=f"provider-payment-{uuid.uuid4()}",
            external_event_id=f"event-{uuid.uuid4()}",
            payment_method_summary="PIX",
            failure_code=None,
            occurred_at=datetime(2027, 11, 10, 8, 0, 0),
            actor_id=actor.id,
            idempotency_key=f"provider-unknown-{uuid.uuid4()}",
        )
        assert unknown.status == SaasPaymentStatusEnum.UNKNOWN
        assert session.exec(select(SaasPaymentAllocation).where(
            SaasPaymentAllocation.payment_id == unknown.id
        )).all() == []
        session.refresh(invoice)
        original_balance = invoice.balance_amount

        reconciled = owner_finance_service.reconcile_unknown_payment(
            session,
            payment_id=unknown.id,
            invoice_id=invoice.id,
            confirmed_status=SaasPaymentStatusEnum.SUCCEEDED,
            expected_invoice_version=invoice.version,
            evidence_reference="provider-query:confirmed-001",
            failure_code=None,
            actor_id=actor.id,
            idempotency_key=f"reconcile-{unknown.id}",
        )
        session.refresh(invoice)
        assert reconciled.status == SaasPaymentStatusEnum.SUCCEEDED
        assert original_balance == reconciled.amount
        assert invoice.status == SaasInvoiceStatusEnum.PAID
        assert invoice.balance_amount == Decimal("0.00")
        assert len(session.exec(select(SaasPaymentAllocation).where(
            SaasPaymentAllocation.payment_id == unknown.id
        )).all()) == 1


def test_f3_tables_are_platform_only_and_financial_facts_are_append_only():
    tables = {
        "saas_payments", "saas_payment_allocations", "saas_refunds",
        "saas_collection_events",
    }
    with Session(engine) as session:
        rows = session.exec(text("""
            SELECT class.relname, class.relrowsecurity, class.relforcerowsecurity,
                   policy.polname
            FROM pg_class AS class
            JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
            LEFT JOIN pg_policy AS policy ON policy.polrelid = class.oid
            WHERE namespace.nspname = current_schema()
              AND class.relname IN (
                'saas_payments', 'saas_payment_allocations', 'saas_refunds',
                'saas_collection_events'
              )
        """)).all()
        triggers = session.exec(text("""
            SELECT event_object_table, trigger_name
            FROM information_schema.triggers
            WHERE trigger_schema = current_schema()
              AND event_object_table IN (
                'saas_payment_allocations', 'saas_refunds', 'saas_collection_events'
              )
        """)).all()
    assert {row[0] for row in rows} == tables
    assert all(row[1] is True and row[2] is True for row in rows)
    assert all(row[3] == f"{row[0]}_platform_only" for row in rows)
    assert {row[0] for row in triggers} == {
        "saas_payment_allocations", "saas_refunds", "saas_collection_events"
    }


def test_f3_webhook_signature_is_fail_closed():
    body = b'{"external_event_id":"evt-real"}'
    secret = "test-only-secret"
    signature = "sha256=9a8dfde37c92fcc6765cf444d9ee7fa4f4ce5d6d6c822a8a450f1fca5c5f75a6"
    # The hard-coded mismatch proves that arbitrary or stale signatures are rejected.
    assert owner_finance_service.verify_webhook_signature(body, signature, secret) is False
    import hashlib
    import hmac
    valid = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert owner_finance_service.verify_webhook_signature(body, valid, secret) is True


def test_f3_webhook_never_acknowledges_without_configuration_or_valid_signature(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(settings, "SAAS_PAYMENT_WEBHOOK_SECRET", None)
    monkeypatch.setattr(settings, "SAAS_PAYMENT_WEBHOOK_ACTOR_ID", None)
    unavailable = client.post(
        "/api/v1/control/finance/provider/webhooks/not-configured",
        content=b"{}",
        headers={"Content-Type": "application/json", "X-Dashem-Signature": "0" * 64},
    )
    assert unavailable.status_code == 503

    monkeypatch.setattr(settings, "SAAS_PAYMENT_WEBHOOK_SECRET", "configured-test-secret")
    monkeypatch.setattr(settings, "SAAS_PAYMENT_WEBHOOK_ACTOR_ID", str(uuid.uuid4()))
    unauthorized = client.post(
        "/api/v1/control/finance/provider/webhooks/configured",
        content=b"{}",
        headers={"Content-Type": "application/json", "X-Dashem-Signature": "0" * 64},
    )
    assert unauthorized.status_code == 401

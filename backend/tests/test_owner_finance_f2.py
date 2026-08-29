import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import platform_finance_overview
from app.api.v1.endpoints.owner_finance import (
    InvoiceGenerateRequest, export_invoices, generate_invoices as generate_invoices_endpoint,
    get_invoice, list_invoices,
)
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.core.tenancy import set_platform_db_context
from app.models.identity import (
    AuthIdentity, ServicePlan, ServicePlanRevision, SubscriptionStatusEnum, Tenant, TenantStatusEnum,
    TenantSubscription, User,
)
from app.models.owner_finance import (
    SaasBillingAccount, SaasInvoice, SaasInvoiceLine, SaasInvoiceStatusEnum,
)
from app.models.platform import PlatformMembership, PlatformRoleEnum, TenantContract
from app.models.reliability import AuditEvent, OutboxEvent
from app.services import owner_finance_service


def _principal(subject: str, assurance_level: str = "aal2") -> AuthPrincipal:
    return AuthPrincipal(
        subject=subject,
        email=f"finance-f2-{subject}@example.test",
        session_id=str(uuid.uuid4()),
        assurance_level=assurance_level,
        claims={"sub": subject, "aal": assurance_level},
        provider="email",
    )


def _platform_user(session: Session, role: PlatformRoleEnum) -> tuple[AuthPrincipal, User]:
    subject = str(uuid.uuid4())
    user = User(email=f"finance-f2-{subject}@example.test", full_name=f"Finance F2 {role.value}")
    session.add(user)
    session.flush()
    session.add(AuthIdentity(
        user_id=user.id,
        provider="supabase",
        provider_subject=subject,
        provider_email=user.email,
        email_verified=True,
    ))
    session.add(PlatformMembership(user_id=user.id, role=role))
    session.commit()
    session.refresh(user)
    return _principal(subject), user


def _invoice_source(session: Session, actor: User):
    suffix = uuid.uuid4().hex[:10]
    tenant = Tenant(
        name=f"Finance F2 {suffix}",
        slug=f"finance-f2-{suffix}",
        status=TenantStatusEnum.ACTIVE,
        legal_name=f"Finance F2 {suffix} LTDA",
    )
    plan = ServicePlan(
        code=f"F2_{suffix.upper()}",
        name=f"Plano F2 {suffix}",
        description="Plano persistido para o faturamento SaaS.",
        monthly_price=Decimal("249.90"),
    )
    session.add(tenant)
    session.add(plan)
    session.flush()
    revision = ServicePlanRevision(
        plan_id=plan.id, version=1, code=plan.code, name=plan.name,
        description=plan.description, is_active=True, capability_keys=[],
        monthly_price=plan.monthly_price, reason="Versão comercial de teste.",
        created_by=actor.id,
    )
    session.add(revision)
    session.flush()
    subscription = TenantSubscription(
        tenant_id=tenant.id,
        plan_id=plan.id,
        status=SubscriptionStatusEnum.ACTIVE,
        gross_monthly_amount=Decimal("249.90"),
        monthly_amount=Decimal("249.90"),
        billing_day=12,
    )
    account = SaasBillingAccount(
        tenant_id=tenant.id,
        legal_name=tenant.legal_name,
        tax_id="04252011000110",
        contact_name="Financeiro Cliente",
        contact_email=f"billing-{suffix}@example.test",
        currency="BRL",
    )
    contract = TenantContract(
        tenant_id=tenant.id,
        version=1,
        status="ACTIVE",
        plan_id=plan.id,
        plan_revision_id=revision.id,
        limits={"users": 10, "devices": 5, "units": 2},
        capability_keys=["inventory"],
        reason="Contrato inicial usado como fonte real da fatura.",
        created_by=actor.id,
    )
    session.add(subscription)
    session.add(account)
    session.add(contract)
    session.commit()
    return tenant, plan, subscription, account, contract


def test_f2_invoice_lifecycle_is_real_idempotent_audited_and_immutable():
    with Session(engine) as session:
        principal, actor = _platform_user(session, PlatformRoleEnum.PLATFORM_OWNER)
        set_platform_db_context(session, actor.id)
        tenant, plan, subscription, _, contract = _invoice_source(session, actor)
        before = platform_finance_overview(principal, session)

        generated, existing, skipped = owner_finance_service.generate_invoices(
            session,
            competence=date(2026, 9, 18),
            actor_id=actor.id,
            idempotency_key=f"generate-{tenant.id}-2026-09",
            tenant_id=tenant.id,
        )
        assert len(generated) == 1 and not existing and not skipped
        invoice = generated[0]
        assert invoice.period_start == date(2026, 9, 1)
        assert invoice.period_end == date(2026, 9, 30)
        assert invoice.total_amount == Decimal("249.90")
        assert invoice.balance_amount == invoice.total_amount
        assert invoice.contract_version == contract.version
        assert invoice.plan_name_snapshot == plan.name
        assert invoice.billing_legal_name_snapshot == tenant.legal_name
        assert invoice.status == SaasInvoiceStatusEnum.DRAFT

        repeated, existing, skipped = owner_finance_service.generate_invoices(
            session,
            competence=date(2026, 9, 1),
            actor_id=actor.id,
            idempotency_key=f"generate-{tenant.id}-2026-09",
            tenant_id=tenant.id,
        )
        assert not repeated and len(existing) == 1 and not skipped
        assert existing[0].id == invoice.id
        assert session.exec(select(SaasInvoice).where(
            SaasInvoice.subscription_id == tenant.id,
            SaasInvoice.period_start == date(2026, 9, 1),
        )).all() == [invoice]

        draft_overview = platform_finance_overview(principal, session)
        assert draft_overview.draft_invoices == before.draft_invoices + 1
        assert draft_overview.invoiced_total == before.invoiced_total

        original_plan_name = invoice.plan_name_snapshot
        original_total = invoice.total_amount
        plan.name = "Plano alterado depois da geração"
        subscription.monthly_amount = Decimal("999.00")
        subscription.gross_monthly_amount = Decimal("999.00")
        session.add(plan); session.add(subscription); session.commit()
        session.refresh(invoice)
        assert invoice.plan_name_snapshot == original_plan_name
        assert invoice.total_amount == original_total

        issue_key = f"issue-{invoice.id}-v{invoice.version}"
        issued = owner_finance_service.issue_invoice(
            session, invoice_id=invoice.id, expected_version=invoice.version,
            reason="Emissão mensal conferida.", actor_id=actor.id,
            idempotency_key=issue_key,
        )
        assert issued.status == SaasInvoiceStatusEnum.OPEN
        assert issued.issued_by == actor.id and issued.version == 2
        replay = owner_finance_service.issue_invoice(
            session, invoice_id=invoice.id, expected_version=1,
            reason="Emissão mensal conferida.", actor_id=actor.id,
            idempotency_key=issue_key,
        )
        assert replay.id == issued.id and replay.version == 2

        issued_overview = platform_finance_overview(principal, session)
        assert issued_overview.invoiced_total == before.invoiced_total + original_total
        assert issued_overview.open_invoice_balance == before.open_invoice_balance + original_total
        assert issued_overview.open_invoices == before.open_invoices + 1

        line = session.exec(select(SaasInvoiceLine).where(
            SaasInvoiceLine.invoice_id == invoice.id
        )).one()
        with pytest.raises(DBAPIError):
            session.exec(text(
                "UPDATE saas_invoice_lines SET description = 'tentativa' WHERE id = :line_id"
            ), params={"line_id": line.id})
            session.commit()
        session.rollback(); set_platform_db_context(session, actor.id)
        with pytest.raises(DBAPIError):
            session.add(SaasInvoiceLine(
                invoice_id=invoice.id,
                line_type=line.line_type,
                description="Item acrescentado após emissão",
                quantity=Decimal("1.0000"),
                unit_amount=Decimal("1.00"),
                total_amount=Decimal("1.00"),
                contract_version=invoice.contract_version,
            ))
            session.commit()
        session.rollback(); set_platform_db_context(session, actor.id)
        with pytest.raises(DBAPIError):
            session.exec(text(
                "UPDATE saas_invoices SET plan_name_snapshot = 'tentativa' WHERE id = :invoice_id"
            ), params={"invoice_id": invoice.id})
            session.commit()
        session.rollback(); set_platform_db_context(session, actor.id)

        current = session.get(SaasInvoice, invoice.id)
        assert current is not None
        void_key = f"void-{current.id}-v{current.version}"
        voided = owner_finance_service.void_invoice(
            session, invoice_id=current.id, expected_version=current.version,
            reason="Cobrança anulada por revisão contratual.", actor_id=actor.id,
            idempotency_key=void_key,
        )
        assert voided.status == SaasInvoiceStatusEnum.VOID
        assert voided.balance_amount == Decimal("0.00")
        replay = owner_finance_service.void_invoice(
            session, invoice_id=voided.id, expected_version=2,
            reason="Cobrança anulada por revisão contratual.", actor_id=actor.id,
            idempotency_key=void_key,
        )
        assert replay.id == voided.id and replay.version == 3

        final_overview = platform_finance_overview(principal, session)
        assert final_overview.invoiced_total == before.invoiced_total
        assert final_overview.open_invoice_balance == before.open_invoice_balance
        assert final_overview.void_invoices == before.void_invoices + 1
        assert session.exec(select(AuditEvent).where(
            AuditEvent.target == f"saas_invoice:{invoice.id}",
            AuditEvent.action == "saas.invoice.issued",
        )).one().platform_scope is True
        assert session.exec(select(OutboxEvent).where(
            OutboxEvent.aggregate_id == str(invoice.id),
            OutboxEvent.event_type == "saas.invoice.voided",
        )).one() is not None


def test_f2_listing_detail_export_permissions_and_incomplete_sources():
    with Session(engine) as session:
        owner, actor = _platform_user(session, PlatformRoleEnum.PLATFORM_OWNER)
        set_platform_db_context(session, actor.id)
        tenant, _, _, account, _ = _invoice_source(session, actor)
        generated = generate_invoices_endpoint(
            InvoiceGenerateRequest(competence=date(2026, 10, 1), tenant_id=tenant.id),
            f"generate-{tenant.id}-2026-10", owner, session,
        )
        invoice = generated.generated[0]
        listing = list_invoices(
            status=SaasInvoiceStatusEnum.DRAFT, tenant_id=tenant.id,
            period_from=None, period_to=None, page=1, size=50,
            principal=owner, session=session,
        )
        assert listing.total == 1 and listing.items[0].invoice.id == invoice.id
        detail = get_invoice(invoice.id, owner, session)
        assert detail.tenant_name == tenant.name and len(detail.lines) == 1
        exported = export_invoices(
            status=None, tenant_id=tenant.id, period_from=None, period_to=None,
            principal=owner, session=session,
        )
        assert exported.media_type == "text/csv; charset=utf-8"

        account.contact_email = None
        session.add(account); session.commit()
        result = generate_invoices_endpoint(
            InvoiceGenerateRequest(competence=date(2026, 11, 1), tenant_id=tenant.id),
            f"generate-{tenant.id}-2026-11", owner, session,
        )
        assert not result.generated and result.skipped[0].code == "INVOICE_SOURCE_INCOMPLETE"

        auditor, _ = _platform_user(session, PlatformRoleEnum.AUDITOR)
        assert list_invoices(
            status=None, tenant_id=tenant.id, period_from=None, period_to=None,
            page=1, size=50, principal=auditor, session=session,
        ).total == 1
        with pytest.raises(HTTPException) as auditor_write:
            generate_invoices_endpoint(
                InvoiceGenerateRequest(competence=date(2026, 12, 1), tenant_id=tenant.id),
                f"generate-{tenant.id}-2026-12", auditor, session,
            )
        assert auditor_write.value.status_code == 403

        with pytest.raises(HTTPException) as aal1_write:
            generate_invoices_endpoint(
                InvoiceGenerateRequest(competence=date(2026, 12, 1), tenant_id=tenant.id),
                f"generate-{tenant.id}-2026-12-aal1", _principal(owner.subject, "aal1"), session,
            )
        assert aal1_write.value.status_code == 403
        assert "Multi-factor" in aal1_write.value.detail

        support, _ = _platform_user(session, PlatformRoleEnum.SUPPORT)
        with pytest.raises(HTTPException) as support_read:
            list_invoices(
                status=None, tenant_id=tenant.id, period_from=None, period_to=None,
                page=1, size=50, principal=support, session=session,
            )
        assert support_read.value.status_code == 403


def test_contract_discount_preserves_list_price_and_zero_invoice_is_not_paid():
    with Session(engine) as session:
        principal, actor = _platform_user(session, PlatformRoleEnum.PLATFORM_OWNER)
        set_platform_db_context(session, actor.id)
        tenant, plan, subscription, _, _ = _invoice_source(session, actor)

        contracted_plan_name = plan.name
        plan.monthly_price = Decimal("119.00")
        plan.name = "Nome atual alterado após a contratação"
        subscription.gross_monthly_amount = Decimal("119.00")
        subscription.discount_type = "FIXED"
        subscription.discount_value = Decimal("59.10")
        subscription.discount_amount = Decimal("59.10")
        subscription.discount_reason_code = "LAUNCH_PROMOTION"
        subscription.discount_reason = "Primeiros clientes DASHEM Essencial."
        subscription.monthly_amount = Decimal("59.90")
        session.add(plan); session.add(subscription); session.commit()

        overview = platform_finance_overview(principal, session)
        row = next(item for item in overview.subscriptions if item.tenant_id == tenant.id)
        assert row.gross_monthly_amount == Decimal("119.00")
        assert row.discount_amount == Decimal("59.10")
        assert row.monthly_amount == Decimal("59.90")

        generated, _, _ = owner_finance_service.generate_invoices(
            session, competence=date(2026, 9, 1), actor_id=actor.id,
            idempotency_key=f"discount-{tenant.id}-2026-09", tenant_id=tenant.id,
        )
        invoice = generated[0]
        lines = session.exec(select(SaasInvoiceLine).where(SaasInvoiceLine.invoice_id == invoice.id)).all()
        assert invoice.plan_name_snapshot == contracted_plan_name
        assert invoice.subtotal == Decimal("119.00")
        assert invoice.discount_amount == Decimal("59.10")
        assert invoice.total_amount == Decimal("59.90")
        assert [line.total_amount for line in lines] == [Decimal("119.00"), Decimal("-59.10")]

        subscription.discount_value = Decimal("119.00")
        subscription.discount_amount = Decimal("119.00")
        subscription.discount_reason_code = "INTERNAL_CONTROLLED_TEST"
        subscription.discount_reason = "Teste interno controlado autorizado pelo Owner."
        subscription.discount_review_on = date(2026, 11, 1)
        subscription.monthly_amount = Decimal("0.00")
        subscription.version += 1
        session.add(subscription); session.commit()

        zero_generated, _, _ = owner_finance_service.generate_invoices(
            session, competence=date(2026, 10, 1), actor_id=actor.id,
            idempotency_key=f"discount-{tenant.id}-2026-10", tenant_id=tenant.id,
        )
        zero_invoice = zero_generated[0]
        assert zero_invoice.total_amount == Decimal("0.00")
        issued = owner_finance_service.issue_invoice(
            session, invoice_id=zero_invoice.id, expected_version=zero_invoice.version,
            reason="Emissão do teste controlado.", actor_id=actor.id,
            idempotency_key=f"issue-zero-{zero_invoice.id}",
        )
        assert issued.status == SaasInvoiceStatusEnum.NO_PAYMENT_DUE
        assert issued.balance_amount == Decimal("0.00")
        assert issued.status != SaasInvoiceStatusEnum.PAID


def test_service_plan_revision_snapshot_is_immutable_in_database():
    with Session(engine) as session:
        _, actor = _platform_user(session, PlatformRoleEnum.PLATFORM_OWNER)
        set_platform_db_context(session, actor.id)
        _, _, _, _, contract = _invoice_source(session, actor)
        assert contract.plan_revision_id is not None
        with pytest.raises(DBAPIError):
            session.exec(text(
                "UPDATE service_plan_revisions SET name = 'tentativa' WHERE id = :revision_id"
            ), params={"revision_id": contract.plan_revision_id})
            session.commit()
        session.rollback()


def test_f2_invoice_tables_are_platform_only():
    with Session(engine) as session:
        rows = session.exec(text("""
            SELECT class.relname, class.relrowsecurity, class.relforcerowsecurity,
                   policy.polname
            FROM pg_class AS class
            JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
            LEFT JOIN pg_policy AS policy ON policy.polrelid = class.oid
            WHERE namespace.nspname = current_schema()
              AND class.relname IN ('saas_invoices', 'saas_invoice_lines')
        """)).all()
    assert {row[0] for row in rows} == {"saas_invoices", "saas_invoice_lines"}
    assert all(row[1] is True and row[2] is True for row in rows)
    assert all(row[3] == f"{row[0]}_platform_only" for row in rows)


def test_database_trigger_functions_have_an_immutable_search_path():
    expected = {
        "dashem_reject_immutable_mutation",
        "protect_issued_saas_invoice_snapshot",
        "protect_issued_saas_invoice_line",
    }
    with Session(engine) as session:
        rows = session.exec(text("""
            SELECT procedure.proname, procedure.proconfig
            FROM pg_proc AS procedure
            JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'public'
              AND procedure.proname IN (
                'dashem_reject_immutable_mutation',
                'protect_issued_saas_invoice_snapshot',
                'protect_issued_saas_invoice_line'
              )
        """)).all()
    assert {row[0] for row in rows} == expected
    assert all(
        row[1] and "search_path=pg_catalog, public" in row[1]
        for row in rows
    )

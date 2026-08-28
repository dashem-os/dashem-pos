import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import (
    PlatformTenantCreate,
    SaasBillingAccountUpdate,
    platform_finance_overview,
    provision_platform_tenant,
    update_saas_billing_account,
)
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.core.tenancy import set_platform_db_context
from app.models.identity import AuthIdentity, User
from app.models.owner_finance import SaasBillingAccount
from app.models.platform import (
    PlatformMembership, PlatformPermissionGrant, PlatformRoleEnum, PlatformRolePermission,
)
from app.models.reliability import AuditEvent, OutboxEvent


def _principal(subject: str, assurance_level: str = "aal2") -> AuthPrincipal:
    return AuthPrincipal(
        subject=subject,
        email=f"finance-{subject}@example.test",
        session_id=str(uuid.uuid4()),
        assurance_level=assurance_level,
        claims={"sub": subject, "aal": assurance_level},
        provider="email",
    )


def _platform_user(session: Session, role: PlatformRoleEnum) -> tuple[str, User]:
    subject = str(uuid.uuid4())
    user = User(email=f"finance-{subject}@example.test", full_name=f"Finance {role.value}")
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
    return subject, user


def _tenant(session: Session, principal: AuthPrincipal):
    suffix = uuid.uuid4().hex[:8]
    return provision_platform_tenant(
        data=PlatformTenantCreate(
            name=f"Finance Permission {suffix}",
            slug=f"finance-permission-{suffix}",
            first_store_name="Matriz",
            first_store_code="MATRIZ",
        ),
        principal=principal,
        session=session,
    ).tenant


def _account_input(expected_version: int, contact_name: str = "Financeiro Dashem"):
    return SaasBillingAccountUpdate(
        legal_name="Cliente Financeiro LTDA",
        tax_id="11222333000181",
        contact_name=contact_name,
        contact_email="financeiro@example.test",
        contact_phone="11999999999",
        currency="BRL",
        expected_version=expected_version,
        reason="Atualização cadastral confirmada pelo cliente.",
    )


def test_finance_billing_account_is_versioned_audited_and_outboxed():
    with Session(engine) as session:
        subject, actor = _platform_user(session, PlatformRoleEnum.PLATFORM_OWNER)
        principal = _principal(subject)
        tenant = _tenant(session, principal)

        created = update_saas_billing_account(
            tenant.id, _account_input(0), principal, session,
        )
        assert created.version == 1
        updated = update_saas_billing_account(
            tenant.id, _account_input(1, "Cobrança Dashem"), principal, session,
        )
        assert updated.version == 2
        assert updated.contact_name == "Cobrança Dashem"

        with pytest.raises(HTTPException) as stale:
            update_saas_billing_account(
                tenant.id, _account_input(1, "Gravação obsoleta"), principal, session,
            )
        assert stale.value.status_code == 409
        persisted = session.exec(
            select(SaasBillingAccount).where(SaasBillingAccount.tenant_id == tenant.id)
        ).one()
        assert persisted.version == 2
        assert persisted.contact_name == "Cobrança Dashem"

        audit = session.exec(select(AuditEvent).where(
            AuditEvent.actor_id == actor.id,
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.action == "platform.finance.billing_account_updated",
        ).order_by(AuditEvent.created_at.desc())).first()
        event = session.exec(select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant.id,
            OutboxEvent.event_type == "platform.finance.billing_account_updated",
        )).first()
        assert audit is not None and audit.platform_scope is True
        assert event is not None and event.aggregate_type == "saas_billing_account"


def test_finance_permissions_are_least_privilege_and_commands_require_aal2():
    with Session(engine) as session:
        owner_subject, _ = _platform_user(session, PlatformRoleEnum.PLATFORM_OWNER)
        owner = _principal(owner_subject)
        tenant = _tenant(session, owner)

        auditor_subject, _ = _platform_user(session, PlatformRoleEnum.AUDITOR)
        auditor = _principal(auditor_subject)
        overview = platform_finance_overview(auditor, session)
        assert overview.facts.billing_accounts is True
        with pytest.raises(HTTPException) as auditor_write:
            update_saas_billing_account(tenant.id, _account_input(0), auditor, session)
        assert auditor_write.value.status_code == 403
        assert "control.finance.manage_billing" in auditor_write.value.detail

        support_subject, _ = _platform_user(session, PlatformRoleEnum.SUPPORT)
        with pytest.raises(HTTPException) as support_read:
            platform_finance_overview(_principal(support_subject), session)
        assert support_read.value.status_code == 403
        assert "control.finance.read" in support_read.value.detail

        with pytest.raises(HTTPException) as aal1_write:
            update_saas_billing_account(
                tenant.id, _account_input(0), _principal(owner_subject, "aal1"), session,
            )
        assert aal1_write.value.status_code == 403
        assert "Multi-factor" in aal1_write.value.detail


def test_finance_authorization_tables_enforce_platform_only_rls():
    expected = {
        "platform_permission_definitions",
        "platform_role_permissions",
        "platform_permission_grants",
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
                'platform_permission_definitions',
                'platform_role_permissions',
                'platform_permission_grants'
              )
        """)).all()
    assert {row[0] for row in rows} == expected
    assert all(row[1] is True and row[2] is True for row in rows)
    assert all(row[3] == f"{row[0]}_platform_only" for row in rows)
    with Session(engine) as session:
        set_platform_db_context(session)
        defaults = session.exec(select(PlatformRolePermission)).all()
    by_role = {
        role: {item.permission_key for item in defaults if item.role == role}
        for role in PlatformRoleEnum
    }
    assert len(by_role[PlatformRoleEnum.PLATFORM_OWNER]) == 7
    assert len(by_role[PlatformRoleEnum.PLATFORM_ADMIN]) == 6
    assert "control.finance.refund" not in by_role[PlatformRoleEnum.PLATFORM_ADMIN]
    assert by_role[PlatformRoleEnum.AUDITOR] == {"control.finance.read"}
    assert not by_role[PlatformRoleEnum.SALES]
    assert not by_role[PlatformRoleEnum.SUPPORT]
    assert not by_role[PlatformRoleEnum.OPERATIONS]


def test_explicit_finance_denial_overrides_owner_role_default():
    with Session(engine) as session:
        subject, actor = _platform_user(session, PlatformRoleEnum.PLATFORM_OWNER)
        principal = _principal(subject)
        platform_finance_overview(principal, session)
        membership = session.exec(select(PlatformMembership).where(
            PlatformMembership.user_id == actor.id,
        )).one()
        session.add(PlatformPermissionGrant(
            platform_membership_id=membership.id,
            permission_key="control.finance.read",
            allowed=False,
            reason="Bloqueio financeiro individual de teste.",
            granted_by=actor.id,
        ))
        session.commit()

        with pytest.raises(HTTPException) as denied:
            platform_finance_overview(principal, session)
        assert denied.value.status_code == 403
        assert "control.finance.read" in denied.value.detail

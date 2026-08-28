import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import (
    PlatformTenantCreate,
    PlatformTenantInvite,
    PlatformTenantLifecycleUpdate,
    ServicePlanCreate,
    ServicePlanUpdate,
    TenantCapabilityUpdate,
    complete_owner_onboarding,
    complete_password_setup,
    create_service_plan,
    get_me,
    platform_overview,
    platform_finance_overview,
    platform_system_health,
    platform_tenant_detail,
    tenant_capability_catalog,
    invite_platform_tenant_user,
    provision_platform_tenant,
    update_platform_tenant_lifecycle,
    update_service_plan,
    update_tenant_capability,
)
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.models.identity import (
    AuthIdentity, MembershipStatusEnum, RoleEnum, TenantCustomerTypeEnum,
    SubscriptionStatusEnum, TenantStatusEnum, TenantSubscription, User,
)
from app.models.platform import PlatformMembership, PlatformRoleEnum
from app.models.reliability import AuditEvent


def _principal(subject: str, assurance_level: str = "aal2") -> AuthPrincipal:
    return AuthPrincipal(
        subject=subject,
        email=f"owner-{subject}@example.test",
        session_id=str(uuid.uuid4()),
        assurance_level=assurance_level,
        claims={"sub": subject, "aal": assurance_level},
        provider="email",
    )


def _owner(session: Session) -> tuple[str, User]:
    subject = str(uuid.uuid4())
    user = User(email=f"owner-{subject}@example.test", full_name="Owner Test")
    session.add(user)
    session.flush()
    session.add(AuthIdentity(
        user_id=user.id,
        provider="supabase",
        provider_subject=subject,
        provider_email=user.email,
        email_verified=True,
    ))
    session.add(PlatformMembership(
        user_id=user.id,
        role=PlatformRoleEnum.PLATFORM_OWNER,
    ))
    session.commit()
    session.refresh(user)
    return subject, user


def _valid_cnpj(base: str) -> str:
    numbers = [int(digit) for digit in base]
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        total = sum(number * weight for number, weight in zip(numbers[:size], weights))
        remainder = total % 11
        numbers.append(0 if remainder < 2 else 11 - remainder)
    return "".join(str(number) for number in numbers)


def test_owner_first_access_and_atomic_tenant_provisioning():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        subject, user = _owner(session)
        principal = _principal(subject)

        me_before = get_me(principal=principal, session=session)
        assert me_before["platform_role"] == PlatformRoleEnum.PLATFORM_OWNER
        assert me_before["password_setup_required"] is True
        assert me_before["mfa_required"] is False

        # First access and password recovery converge on this transition.
        # A retry must remain safe if the password was already updated.
        complete_password_setup(principal=principal, session=session)
        complete_password_setup(principal=principal, session=session)
        created = provision_platform_tenant(
            data=PlatformTenantCreate(
                name=f"Tenant Owner {suffix}",
                slug=f"tenant-owner-{suffix}",
                first_store_name="Unidade Principal",
                first_store_code="matriz",
            ),
            principal=principal,
            session=session,
        )
        assert created.tenant.slug == f"tenant-owner-{suffix}"
        assert created.first_store.tenant_id == created.tenant.id
        assert created.first_store.code == "MATRIZ"

        audit = session.exec(
            select(AuditEvent).where(
                AuditEvent.actor_id == user.id,
                AuditEvent.tenant_id == created.tenant.id,
                AuditEvent.action == "platform.tenant.provisioned",
            )
        ).first()
        assert audit is not None
        assert audit.platform_scope is True

        complete_owner_onboarding(principal=principal, session=session)
        me_after = get_me(principal=principal, session=session)
        assert me_after["password_setup_required"] is False
        assert me_after["onboarding_completed"] is True

        overview = platform_overview(principal=principal, session=session)
        assert any(item.id == created.tenant.id for item in overview.tenants)


def test_owner_mutations_require_aal2():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        subject, _ = _owner(session)
        principal = _principal(subject, assurance_level="aal1")
        with pytest.raises(HTTPException) as exc:
            provision_platform_tenant(
                data=PlatformTenantCreate(
                    name=f"Denied {suffix}",
                    slug=f"denied-{suffix}",
                    first_store_name="Principal",
                    first_store_code="MAIN",
                ),
                principal=principal,
                session=session,
            )
        assert exc.value.status_code == 403
        assert "Multi-factor" in exc.value.detail


def test_tenant_role_payload_never_accepts_platform_roles():
    invite = PlatformTenantInvite(
        email="manager@example.test",
        full_name="Tenant Manager",
        role=RoleEnum.MANAGER,
    )
    assert invite.role == RoleEnum.MANAGER
    with pytest.raises(ValidationError):
        PlatformTenantInvite(
            email="platform@example.test",
            full_name="Platform Owner",
            role="PLATFORM_OWNER",
        )


def test_owner_manages_capabilities_with_real_dependencies_and_audit():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        subject, owner = _owner(session)
        principal = _principal(subject)
        created = provision_platform_tenant(
            data=PlatformTenantCreate(
                name=f"Capabilities {suffix}", slug=f"capabilities-{suffix}",
                first_store_name="Matriz", first_store_code="MATRIZ",
            ), principal=principal, session=session,
        )
        catalog = tenant_capability_catalog(created.tenant.id, principal, session)
        assert len(catalog) >= 20
        assert not next(item for item in catalog if item.key == "high_speed_checkout").enabled

        updated = update_tenant_capability(
            tenant_id=created.tenant.id,
            capability_key="high_speed_checkout",
            data=TenantCapabilityUpdate(
                enabled=True,
                reason="Checkout contratado para o novo terminal.",
            ),
            principal=principal,
            session=session,
        )
        enabled = {item.key for item in updated if item.enabled}
        assert {"catalog", "barcode_scanning", "payments", "high_speed_checkout"} <= enabled

        with pytest.raises(HTTPException) as exc:
            update_tenant_capability(
                tenant_id=created.tenant.id,
                capability_key="catalog",
                data=TenantCapabilityUpdate(
                    enabled=False,
                    reason="Tentativa inválida de reduzir dependência.",
                ),
                principal=principal,
                session=session,
            )
        assert exc.value.status_code == 409
        audit = session.exec(select(AuditEvent).where(
            AuditEvent.actor_id == owner.id,
            AuditEvent.tenant_id == created.tenant.id,
            AuditEvent.action == "platform.tenant.capability_updated",
        )).first()
        assert audit is not None


def test_owner_health_contains_only_contractual_and_technical_totals(monkeypatch):
    suffix = uuid.uuid4().hex[:8]

    class HealthyAuth:
        status_code = 200

    monkeypatch.setattr("app.api.v1.endpoints.identity.httpx.get", lambda *_, **__: HealthyAuth())
    with Session(engine) as session:
        subject, _ = _owner(session)
        principal = _principal(subject)
        provision_platform_tenant(
            data=PlatformTenantCreate(
                name=f"Metrics {suffix}", slug=f"metrics-{suffix}",
                first_store_name="Matriz", first_store_code="MATRIZ",
            ), principal=principal, session=session,
        )
        health = platform_system_health(principal, session)
        components = {component.key: component for component in health.components}
        assert components["api"].status == "HEALTHY"
        assert components["database"].status == "HEALTHY"
        assert components["outbox"].details["failed"] >= 0
        totals = health.totals.model_dump()
        assert set(totals) == {"tenants", "pending_outbox", "failed_outbox"}
        assert totals["tenants"] >= 1


def test_owner_finance_projects_only_saas_contracts():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        subject, _ = _owner(session)
        principal = _principal(subject)
        created = provision_platform_tenant(
            data=PlatformTenantCreate(
                name=f"Finance SaaS {suffix}", slug=f"finance-saas-{suffix}",
                first_store_name="Matriz", first_store_code="MATRIZ",
            ), principal=principal, session=session,
        )
        subscription = session.get(TenantSubscription, created.tenant.id)
        assert subscription is not None
        subscription.status = SubscriptionStatusEnum.ACTIVE
        subscription.monthly_amount = Decimal("249.90")
        subscription.billing_status = "OVERDUE"
        session.add(subscription); session.commit()

        overview = platform_finance_overview(principal, session)
        row = next(item for item in overview.subscriptions if item.tenant_id == created.tenant.id)
        assert row.tenant_name == f"Finance SaaS {suffix}"
        assert row.monthly_amount == Decimal("249.90")
        assert row.billing_status == "OVERDUE"
        assert overview.contracted_mrr >= Decimal("249.90")
        assert overview.overdue_subscriptions >= 1


def test_owner_can_open_tenant_and_invite_first_user(monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    invite_subject = str(uuid.uuid4())
    with Session(engine) as session:
        owner_subject, _ = _owner(session)
        principal = _principal(owner_subject)
        complete_password_setup(principal=principal, session=session)
        created = provision_platform_tenant(
            data=PlatformTenantCreate(
                name=f"Invite Tenant {suffix}", slug=f"invite-{suffix}",
                first_store_name="Unidade Centro", first_store_code="CENTRO",
            ), principal=principal, session=session,
        )
        monkeypatch.setattr(
            "app.services.supabase_admin.invite_user",
            lambda **_: {"id": invite_subject, "email": f"user-{suffix}@example.test"},
        )
        with pytest.raises(HTTPException) as operational_role:
            invite_platform_tenant_user(
                tenant_id=created.tenant.id,
                data=PlatformTenantInvite(
                    email=f"manager-{suffix}@example.test",
                    full_name="Tenant Manager",
                    role=RoleEnum.MANAGER,
                ),
                principal=principal,
                session=session,
            )
        assert operational_role.value.status_code == 403
        assert "administrador contratual" in operational_role.value.detail

        result = invite_platform_tenant_user(
            tenant_id=created.tenant.id,
            data=PlatformTenantInvite(
                email=f"user-{suffix}@example.test", full_name="Tenant User",
            ), principal=principal, session=session,
        )
        assert result.delivery_status == "ENVIADO"
        assert result.access.status == MembershipStatusEnum.INVITED
        assert result.access.role == RoleEnum.TENANT_OWNER

        detail = platform_tenant_detail(
            tenant_id=created.tenant.id, principal=principal, session=session,
        )
        assert len(detail.stores) == 1
        assert any(access.email == f"user-{suffix}@example.test" for access in detail.accesses)

        invited_principal = AuthPrincipal(
            subject=invite_subject, email=f"user-{suffix}@example.test",
            session_id=str(uuid.uuid4()), assurance_level="aal1",
            claims={"sub": invite_subject, "aal": "aal1"}, provider="email",
        )
        complete_password_setup(principal=invited_principal, session=session)
        invited_me = get_me(principal=invited_principal, session=session)
        assert invited_me["memberships"][0].status == MembershipStatusEnum.ACTIVE


def test_owner_customer_master_is_persisted_and_audited():
    suffix = uuid.uuid4().hex[:8]
    cnpj = _valid_cnpj(f"{int(suffix, 16) % 100_000_000:08d}0001")
    with Session(engine) as session:
        owner_subject, owner = _owner(session)
        principal = _principal(owner_subject)
        plan = create_service_plan(
            data=ServicePlanCreate(
                code=f"PILOT_{suffix.upper()}",
                name=f"Piloto {suffix}",
                store_limit=3,
                user_limit=12,
                terminal_limit=4,
            ),
            principal=principal,
            session=session,
        )
        created = provision_platform_tenant(
            data=PlatformTenantCreate(
                name=f"Comércio {suffix}",
                legal_name=f"Comércio {suffix} LTDA",
                slug=f"comercio-{suffix}",
                customer_type=TenantCustomerTypeEnum.PILOT,
                tax_id=cnpj,
                state_registration="ISENTO",
                industry="Varejo",
                company_email=f"contato-{suffix}@example.test",
                company_phone="+5521999999999",
                contact_name="Responsável Contratual",
                contact_job_title="Diretoria",
                contact_email=f"responsavel-{suffix}@example.test",
                contact_phone="+5521988888888",
                first_store_name="Matriz Centro",
                first_store_code="MATRIZ",
                postal_code="20040020",
                street="Rua do Mercado",
                street_number="100",
                district="Centro",
                city="Rio de Janeiro",
                state="RJ",
                plan_id=plan.id,
            ),
            principal=principal,
            session=session,
        )
        detail = platform_tenant_detail(
            tenant_id=created.tenant.id,
            principal=principal,
            session=session,
        )
        assert detail.tenant.profile_complete is True
        assert detail.tenant.customer_type == TenantCustomerTypeEnum.PILOT
        assert detail.profile is not None and detail.profile.tax_id == cnpj
        assert detail.contacts[0].is_primary is True
        assert detail.stores[0].is_headquarters is True
        assert detail.plan is not None and detail.plan.id == plan.id

        paused = update_platform_tenant_lifecycle(
            tenant_id=created.tenant.id,
            data=PlatformTenantLifecycleUpdate(
                status=TenantStatusEnum.PAUSED,
                reason="Pausa solicitada pelo cliente durante o piloto.",
            ),
            principal=principal,
            session=session,
        )
        assert paused.status == TenantStatusEnum.PAUSED
        audit = session.exec(select(AuditEvent).where(
            AuditEvent.actor_id == owner.id,
            AuditEvent.tenant_id == created.tenant.id,
            AuditEvent.action == "platform.tenant.lifecycle_changed",
        )).first()
        assert audit is not None
        assert "Pausa solicitada" in audit.payload


def test_owner_updates_the_commercial_plan_catalog_with_audit():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        owner_subject, _ = _owner(session)
        principal = _principal(owner_subject)
        plan = create_service_plan(
            data=ServicePlanCreate(code=f"START_{suffix.upper()}", name="Inicial"),
            principal=principal,
            session=session,
        )

        updated = update_service_plan(
            plan_id=plan.id,
            data=ServicePlanUpdate(
                code=f"PILOT_{suffix.upper()}", name="Plano Piloto",
                description="Plano comercial para validação assistida.",
                store_limit=2, user_limit=8, terminal_limit=4,
                storage_limit_mb=1024, monthly_price=Decimal("149.90"),
                is_active=False,
            ),
            principal=principal,
            session=session,
        )

        assert updated.name == "Plano Piloto"
        assert updated.monthly_price == Decimal("149.90")
        assert updated.store_limit == 2
        assert updated.is_active is False
        audit = session.exec(select(AuditEvent).where(
            AuditEvent.action == "platform.plan.updated",
            AuditEvent.target == f"service_plan:{plan.id}",
        )).first()
        assert audit is not None

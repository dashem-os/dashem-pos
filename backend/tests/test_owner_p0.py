import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import (
    OwnerBillingCreate, OwnerInitialAdminCreate, OwnerQuotaCreate,
    OwnerTenantContractUpdate, OwnerTenantProvisionCreate, PlatformTenantCreate,
    PlatformTenantAdministratorReplace, SaasBillingAccountUpdate,
    ServicePlanCreate, create_service_plan,
    platform_tenant_detail, provision_owner_tenant, tenant_capability_catalog,
    update_owner_tenant_contract, update_saas_billing_account, provision_platform_tenant,
    replace_platform_tenant_administrator, _normalize_tax_id,
)
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.models.identity import (
    AuthIdentity, Membership, MembershipStatusEnum, RoleEnum,
    SubscriptionStatusEnum, TenantPhaseEnum, TenantTypeEnum, User,
)
from app.models.platform import PlatformMembership, PlatformRoleEnum, TenantContract, TenantProfileAssignment
from app.modules.capabilities.niches import BusinessNiche, NICHE_CONTRACTS


def _owner(session: Session) -> tuple[AuthPrincipal, User]:
    subject = str(uuid.uuid4())
    user = User(email=f"owner-p0-{subject}@example.test", full_name="Owner P0")
    session.add(user); session.flush()
    session.add(AuthIdentity(user_id=user.id, provider="supabase", provider_subject=subject, provider_email=user.email, email_verified=True))
    session.add(PlatformMembership(user_id=user.id, role=PlatformRoleEnum.PLATFORM_OWNER))
    session.commit(); session.refresh(user)
    return AuthPrincipal(subject=subject, email=user.email, session_id=str(uuid.uuid4()), assurance_level="aal2", claims={"sub": subject, "aal": "aal2"}, provider="email"), user


def test_owner_billing_contract_accepts_one_persisted_day_between_1_and_28():
    billing = OwnerBillingCreate(
        contact_name="Financeiro",
        email="financeiro@example.test",
        monthly_amount=119,
        billing_day=28,
    )
    assert billing.billing_day == 28
    with pytest.raises(ValueError):
        OwnerBillingCreate(
            contact_name="Financeiro",
            email="financeiro@example.test",
            monthly_amount=119,
        )
    for invalid_day in (0, 29):
        with pytest.raises(ValueError):
            OwnerBillingCreate(
                contact_name="Financeiro",
                email="financeiro@example.test",
                monthly_amount=119,
                billing_day=invalid_day,
            )


def _valid_cnpj(base: str) -> str:
    numbers = [int(digit) for digit in base]
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        remainder = sum(number * weight for number, weight in zip(numbers[:size], weights)) % 11
        numbers.append(0 if remainder < 2 else 11 - remainder)
    return "".join(str(number) for number in numbers)


def test_owner_accepts_valid_cpf_and_cnpj_and_rejects_invalid_document():
    assert _normalize_tax_id("529.982.247-25") == "52998224725"
    assert _normalize_tax_id("04.252.011/0001-10") == "04252011000110"
    with pytest.raises(Exception) as error:
        _normalize_tax_id("111.111.111-11")
    assert "CPF ou CNPJ válido" in str(error.value)


@pytest.mark.parametrize(
    ("niche", "addons", "must_have", "must_not_have"),
    [
        (BusinessNiche.FOOD_SERVICE, ["table_service", "kitchen_routing"], {"delivery_orders", "table_service", "kitchen_routing"}, set()),
        (BusinessNiche.RETAIL, ["receivables"], {"delivery_orders", "inventory", "receivables"}, {"table_service", "kitchen_routing"}),
        (BusinessNiche.BEAUTY_RESELLER, ["barcode_scanning"], {"delivery_orders", "inventory", "barcode_scanning"}, {"table_service", "kitchen_routing"}),
    ],
)
def test_owner_p0_provisions_complete_tenant_by_niche(monkeypatch, niche, addons, must_have, must_not_have):
    suffix = uuid.uuid4().hex[:8]
    monkeypatch.setattr("app.api.v1.endpoints.identity.supabase_admin.invite_user", lambda **_: {"id": str(uuid.uuid4())})
    with Session(engine) as session:
        principal, _ = _owner(session)
        plan = create_service_plan(
            ServicePlanCreate(
                code=f"P0_{suffix.upper()}", name=f"Owner P0 {suffix}",
                store_limit=3, user_limit=10, terminal_limit=5, storage_limit_mb=4096,
            ), principal, session,
        )
        provisioned = provision_owner_tenant(
            OwnerTenantProvisionCreate(
                name=f"Cliente {suffix}", legal_name=f"Cliente {suffix} LTDA", slug=f"owner-p0-{suffix}",
                tenant_type=TenantTypeEnum.CUSTOMER, lifecycle_phase=TenantPhaseEnum.PILOT,
                tax_id=_valid_cnpj(f"{int(suffix, 16) % 100_000_000:08d}0001"),
                company_phone="11999999999", company_email=f"empresa-{suffix}@example.test",
                contact_name="Responsável Contratual", contact_email=f"contrato-{suffix}@example.test",
                first_store_name="Matriz", first_store_code="MATRIZ", postal_code="01310100",
                street="Avenida Paulista", street_number="1000", district="Bela Vista", city="São Paulo", state="SP",
                niches=[niche], plan_id=plan.id,
                capability_keys=list(NICHE_CONTRACTS[niche].required) + addons,
                quotas=OwnerQuotaCreate(users=8, devices=4, units=2, storage_mb=2048),
                billing=OwnerBillingCreate(contact_name="Financeiro", email=f"financeiro-{suffix}@example.test", billing_day=10),
                initial_admin=OwnerInitialAdminCreate(full_name="Administrador Inicial", email=f"admin-{suffix}@example.test"),
            ), principal, session,
        )

        assert provisioned.niche == niche
        assert provisioned.delivery_status == "ENVIADO"
        assert provisioned.contract is not None and provisioned.contract.status == "ACTIVE"
        assert provisioned.contract.limits["users"] == 8
        assert provisioned.contract.limits["storage_mb"] == 2048
        assert provisioned.contract.limits["billing"]["email"] == f"financeiro-{suffix}@example.test"
        assert must_have <= set(provisioned.contract.capability_keys)
        assert set(provisioned.contract.capability_keys).isdisjoint(must_not_have)

        assignments = session.exec(select(TenantProfileAssignment).where(TenantProfileAssignment.tenant_id == provisioned.tenant.id)).all()
        assert len(assignments) == 1 and assignments[0].status == "ACTIVE"
        contract_rows = session.exec(select(TenantContract).where(TenantContract.tenant_id == provisioned.tenant.id)).all()
        assert len(contract_rows) == 1
        memberships = session.exec(select(Membership).where(Membership.tenant_id == provisioned.tenant.id)).all()
        assert len(memberships) == 1 and memberships[0].role == RoleEnum.TENANT_OWNER

        # Operational identities may exist, but the Control projection must not
        # expose them to the SaaS Owner.
        operator = User(email=f"operator-{suffix}@example.test", full_name="Operador do Tenant")
        session.add(operator); session.flush()
        session.add(Membership(
            user_id=operator.id, tenant_id=provisioned.tenant.id,
            store_id=provisioned.first_store.id, role=RoleEnum.OPERATOR,
            status=MembershipStatusEnum.ACTIVE,
        ))
        session.commit()

        catalog = tenant_capability_catalog(provisioned.tenant.id, principal, session)
        assert {item.key for item in catalog} >= NICHE_CONTRACTS[niche].allowed
        assert {item.key for item in catalog if item.required} == set(NICHE_CONTRACTS[niche].required)
        detail = platform_tenant_detail(provisioned.tenant.id, principal, session)
        assert detail.niche == niche and len(detail.accesses) == 1
        assert detail.accesses[0].role == RoleEnum.TENANT_OWNER


def test_owner_can_combine_niches_and_version_existing_contract(monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    monkeypatch.setattr("app.api.v1.endpoints.identity.supabase_admin.invite_user", lambda **_: {"id": str(uuid.uuid4())})
    with Session(engine) as session:
        principal, _ = _owner(session)
        plan = create_service_plan(ServicePlanCreate(
            code=f"HYBRID_{suffix.upper()}", name=f"Híbrido {suffix}", monthly_price=149,
            store_limit=4, user_limit=12, terminal_limit=8, storage_limit_mb=8192,
        ), principal, session)
        provisioned = provision_owner_tenant(OwnerTenantProvisionCreate(
            name=f"Confeitaria e Beleza {suffix}", legal_name="Empreendedora Híbrida",
            slug=f"hybrid-{suffix}", tenant_type=TenantTypeEnum.CUSTOMER,
            lifecycle_phase=TenantPhaseEnum.PILOT,
            tax_id=_valid_cnpj(f"{int(suffix, 16) % 100_000_000:08d}0001"),
            company_phone="11999999999", contact_name="Responsável",
            contact_email=f"responsavel-{suffix}@example.test", first_store_name="Matriz",
            first_store_code="MATRIZ", postal_code="01310100", street="Avenida Paulista",
            street_number="1000", district="Bela Vista", city="São Paulo", state="SP",
            plan_id=plan.id, niches=[BusinessNiche.FOOD_SERVICE, BusinessNiche.BEAUTY_RESELLER],
            capability_keys=[],
            quotas=OwnerQuotaCreate(users=5, devices=3, units=1, storage_mb=2048),
            billing=OwnerBillingCreate(contact_name="Financeiro", email=f"financeiro-{suffix}@example.test", monthly_amount=149, billing_day=1),
            initial_admin=OwnerInitialAdminCreate(full_name="Admin", email=f"admin-{suffix}@example.test"),
        ), principal, session)
        assert provisioned.niches == [BusinessNiche.FOOD_SERVICE, BusinessNiche.BEAUTY_RESELLER]
        assert provisioned.contract.capability_keys == []

        detail = update_owner_tenant_contract(provisioned.tenant.id, OwnerTenantContractUpdate(
            plan_id=plan.id, niches=[BusinessNiche.RETAIL, BusinessNiche.BEAUTY_RESELLER],
            capability_keys=["catalog", "inventory", "payments", "receivables"],
            quotas=OwnerQuotaCreate(users=8, devices=4, units=2, storage_mb=4096),
            billing=OwnerBillingCreate(contact_name="Novo Financeiro", email=f"cobranca-{suffix}@example.test", monthly_amount=229, billing_day=12),
            subscription_status=SubscriptionStatusEnum.ACTIVE,
            expected_contract_version=1,
            expected_billing_account_version=1,
            reason="Ampliação da operação híbrida.",
        ), principal, session)
        assert detail.contract.version == 2
        assert detail.niches == [BusinessNiche.RETAIL, BusinessNiche.BEAUTY_RESELLER]
        assert detail.subscription.monthly_amount == 229
        assert detail.subscription.billing_day == 12
        assert detail.billing_account.contact_name == "Novo Financeiro"
        assert detail.billing_account.contact_email == f"cobranca-{suffix}@example.test"
        assert detail.billing_account.version == 2
        assert {item.key for item in detail.capabilities if item.enabled} >= {"catalog", "inventory", "payments", "receivables"}

        with pytest.raises(HTTPException) as stale:
            update_owner_tenant_contract(provisioned.tenant.id, OwnerTenantContractUpdate(
                plan_id=plan.id, niches=[BusinessNiche.RETAIL],
                capability_keys=["catalog", "inventory", "payments"],
                quotas=OwnerQuotaCreate(users=8, devices=4, units=2, storage_mb=4096),
                billing=OwnerBillingCreate(
                    contact_name="Concorrente", email=f"concorrente-{suffix}@example.test",
                    monthly_amount=229, billing_day=1,
                ),
                subscription_status=SubscriptionStatusEnum.ACTIVE,
                expected_contract_version=1,
                expected_billing_account_version=1,
                reason="Tentativa com versão contratual obsoleta.",
            ), principal, session)
        assert stale.value.status_code == 409

        billing = update_saas_billing_account(
            provisioned.tenant.id,
            SaasBillingAccountUpdate(
                legal_name="Empreendedora Híbrida",
                tax_id="11222333000181",
                contact_name="Financeiro dedicado",
                contact_email=f"dedicado-{suffix}@example.test",
                expected_version=2,
                reason="Atualização independente da conta de cobrança.",
            ),
            principal,
            session,
        )
        assert billing.version == 3
        with pytest.raises(HTTPException) as stale_billing:
            update_owner_tenant_contract(provisioned.tenant.id, OwnerTenantContractUpdate(
                plan_id=plan.id, niches=[BusinessNiche.RETAIL],
                capability_keys=["catalog", "inventory", "payments"],
                quotas=OwnerQuotaCreate(users=8, devices=4, units=2, storage_mb=4096),
                billing=OwnerBillingCreate(
                    contact_name="Sobrescrita", email=f"sobrescrita-{suffix}@example.test",
                    monthly_amount=229, billing_day=1,
                ),
                subscription_status=SubscriptionStatusEnum.ACTIVE,
                expected_contract_version=2,
                expected_billing_account_version=2,
                reason="Tentativa com versão da conta de cobrança obsoleta.",
            ), principal, session)
        assert stale_billing.value.status_code == 409
        after_conflict = platform_tenant_detail(provisioned.tenant.id, principal, session)
        assert after_conflict.contract.version == 2
        assert after_conflict.billing_account.version == 3
        assert after_conflict.billing_account.contact_name == "Financeiro dedicado"


def test_owner_can_regularize_legacy_tenant_and_recognizes_existing_admin():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        principal, _ = _owner(session)
        plan = create_service_plan(ServicePlanCreate(
            code=f"LEGACY_{suffix.upper()}", name=f"Legado {suffix}", monthly_price=99,
            store_limit=2, user_limit=5, terminal_limit=3, storage_limit_mb=2048,
        ), principal, session)
        legacy = provision_platform_tenant(PlatformTenantCreate(
            name=f"Legado {suffix}", slug=f"legacy-{suffix}", first_store_name="Matriz",
            first_store_code="MATRIZ",
        ), principal, session)
        existing_admin = User(email=f"legacy-admin-{suffix}@example.test", full_name="Administrador Existente")
        session.add(existing_admin); session.flush()
        session.add(Membership(
            user_id=existing_admin.id, tenant_id=legacy.tenant.id,
            role=RoleEnum.ADMIN, status=MembershipStatusEnum.ACTIVE,
        ))
        session.commit()

        detail = update_owner_tenant_contract(legacy.tenant.id, OwnerTenantContractUpdate(
            plan_id=plan.id, niches=[BusinessNiche.RETAIL],
            capability_keys=["catalog", "inventory", "payments"],
            quotas=OwnerQuotaCreate(users=4, devices=2, units=1, storage_mb=1024),
            billing=OwnerBillingCreate(contact_name="Financeiro", email=f"financeiro-{suffix}@example.test", monthly_amount=119, billing_day=1),
            subscription_status=SubscriptionStatusEnum.ACTIVE,
            expected_contract_version=0,
            expected_billing_account_version=0,
            reason="Regularização do tenant anterior ao contrato Owner.",
        ), principal, session)
        assert detail.contract.version == 1
        assert detail.niches == [BusinessNiche.RETAIL]
        assert len(detail.accesses) == 1
        assert detail.accesses[0].email == existing_admin.email
        assert detail.accesses[0].role == RoleEnum.ADMIN


def test_owner_can_replace_contract_administrator_with_audited_access(monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    monkeypatch.setattr("app.api.v1.endpoints.identity.supabase_admin.invite_user", lambda **_: {"id": str(uuid.uuid4())})
    with Session(engine) as session:
        principal, _ = _owner(session)
        tenant = provision_platform_tenant(PlatformTenantCreate(
            name=f"Troca Admin {suffix}", slug=f"replace-admin-{suffix}",
            first_store_name="Matriz", first_store_code="MATRIZ",
        ), principal, session)
        previous_user = User(email=f"old-admin-{suffix}@example.test", full_name="Admin Anterior")
        session.add(previous_user); session.flush()
        previous = Membership(
            user_id=previous_user.id, tenant_id=tenant.tenant.id,
            role=RoleEnum.ADMIN, status=MembershipStatusEnum.ACTIVE,
        )
        session.add(previous); session.commit(); session.refresh(previous)

        result = replace_platform_tenant_administrator(
            tenant.tenant.id,
            PlatformTenantAdministratorReplace(
                current_membership_id=previous.id,
                full_name="Nova Administradora",
                email=f"new-admin-{suffix}@example.test",
                reason="Substituição solicitada formalmente pelo cliente.",
            ),
            principal,
            session,
        )

        session.refresh(previous)
        assert previous.status == MembershipStatusEnum.SUSPENDED
        assert result.access.role == RoleEnum.TENANT_OWNER
        assert result.access.status == MembershipStatusEnum.INVITED
        assert result.access.email == f"new-admin-{suffix}@example.test"
        assert result.delivery_status == "ENVIADO"

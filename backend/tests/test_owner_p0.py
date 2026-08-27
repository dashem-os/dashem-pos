import uuid

import pytest
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import (
    OwnerBillingCreate, OwnerInitialAdminCreate, OwnerQuotaCreate,
    OwnerTenantProvisionCreate, ServicePlanCreate, create_service_plan,
    platform_tenant_detail, provision_owner_tenant, tenant_capability_catalog,
)
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.models.identity import AuthIdentity, Membership, MembershipStatusEnum, RoleEnum, TenantCustomerTypeEnum, User
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


def _valid_cnpj(base: str) -> str:
    numbers = [int(digit) for digit in base]
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        remainder = sum(number * weight for number, weight in zip(numbers[:size], weights)) % 11
        numbers.append(0 if remainder < 2 else 11 - remainder)
    return "".join(str(number) for number in numbers)


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
                customer_type=TenantCustomerTypeEnum.PILOT, tax_id=_valid_cnpj(f"{int(suffix, 16) % 100_000_000:08d}0001"),
                company_phone="11999999999", company_email=f"empresa-{suffix}@example.test",
                contact_name="Responsável Contratual", contact_email=f"contrato-{suffix}@example.test",
                first_store_name="Matriz", first_store_code="MATRIZ", postal_code="01310100",
                street="Avenida Paulista", street_number="1000", district="Bela Vista", city="São Paulo", state="SP",
                niche=niche, plan_id=plan.id, addon_keys=addons,
                quotas=OwnerQuotaCreate(users=8, devices=4, units=2, storage_mb=2048),
                billing=OwnerBillingCreate(contact_name="Financeiro", email=f"financeiro-{suffix}@example.test"),
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
        assert {item.key for item in catalog} == NICHE_CONTRACTS[niche].allowed
        assert {item.key for item in catalog if item.required} == set(NICHE_CONTRACTS[niche].required)
        detail = platform_tenant_detail(provisioned.tenant.id, principal, session)
        assert detail.niche == niche and len(detail.accesses) == 1
        assert detail.accesses[0].role == RoleEnum.TENANT_OWNER

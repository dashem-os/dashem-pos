import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.api.v1.endpoints.team import (
    OperationalMemberCreate, TeamActivationIssue, TeamInvite,
    create_operational_member, invite_team_member, issue_operational_activation, list_team,
)
from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.identity import (
    Employee,
    Membership,
    MembershipStatusEnum,
    OperationalCredential,
    RoleEnum,
    ServicePlan,
    Store,
    SubscriptionStatusEnum,
    Tenant,
    TenantStatusEnum,
    TenantSubscription,
    User,
)


def test_tenant_admin_creates_pin_operator_and_enforces_contract_limit(monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"Team API {suffix}", slug=f"team-api-{suffix}", status=TenantStatusEnum.ACTIVE)
        plan = ServicePlan(code=f"TEAM-{suffix}", name="Equipe limitada", user_limit=2)
        admin = User(email=f"admin-team-{suffix}@example.test", full_name="Tenant Admin")
        session.add(tenant); session.add(plan); session.add(admin); session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"M-{suffix}")
        session.add(store); session.flush()
        session.add(TenantSubscription(tenant_id=tenant.id, plan_id=plan.id, status=SubscriptionStatusEnum.ACTIVE))
        session.add(Membership(
            user_id=admin.id, tenant_id=tenant.id, role=RoleEnum.ADMIN,
            status=MembershipStatusEnum.ACTIVE,
        ))
        tenant_id, store_id, admin_id = tenant.id, store.id, admin.id
        session.commit()

    monkeypatch.setattr(
        "app.services.supabase_admin.invite_user",
        lambda **_: {"id": str(uuid.uuid4()), "email": f"cashier-{suffix}@example.test"},
    )
    context = TenantContext(
        tenant_id=tenant_id,
        user_id=admin_id,
        role=RoleEnum.ADMIN,
        permissions=("team.manage", "team.read"),
    )
    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, user_id=admin_id)
        employee = Employee(
            tenant_id=tenant_id, home_store_id=store_id,
            employee_number=f"CX{suffix[:4]}", full_name="Atendente do salão",
        )
        session.add(employee); session.commit(); session.refresh(employee)
        invited = create_operational_member(
            data=OperationalMemberCreate(
                employee_id=employee.id,
                role=RoleEnum.CASHIER,
                store_id=store_id,
                employee_code=f"CX{suffix[:4]}",
            ),
            context=context,
            session=session,
        )
        assert invited.role == RoleEnum.CASHIER
        assert invited.store_id == store_id
        assert invited.status == MembershipStatusEnum.ACTIVE
        assert invited.access_mode == "PIN"
        assert invited.credential_state == "PENDING_ACTIVATION"
        assert invited.activation_code is not None and len(invited.activation_code) == 8
        assert invited.email is None
        credential = session.exec(select(OperationalCredential).where(
            OperationalCredential.membership_id == invited.membership_id,
        )).one()
        first_activation_hash = credential.activation_secret_hash
        replacement = issue_operational_activation(
            invited.membership_id,
            TeamActivationIssue(reason="Código inicial não foi entregue ao colaborador"),
            context,
            session,
        )
        assert replacement.credential_state == "PENDING_ACTIVATION"
        assert replacement.activation_code is not None and len(replacement.activation_code) == 8
        session.refresh(credential)
        assert credential.activation_secret_hash != first_activation_hash
        assert len(list_team(context=context, session=session)) == 2

        with pytest.raises(HTTPException) as limit:
            invite_team_member(
                data=TeamInvite(
                    email=f"manager-{suffix}@example.test",
                    full_name="Second manager",
                    role=RoleEnum.MANAGER,
                ),
                context=context,
                session=session,
            )
        assert limit.value.status_code == 409
        assert "Limite contratual" in limit.value.detail

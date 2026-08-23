import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.api.v1.endpoints.team import TeamInvite, invite_team_member, list_team
from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.identity import (
    Membership,
    MembershipStatusEnum,
    RoleEnum,
    ServicePlan,
    Store,
    SubscriptionStatusEnum,
    Tenant,
    TenantStatusEnum,
    TenantSubscription,
    User,
)


def test_tenant_admin_invites_team_with_store_scope_and_contract_limit(monkeypatch):
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
        invited = invite_team_member(
            data=TeamInvite(
                email=f"cashier-{suffix}@example.test",
                full_name="Cashier",
                role=RoleEnum.CASHIER,
                store_id=store_id,
            ),
            context=context,
            session=session,
        )
        assert invited.role == RoleEnum.CASHIER
        assert invited.store_id == store_id
        assert invited.status == MembershipStatusEnum.INVITED
        assert len(list_team(context=context, session=session)) == 2

        with pytest.raises(HTTPException) as limit:
            invite_team_member(
                data=TeamInvite(
                    email=f"second-{suffix}@example.test",
                    full_name="Second",
                    role=RoleEnum.OPERATOR,
                    store_id=store_id,
                ),
                context=context,
                session=session,
            )
        assert limit.value.status_code == 409
        assert "Limite contratual" in limit.value.detail

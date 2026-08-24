import uuid

from fastapi import HTTPException
import pytest
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import get_me
from app.api.v1.endpoints.team import OperationalMemberCreate, create_operational_member
from app.core.context import TenantContext
from app.core.database import engine
from app.core.security import AuthPrincipal, decode_access_token
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.identity import Employee, Membership, MembershipStatusEnum, OperationalCredential, RoleEnum, Store, Tenant, TenantStatusEnum, User
from app.models.payment import Register
from app.services import operational_access_service


def test_operational_member_has_no_fake_email_and_activates_store_scoped_token():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"PIN {suffix}", slug=f"pin-{suffix}", status=TenantStatusEnum.ACTIVE)
        admin = User(email=f"pin-admin-{suffix}@example.test", full_name="Admin")
        session.add(tenant); session.add(admin); session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"PIN-{suffix}")
        session.add(store); session.flush()
        register = Register(tenant_id=tenant.id, store_id=store.id, name="Caixa", code=f"CX-{suffix}")
        session.add(register)
        session.add(Membership(user_id=admin.id, tenant_id=tenant.id, role=RoleEnum.ADMIN, status=MembershipStatusEnum.ACTIVE))
        tenant_id, store_id, register_id, admin_id = tenant.id, store.id, register.id, admin.id
        session.commit()

    context = TenantContext(tenant_id=tenant_id, store_id=store_id, user_id=admin_id, role=RoleEnum.ADMIN)
    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_id, admin_id)
        employee = Employee(
            tenant_id=tenant_id, home_store_id=store_id, employee_number="ATD-01",
            full_name="Ana Atendimento",
        )
        session.add(employee); session.commit(); session.refresh(employee)
        member = create_operational_member(
            OperationalMemberCreate(
                employee_id=employee.id, role=RoleEnum.OPERATOR, store_id=store_id,
                employee_code="atd-01", pin="4826",
            ),
            context,
            session,
        )
        credential = session.exec(select(OperationalCredential).where(OperationalCredential.membership_id == member.membership_id)).one()
        user = session.get(User, member.user_id)
        assert user is not None and user.email is None
        assert credential.employee_code == "ATD-01"
        assert credential.pin_hash != "4826"

        with pytest.raises(HTTPException) as wrong:
            operational_access_service.activate(
                session, context, employee_code="ATD-01", pin="6782", store_id=store_id, register_id=register_id,
            )
        assert wrong.value.status_code == 401

        activated = operational_access_service.activate(
            session, context, employee_code="atd-01", pin="4826", store_id=store_id, register_id=register_id,
        )
        claims = decode_access_token(activated["access_token"])
        assert claims["tenant_id"] == str(tenant_id)
        assert claims["store_id"] == str(store_id)
        assert claims["register_id"] == str(register_id)
        assert claims["role"] == "OPERATOR"
        assert claims["app_metadata"]["provider"] == "operational"
        principal = AuthPrincipal(
            subject=claims["sub"], email=None, session_id=claims["session_id"],
            assurance_level="pin", claims=claims, provider="operational",
            legacy_user_id=uuid.UUID(claims["sub"]),
        )
        me = get_me(principal=principal, session=session)
        assert len(me["memberships"]) == 1
        assert me["memberships"][0].id == member.membership_id


def test_pin_policy_rejects_repeated_and_sequential_values():
    for invalid in ("1111", "1234", "9876", "12AB"):
        with pytest.raises(HTTPException):
            operational_access_service.validate_pin(invalid)

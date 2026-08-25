import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException
import pytest
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import get_me
from app.api.v1.endpoints.team import OperationalMemberCreate, create_operational_member
from app.core.context import TenantContext, authorize_tenant_context
from app.core.database import engine
from app.core.config import settings
from app.core.security import AuthPrincipal, decode_access_token, get_current_principal
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.identity import Employee, Membership, MembershipStatusEnum, OperationalCredential, OperationalSession, OperationalSessionStatusEnum, RoleEnum, Store, Tenant, TenantStatusEnum, User
from app.models.device import OperationalDevice, OperationalDeviceStatusEnum, OperationalDeviceTypeEnum
from app.models.payment import Register
from app.services import device_service, operational_access_service


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
        session.flush()
        device = OperationalDevice(
            tenant_id=tenant.id, store_id=store.id, code=f"POS-{suffix}", name="Caixa",
            device_type=OperationalDeviceTypeEnum.POS, register_id=register.id,
        )
        session.add(device)
        session.add(Membership(user_id=admin.id, tenant_id=tenant.id, role=RoleEnum.ADMIN, status=MembershipStatusEnum.ACTIVE))
        tenant_id, store_id, register_id, device_id, admin_id = tenant.id, store.id, register.id, device.id, admin.id
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
        assert wrong.value.status_code == 403

        authorization = operational_access_service.authorize_terminal(session, context, device_id)
        activated = operational_access_service.activate_from_terminal(
            session, terminal_token=authorization["terminal_token"], employee_code="atd-01", pin="4826",
        )
        claims = decode_access_token(activated["access_token"])
        assert claims["tenant_id"] == str(tenant_id)
        assert claims["store_id"] == str(store_id)
        assert claims["register_id"] == str(register_id)
        assert claims["role"] == "OPERATOR"
        assert claims["device_id"] == str(device_id)
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


def test_public_pin_exchange_requires_an_active_manager_authorized_terminal(monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"Terminal {suffix}", slug=f"terminal-{suffix}", status=TenantStatusEnum.ACTIVE)
        admin = User(email=f"terminal-admin-{suffix}@example.test", full_name="Gestora")
        operator = User(full_name="Operadora")
        session.add(tenant); session.add(admin); session.add(operator); session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"TRM-{suffix}")
        session.add(store); session.flush()
        register = Register(tenant_id=tenant.id, store_id=store.id, name="Caixa 01", code=f"CX-{suffix}")
        admin_membership = Membership(user_id=admin.id, tenant_id=tenant.id, role=RoleEnum.ADMIN, status=MembershipStatusEnum.ACTIVE)
        operator_membership = Membership(user_id=operator.id, tenant_id=tenant.id, store_id=store.id, role=RoleEnum.OPERATOR, status=MembershipStatusEnum.ACTIVE)
        employee = Employee(tenant_id=tenant.id, user_id=operator.id, home_store_id=store.id, employee_number="ATD-17", full_name="Operadora")
        session.add(register); session.add(admin_membership); session.add(operator_membership); session.add(employee); session.flush()
        salt, pin_hash, iterations = operational_access_service.new_pin_secret("4826")
        session.add(OperationalCredential(
            tenant_id=tenant.id, store_id=store.id, user_id=operator.id,
            membership_id=operator_membership.id, employee_id=employee.id,
            employee_code="ATD-17", pin_salt=salt, pin_hash=pin_hash, pin_iterations=iterations,
        ))
        device = OperationalDevice(
            tenant_id=tenant.id, store_id=store.id, code="POS-01", name="Caixa principal",
            device_type=OperationalDeviceTypeEnum.POS, register_id=register.id,
        )
        session.add(device); session.commit()
        tenant_id, store_id, admin_id, device_id = tenant.id, store.id, admin.id, device.id

    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_id, admin_id)
        authorization = operational_access_service.authorize_terminal(
            session,
            TenantContext(tenant_id=tenant_id, store_id=store_id, user_id=admin_id, role=RoleEnum.ADMIN),
            device_id,
        )
        terminal_token = authorization["terminal_token"]
        status = operational_access_service.terminal_status(session, terminal_token)
        assert status["device_id"] == device_id
        operational = operational_access_service.activate_from_terminal(
            session, terminal_token=terminal_token, employee_code="ATD-17", pin="4826",
        )
        claims = decode_access_token(operational["access_token"])
        assert claims["register_id"] == str(status["register_id"])
        assert claims["tenant_id"] == str(tenant_id)
        persisted = session.get(OperationalSession, uuid.UUID(claims["session_id"]))
        assert persisted is not None and persisted.status == OperationalSessionStatusEnum.ACTIVE

        principal = AuthPrincipal(
            subject=claims["sub"], email=None, session_id=claims["session_id"],
            assurance_level="pin", claims=claims, provider="operational",
            legacy_user_id=uuid.UUID(claims["sub"]),
        )
        authorized = authorize_tenant_context(session, principal, tenant_id, store_id, "POST", "/api/v1/operational-access/session/end")
        assert authorized.device_id == device_id
        assert authorized.operational_session_id == persisted.id

        persisted.last_seen_at = datetime.utcnow() - timedelta(minutes=5)
        session.add(persisted); session.commit()
        before_heartbeat = persisted.last_seen_at
        heartbeat = operational_access_service.heartbeat_operational_session(session, authorized)
        assert heartbeat.last_seen_at > before_heartbeat

        manager_context = TenantContext(tenant_id=tenant_id, store_id=store_id, user_id=admin_id, role=RoleEnum.ADMIN)
        device_service.update_device(
            session, manager_context, device_id, name=None,
            status=OperationalDeviceStatusEnum.PAUSED, configuration_ref=None,
            actor_id=None, reason="Teste de revogação",
        )
        with pytest.raises(HTTPException) as revoked:
            operational_access_service.terminal_status(session, terminal_token)
        assert revoked.value.status_code == 403
        with pytest.raises(HTTPException) as ended:
            authorize_tenant_context(session, principal, tenant_id, store_id, "POST", "/api/v1/operational-access/session/end")
        assert ended.value.status_code == 403

        device_service.update_device(
            session, manager_context, device_id, name=None,
            status=OperationalDeviceStatusEnum.ACTIVE, configuration_ref=None,
            actor_id=None, reason="Teste de reativação",
        )
        with pytest.raises(HTTPException) as stale_after_reactivation:
            operational_access_service.terminal_status(session, terminal_token)
        assert stale_after_reactivation.value.status_code == 403

        new_authorization = operational_access_service.authorize_terminal(session, manager_context, device_id)
        new_operational = operational_access_service.activate_from_terminal(
            session, terminal_token=new_authorization["terminal_token"], employee_code="ATD-17", pin="4826",
        )
        new_claims = decode_access_token(new_operational["access_token"])
        new_principal = AuthPrincipal(
            subject=new_claims["sub"], email=None, session_id=new_claims["session_id"],
            assurance_level="pin", claims=new_claims, provider="operational",
            legacy_user_id=uuid.UUID(new_claims["sub"]),
        )
        new_context = authorize_tenant_context(
            session, new_principal, tenant_id, store_id, "POST", "/api/v1/operational-access/session/end",
        )
        assert new_context.operational_session_id is not None

        replacement_authorization = operational_access_service.authorize_terminal(session, manager_context, device_id)
        with pytest.raises(HTTPException) as replaced:
            authorize_tenant_context(session, new_principal, tenant_id, store_id, "POST", "/api/v1/operational-access/session/end")
        assert replaced.value.status_code == 403
        replaced_session = session.get(OperationalSession, new_context.operational_session_id)
        assert replaced_session is not None and replaced_session.status == OperationalSessionStatusEnum.REVOKED

        final_operational = operational_access_service.activate_from_terminal(
            session, terminal_token=replacement_authorization["terminal_token"], employee_code="ATD-17", pin="4826",
        )
        final_claims = decode_access_token(final_operational["access_token"])
        final_principal = AuthPrincipal(
            subject=final_claims["sub"], email=None, session_id=final_claims["session_id"],
            assurance_level="pin", claims=final_claims, provider="operational",
            legacy_user_id=uuid.UUID(final_claims["sub"]),
        )
        final_context = authorize_tenant_context(
            session, final_principal, tenant_id, store_id, "POST", "/api/v1/operational-access/session/end",
        )
        operational_access_service.end_operational_session(session, final_context, reason="Fim de turno")
        with pytest.raises(HTTPException) as logged_out:
            authorize_tenant_context(session, final_principal, tenant_id, store_id, "POST", "/api/v1/operational-access/session/end")
        assert logged_out.value.status_code == 403

        expiry_operational = operational_access_service.activate_from_terminal(
            session, terminal_token=replacement_authorization["terminal_token"], employee_code="ATD-17", pin="4826",
        )
        expiry_claims = decode_access_token(expiry_operational["access_token"])
        expiry_authority = session.get(OperationalSession, uuid.UUID(expiry_claims["session_id"]))
        assert expiry_authority is not None
        expiry_authority.expires_at = datetime.utcnow() - timedelta(minutes=1)
        session.add(expiry_authority); session.commit()
        now = datetime.now(timezone.utc)
        expired_claims = {
            **expiry_claims,
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(minutes=1),
        }
        expired_token = jwt.encode(expired_claims, settings.SECRET_KEY, algorithm="HS256")
        monkeypatch.setattr(settings, "AUTH_MODE", "required")
        with pytest.raises(HTTPException) as expired:
            get_current_principal(
                authorization=f"Bearer {expired_token}", x_user_id=None, session=session,
            )
        assert expired.value.status_code == 401
        session.expire_all()
        persisted_expiry = session.get(OperationalSession, expiry_authority.id)
        assert persisted_expiry is not None
        assert persisted_expiry.status == OperationalSessionStatusEnum.EXPIRED
        assert persisted_expiry.ended_at is not None

"""OA-4 scenario 5: a refusal must not teach, and must not be free.

Two defects were found during the credentialed homologation of 3 September 2026:

  * the only throttle lived on the credential, so an employee code that resolved
    to nobody returned before any counter was touched — sweeping codes on an
    authorized terminal cost nothing;
  * the refusals were not uniform. A code that existed but had no PIN yet
    answered 409, a suspended one answered 403, and both confirmed to whoever
    typed them that the code was real.

These tests hold both closed.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.api.v1.endpoints.team import (
    OperationalMemberCreate, TeamActivationIssue, create_operational_member,
    unlock_operational_credential,
)
from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.device import OperationalDevice, OperationalDeviceTypeEnum
from app.models.identity import (
    Register, Employee, Membership, MembershipStatusEnum, OperationalCredential,
    RoleEnum, Store, Tenant, TenantStatusEnum, User,
)
from app.services import operational_access_service


GENERIC = "Código ou PIN inválido para esta unidade."


def _terminal_with_operator(pin: str = "4826"):
    """One tenant, one authorized POS and one collaborator with an active PIN."""
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"Throttle {suffix}", slug=f"throttle-{suffix}", status=TenantStatusEnum.ACTIVE)
        admin = User(email=f"throttle-admin-{suffix}@example.test", full_name="Gestora")
        session.add(tenant); session.add(admin); session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"THR-{suffix}")
        session.add(store); session.flush()
        register = Register(tenant_id=tenant.id, store_id=store.id, name="Caixa", code=f"CX-{suffix}")
        session.add(register); session.flush()
        device = OperationalDevice(
            tenant_id=tenant.id, store_id=store.id, code=f"POS-{suffix}", name="Caixa",
            device_type=OperationalDeviceTypeEnum.POS, register_id=register.id,
        )
        session.add(device)
        session.add(Membership(user_id=admin.id, tenant_id=tenant.id, role=RoleEnum.ADMIN, status=MembershipStatusEnum.ACTIVE))
        ids = (tenant.id, store.id, device.id, admin.id)
        session.commit()

    tenant_id, store_id, device_id, admin_id = ids
    context = TenantContext(tenant_id=tenant_id, store_id=store_id, user_id=admin_id, role=RoleEnum.ADMIN)
    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_id, admin_id)
        employee = Employee(
            tenant_id=tenant_id, home_store_id=store_id,
            employee_number=f"ATD-{suffix[:4]}", full_name="Ana Atendimento",
        )
        session.add(employee); session.commit(); session.refresh(employee)
        member = create_operational_member(
            OperationalMemberCreate(
                employee_id=employee.id, role=RoleEnum.OPERATOR, store_id=store_id,
                employee_code=f"AT{suffix[:4]}",
            ),
            context, session,
        )
        authorization = operational_access_service.authorize_terminal(session, context, device_id)
        token = authorization["terminal_token"]
        operational_access_service.activate_pin_from_terminal(
            session, terminal_token=token, employee_code=member.employee_code,
            activation_code=member.activation_code, pin=pin,
        )
    return context, token, member


def test_every_failed_assumption_says_the_same_thing():
    context, token, member = _terminal_with_operator()
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)

        # A code nobody carries.
        with pytest.raises(HTTPException) as unknown:
            operational_access_service.activate_from_terminal(
                session, terminal_token=token, employee_code="ZZ-9999", pin="4826",
            )
        assert (unknown.value.status_code, unknown.value.detail) == (401, GENERIC)

        # A real code with the wrong PIN.
        with pytest.raises(HTTPException) as wrong_pin:
            operational_access_service.activate_from_terminal(
                session, terminal_token=token, employee_code=member.employee_code, pin="5937",
            )
        assert (wrong_pin.value.status_code, wrong_pin.value.detail) == (401, GENERIC)

        # A real code whose access was suspended: used to answer 403.
        membership = session.get(Membership, member.membership_id)
        assert membership is not None
        membership.status = MembershipStatusEnum.SUSPENDED
        session.add(membership); session.commit()
        with pytest.raises(HTTPException) as suspended:
            operational_access_service.activate_from_terminal(
                session, terminal_token=token, employee_code=member.employee_code, pin="4826",
            )
        assert (suspended.value.status_code, suspended.value.detail) == (401, GENERIC)


def test_a_code_that_resolves_to_nobody_still_costs_the_terminal_an_attempt():
    context, token, _member = _terminal_with_operator()
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
        for attempt in range(operational_access_service.DEVICE_MAX_ATTEMPTS):
            with pytest.raises(HTTPException) as refused:
                operational_access_service.activate_from_terminal(
                    session, terminal_token=token, employee_code=f"NAO{attempt:04d}", pin="4826",
                )
            assert refused.value.status_code == 401, "a varredura não pode ser recusada com 429 antes do teto"

        with pytest.raises(HTTPException) as locked:
            operational_access_service.activate_from_terminal(
                session, terminal_token=token, employee_code="NAO9999", pin="4826",
            )
        assert locked.value.status_code == 429
        assert "Terminal temporariamente bloqueado" in locked.value.detail


def test_a_valid_shift_clears_the_terminal_counter():
    context, token, member = _terminal_with_operator()
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
        for attempt in range(3):
            with pytest.raises(HTTPException):
                operational_access_service.activate_from_terminal(
                    session, terminal_token=token, employee_code=f"NAO{attempt:04d}", pin="4826",
                )
        operational_access_service.activate_from_terminal(
            session, terminal_token=token, employee_code=member.employee_code, pin="4826",
        )
        device = session.exec(select(OperationalDevice).where(
            OperationalDevice.tenant_id == context.tenant_id,
        )).one()
        assert device.auth_failed_attempts == 0
        assert device.auth_locked_until is None


def test_management_releases_a_lock_without_destroying_the_pin():
    context, token, member = _terminal_with_operator()
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
        credential = session.exec(select(OperationalCredential).where(
            OperationalCredential.membership_id == member.membership_id,
        )).one()
        pin_hash_before = credential.pin_hash
        credential.failed_attempts = 5
        credential.locked_until = datetime.utcnow() + timedelta(minutes=15)
        session.add(credential); session.commit()

        with pytest.raises(HTTPException) as blocked:
            operational_access_service.activate_from_terminal(
                session, terminal_token=token, employee_code=member.employee_code, pin="4826",
            )
        assert blocked.value.status_code == 429

        released = unlock_operational_credential(
            member.membership_id, TeamActivationIssue(reason="Colaboradora digitou errado no balcão"),
            context, session,
        )
        assert released.locked_until is None
        assert released.credential_state == "ACTIVE", "liberar o bloqueio não pode apagar o PIN"

        session.refresh(credential)
        assert credential.pin_hash == pin_hash_before
        operational_access_service.activate_from_terminal(
            session, terminal_token=token, employee_code=member.employee_code, pin="4826",
        )

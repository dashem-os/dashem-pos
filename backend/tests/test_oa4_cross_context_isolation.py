"""OA-4 scenarios 6 and 7: the condominium wall, and a tampered context.

Neither can be exercised through the interface — the interface never offers the
wrong tenant or the wrong unit, which is precisely why they have to be proven
against the API. Scenario 6 asks that a collaborator from another tenant or
another unit be refused without ever being offered a context picker. Scenario 7
asks that a legitimate operational session, pointed at a context it does not
belong to, be refused by the backend *before* any mutation is written.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.api.v1.endpoints.team import OperationalMemberCreate, create_operational_member
from app.core.context import TenantContext, authorize_tenant_context
from app.core.database import engine
from app.core.security import AuthPrincipal, decode_access_token
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.device import OperationalDevice, OperationalDeviceTypeEnum
from app.models.identity import (
    Employee, Membership, MembershipStatusEnum, RoleEnum, Store, Tenant,
    TenantStatusEnum, User,
)
from app.models.payment import CashSession, Register
from app.services import cash_service, operational_access_service


GENERIC = "Código ou PIN inválido para esta unidade."
PIN = "4826"


def _tenant(label: str, store_count: int = 1) -> dict:
    """A tenant with one authorized POS per store and one collaborator in each."""
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"{label} {suffix}", slug=f"{label.lower()}-{suffix}", status=TenantStatusEnum.ACTIVE)
        admin = User(email=f"{label.lower()}-{suffix}@example.test", full_name="Gestora")
        session.add(tenant); session.add(admin); session.flush()
        stores = []
        for index in range(store_count):
            store = Store(tenant_id=tenant.id, name=f"Unidade {index + 1}", code=f"{label[:3].upper()}{index}-{suffix}")
            session.add(store); session.flush()
            register = Register(tenant_id=tenant.id, store_id=store.id, name="Caixa", code=f"CX{index}-{suffix}")
            session.add(register); session.flush()
            device = OperationalDevice(
                tenant_id=tenant.id, store_id=store.id, code=f"POS{index}-{suffix}", name="Caixa",
                device_type=OperationalDeviceTypeEnum.POS, register_id=register.id,
            )
            session.add(device); session.flush()
            stores.append({"store_id": store.id, "register_id": register.id, "device_id": device.id})
        session.add(Membership(user_id=admin.id, tenant_id=tenant.id, role=RoleEnum.ADMIN, status=MembershipStatusEnum.ACTIVE))
        fixture = {"tenant_id": tenant.id, "admin_id": admin.id, "suffix": suffix, "stores": stores}
        session.commit()

    for index, unit in enumerate(fixture["stores"]):
        context = TenantContext(
            tenant_id=fixture["tenant_id"], store_id=unit["store_id"],
            user_id=fixture["admin_id"], role=RoleEnum.ADMIN,
        )
        with Session(engine) as session:
            set_tenant_db_context(session, fixture["tenant_id"], unit["store_id"], fixture["admin_id"])
            employee = Employee(
                tenant_id=fixture["tenant_id"], home_store_id=unit["store_id"],
                employee_number=f"E{index}-{fixture['suffix'][:4]}", full_name="Colaboradora",
            )
            session.add(employee); session.commit(); session.refresh(employee)
            member = create_operational_member(
                OperationalMemberCreate(
                    employee_id=employee.id, role=RoleEnum.CASHIER, store_id=unit["store_id"],
                    employee_code=f"C{index}{fixture['suffix'][:4]}",
                ),
                context, session,
            )
            authorization = operational_access_service.authorize_terminal(session, context, unit["device_id"])
            operational_access_service.activate_pin_from_terminal(
                session, terminal_token=authorization["terminal_token"],
                employee_code=member.employee_code, activation_code=member.activation_code, pin=PIN,
            )
            unit["terminal_token"] = authorization["terminal_token"]
            unit["employee_code"] = member.employee_code
            unit["admin_context"] = context
    return fixture


def test_a_collaborator_from_another_tenant_is_refused_at_this_terminal():
    """Scenario 6, across the condominium wall."""
    first = _tenant("Alfa")
    second = _tenant("Beta")
    with Session(engine) as session:
        set_tenant_db_context(session, first["tenant_id"], first["stores"][0]["store_id"], first["admin_id"])
        with pytest.raises(HTTPException) as refused:
            operational_access_service.activate_from_terminal(
                session, terminal_token=first["stores"][0]["terminal_token"],
                employee_code=second["stores"][0]["employee_code"], pin=PIN,
            )
        # Refused, and refused in the same words as a code that exists nowhere:
        # the terminal must not confirm that this person is real next door.
        assert (refused.value.status_code, refused.value.detail) == (401, GENERIC)


def test_a_collaborator_from_another_unit_is_refused_at_this_terminal():
    """Scenario 6, between units of the same tenant."""
    tenant = _tenant("Gama", store_count=2)
    first, second = tenant["stores"]
    with Session(engine) as session:
        set_tenant_db_context(session, tenant["tenant_id"], first["store_id"], tenant["admin_id"])
        with pytest.raises(HTTPException) as refused:
            operational_access_service.activate_from_terminal(
                session, terminal_token=first["terminal_token"],
                employee_code=second["employee_code"], pin=PIN,
            )
        assert (refused.value.status_code, refused.value.detail) == (401, GENERIC)

        # And the credential that belongs here still works, so the refusal above
        # is isolation and not a broken terminal.
        assert operational_access_service.activate_from_terminal(
            session, terminal_token=first["terminal_token"],
            employee_code=first["employee_code"], pin=PIN,
        )["access_token"]


def _operational_principal(access_token: str) -> tuple[AuthPrincipal, dict]:
    claims = decode_access_token(access_token)
    return AuthPrincipal(
        subject=claims["sub"], email=None, session_id=claims["session_id"],
        assurance_level="pin", claims=claims, provider="operational",
        legacy_user_id=uuid.UUID(claims["sub"]),
    ), claims


def test_a_tampered_context_is_refused_before_anything_is_written():
    """Scenario 7: a real session pointed at a unit it does not belong to."""
    tenant = _tenant("Delta", store_count=2)
    home, other = tenant["stores"]
    with Session(engine) as session:
        set_tenant_db_context(session, tenant["tenant_id"], home["store_id"], tenant["admin_id"])
        issued = operational_access_service.activate_from_terminal(
            session, terminal_token=home["terminal_token"],
            employee_code=home["employee_code"], pin=PIN,
        )
        principal, claims = _operational_principal(issued["access_token"])

        # The honest context resolves and projects.
        honest = authorize_tenant_context(
            session, principal, tenant["tenant_id"], home["store_id"],
            "GET", "/api/v1/operational-access/session/context",
        )
        assert operational_access_service.operational_session_context(session, honest)["store_id"] == home["store_id"]

        # The same token, asking for the neighbouring unit.
        with pytest.raises(HTTPException) as tampered_store:
            authorize_tenant_context(
                session, principal, tenant["tenant_id"], other["store_id"],
                "GET", "/api/v1/operational-access/session/context",
            )
        assert tampered_store.value.status_code == 403

        # The same token, asking for another tenant entirely.
        with pytest.raises(HTTPException) as tampered_tenant:
            authorize_tenant_context(
                session, principal, uuid.uuid4(), home["store_id"],
                "GET", "/api/v1/operational-access/session/context",
            )
        assert tampered_tenant.value.status_code == 403

        # A mutation is the real question. The 403s above close the door on a
        # forged header; what remains is an authentic session sending a payload
        # that points somewhere else — the context is honest, the body is not.
        with pytest.raises(HTTPException) as mutation:
            cash_service.open_cash_session(
                session, honest, other["store_id"], other["register_id"],
                principal.legacy_user_id, Decimal("100.00"),
            )
        assert mutation.value.status_code in (400, 403, 404), mutation.value.detail
        session.rollback()

    # Nothing was written anywhere, read back outside the refused transaction.
    with Session(engine) as session:
        set_tenant_db_context(session, tenant["tenant_id"], other["store_id"], tenant["admin_id"])
        opened = session.exec(select(CashSession).where(CashSession.register_id == other["register_id"])).all()
        assert opened == [], "uma recusa não pode deixar caixa aberto para trás"

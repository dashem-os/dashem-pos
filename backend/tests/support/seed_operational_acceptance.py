"""Create an isolated OA-4 browser fixture without printing credentials."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from sqlmodel import Session

from app.api.v1.endpoints.team import OperationalMemberCreate, create_operational_member
from app.core.config import settings
from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.device import OperationalDevice, OperationalDeviceTypeEnum
from app.models.identity import (
    AuthIdentity,
    Employee,
    Membership,
    MembershipStatusEnum,
    RoleEnum,
    Store,
    Tenant,
    TenantStatusEnum,
    User,
)
from app.models.payment import Register
from app.models.platform import TenantCapability


def _manager_token(subject: str, email: str) -> str:
    if not settings.AUTH_TEST_SECRET:
        raise RuntimeError("AUTH_TEST_SECRET is required for the OA-4 fixture.")
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": subject,
            "email": email,
            "aud": settings.SUPABASE_JWT_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(hours=2),
            "aal": "aal1",
            "app_metadata": {"provider": "email"},
        },
        settings.AUTH_TEST_SECRET,
        algorithm="HS256",
    )


def create_fixture(output: Path) -> None:
    suffix = uuid.uuid4().hex[:8]
    manager_subject = str(uuid.uuid4())
    manager_email = f"oa4-manager-{suffix}@example.test"

    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(
            name=f"OA4 Tenant {suffix}",
            slug=f"oa4-{suffix}",
            status=TenantStatusEnum.ACTIVE,
        )
        manager = User(email=manager_email, full_name="Gestora OA4")
        session.add(tenant)
        session.add(manager)
        session.flush()
        session.add(
            AuthIdentity(
                user_id=manager.id,
                provider="supabase",
                provider_subject=manager_subject,
                provider_email=manager_email,
                email_verified=True,
            )
        )
        store = Store(
            tenant_id=tenant.id,
            name="Unidade OA4",
            code=f"OA4-{suffix}",
            is_headquarters=True,
        )
        session.add(store)
        session.flush()
        session.add_all([
            TenantCapability(tenant_id=tenant.id, key=key, enabled=True)
            for key in ("catalog", "counter_order", "cash_management")
        ])
        register = Register(
            tenant_id=tenant.id,
            store_id=store.id,
            name="Caixa OA4",
            code=f"CX-{suffix}",
        )
        session.add(register)
        session.flush()
        device = OperationalDevice(
            tenant_id=tenant.id,
            store_id=store.id,
            code=f"POS-{suffix}",
            name="Terminal OA4",
            device_type=OperationalDeviceTypeEnum.POS,
            register_id=register.id,
        )
        session.add(device)
        session.add(
            Membership(
                user_id=manager.id,
                tenant_id=tenant.id,
                role=RoleEnum.ADMIN,
                status=MembershipStatusEnum.ACTIVE,
            )
        )
        employees = [
            Employee(
                tenant_id=tenant.id,
                home_store_id=store.id,
                employee_number=f"OA4A-{suffix}",
                full_name="Operadora OA4 A",
            ),
            Employee(
                tenant_id=tenant.id,
                home_store_id=store.id,
                employee_number=f"OA4B-{suffix}",
                full_name="Operador OA4 B",
            ),
        ]
        session.add_all(employees)
        session.commit()
        tenant_id = tenant.id
        store_id = store.id
        register_id = register.id
        device_id = device.id
        manager_id = manager.id
        employee_ids = [employee.id for employee in employees]

    context = TenantContext(
        tenant_id=tenant_id,
        store_id=store_id,
        user_id=manager_id,
        role=RoleEnum.ADMIN,
        permissions=("team.manage", "team.read", "device.manage"),
    )
    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_id, manager_id)
        members = [
            create_operational_member(
                OperationalMemberCreate(
                    employee_id=employee_ids[0],
                    role=RoleEnum.CASHIER,
                    store_id=store_id,
                    employee_code="OA4-A",
                ),
                context,
                session,
            ),
            create_operational_member(
                OperationalMemberCreate(
                    employee_id=employee_ids[1],
                    role=RoleEnum.OPERATOR,
                    store_id=store_id,
                    employee_code="OA4-B",
                ),
                context,
                session,
            ),
        ]
    fixture = {
        "tenant_id": str(tenant_id),
        "store_id": str(store_id),
        "register_id": str(register_id),
        "device_id": str(device_id),
        "manager_token": _manager_token(manager_subject, manager_email),
        "operators": [
            {
                "employee_code": members[0].employee_code,
                "activation_code": members[0].activation_code,
                "pin": "4826",
            },
            {
                "employee_code": members[1].employee_code,
                "activation_code": members[1].activation_code,
                "pin": "6752",
            },
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(fixture), encoding="utf-8")
    print("OA-4 fixture created with sanitized tenant, store, register and device identifiers.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    create_fixture(parser.parse_args().output)

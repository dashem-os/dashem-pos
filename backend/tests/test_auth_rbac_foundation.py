import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.core.context import authorize_tenant_context
from app.core.database import engine
from app.core.rbac import tenant_role_allows
from app.core.security import AuthPrincipal, decode_access_token, get_current_principal
from app.core.tenancy import set_platform_db_context
from app.models.identity import (
    AuthIdentity, Membership, MembershipStatusEnum, RoleEnum, Store, Tenant,
    TenantStatusEnum, User,
)
from app.models.platform import PlatformMembership, PlatformRoleEnum, TenantCapability


def _principal(subject: str) -> AuthPrincipal:
    return AuthPrincipal(
        subject=subject, email=f"{subject}@example.test",
        session_id=str(uuid.uuid4()), assurance_level="aal1",
        claims={"sub": subject},
    )


def test_missing_bearer_is_rejected_when_authentication_is_required(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    with pytest.raises(HTTPException) as exc:
        get_current_principal(authorization=None, x_user_id=None)
    assert exc.value.status_code == 401


def test_test_mode_validates_signed_token_and_rejects_expired_token(monkeypatch):
    from app.core.config import settings
    secret = "isolated-test-signing-key-with-sufficient-length"
    monkeypatch.setattr(settings, "AUTH_MODE", "test")
    monkeypatch.setattr(settings, "AUTH_TEST_SECRET", secret)
    now = datetime.now(timezone.utc)
    valid = jwt.encode(
        {"sub": str(uuid.uuid4()), "aud": "authenticated", "iat": now, "exp": now + timedelta(minutes=5)},
        secret,
        algorithm="HS256",
    )
    assert decode_access_token(valid)["aud"] == "authenticated"
    expired = jwt.encode(
        {"sub": str(uuid.uuid4()), "aud": "authenticated", "iat": now - timedelta(minutes=10), "exp": now - timedelta(minutes=5)},
        secret,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        decode_access_token(expired)
    assert exc.value.status_code == 401


def test_permission_matrix_denies_management_to_cashier_and_keeps_supervisor_operational():
    assert tenant_role_allows(RoleEnum.CASHIER, "POST", "/api/v1/sales")
    assert not tenant_role_allows(RoleEnum.CASHIER, "POST", "/api/v1/catalog/products")
    assert tenant_role_allows(RoleEnum.SUPERVISOR, "GET", "/api/v1/sales")
    assert tenant_role_allows(RoleEnum.SUPERVISOR, "POST", "/api/v1/sales")
    assert not tenant_role_allows(RoleEnum.SUPERVISOR, "POST", "/api/v1/team/operational")


def test_membership_and_store_scope_block_cross_tenant_access():
    suffix = uuid.uuid4().hex[:8]
    subject = str(uuid.uuid4())
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant_a = Tenant(name=f"Auth A {suffix}", slug=f"auth-a-{suffix}", status=TenantStatusEnum.ACTIVE)
        tenant_b = Tenant(name=f"Auth B {suffix}", slug=f"auth-b-{suffix}", status=TenantStatusEnum.ACTIVE)
        session.add(tenant_a); session.add(tenant_b); session.flush()
        store_a = Store(tenant_id=tenant_a.id, name="A", code=f"A-{suffix}")
        store_b = Store(tenant_id=tenant_b.id, name="B", code=f"B-{suffix}")
        user = User(email=f"auth-{suffix}@example.test", full_name="Auth Test")
        session.add(store_a); session.add(store_b); session.add(user); session.flush()
        session.add(AuthIdentity(user_id=user.id, provider="supabase", provider_subject=subject))
        session.add(Membership(
            user_id=user.id, tenant_id=tenant_a.id, store_id=store_a.id,
            role=RoleEnum.CASHIER, status=MembershipStatusEnum.ACTIVE,
        ))
        session.add(TenantCapability(tenant_id=tenant_a.id, key="catalog", enabled=True))
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id
        store_a_id = store_a.id
        store_b_id = store_b.id
        user_id = user.id
        session.commit()

        context = authorize_tenant_context(
            session, _principal(subject), tenant_a_id, store_a_id,
            "GET", "/api/v1/catalog/products",
        )
        assert context.user_id == user_id
        assert context.role == RoleEnum.CASHIER

        with pytest.raises(HTTPException) as cross_tenant:
            authorize_tenant_context(
                session, _principal(subject), tenant_b_id, store_b_id,
                "GET", "/api/v1/catalog/products",
            )
        assert cross_tenant.value.status_code == 403

        with pytest.raises(HTTPException) as mismatched_store:
            authorize_tenant_context(
                session, _principal(subject), tenant_a_id, store_b_id,
                "GET", "/api/v1/catalog/products",
            )
        assert mismatched_store.value.status_code == 403

        with pytest.raises(HTTPException) as forbidden_write:
            authorize_tenant_context(
                session, _principal(subject), tenant_a_id, store_a_id,
                "POST", "/api/v1/catalog/products",
            )
        assert forbidden_write.value.status_code == 403


def test_platform_membership_does_not_grant_implicit_tenant_access():
    suffix = uuid.uuid4().hex[:8]
    subject = str(uuid.uuid4())
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"No Implicit {suffix}", slug=f"no-implicit-{suffix}", status=TenantStatusEnum.ACTIVE)
        user = User(email=f"platform-{suffix}@example.test", full_name="Platform Test")
        session.add(tenant); session.add(user); session.flush()
        session.add(AuthIdentity(user_id=user.id, provider="supabase", provider_subject=subject))
        session.add(PlatformMembership(user_id=user.id, role=PlatformRoleEnum.SUPPORT))
        tenant_id = tenant.id
        session.commit()
        with pytest.raises(HTTPException) as exc:
            authorize_tenant_context(
                session, _principal(subject), tenant_id, None,
                "GET", "/api/v1/catalog/products",
            )
        assert exc.value.status_code == 403

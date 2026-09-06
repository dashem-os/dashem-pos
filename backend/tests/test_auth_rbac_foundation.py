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


def _settings(**overrides):
    from app.core.config import Settings

    return Settings(
        _env_file=None,
        DATABASE_URL="postgresql://test:test@localhost/test",
        SECRET_KEY="test-secret-key-with-at-least-32-characters",
        **overrides,
    )


def test_relaxed_authentication_is_allowed_only_where_it_was_declared():
    """A proteção é por allowlist, e um ambiente novo nasce fechado.

    Bloquear `production` e `prod` pelo nome exigia acertar o futuro: qualquer
    ambiente chamado de outra coisa aceitava `AUTH_MODE=disabled`, e com ele o
    cabeçalho `X-User-ID` impersona qualquer usuário sem token nenhum.
    """
    from app.core.config import RELAXED_AUTH_ENVIRONMENTS

    assert RELAXED_AUTH_ENVIRONMENTS == {"development", "test"}
    # Os dois ambientes que de fato existem no repositório continuam abrindo.
    for environment in RELAXED_AUTH_ENVIRONMENTS:
        assert _settings(ENVIRONMENT=environment, AUTH_MODE="disabled").AUTH_MODE == "disabled"


@pytest.mark.parametrize(
    "environment",
    ["production", "prod", "staging", "qa", "uat", "homologacao", "producton", " Production "],
)
def test_an_environment_nobody_listed_refuses_to_relax_authentication(environment):
    """Inclui o nome digitado errado e o que veio com espaço: os dois passavam."""
    with pytest.raises(ValueError, match="AUTH_MODE must be 'required'"):
        _settings(ENVIRONMENT=environment, AUTH_MODE="disabled")
    with pytest.raises(ValueError, match="AUTH_MODE must be 'required'"):
        _settings(ENVIRONMENT=environment, AUTH_MODE="test", AUTH_TEST_SECRET="x" * 32)


@pytest.mark.parametrize("environment", ["production", "staging", "qa"])
def test_identity_provider_is_required_wherever_authentication_is(environment):
    """Exigir autenticação sem provedor de identidade seria exigir o impossível."""
    with pytest.raises(ValueError, match="SUPABASE_URL is required"):
        _settings(ENVIRONMENT=environment, AUTH_MODE="required")
    configured = _settings(
        ENVIRONMENT=environment, AUTH_MODE="required",
        SUPABASE_URL="https://project.supabase.co",
    )
    assert configured.AUTH_MODE == "required"


def test_the_security_core_does_not_lean_on_assert():
    """`assert` some com `python -O`, e decisão de acesso não pode sumir junto.

    Os que existiam aqui eram narrowing depois de chamadas que já levantam, então
    o efeito de removê-los seria um 500 no meio da autorização — não um bypass.
    Mesmo assim a classe é fácil de fechar e cara de reaprender: nada garante que
    o próximo `assert` escrito neste caminho também seja inofensivo.

    O escopo é o núcleo. Os endpoints ainda usam `assert actor is not None` para
    estreitar tipo depois de `require_platform_role`, que levanta sozinha; isso é
    ruído de tipagem, não controle de acesso.
    """
    import ast
    from pathlib import Path

    core = Path(__file__).resolve().parents[1] / "app" / "core"
    offenders = []
    for path in sorted(core.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [
            f"{path.name}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Assert)
        ]
    assert offenders == [], (
        "O núcleo de segurança voltou a depender de `assert`: " + ", ".join(offenders)
    )

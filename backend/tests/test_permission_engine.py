import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.core.context import authorize_tenant_context
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.core.tenancy import set_platform_db_context
from app.models.identity import (
    AuthIdentity,
    Membership,
    MembershipStatusEnum,
    PermissionGrant,
    PermissionGrantEffectEnum,
    RoleEnum,
    Store,
    Tenant,
    TenantStatusEnum,
    User,
)
from app.models.platform import TenantCapability


def _principal(subject: str) -> AuthPrincipal:
    return AuthPrincipal(
        subject=subject,
        email=f"{subject}@example.test",
        session_id=str(uuid.uuid4()),
        assurance_level="aal1",
        claims={"sub": subject},
    )


def _identity(session: Session, tenant: Tenant, role: RoleEnum, suffix: str):
    subject = str(uuid.uuid4())
    user = User(email=f"{role.value.lower()}-{suffix}@example.test", full_name=role.value)
    session.add(user)
    session.flush()
    session.add(AuthIdentity(user_id=user.id, provider="supabase", provider_subject=subject))
    membership = Membership(
        user_id=user.id,
        tenant_id=tenant.id,
        store_id=None,
        role=role,
        status=MembershipStatusEnum.ACTIVE,
    )
    session.add(membership)
    session.flush()
    return subject, membership


def test_permission_capability_context_and_store_grant_are_all_required():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"Permission {suffix}", slug=f"permission-{suffix}", status=TenantStatusEnum.ACTIVE)
        session.add(tenant)
        session.flush()
        store_a = Store(tenant_id=tenant.id, name="A", code=f"A-{suffix}")
        store_b = Store(tenant_id=tenant.id, name="B", code=f"B-{suffix}")
        session.add(store_a)
        session.add(store_b)
        session.flush()
        cashier_subject, cashier = _identity(session, tenant, RoleEnum.CASHIER, suffix)
        admin_subject, _admin = _identity(session, tenant, RoleEnum.ADMIN, suffix)
        session.add(TenantCapability(tenant_id=tenant.id, key="catalog", enabled=True))
        session.add(PermissionGrant(
            tenant_id=tenant.id,
            store_id=store_a.id,
            membership_id=cashier.id,
            permission_key="catalog.update",
            effect=PermissionGrantEffectEnum.ALLOW,
            reason="Delegação de teste restrita à unidade A",
        ))
        tenant_id, store_a_id, store_b_id = tenant.id, store_a.id, store_b.id
        session.commit()

    with Session(engine) as session:
        read_context = authorize_tenant_context(
            session, _principal(cashier_subject), tenant_id, store_a_id,
            "GET", "/api/v1/catalog/products",
        )
        assert "catalog.read" in read_context.permissions
        assert "catalog" in read_context.capabilities

    with Session(engine) as session:
        delegated = authorize_tenant_context(
            session, _principal(cashier_subject), tenant_id, store_a_id,
            "POST", "/api/v1/catalog/products",
        )
        assert "catalog.update" in delegated.permissions

    with Session(engine) as session:
        with pytest.raises(HTTPException) as sibling_store:
            authorize_tenant_context(
                session, _principal(cashier_subject), tenant_id, store_b_id,
                "POST", "/api/v1/catalog/products",
            )
        assert sibling_store.value.status_code == 403
        assert "catalog.update" in sibling_store.value.detail

    with Session(engine) as session:
        admin = authorize_tenant_context(
            session, _principal(admin_subject), tenant_id, store_b_id,
            "POST", "/api/v1/catalog/products",
        )
        assert "catalog.update" in admin.permissions

    with Session(engine) as session:
        with pytest.raises(HTTPException) as missing_capability:
            authorize_tenant_context(
                session, _principal(admin_subject), tenant_id, store_a_id,
                "POST", "/api/v1/inventory/adjust",
            )
        assert missing_capability.value.status_code == 403
        assert "inventory" in missing_capability.value.detail


def test_explicit_deny_overrides_system_role_profile():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"Deny {suffix}", slug=f"deny-{suffix}", status=TenantStatusEnum.ACTIVE)
        session.add(tenant)
        session.flush()
        store = Store(tenant_id=tenant.id, name="Store", code=f"S-{suffix}")
        session.add(store)
        session.flush()
        subject, membership = _identity(session, tenant, RoleEnum.ADMIN, suffix)
        session.add(TenantCapability(tenant_id=tenant.id, key="counter_order", enabled=True))
        session.add(PermissionGrant(
            tenant_id=tenant.id,
            store_id=None,
            membership_id=membership.id,
            permission_key="sale.cancel",
            effect=PermissionGrantEffectEnum.DENY,
            reason="Separação de função",
        ))
        tenant_id, store_id = tenant.id, store.id
        session.commit()

    with Session(engine) as session:
        with pytest.raises(HTTPException) as denied:
            authorize_tenant_context(
                session, _principal(subject), tenant_id, store_id,
                "POST", f"/api/v1/sales/{uuid.uuid4()}/cancel",
            )
        assert denied.value.status_code == 403
        assert "sale.cancel" in denied.value.detail


def test_only_tenant_administrator_profile_can_manage_the_team():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"Team {suffix}", slug=f"team-{suffix}", status=TenantStatusEnum.ACTIVE)
        session.add(tenant)
        session.flush()
        admin_subject, _ = _identity(session, tenant, RoleEnum.ADMIN, f"admin-{suffix}")
        manager_subject, _ = _identity(session, tenant, RoleEnum.MANAGER, f"manager-{suffix}")
        tenant_id = tenant.id
        session.commit()

    with Session(engine) as session:
        admin = authorize_tenant_context(
            session, _principal(admin_subject), tenant_id, None,
            "POST", "/api/v1/team/invitations",
        )
        assert "team.manage" in admin.permissions

    with Session(engine) as session:
        with pytest.raises(HTTPException) as manager:
            authorize_tenant_context(
                session, _principal(manager_subject), tenant_id, None,
                "POST", "/api/v1/team/invitations",
            )
        assert manager.value.status_code == 403
        assert "team.manage" in manager.value.detail


def test_contract_requests_have_a_dedicated_tenant_permission():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(
            name=f"Contract {suffix}",
            slug=f"contract-{suffix}",
            status=TenantStatusEnum.ACTIVE,
        )
        session.add(tenant)
        session.flush()
        admin_subject, _ = _identity(session, tenant, RoleEnum.ADMIN, f"admin-{suffix}")
        manager_subject, _ = _identity(session, tenant, RoleEnum.MANAGER, f"manager-{suffix}")
        tenant_id = tenant.id
        session.commit()

    with Session(engine) as session:
        admin = authorize_tenant_context(
            session, _principal(admin_subject), tenant_id, None,
            "POST", "/api/v1/commercial-requests",
        )
        assert "contract.request" in admin.permissions

    with Session(engine) as session:
        with pytest.raises(HTTPException) as manager:
            authorize_tenant_context(
                session, _principal(manager_subject), tenant_id, None,
                "POST", "/api/v1/commercial-requests",
            )
        assert manager.value.status_code == 403
        assert "contract.request" in manager.value.detail


def test_permission_mapping_downgrades_on_a_trailing_slash_and_routing_is_what_saves_it():
    """Achado em aberto, com a suposição que o mantém inofensivo pinada aqui.

    `route_requirement` casa a rota por string. Com barra final, `/refund/` e
    `/cancel/` deixam de casar com a regra específica e **caem no ramo genérico**
    — trocando `checkout.payment.refund` por `checkout.payment`, que é a
    permissão de criar parcela. Uma barra rebaixaria a autoridade exigida para
    devolver dinheiro.

    Hoje isso não é alcançável: a autorização roda como dependência, e o
    roteamento do FastAPI responde 307 para a barra final antes de qualquer
    dependência executar. Ou seja, o que protege não é a regra — é o roteador.

    A correção combinada é mover a autorização para as rotas, e ela tem contrato
    próprio; um `rstrip` aqui esconderia o problema em vez de resolvê-lo. Até lá,
    este teste falha alto se alguém desligar `redirect_slashes` ou registrar uma
    rota com barra final, que são as duas formas de tornar o rebaixamento real.
    """
    from app.core.permissions import route_requirement
    from app.main import app

    canonical = route_requirement("POST", "/api/v1/negotiations/intents/abc/refund")
    slashed = route_requirement("POST", "/api/v1/negotiations/intents/abc/refund/")
    assert canonical.permission == "checkout.payment.refund"
    assert slashed.permission == "checkout.payment", (
        "o rebaixamento por barra final mudou; reavalie o contrato pendente"
    )

    assert app.router.redirect_slashes is True, (
        "sem o redirecionamento do roteador, a barra final vira rebaixamento real "
        "de permissão — mova a autorização para as rotas antes de desligar isto"
    )
    with_trailing = [
        route.path for route in app.routes
        if getattr(route, "path", "").endswith("/") and route.path != "/"
    ]
    assert with_trailing == [], (
        "rota registrada com barra final alcança o ramo genérico de permissão: "
        + ", ".join(with_trailing)
    )

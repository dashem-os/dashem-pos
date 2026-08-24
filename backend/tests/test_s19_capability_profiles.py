import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.api.v1.endpoints.capabilities import get_effective_capabilities
from app.api.v1.endpoints.control import ProfileApply, apply_capability_profile, list_capability_profiles
from app.api.v1.endpoints.identity import (
    PlatformTenantCreate, TenantCapabilityUpdate, provision_platform_tenant,
    update_tenant_capability,
)
from app.core.context import TenantContext
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.models.identity import AuthIdentity, User
from app.models.platform import (
    CapabilityProfileRevision, PlatformMembership, PlatformRoleEnum,
    StoreCapabilityOverride, TenantCapability, TenantProfileAssignment,
)
from app.modules.capabilities.service import effective_capabilities


def _owner(session: Session) -> tuple[AuthPrincipal, User]:
    subject = str(uuid.uuid4())
    user = User(email=f"s19-{subject}@example.test", full_name="S19 Owner")
    session.add(user); session.flush()
    session.add(AuthIdentity(user_id=user.id, provider="supabase", provider_subject=subject, provider_email=user.email, email_verified=True))
    session.add(PlatformMembership(user_id=user.id, role=PlatformRoleEnum.PLATFORM_OWNER))
    session.commit(); session.refresh(user)
    return AuthPrincipal(subject=subject, email=user.email, session_id=str(uuid.uuid4()), assurance_level="aal2", claims={"sub": subject, "aal": "aal2"}, provider="email"), user


def test_s19_profiles_are_versioned_shortcuts_and_contributions_are_effective():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        principal, owner = _owner(session)
        provisioned = provision_platform_tenant(
            PlatformTenantCreate(name=f"S19 {suffix}", slug=f"s19-{suffix}", first_store_name="Principal", first_store_code="MAIN"),
            principal, session,
        )
        profiles = list_capability_profiles(principal, session)
        retail = next(row["revision"] for row in profiles if row["revision"].profile_key == "RETAIL")
        food = next(row["revision"] for row in profiles if row["revision"].profile_key == "FOOD_SERVICE")
        grocery = next(row["revision"] for row in profiles if row["revision"].profile_key == "GROCERY")

        result = apply_capability_profile(
            provisioned.tenant.id, retail.id, ProfileApply(reason="Contrato de varejo aprovado para validação."), principal, session,
        )
        assert result["profile"] == {"key": "RETAIL", "version": "1.0.0"}
        assert "catalog" in result["capabilities"] and "table_service" not in result["capabilities"]

        context = TenantContext(
            tenant_id=provisioned.tenant.id, store_id=provisioned.first_store.id,
            user_id=owner.id, permissions=("management.read", "catalog.read", "sale.read", "cash.read", "inventory.read", "customer.read", "receivable.read", "team.read", "device.read", "table.read"),
        )
        effective = get_effective_capabilities(context=context, session=session)
        navigation = {item.contribution_key for item in effective["contributions"] if item.surface == "MANAGEMENT_NAV"}
        assert {"overview", "sales", "cash", "products", "categories", "inventory", "customers", "receivables", "team", "devices"} <= navigation
        assert "tables" not in navigation
        assert effective["profile"] == {"key": "RETAIL", "version": "1.0.0"}

        # Migrating profiles ends the old assignment but preserves entitlement rows.
        apply_capability_profile(
            provisioned.tenant.id, food.id, ProfileApply(reason="Migração contratual para operação food service."), principal, session,
        )
        assignments = list(session.exec(select(TenantProfileAssignment).where(TenantProfileAssignment.tenant_id == provisioned.tenant.id)).all())
        assert {item.status for item in assignments} == {"ACTIVE", "ENDED"}
        inventory = session.exec(select(TenantCapability).where(TenantCapability.tenant_id == provisioned.tenant.id, TenantCapability.key == "inventory")).one()
        assert inventory.enabled is False
        assert "tables" in {item.contribution_key for item in get_effective_capabilities(context=context, session=session)["contributions"]}

        with pytest.raises(HTTPException) as draft:
            apply_capability_profile(provisioned.tenant.id, grocery.id, ProfileApply(reason="Profile futuro não pode ser ativado."), principal, session)
        assert draft.value.status_code == 409


def test_s19_unimplemented_modules_and_store_minting_are_rejected():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        principal, _ = _owner(session)
        provisioned = provision_platform_tenant(
            PlatformTenantCreate(name=f"S19 Guard {suffix}", slug=f"s19-guard-{suffix}", first_store_name="Principal", first_store_code="MAIN"),
            principal, session,
        )
        with pytest.raises(HTTPException) as unavailable:
            update_tenant_capability(
                provisioned.tenant.id, "self_checkout",
                TenantCapabilityUpdate(enabled=True, reason="Tentativa de vender módulo sem implementação."),
                principal, session,
            )
        assert unavailable.value.status_code == 409

        session.add(StoreCapabilityOverride(
            tenant_id=provisioned.tenant.id, store_id=provisioned.first_store.id,
            key="inventory", enabled=True, configuration={"source": "invalid-store-mint"},
        ))
        session.commit()
        assert "inventory" not in effective_capabilities(session, provisioned.tenant.id, provisioned.first_store.id)

"""The persisted navigation must require both TEF and read permission."""

import uuid

import pytest
from sqlmodel import Session, select

from app.api.v1.endpoints.capabilities import get_effective_capabilities
from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.identity import Store, Tenant
from app.models.platform import ModuleContribution, StoreCapabilityOverride, TenantCapability


@pytest.mark.parametrize(
    "tef_enabled,permissions,store_disabled,visible",
    [
        (True, ("provider.read",), False, True),
        (True, ("provider.configure",), False, False),
        (False, ("provider.read", "provider.configure"), False, False),
        (True, ("provider.read",), True, False),
    ],
)
def test_payment_provider_navigation_requires_effective_access(tef_enabled, permissions, store_disabled, visible):
    with Session(engine) as session:
        set_platform_db_context(session)
        contribution = session.exec(select(ModuleContribution).where(
            ModuleContribution.surface == "MANAGEMENT_NAV",
            ModuleContribution.contribution_key == "payment_providers",
        )).one()
        assert contribution.implementation_key == "payment_providers"
        assert contribution.permission_key == "provider.read"
        assert contribution.capability_key == "tef"
        assert contribution.is_active

        tenant = Tenant(name="Provider navigation test", slug=f"provider-nav-{uuid.uuid4().hex}")
        session.add(tenant)
        session.flush()
        store = Store(tenant_id=tenant.id, name="Principal", code="MAIN")
        session.add(store)
        session.add(TenantCapability(tenant_id=tenant.id, key="tef", enabled=tef_enabled))
        session.flush()
        if store_disabled:
            session.add(StoreCapabilityOverride(tenant_id=tenant.id, store_id=store.id, key="tef", enabled=False))
            session.flush()
        context = TenantContext(tenant_id=tenant.id, store_id=store.id, permissions=permissions)
        set_tenant_db_context(session, tenant.id, store.id)
        effective = get_effective_capabilities(context=context, session=session)
        navigation = {item.implementation_key for item in effective["contributions"] if item.surface == "MANAGEMENT_NAV"}
        assert ("payment_providers" in navigation) is visible
        # No commit: every parametrized scenario leaves the database unchanged.

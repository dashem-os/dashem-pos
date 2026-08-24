from typing import Any, Optional

from sqlmodel import Session, select

from app.models.platform import EntitlementStatusEnum, StoreCapabilityOverride, TenantCapability
from app.modules.capabilities.registry import CAPABILITY_REGISTRY, resolve_dependencies


def effective_capabilities(session: Session, tenant_id, store_id: Optional[object] = None) -> dict[str, dict[str, Any]]:
    entitlements = session.exec(
        select(TenantCapability).where(
            TenantCapability.tenant_id == tenant_id,
            TenantCapability.enabled.is_(True),
            TenantCapability.status.in_({EntitlementStatusEnum.CONFIGURED, EntitlementStatusEnum.ACTIVE}),
        )
    ).all()
    enabled = {item.key: dict(item.configuration) for item in entitlements if item.key in CAPABILITY_REGISTRY}
    if store_id:
        overrides = session.exec(
            select(StoreCapabilityOverride).where(
                StoreCapabilityOverride.tenant_id == tenant_id,
                StoreCapabilityOverride.store_id == store_id,
            )
        ).all()
        for override in overrides:
            # A store override can narrow or configure a contracted entitlement;
            # it can never mint a tenant entitlement by itself.
            if override.key not in enabled:
                continue
            if override.enabled:
                enabled[override.key] = {**enabled.get(override.key, {}), **override.configuration}
            else:
                enabled.pop(override.key, None)
    resolved = resolve_dependencies(enabled)
    return {
        key: {
            "key": key,
            "version": CAPABILITY_REGISTRY[key].version,
            "scope": CAPABILITY_REGISTRY[key].scope.value,
            "configuration": enabled.get(key, {}),
            "inherited": key not in enabled,
        }
        for key in resolved
    }

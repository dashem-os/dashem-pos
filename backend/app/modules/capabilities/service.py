from typing import Any, Optional

from sqlmodel import Session, select

from app.models.platform import EntitlementStatusEnum, StoreCapabilityOverride, TenantCapability
from app.modules.capabilities.registry import CAPABILITY_REGISTRY, resolve_dependencies
from app.services.contract_entitlement_service import resolve_contract_entitlements


TABLE_SERVICE_ACTIVITY = "FOOD_SERVICE"


def capability_allowed_by_activity(session: Session, tenant_id, capability_key: str) -> bool:
    """Return whether a contracted capability is coherent with tenant activities.

    The activity list is part of the immutable contract snapshot.  A table
    journey is a food-service concern; a permission or a stale capability row
    must never publish it for a retail/beauty tenant.  Pre-contract tenants are
    kept readable through the explicit legacy path until they receive a
    contract snapshot.
    """
    if capability_key != "table_service":
        return True
    snapshot = resolve_contract_entitlements(session, tenant_id)
    return snapshot is None or TABLE_SERVICE_ACTIVITY in snapshot.activity_keys


def effective_capabilities(session: Session, tenant_id, store_id: Optional[object] = None) -> dict[str, dict[str, Any]]:
    entitlements = session.exec(
        select(TenantCapability).where(
            TenantCapability.tenant_id == tenant_id,
            TenantCapability.enabled.is_(True),
            TenantCapability.status.in_({EntitlementStatusEnum.CONFIGURED, EntitlementStatusEnum.ACTIVE}),
        )
    ).all()
    persisted = {item.key: dict(item.configuration) for item in entitlements if item.key in CAPABILITY_REGISTRY}
    snapshot = resolve_contract_entitlements(session, tenant_id)
    if snapshot is not None:
        enabled = {
            key: persisted.get(key, {})
            for key in snapshot.capability_keys
            if key in CAPABILITY_REGISTRY
        }
    else:
        # Pre-contract tenants remain readable from their persisted grants. This
        # is explicit legacy state, never an inference from the current plan.
        enabled = persisted
    enabled = {
        key: value
        for key, value in enabled.items()
        if capability_allowed_by_activity(session, tenant_id, key)
    }
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
    resolved = tuple(enabled) if snapshot is not None else resolve_dependencies(enabled)
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

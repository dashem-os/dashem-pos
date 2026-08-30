"""Canonical read/write boundary for immutable tenant entitlement snapshots."""

import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from sqlmodel import Session, select

from app.models.platform import TenantContract


@dataclass(frozen=True)
class ResolvedContractEntitlements:
    tenant_id: uuid.UUID
    contract_id: uuid.UUID
    contract_version: int
    plan_revision_id: uuid.UUID | None
    schema_version: int
    activity_keys: tuple[str, ...]
    capability_keys: tuple[str, ...]
    capability_entitlements: tuple[Mapping[str, Any], ...]
    limit_entitlements: Mapping[str, Any]
    storage_entitlement: Mapping[str, Any]


def build_entitlement_snapshot(
    *,
    proposal: Mapping[str, Any],
    users: int,
    devices: int,
    units: int,
    storage_mb: int,
) -> dict[str, Any]:
    """Build columns copied into a contract; no mutable catalog lookup is needed later."""

    capabilities = [
        {
            "key": item["key"],
            "sources": sorted(set(item["sources"]) | {"OWNER_DECISION"}),
            "activity_keys": list(item.get("activity_keys", [])),
        }
        for item in proposal["capabilities"]
    ]
    limit_entitlements = {
        resource: {
            "limit": value,
            "sources": ["PLAN", "OWNER_DECISION"],
        }
        for resource, value in (
            ("users", users),
            ("devices", devices),
            ("units", units),
        )
    }
    return {
        "activity_keys": list(proposal["activity_keys"]),
        "capability_keys": [item["key"] for item in capabilities],
        "capability_entitlements": capabilities,
        "limit_entitlements": limit_entitlements,
        "storage_entitlement": {
            "limit_mb": storage_mb,
            "sources": ["PLAN", "OWNER_DECISION"],
            "measurement_status": "NOT_MEASURED",
        },
        "schema_version": 2,
    }


def latest_contract(session: Session, tenant_id: uuid.UUID) -> TenantContract | None:
    return session.exec(
        select(TenantContract)
        .where(TenantContract.tenant_id == tenant_id)
        .order_by(TenantContract.version.desc())
    ).first()


def resolve_contract_entitlements(
    session: Session, tenant_id: uuid.UUID
) -> ResolvedContractEntitlements | None:
    contract = latest_contract(session, tenant_id)
    if contract is None:
        return None
    capability_keys = tuple(
        str(item["key"])
        for item in contract.capability_entitlements
        if isinstance(item, dict) and item.get("key")
    )
    if not capability_keys:
        capability_keys = tuple(contract.capability_keys)
    activity_keys = tuple(contract.activity_keys)
    if not activity_keys:
        activity_keys = tuple(contract.limits.get("business_niches", []))
    return ResolvedContractEntitlements(
        tenant_id=tenant_id,
        contract_id=contract.id,
        contract_version=contract.version,
        plan_revision_id=contract.plan_revision_id,
        schema_version=contract.schema_version,
        activity_keys=activity_keys,
        capability_keys=capability_keys,
        capability_entitlements=tuple(contract.capability_entitlements),
        limit_entitlements=dict(contract.limit_entitlements),
        storage_entitlement=dict(contract.storage_entitlement),
    )


def contracted_limit(
    session: Session, tenant_id: uuid.UUID, resource: str
) -> int | None:
    if resource not in {"users", "devices", "units"}:
        raise ValueError(f"Unsupported contractual resource: {resource}")
    snapshot = resolve_contract_entitlements(session, tenant_id)
    if snapshot is None:
        return None
    entitlement = snapshot.limit_entitlements.get(resource)
    if not isinstance(entitlement, dict):
        return None
    value = entitlement.get("limit")
    return int(value) if value is not None else None

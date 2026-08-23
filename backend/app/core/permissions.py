from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlmodel import Session, select

from app.models.identity import (
    Membership,
    MembershipRoleProfile,
    Permission,
    PermissionGrant,
    PermissionGrantEffectEnum,
    RoleProfile,
    RoleProfilePermission,
)
from app.modules.capabilities.service import effective_capabilities


@dataclass(frozen=True)
class RouteRequirement:
    permission: str


@dataclass(frozen=True)
class EffectiveAccess:
    permissions: tuple[str, ...]
    capabilities: tuple[str, ...]


def route_requirement(method: str, path: str) -> RouteRequirement:
    method = method.upper()
    if path == "/api/v1/capabilities/effective":
        return RouteRequirement("capability.read")
    if path.startswith("/api/v1/team"):
        return RouteRequirement("team.read" if method == "GET" else "team.manage")
    if path.startswith("/api/v1/catalog"):
        return RouteRequirement("catalog.read" if method == "GET" else "catalog.update")
    if path.startswith("/api/v1/inventory"):
        return RouteRequirement("inventory.read" if method == "GET" else "inventory.adjust")
    if path.startswith("/api/v1/sales/customers"):
        return RouteRequirement("customer.read" if method == "GET" else "customer.update")
    if path.startswith("/api/v1/sales"):
        if method == "GET":
            return RouteRequirement("sale.read")
        if path.endswith("/discount"):
            return RouteRequirement("sale.discount")
        if path.endswith("/cancel"):
            return RouteRequirement("sale.cancel")
        if path.endswith("/checkout"):
            return RouteRequirement("sale.checkout")
        if "/items" in path:
            return RouteRequirement("sale.item.update")
        return RouteRequirement("sale.create")
    if path.startswith("/api/v1/cash"):
        if method == "GET":
            return RouteRequirement("cash.read")
        if path.endswith("/registers"):
            return RouteRequirement("cash.configure")
        if path.endswith("/open"):
            return RouteRequirement("cash.open")
        if path.endswith("/close"):
            return RouteRequirement("cash.close")
        if path.endswith("/movements"):
            return RouteRequirement("cash.move")
    if path.startswith("/api/v1/payments"):
        if method == "GET":
            return RouteRequirement("payment.read")
        return RouteRequirement("payment.confirm" if path.endswith("/confirm") else "payment.create")
    if path.startswith("/api/v1/fiscal"):
        if method == "GET":
            return RouteRequirement("fiscal.read")
        if path.endswith("/cancel"):
            return RouteRequirement("fiscal.cancel")
        return RouteRequirement("fiscal.issue")
    raise HTTPException(status_code=403, detail="No canonical permission protects this operation.")


def _profile_permissions(session: Session, membership: Membership) -> set[str]:
    system_profile = session.exec(
        select(RoleProfile).where(
            RoleProfile.tenant_id.is_(None),
            RoleProfile.code == getattr(membership.role, "value", str(membership.role)),
            RoleProfile.is_system.is_(True),
            RoleProfile.is_active.is_(True),
        )
    ).first()
    profile_ids = [system_profile.id] if system_profile else []
    assigned = session.exec(
        select(MembershipRoleProfile).where(MembershipRoleProfile.membership_id == membership.id)
    ).all()
    profile_ids.extend(item.role_profile_id for item in assigned)
    if not profile_ids:
        return set()
    return set(session.exec(
        select(RoleProfilePermission.permission_key).where(
            RoleProfilePermission.role_profile_id.in_(profile_ids)
        )
    ).all())


def effective_access(
    session: Session,
    membership: Membership,
    store_id: Optional[object],
) -> EffectiveAccess:
    permissions = _profile_permissions(session, membership)
    grants_query = select(PermissionGrant).where(
        PermissionGrant.membership_id == membership.id,
        PermissionGrant.tenant_id == membership.tenant_id,
    )
    if store_id:
        grants_query = grants_query.where(
            or_(PermissionGrant.store_id.is_(None), PermissionGrant.store_id == store_id)
        )
    else:
        grants_query = grants_query.where(PermissionGrant.store_id.is_(None))
    grants = session.exec(grants_query).all()
    for grant in grants:
        if PermissionGrantEffectEnum(grant.effect) == PermissionGrantEffectEnum.DENY:
            permissions.discard(grant.permission_key)
        else:
            permissions.add(grant.permission_key)
    capabilities = tuple(sorted(effective_capabilities(session, membership.tenant_id, store_id)))
    return EffectiveAccess(tuple(sorted(permissions)), capabilities)


def enforce_effective_access(
    session: Session,
    membership: Membership,
    store_id: Optional[object],
    method: str,
    path: str,
) -> EffectiveAccess:
    requirement = route_requirement(method, path)
    access = effective_access(session, membership, store_id)
    if requirement.permission not in access.permissions:
        raise HTTPException(status_code=403, detail=f"Missing permission: {requirement.permission}")
    permission = session.get(Permission, requirement.permission)
    if not permission:
        raise HTTPException(status_code=403, detail="Permission contract is unavailable.")
    if permission.capability_key and permission.capability_key not in access.capabilities:
        raise HTTPException(status_code=403, detail=f"Capability is not contracted: {permission.capability_key}")
    return access

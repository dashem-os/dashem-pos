from typing import Iterable, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.context import resolve_internal_user
from app.core.security import AuthPrincipal
from app.core.tenancy import set_platform_db_context, set_tenant_db_context, set_user_db_context
from app.models.identity import Membership, MembershipStatusEnum, RoleEnum, User
from app.models.platform import (
    PlatformMembership, PlatformPermissionDefinition, PlatformPermissionGrant,
    PlatformRoleEnum, PlatformRolePermission,
)


def get_request_user(session: Session, principal: AuthPrincipal) -> Optional[User]:
    user = resolve_internal_user(session, principal)
    set_user_db_context(session, user.id if user else principal.legacy_user_id)
    return user


def get_platform_membership(
    session: Session, principal: AuthPrincipal
) -> Optional[PlatformMembership]:
    if principal.bypass:
        return None
    user = resolve_internal_user(session, principal)
    assert user is not None
    return session.exec(
        select(PlatformMembership).where(
            PlatformMembership.user_id == user.id,
            PlatformMembership.is_active.is_(True),
        )
    ).first()


def require_platform_role(
    session: Session,
    principal: AuthPrincipal,
    allowed: Iterable[PlatformRoleEnum],
    require_aal2: bool = False,
) -> Optional[User]:
    if principal.bypass:
        set_platform_db_context(session, principal.legacy_user_id)
        return get_request_user(session, principal)
    membership = get_platform_membership(session, principal)
    if not membership or PlatformRoleEnum(membership.role) not in set(allowed):
        raise HTTPException(status_code=403, detail="Platform role does not allow this operation.")
    if require_aal2 and principal.assurance_level != "aal2":
        raise HTTPException(status_code=403, detail="Multi-factor authentication is required.")
    user = resolve_internal_user(session, principal)
    set_platform_db_context(session, user.id if user else None)
    return user


def require_platform_permission(
    session: Session,
    principal: AuthPrincipal,
    permission_key: str,
    require_aal2: bool = False,
) -> Optional[User]:
    """Authorize a Control-plane permission with explicit membership overrides."""
    if principal.bypass:
        set_platform_db_context(session, principal.legacy_user_id)
        return get_request_user(session, principal)

    membership = get_platform_membership(session, principal)
    if membership is None:
        raise HTTPException(status_code=403, detail="Platform access is required.")

    user = resolve_internal_user(session, principal)
    assert user is not None
    set_platform_db_context(session, user.id)

    definition = session.get(PlatformPermissionDefinition, permission_key)
    if definition is None:
        raise HTTPException(status_code=403, detail="Platform permission is not available.")

    grant = session.exec(
        select(PlatformPermissionGrant).where(
            PlatformPermissionGrant.platform_membership_id == membership.id,
            PlatformPermissionGrant.permission_key == permission_key,
        )
    ).first()
    if grant is not None:
        allowed = grant.allowed
    else:
        role = getattr(membership.role, "value", str(membership.role))
        allowed = session.exec(
            select(PlatformRolePermission.id).where(
                PlatformRolePermission.role == role,
                PlatformRolePermission.permission_key == permission_key,
            )
        ).first() is not None

    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Platform permission {permission_key} is required.",
        )
    if require_aal2 and principal.assurance_level != "aal2":
        raise HTTPException(status_code=403, detail="Multi-factor authentication is required.")
    return user


def require_tenant_admin(
    session: Session,
    principal: AuthPrincipal,
    tenant_id,
) -> Optional[User]:
    if principal.bypass:
        set_tenant_db_context(session, tenant_id, user_id=principal.legacy_user_id)
        return resolve_internal_user(session, principal)
    user = resolve_internal_user(session, principal)
    assert user is not None
    set_tenant_db_context(session, tenant_id, user_id=user.id)
    membership = session.exec(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.tenant_id == tenant_id,
            Membership.store_id.is_(None),
            Membership.status == MembershipStatusEnum.ACTIVE,
        )
    ).first()
    if not membership or RoleEnum(membership.role) not in {
        RoleEnum.OWNER, RoleEnum.TENANT_OWNER, RoleEnum.ADMIN,
    }:
        raise HTTPException(status_code=403, detail="Tenant administrator role is required.")
    return user

from typing import Iterable, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.context import resolve_internal_user
from app.core.security import AuthPrincipal
from app.models.identity import Membership, MembershipStatusEnum, RoleEnum, User
from app.models.platform import PlatformMembership, PlatformRoleEnum


def get_request_user(session: Session, principal: AuthPrincipal) -> Optional[User]:
    return resolve_internal_user(session, principal)


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
        return get_request_user(session, principal)
    membership = get_platform_membership(session, principal)
    if not membership or PlatformRoleEnum(membership.role) not in set(allowed):
        raise HTTPException(status_code=403, detail="Platform role does not allow this operation.")
    if require_aal2 and principal.assurance_level != "aal2":
        raise HTTPException(status_code=403, detail="Multi-factor authentication is required.")
    return resolve_internal_user(session, principal)


def require_tenant_admin(
    session: Session,
    principal: AuthPrincipal,
    tenant_id,
) -> Optional[User]:
    if principal.bypass:
        return get_request_user(session, principal)
    user = resolve_internal_user(session, principal)
    assert user is not None
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

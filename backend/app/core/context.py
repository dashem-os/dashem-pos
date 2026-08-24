import uuid
from typing import Optional, Type, TypeVar

from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlmodel import Session, select
from sqlmodel.sql.expression import SelectOfScalar

from app.core.database import get_session
from app.core.permissions import enforce_effective_access
from app.core.security import AuthPrincipal, get_current_principal
from app.core.tenancy import set_tenant_db_context
from app.models.identity import (
    AuthIdentity, Membership, MembershipStatusEnum, RoleEnum, Store, Tenant,
    TenantStatusEnum, User,
)


class TenantContext(BaseModel):
    tenant_id: uuid.UUID
    store_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None
    role: Optional[RoleEnum] = None
    membership_id: Optional[uuid.UUID] = None
    permissions: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    auth_subject: Optional[str] = None
    assurance_level: str = "aal1"


def _parse_uuid(value: Optional[str], header: str, required: bool = False) -> Optional[uuid.UUID]:
    if not value:
        if required:
            raise HTTPException(status_code=400, detail=f"Header '{header}' is required.")
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {header} UUID.") from exc


def resolve_internal_user(session: Session, principal: AuthPrincipal) -> Optional[User]:
    if principal.bypass:
        return session.get(User, principal.legacy_user_id) if principal.legacy_user_id else None

    if principal.provider == "operational":
        user = session.get(User, principal.legacy_user_id) if principal.legacy_user_id else None
        if not user or not user.is_active:
            raise HTTPException(status_code=403, detail="Operational identity is inactive or unavailable.")
        return user

    identity = session.exec(
        select(AuthIdentity).where(
            AuthIdentity.provider == "supabase",
            AuthIdentity.provider_subject == principal.subject,
        )
    ).first()
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated identity has not been provisioned in Dashem POS.",
        )
    user = session.get(User, identity.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive or unavailable.")
    return user


def authorize_tenant_context(
    session: Session,
    principal: AuthPrincipal,
    tenant_id: uuid.UUID,
    store_id: Optional[uuid.UUID],
    method: str,
    path: str,
) -> TenantContext:
    if principal.bypass:
        set_tenant_db_context(session, tenant_id, store_id, principal.legacy_user_id)
        return TenantContext(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=principal.legacy_user_id,
            auth_subject=principal.subject,
        )

    user = resolve_internal_user(session, principal)
    assert user is not None
    if principal.provider == "operational":
        claims = principal.claims
        if claims.get("tenant_id") != str(tenant_id):
            raise HTTPException(status_code=403, detail="Operational session belongs to another tenant.")
        token_store_id = claims.get("store_id")
        if not store_id or token_store_id != str(store_id):
            raise HTTPException(status_code=403, detail="Operational session belongs to another store.")
    set_tenant_db_context(session, tenant_id, store_id, user.id)
    tenant = session.get(Tenant, tenant_id)
    if not tenant or tenant.status not in {TenantStatusEnum.TRIAL, TenantStatusEnum.ACTIVE}:
        raise HTTPException(status_code=403, detail="Tenant is unavailable.")

    if store_id:
        store = session.get(Store, store_id)
        if not store or store.tenant_id != tenant_id or not store.is_active:
            raise HTTPException(status_code=403, detail="Store does not belong to the active tenant.")

    membership_query = select(Membership).where(
        Membership.user_id == user.id,
        Membership.tenant_id == tenant_id,
        Membership.status == MembershipStatusEnum.ACTIVE,
    )
    if principal.provider == "operational":
        try:
            membership_query = membership_query.where(Membership.id == uuid.UUID(str(principal.claims.get("membership_id"))))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="Operational session has no valid membership.") from exc
    if store_id:
        membership_query = membership_query.where(
            or_(Membership.store_id.is_(None), Membership.store_id == store_id)
        )
    else:
        membership_query = membership_query.where(Membership.store_id.is_(None))
    membership = session.exec(membership_query).first()
    if not membership:
        raise HTTPException(status_code=403, detail="No active membership for this tenant and store.")

    role = RoleEnum(membership.role)
    access = enforce_effective_access(session, membership, store_id, method, path)
    return TenantContext(
        tenant_id=tenant_id,
        store_id=store_id,
        user_id=user.id,
        role=role,
        membership_id=membership.id,
        permissions=access.permissions,
        capabilities=access.capabilities,
        auth_subject=principal.subject,
        assurance_level=principal.assurance_level,
    )


def get_tenant_context(
    request: Request,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    x_store_id: Optional[str] = Header(None, alias="X-Store-ID"),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> TenantContext:
    tenant_id = _parse_uuid(x_tenant_id, "X-Tenant-ID", required=True)
    store_id = _parse_uuid(x_store_id, "X-Store-ID")
    assert tenant_id is not None
    return authorize_tenant_context(
        session, principal, tenant_id, store_id, request.method, request.url.path
    )


T = TypeVar("T")


def scope_tenant_query(
    query: SelectOfScalar[T], model_class: Type[T], context: TenantContext
) -> SelectOfScalar[T]:
    if hasattr(model_class, "tenant_id"):
        query = query.where(getattr(model_class, "tenant_id") == context.tenant_id)
    if context.store_id and hasattr(model_class, "store_id"):
        query = query.where(getattr(model_class, "store_id") == context.store_id)
    return query

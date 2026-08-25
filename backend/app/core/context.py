import uuid
from datetime import datetime
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
    AuthIdentity, Employee, EmployeeStatusEnum, Membership, MembershipStatusEnum,
    OperationalCredential, OperationalSession, OperationalSessionStatusEnum,
    RoleEnum, Store, Tenant, TenantStatusEnum, User,
)
from app.models.device import OperationalDevice, OperationalDeviceStatusEnum
from app.services.operational_session_service import mark_expired


LOCAL_BYPASS_ACTOR_ID = uuid.uuid5(uuid.NAMESPACE_URL, "dashem-pos:local-auth-bypass")


class TenantContext(BaseModel):
    tenant_id: uuid.UUID
    store_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None
    role: Optional[RoleEnum] = None
    membership_id: Optional[uuid.UUID] = None
    permissions: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    auth_subject: Optional[str] = None
    auth_provider: Optional[str] = None
    assurance_level: str = "aal1"
    device_id: Optional[uuid.UUID] = None
    register_id: Optional[uuid.UUID] = None
    operational_session_id: Optional[uuid.UUID] = None


def resolve_actor(
    context: TenantContext,
    claimed_actor_id: Optional[uuid.UUID] = None,
) -> uuid.UUID:
    """Resolve mutation authorship from the authenticated server context.

    A caller-supplied actor is accepted only as a compatibility assertion and
    must match the authenticated principal.  The sole exception is the
    explicitly disabled local-auth mode used by the integration test suite;
    it never applies to an authenticated deployment.
    """
    if context.user_id:
        if claimed_actor_id and claimed_actor_id != context.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ator não corresponde à identidade autenticada.",
            )
        return context.user_id
    if context.auth_subject == "local-auth-bypass":
        return claimed_actor_id or LOCAL_BYPASS_ACTOR_ID
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A operação exige uma identidade autenticada.",
    )


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
            auth_provider=principal.provider,
        )

    user = resolve_internal_user(session, principal)
    assert user is not None
    # Establish a restrictive RLS scope before validating any tenant-owned
    # infrastructure referenced by an operational token.
    set_tenant_db_context(session, tenant_id, store_id, user.id)
    if principal.provider == "operational":
        claims = principal.claims
        if claims.get("tenant_id") != str(tenant_id):
            raise HTTPException(status_code=403, detail="Operational session belongs to another tenant.")
        token_store_id = claims.get("store_id")
        if not store_id or token_store_id != str(store_id):
            raise HTTPException(status_code=403, detail="Operational session belongs to another store.")
        try:
            device_id = uuid.UUID(str(claims["device_id"]))
            register_id = uuid.UUID(str(claims["register_id"]))
            session_id = uuid.UUID(str(claims["session_id"]))
            credential_id = uuid.UUID(str(claims["credential_id"]))
            membership_id = uuid.UUID(str(claims["membership_id"]))
            terminal_version = int(claims["terminal_authorization_version"])
            credential_version = int(claims["credential_version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="Operational session has no valid authority context.") from exc
        device = session.get(OperationalDevice, device_id)
        authority = session.get(OperationalSession, session_id)
        credential = session.get(OperationalCredential, credential_id)
        employee = session.get(Employee, credential.employee_id) if credential else None
        if authority and mark_expired(session, authority):
            session.commit()
            raise HTTPException(status_code=403, detail="Operational authority was ended, revoked, expired or changed.")
        if (
            not device or device.tenant_id != tenant_id or device.store_id != store_id
            or device.status != OperationalDeviceStatusEnum.ACTIVE or device.register_id != register_id
            or device.authorization_version != terminal_version
            or not device.authorization_expires_at or device.authorization_expires_at <= datetime.utcnow()
            or not authority or authority.status != OperationalSessionStatusEnum.ACTIVE
            or authority.expires_at <= datetime.utcnow() or authority.tenant_id != tenant_id
            or authority.store_id != store_id or authority.device_id != device_id
            or authority.register_id != register_id or authority.user_id != user.id
            or authority.membership_id != membership_id or authority.credential_id != credential_id
            or authority.terminal_authorization_version != terminal_version
            or authority.credential_version != credential_version
            or not credential or credential.tenant_id != tenant_id or credential.store_id != store_id
            or credential.user_id != user.id or credential.membership_id != membership_id
            or credential.session_version != credential_version
            or not employee or employee.tenant_id != tenant_id or employee.user_id != user.id
            or employee.status != EmployeeStatusEnum.ACTIVE
        ):
            raise HTTPException(status_code=403, detail="Operational authority was ended, revoked, expired or changed.")
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
        membership_query = membership_query.where(Membership.id == membership_id)
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
    operational_claims = principal.claims if principal.provider == "operational" else {}
    return TenantContext(
        tenant_id=tenant_id,
        store_id=store_id,
        user_id=user.id,
        role=role,
        membership_id=membership.id,
        permissions=access.permissions,
        capabilities=access.capabilities,
        auth_subject=principal.subject,
        auth_provider=principal.provider,
        assurance_level=principal.assurance_level,
        device_id=uuid.UUID(operational_claims["device_id"]) if operational_claims.get("device_id") else None,
        register_id=uuid.UUID(operational_claims["register_id"]) if operational_claims.get("register_id") else None,
        operational_session_id=uuid.UUID(operational_claims["session_id"]) if operational_claims.get("session_id") else None,
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

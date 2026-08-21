import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import or_
from sqlmodel import Session, select

from app.core.access import (
    get_platform_membership, get_request_user, require_platform_role,
    require_tenant_admin,
)
from app.core.database import get_session
from app.core.security import AuthPrincipal, get_current_principal
from app.models.identity import (
    Membership, MembershipStatusEnum, RoleEnum, Store, Tenant, TenantStatusEnum, User,
)
from app.models.platform import Lead, LeadStatusEnum, PlatformRoleEnum
from app.services import identity_service, reliability_service


router = APIRouter(dependencies=[Depends(get_current_principal)])
PLATFORM_MANAGERS = {PlatformRoleEnum.PLATFORM_OWNER, PlatformRoleEnum.PLATFORM_ADMIN}


class TenantCreate(BaseModel):
    name: str
    slug: str


class PlatformTenantCreate(BaseModel):
    name: str = PydanticField(min_length=2, max_length=160)
    slug: str = PydanticField(
        min_length=3,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    first_store_name: str = PydanticField(min_length=2, max_length=160)
    first_store_code: str = PydanticField(min_length=2, max_length=40)


class PlatformTenantRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    created_at: datetime
    store_count: int


class PlatformOverview(BaseModel):
    tenant_count: int
    trial_count: int
    active_count: int
    lead_count: int
    tenants: List[PlatformTenantRead]


class PlatformTenantProvisioned(BaseModel):
    tenant: Tenant
    first_store: Store


class StoreCreate(BaseModel):
    tenant_id: uuid.UUID
    name: str
    code: str


class UserCreate(BaseModel):
    email: str
    full_name: str
    provider_subject: Optional[str] = None
    password: Optional[str] = None  # ignored; temporary request compatibility only


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool


class MembershipCreate(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: Optional[uuid.UUID] = None
    role: RoleEnum


class TestMutationRequest(BaseModel):
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    actor_id: uuid.UUID
    action_name: str
    payload_data: str


def _platform_or_tenant_admin(
    session: Session, principal: AuthPrincipal, tenant_id: uuid.UUID
) -> None:
    if principal.bypass:
        return
    platform = get_platform_membership(session, principal)
    if platform and PlatformRoleEnum(platform.role) in PLATFORM_MANAGERS:
        return
    require_tenant_admin(session, principal, tenant_id)


@router.get("/me")
def get_me(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    user = get_request_user(session, principal)
    if principal.bypass and not user:
        return {"mode": "local-bypass", "user": None, "platform_role": None, "memberships": []}
    assert user is not None
    platform = get_platform_membership(session, principal)
    memberships = session.exec(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.status == MembershipStatusEnum.ACTIVE,
        )
    ).all()
    return {
        "mode": "authenticated",
        "user": UserRead.model_validate(user),
        "platform_role": platform.role if platform else None,
        "memberships": memberships,
        "assurance_level": principal.assurance_level,
        "auth_provider": principal.provider,
        "password_setup_required": principal.provider == "email" and user.password_setup_completed_at is None,
        "mfa_required": bool(
            platform
            and PlatformRoleEnum(platform.role) in PLATFORM_MANAGERS
            and principal.assurance_level != "aal2"
        ),
        "onboarding_completed": user.onboarding_completed_at is not None,
    }


@router.post("/me/password-setup-complete", response_model=UserRead)
def complete_password_setup(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    user = get_request_user(session, principal)
    assert user is not None
    if principal.provider != "email":
        raise HTTPException(status_code=409, detail="Password setup is not required for this provider.")
    return identity_service.mark_password_setup_completed(session, user)


@router.post("/me/onboarding-complete", response_model=UserRead)
def complete_owner_onboarding(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    user = require_platform_role(
        session, principal, PLATFORM_MANAGERS, require_aal2=True
    )
    assert user is not None
    if principal.provider == "email" and user.password_setup_completed_at is None:
        raise HTTPException(status_code=409, detail="Password setup is required first.")
    return identity_service.mark_onboarding_completed(session, user)


@router.get("/platform/overview", response_model=PlatformOverview)
def platform_overview(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    tenants = session.exec(select(Tenant).order_by(Tenant.created_at.desc())).all()
    stores = session.exec(select(Store)).all()
    store_counts: dict[uuid.UUID, int] = {}
    for store in stores:
        store_counts[store.tenant_id] = store_counts.get(store.tenant_id, 0) + 1
    leads = session.exec(select(Lead).where(Lead.status != LeadStatusEnum.LOST)).all()
    return PlatformOverview(
        tenant_count=len(tenants),
        trial_count=sum(1 for tenant in tenants if tenant.status == TenantStatusEnum.TRIAL),
        active_count=sum(1 for tenant in tenants if tenant.status == TenantStatusEnum.ACTIVE),
        lead_count=len(leads),
        tenants=[
            PlatformTenantRead(
                id=tenant.id,
                name=tenant.name,
                slug=tenant.slug,
                status=getattr(tenant.status, "value", str(tenant.status)),
                created_at=tenant.created_at,
                store_count=store_counts.get(tenant.id, 0),
            )
            for tenant in tenants
        ],
    )


@router.post("/platform/tenants", response_model=PlatformTenantProvisioned, status_code=201)
def provision_platform_tenant(
    data: PlatformTenantCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    user = require_platform_role(
        session, principal, PLATFORM_MANAGERS, require_aal2=True
    )
    assert user is not None
    tenant, store = identity_service.provision_tenant(
        session,
        name=data.name.strip(),
        slug=data.slug,
        first_store_name=data.first_store_name.strip(),
        first_store_code=data.first_store_code.strip().upper(),
        actor_id=user.id,
    )
    return PlatformTenantProvisioned(tenant=tenant, first_store=store)


@router.post("/tenants", response_model=Tenant)
def create_tenant_endpoint(
    data: TenantCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    return identity_service.create_tenant(session, name=data.name, slug=data.slug)


@router.get("/tenants", response_model=List[Tenant])
def list_tenants(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    platform = get_platform_membership(session, principal)
    if principal.bypass:
        return session.exec(select(Tenant)).all()
    if platform:
        require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
        return session.exec(select(Tenant)).all()
    user = get_request_user(session, principal)
    assert user is not None
    return session.exec(
        select(Tenant).join(Membership).where(
            Membership.user_id == user.id,
            Membership.status == MembershipStatusEnum.ACTIVE,
        ).distinct()
    ).all()


@router.post("/stores", response_model=Store)
def create_store_endpoint(
    data: StoreCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _platform_or_tenant_admin(session, principal, data.tenant_id)
    return identity_service.create_store(session, data.tenant_id, data.name, data.code)


@router.get("/stores", response_model=List[Store])
def list_stores(
    tenant_id: Optional[uuid.UUID] = None,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    if principal.bypass or get_platform_membership(session, principal):
        query = select(Store)
        return session.exec(query.where(Store.tenant_id == tenant_id) if tenant_id else query).all()
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="tenant_id is required.")
    user = get_request_user(session, principal)
    assert user is not None
    memberships = session.exec(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.tenant_id == tenant_id,
            Membership.status == MembershipStatusEnum.ACTIVE,
        )
    ).all()
    if not memberships:
        raise HTTPException(status_code=403, detail="No active membership for this tenant.")
    if any(m.store_id is None for m in memberships):
        return session.exec(select(Store).where(Store.tenant_id == tenant_id)).all()
    allowed_store_ids = [m.store_id for m in memberships if m.store_id]
    return session.exec(
        select(Store).where(Store.tenant_id == tenant_id, Store.id.in_(allowed_store_ids))
    ).all()


@router.post("/users", response_model=UserRead)
def create_user_endpoint(
    data: UserCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    return identity_service.create_user(session, data.email, data.full_name, data.provider_subject)


@router.get("/users", response_model=List[UserRead])
def list_users(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS)
    return session.exec(select(User)).all()


@router.post("/memberships", response_model=Membership)
def create_membership_endpoint(
    data: MembershipCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _platform_or_tenant_admin(session, principal, data.tenant_id)
    return identity_service.create_membership(
        session, data.user_id, data.tenant_id, data.store_id, data.role
    )


@router.get("/memberships", response_model=List[Membership])
def list_memberships(
    user_id: Optional[uuid.UUID] = None,
    tenant_id: Optional[uuid.UUID] = None,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    if tenant_id:
        _platform_or_tenant_admin(session, principal, tenant_id)
    else:
        require_platform_role(session, principal, PLATFORM_MANAGERS)
    query = select(Membership)
    if user_id:
        query = query.where(Membership.user_id == user_id)
    if tenant_id:
        query = query.where(Membership.tenant_id == tenant_id)
    return session.exec(query).all()


@router.post("/test-atomic-mutation", include_in_schema=False)
def test_atomic_mutation_endpoint(
    data: TestMutationRequest,
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    if not principal.bypass:
        raise HTTPException(status_code=404, detail="Not found.")
    if x_idempotency_key:
        is_cached, status_code, body = reliability_service.check_idempotency(
            session, data.tenant_id, data.actor_id, "POST /test-atomic-mutation",
            x_idempotency_key, data.model_dump(),
        )
        if is_cached and status_code and body:
            return body
    audit, outbox = reliability_service.write_audit_and_outbox(
        session=session, tenant_id=data.tenant_id, store_id=data.store_id,
        actor_id=data.actor_id, action=data.action_name,
        target=f"MUTATION-{uuid.uuid4().hex[:6]}",
        audit_payload={"data": data.payload_data}, aggregate_type="test_aggregate",
        aggregate_id=str(uuid.uuid4()), event_type="test.mutated",
        outbox_payload={"data": data.payload_data}, correlation_id=x_correlation_id,
    )
    response = {"status": "success", "audit_id": str(audit.id), "outbox_id": str(outbox.id), "correlation_id": x_correlation_id}
    if x_idempotency_key:
        response = reliability_service.save_idempotency_record(
            session, data.tenant_id, data.actor_id, "POST /test-atomic-mutation",
            x_idempotency_key, data.model_dump(), 200, response,
        )
    session.commit()
    return response

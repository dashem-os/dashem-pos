import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlmodel import Session, select

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.identity import (
    Membership,
    MembershipStatusEnum,
    RoleEnum,
    ServicePlan,
    Store,
    Tenant,
    TenantSubscription,
    User,
)
from app.services import identity_service, reliability_service, supabase_admin


router = APIRouter()


class TeamMemberRead(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: str
    role: RoleEnum
    status: MembershipStatusEnum
    store_id: Optional[uuid.UUID] = None
    store_name: Optional[str] = None


class TeamInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = PydanticField(min_length=5, max_length=254)
    full_name: str = PydanticField(min_length=2, max_length=160)
    role: RoleEnum
    store_id: Optional[uuid.UUID] = None


class TeamAccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: RoleEnum
    status: MembershipStatusEnum
    store_id: Optional[uuid.UUID] = None
    reason: str = PydanticField(min_length=3, max_length=500)


def _member_read(session: Session, membership: Membership) -> TeamMemberRead:
    user = session.get(User, membership.user_id)
    store = session.get(Store, membership.store_id) if membership.store_id else None
    assert user is not None
    return TeamMemberRead(
        membership_id=membership.id,
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=membership.role,
        status=membership.status,
        store_id=membership.store_id,
        store_name=store.name if store else None,
    )


def _validate_scope(session: Session, context: TenantContext, role: RoleEnum, store_id: Optional[uuid.UUID]) -> None:
    if role in {RoleEnum.CASHIER, RoleEnum.OPERATOR} and store_id is None:
        raise HTTPException(status_code=422, detail="Caixa e operador exigem uma unidade específica.")
    if store_id:
        store = session.get(Store, store_id)
        if not store or store.tenant_id != context.tenant_id or not store.is_active:
            raise HTTPException(status_code=422, detail="A unidade não pertence ao tenant ativo.")


def _enforce_user_limit(session: Session, tenant_id: uuid.UUID) -> None:
    subscription = session.get(TenantSubscription, tenant_id)
    plan = session.get(ServicePlan, subscription.plan_id) if subscription and subscription.plan_id else None
    if not plan or plan.user_limit is None:
        return
    current = len(session.exec(select(Membership).where(
        Membership.tenant_id == tenant_id,
        Membership.status.in_({MembershipStatusEnum.ACTIVE, MembershipStatusEnum.INVITED}),
    )).all())
    if current >= plan.user_limit:
        raise HTTPException(status_code=409, detail="Limite contratual de usuários atingido.")


@router.get("", response_model=list[TeamMemberRead])
def list_team(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    memberships = session.exec(select(Membership).where(Membership.tenant_id == context.tenant_id)).all()
    return [_member_read(session, membership) for membership in memberships]


@router.post("/invitations", response_model=TeamMemberRead, status_code=201)
def invite_team_member(
    data: TeamInvite,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    _validate_scope(session, context, data.role, data.store_id)
    _enforce_user_limit(session, context.tenant_id)
    tenant = session.get(Tenant, context.tenant_id)
    assert tenant is not None and context.user_id is not None
    email = data.email.strip().lower()
    existing_user = session.exec(select(User).where(User.email == email)).first()
    provider_subject = None
    if existing_user is None:
        invited = supabase_admin.invite_user(
            email=email, full_name=data.full_name.strip(), tenant_id=str(context.tenant_id)
        )
        provider_subject = str(invited["id"])
    membership = identity_service.provision_tenant_access(
        session,
        tenant=tenant,
        email=email,
        full_name=data.full_name,
        role=data.role,
        store_id=data.store_id,
        actor_id=context.user_id,
        provider_subject=provider_subject,
        audit_scope="tenant",
    )
    return _member_read(session, membership)


@router.patch("/{membership_id}", response_model=TeamMemberRead)
def update_team_member(
    membership_id: uuid.UUID,
    data: TeamAccessUpdate,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    _validate_scope(session, context, data.role, data.store_id)
    membership = session.get(Membership, membership_id)
    if not membership or membership.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Membro não encontrado.")
    if membership.user_id == context.user_id and data.status in {MembershipStatusEnum.SUSPENDED, MembershipStatusEnum.REVOKED}:
        raise HTTPException(status_code=409, detail="O administrador não pode revogar a própria sessão.")
    previous = {"role": membership.role.value, "status": membership.status.value, "store_id": str(membership.store_id) if membership.store_id else None}
    membership.role = data.role
    membership.status = data.status
    membership.store_id = data.store_id
    membership.updated_at = datetime.utcnow()
    session.add(membership)
    assert context.user_id is not None
    payload = {
        "membership_id": str(membership.id), "previous": previous,
        "current": {"role": data.role.value, "status": data.status.value, "store_id": str(data.store_id) if data.store_id else None},
        "reason": data.reason, "actor_id": str(context.user_id),
    }
    reliability_service.write_audit_and_outbox(
        session, tenant_id=context.tenant_id, store_id=data.store_id, actor_id=context.user_id,
        action="tenant.team.access_updated", target=f"membership:{membership.id}",
        audit_payload=payload, aggregate_type="membership", aggregate_id=str(membership.id),
        event_type="tenant.team.access_updated", outbox_payload=payload,
    )
    session.commit()
    session.refresh(membership)
    return _member_read(session, membership)

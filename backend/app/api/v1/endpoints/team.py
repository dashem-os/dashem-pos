import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlmodel import Session, select

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.identity import Membership, MembershipStatusEnum, OperationalCredential, RoleEnum, ServicePlan, Store, Tenant, TenantSubscription, User
from app.services import identity_service, operational_access_service, reliability_service, supabase_admin


router = APIRouter()
EMAIL_ROLES = {RoleEnum.ADMIN, RoleEnum.MANAGER}
OPERATIONAL_ROLES = {RoleEnum.SUPERVISOR, RoleEnum.CASHIER, RoleEnum.OPERATOR}


class TeamMemberRead(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: Optional[str] = None
    access_mode: Literal["EMAIL", "PIN"]
    employee_code: Optional[str] = None
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


class OperationalMemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = PydanticField(min_length=2, max_length=160)
    role: RoleEnum
    store_id: uuid.UUID
    employee_code: str = PydanticField(min_length=3, max_length=20)
    pin: str = PydanticField(min_length=4, max_length=8)


class TeamAccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: RoleEnum
    status: MembershipStatusEnum
    store_id: Optional[uuid.UUID] = None
    reason: str = PydanticField(min_length=3, max_length=500)


class TeamPinReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: str = PydanticField(min_length=4, max_length=8)
    reason: str = PydanticField(min_length=3, max_length=500)


def _credential(session: Session, membership_id: uuid.UUID) -> Optional[OperationalCredential]:
    return session.exec(select(OperationalCredential).where(OperationalCredential.membership_id == membership_id)).first()


def _member_read(session: Session, membership: Membership) -> TeamMemberRead:
    user = session.get(User, membership.user_id)
    store = session.get(Store, membership.store_id) if membership.store_id else None
    credential = _credential(session, membership.id)
    assert user is not None
    return TeamMemberRead(
        membership_id=membership.id, user_id=user.id, full_name=user.full_name, email=user.email,
        access_mode="PIN" if credential else "EMAIL", employee_code=credential.employee_code if credential else None,
        role=membership.role, status=membership.status, store_id=membership.store_id,
        store_name=store.name if store else None,
    )


def _validate_scope(session: Session, context: TenantContext, role: RoleEnum, store_id: Optional[uuid.UUID]) -> None:
    if role in OPERATIONAL_ROLES and store_id is None:
        raise HTTPException(status_code=422, detail="Supervisor, caixa e atendente exigem uma unidade específica.")
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


def _audit(session: Session, context: TenantContext, membership: Membership, action: str, payload: dict) -> None:
    reliability_service.write_audit_and_outbox(
        session, tenant_id=context.tenant_id, store_id=membership.store_id, actor_id=context.user_id,
        action=action, target=f"membership:{membership.id}", audit_payload=payload,
        aggregate_type="membership", aggregate_id=str(membership.id), event_type=action, outbox_payload=payload,
    )


@router.get("", response_model=list[TeamMemberRead])
def list_team(context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    memberships = session.exec(select(Membership).where(Membership.tenant_id == context.tenant_id)).all()
    return [_member_read(session, membership) for membership in memberships]


@router.post("/invitations", response_model=TeamMemberRead, status_code=201)
def invite_team_member(data: TeamInvite, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    if data.role not in EMAIL_ROLES:
        raise HTTPException(status_code=422, detail="Somente administradores e gerentes usam convite por e-mail. Cadastre a operação com código e PIN.")
    if data.store_id is not None:
        raise HTTPException(status_code=422, detail="Administrador e gerente possuem acesso por e-mail no tenant inteiro.")
    _enforce_user_limit(session, context.tenant_id)
    tenant = session.get(Tenant, context.tenant_id)
    assert tenant is not None and context.user_id is not None
    email = data.email.strip().lower()
    existing_user = session.exec(select(User).where(User.email == email)).first()
    provider_subject = None
    if existing_user is None:
        invited = supabase_admin.invite_user(email=email, full_name=data.full_name.strip(), tenant_id=str(context.tenant_id))
        provider_subject = str(invited["id"])
    membership = identity_service.provision_tenant_access(
        session, tenant=tenant, email=email, full_name=data.full_name, role=data.role, store_id=None,
        actor_id=context.user_id, provider_subject=provider_subject, audit_scope="tenant",
    )
    return _member_read(session, membership)


@router.post("/operational", response_model=TeamMemberRead, status_code=201)
def create_operational_member(data: OperationalMemberCreate, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    if data.role not in OPERATIONAL_ROLES:
        raise HTTPException(status_code=422, detail="O acesso por PIN é exclusivo de supervisor, caixa e atendente.")
    _validate_scope(session, context, data.role, data.store_id)
    _enforce_user_limit(session, context.tenant_id)
    code = operational_access_service.normalize_employee_code(data.employee_code)
    if session.exec(select(OperationalCredential).where(
        OperationalCredential.tenant_id == context.tenant_id,
        OperationalCredential.store_id == data.store_id,
        OperationalCredential.employee_code == code,
    )).first():
        raise HTTPException(status_code=409, detail="Este código já identifica outro colaborador nesta unidade.")
    salt, pin_hash, iterations = operational_access_service.new_pin_secret(data.pin)
    user = User(email=None, full_name=data.full_name.strip(), is_active=True)
    membership = Membership(user_id=user.id, tenant_id=context.tenant_id, store_id=data.store_id, role=data.role, status=MembershipStatusEnum.ACTIVE)
    credential = OperationalCredential(
        tenant_id=context.tenant_id, store_id=data.store_id, user_id=user.id, membership_id=membership.id,
        employee_code=code, pin_salt=salt, pin_hash=pin_hash, pin_iterations=iterations,
    )
    # Explicit flushes preserve FK order even though these identity models do
    # not expose credential relationships through the ORM.
    session.add(user); session.flush()
    session.add(membership); session.flush()
    session.add(credential)
    payload = {"membership_id": str(membership.id), "role": data.role.value, "store_id": str(data.store_id), "employee_code": code}
    _audit(session, context, membership, "tenant.team.operational_created", payload)
    session.commit(); session.refresh(membership)
    return _member_read(session, membership)


@router.patch("/{membership_id}", response_model=TeamMemberRead)
def update_team_member(membership_id: uuid.UUID, data: TeamAccessUpdate, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    _validate_scope(session, context, data.role, data.store_id)
    membership = session.get(Membership, membership_id)
    if not membership or membership.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Membro não encontrado.")
    credential = _credential(session, membership.id)
    if credential and data.role not in OPERATIONAL_ROLES:
        raise HTTPException(status_code=409, detail="Um acesso por PIN não pode ser convertido em acesso por e-mail.")
    if not credential and data.role not in EMAIL_ROLES:
        raise HTTPException(status_code=409, detail="Um acesso por e-mail não pode ser convertido em acesso por PIN.")
    if membership.user_id == context.user_id and data.status in {MembershipStatusEnum.SUSPENDED, MembershipStatusEnum.REVOKED}:
        raise HTTPException(status_code=409, detail="O administrador não pode revogar a própria sessão.")
    previous = {"role": RoleEnum(membership.role).value, "status": MembershipStatusEnum(membership.status).value, "store_id": str(membership.store_id) if membership.store_id else None}
    membership.role = data.role; membership.status = data.status; membership.store_id = data.store_id; membership.updated_at = datetime.utcnow()
    session.add(membership)
    if credential:
        assert data.store_id is not None
        credential.store_id = data.store_id; credential.updated_at = datetime.utcnow(); session.add(credential)
    payload = {"membership_id": str(membership.id), "previous": previous, "current": {"role": data.role.value, "status": data.status.value, "store_id": str(data.store_id) if data.store_id else None}, "reason": data.reason}
    _audit(session, context, membership, "tenant.team.access_updated", payload)
    session.commit(); session.refresh(membership)
    return _member_read(session, membership)


@router.post("/{membership_id}/pin", response_model=TeamMemberRead)
def reset_operational_pin(membership_id: uuid.UUID, data: TeamPinReset, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    membership = session.get(Membership, membership_id)
    credential = _credential(session, membership_id)
    if not membership or membership.tenant_id != context.tenant_id or not credential:
        raise HTTPException(status_code=404, detail="Acesso operacional não encontrado.")
    salt, pin_hash, iterations = operational_access_service.new_pin_secret(data.pin)
    credential.pin_salt = salt; credential.pin_hash = pin_hash; credential.pin_iterations = iterations
    credential.failed_attempts = 0; credential.locked_until = None; credential.updated_at = datetime.utcnow()
    session.add(credential)
    _audit(session, context, membership, "tenant.team.pin_reset", {"membership_id": str(membership.id), "reason": data.reason})
    session.commit()
    return _member_read(session, membership)

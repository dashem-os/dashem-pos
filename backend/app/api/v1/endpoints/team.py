import re
import uuid
from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field as PydanticField, field_validator
from sqlmodel import Session, select

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.identity import (
    Employee, EmployeeStatusEnum, Membership, MembershipStatusEnum,
    OperationalCredential, RoleEnum, Store, Tenant, User,
)
from app.services.contract_limit_service import effective_limit
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
    employee_id: Optional[uuid.UUID] = None
    role: RoleEnum
    status: MembershipStatusEnum
    store_id: Optional[uuid.UUID] = None
    store_name: Optional[str] = None
    credential_state: Optional[Literal["PENDING_ACTIVATION", "ACTIVE"]] = None
    pin_activated_at: Optional[datetime] = None
    activation_code: Optional[str] = None
    activation_expires_at: Optional[datetime] = None


class TeamInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = PydanticField(min_length=5, max_length=254)
    full_name: str = PydanticField(min_length=2, max_length=160)
    role: RoleEnum
    store_id: Optional[uuid.UUID] = None


class OperationalMemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: uuid.UUID
    role: RoleEnum
    store_id: uuid.UUID
    employee_code: str = PydanticField(min_length=3, max_length=20)


class TeamAccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: RoleEnum
    status: MembershipStatusEnum
    store_id: Optional[uuid.UUID] = None
    reason: str = PydanticField(min_length=3, max_length=500)


class TeamActivationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = PydanticField(min_length=3, max_length=500)


class EmployeeWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_number: str = PydanticField(min_length=2, max_length=30)
    full_name: str = PydanticField(min_length=2, max_length=160)
    preferred_name: Optional[str] = PydanticField(default=None, max_length=100)
    tax_id: Optional[str] = PydanticField(default=None, max_length=14)
    email: Optional[str] = PydanticField(default=None, max_length=254)
    phone: Optional[str] = PydanticField(default=None, max_length=32)
    job_title: Optional[str] = PydanticField(default=None, max_length=120)
    department: Optional[str] = PydanticField(default=None, max_length=120)
    hire_date: Optional[date] = None
    home_store_id: Optional[uuid.UUID] = None
    postal_code: Optional[str] = PydanticField(default=None, max_length=10)
    street: Optional[str] = PydanticField(default=None, max_length=200)
    street_number: Optional[str] = PydanticField(default=None, max_length=32)
    address_complement: Optional[str] = PydanticField(default=None, max_length=120)
    district: Optional[str] = PydanticField(default=None, max_length=120)
    city: Optional[str] = PydanticField(default=None, max_length=120)
    state: Optional[str] = PydanticField(default=None, max_length=2)
    emergency_contact_name: Optional[str] = PydanticField(default=None, max_length=160)
    emergency_contact_phone: Optional[str] = PydanticField(default=None, max_length=32)
    status: EmployeeStatusEnum = EmployeeStatusEnum.ACTIVE
    notes: Optional[str] = PydanticField(default=None, max_length=2000)

    @field_validator("hire_date", "home_store_id", mode="before")
    @classmethod
    def blank_is_none(cls, value):
        return None if value == "" else value


class EmployeeRead(EmployeeWrite):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


def _credential(session: Session, membership_id: uuid.UUID) -> Optional[OperationalCredential]:
    return session.exec(select(OperationalCredential).where(OperationalCredential.membership_id == membership_id)).first()


def _member_read(
    session: Session, membership: Membership, *,
    activation_code: Optional[str] = None,
    activation_expires_at: Optional[datetime] = None,
) -> TeamMemberRead:
    user = session.get(User, membership.user_id)
    store = session.get(Store, membership.store_id) if membership.store_id else None
    credential = _credential(session, membership.id)
    assert user is not None
    return TeamMemberRead(
        membership_id=membership.id, user_id=user.id, full_name=user.full_name, email=user.email,
        access_mode="PIN" if credential else "EMAIL", employee_code=credential.employee_code if credential else None,
        employee_id=credential.employee_id if credential else None,
        role=membership.role, status=membership.status, store_id=membership.store_id,
        store_name=store.name if store else None,
        credential_state=("ACTIVE" if credential.pin_hash else "PENDING_ACTIVATION") if credential else None,
        pin_activated_at=credential.pin_activated_at if credential else None,
        activation_code=activation_code,
        activation_expires_at=activation_expires_at,
    )


def _validate_scope(session: Session, context: TenantContext, role: RoleEnum, store_id: Optional[uuid.UUID]) -> None:
    if role in OPERATIONAL_ROLES and store_id is None:
        raise HTTPException(status_code=422, detail="Supervisor, caixa e atendente exigem uma unidade específica.")
    if store_id:
        store = session.get(Store, store_id)
        if not store or store.tenant_id != context.tenant_id or not store.is_active:
            raise HTTPException(status_code=422, detail="A unidade não pertence ao tenant ativo.")


def _clean_optional(value: Optional[str]) -> Optional[str]:
    cleaned = value.strip() if value else None
    return cleaned or None


def _employee_number(value: str) -> str:
    normalized = re.sub(r"[^A-Z0-9_-]", "", value.strip().upper())
    if len(normalized) < 2:
        raise HTTPException(status_code=422, detail="A matrícula deve possuir ao menos 2 caracteres.")
    return normalized


def _tax_id(value: Optional[str]) -> Optional[str]:
    normalized = re.sub(r"\D", "", value or "") or None
    if normalized and len(normalized) != 11:
        raise HTTPException(status_code=422, detail="O CPF deve possuir 11 números.")
    return normalized


def _employee_values(data: EmployeeWrite) -> dict:
    values = data.model_dump()
    values["employee_number"] = _employee_number(data.employee_number)
    values["full_name"] = data.full_name.strip()
    values["tax_id"] = _tax_id(data.tax_id)
    values["postal_code"] = re.sub(r"\D", "", data.postal_code or "") or None
    values["state"] = data.state.strip().upper() if data.state else None
    for field in (
        "preferred_name", "email", "phone", "job_title", "department", "street",
        "street_number", "address_complement", "district", "city",
        "emergency_contact_name", "emergency_contact_phone", "notes",
    ):
        values[field] = _clean_optional(values.get(field))
    if values["email"]:
        values["email"] = values["email"].lower()
    return values


def _validate_employee_store(session: Session, context: TenantContext, store_id: Optional[uuid.UUID]) -> None:
    if store_id is None:
        return
    store = session.get(Store, store_id)
    if not store or store.tenant_id != context.tenant_id or not store.is_active:
        raise HTTPException(status_code=422, detail="A unidade principal não pertence ao tenant ativo.")


def _enforce_user_limit(session: Session, tenant_id: uuid.UUID) -> None:
    maximum = effective_limit(session, tenant_id, "users")
    if maximum is None:
        return
    current = len(session.exec(select(Membership).where(
        Membership.tenant_id == tenant_id,
        Membership.status.in_({MembershipStatusEnum.ACTIVE, MembershipStatusEnum.INVITED}),
    )).all())
    if current >= maximum:
        raise HTTPException(status_code=409, detail="Limite contratual de usuários atingido.")


def _audit(session: Session, context: TenantContext, membership: Membership, action: str, payload: dict) -> None:
    reliability_service.write_audit_and_outbox(
        session, tenant_id=context.tenant_id, store_id=membership.store_id, actor_id=context.user_id,
        action=action, target=f"membership:{membership.id}", audit_payload=payload,
        aggregate_type="membership", aggregate_id=str(membership.id), event_type=action, outbox_payload=payload,
    )


def _audit_employee(session: Session, context: TenantContext, employee: Employee, action: str, payload: dict) -> None:
    reliability_service.write_audit_and_outbox(
        session, tenant_id=context.tenant_id, store_id=employee.home_store_id, actor_id=context.user_id,
        action=action, target=f"employee:{employee.id}", audit_payload=payload,
        aggregate_type="employee", aggregate_id=str(employee.id), event_type=action, outbox_payload=payload,
    )


@router.get("/employees", response_model=list[EmployeeRead])
def list_employees(context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return session.exec(
        select(Employee).where(Employee.tenant_id == context.tenant_id).order_by(Employee.full_name)
    ).all()


@router.post("/employees", response_model=EmployeeRead, status_code=201)
def create_employee(data: EmployeeWrite, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    values = _employee_values(data)
    _validate_employee_store(session, context, values["home_store_id"])
    duplicate = session.exec(select(Employee).where(
        Employee.tenant_id == context.tenant_id,
        Employee.employee_number == values["employee_number"],
    )).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Já existe um funcionário com esta matrícula.")
    if values["tax_id"] and session.exec(select(Employee).where(
        Employee.tenant_id == context.tenant_id, Employee.tax_id == values["tax_id"],
    )).first():
        raise HTTPException(status_code=409, detail="Já existe um funcionário com este CPF.")
    employee = Employee(tenant_id=context.tenant_id, **values)
    session.add(employee); session.flush()
    _audit_employee(session, context, employee, "tenant.employee.created", {
        "employee_id": str(employee.id), "employee_number": employee.employee_number,
        "home_store_id": str(employee.home_store_id) if employee.home_store_id else None,
    })
    session.commit(); session.refresh(employee)
    return employee


@router.patch("/employees/{employee_id}", response_model=EmployeeRead)
def update_employee(employee_id: uuid.UUID, data: EmployeeWrite, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    employee = session.get(Employee, employee_id)
    if not employee or employee.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Funcionário não encontrado.")
    values = _employee_values(data)
    _validate_employee_store(session, context, values["home_store_id"])
    number_owner = session.exec(select(Employee).where(
        Employee.tenant_id == context.tenant_id,
        Employee.employee_number == values["employee_number"],
        Employee.id != employee.id,
    )).first()
    if number_owner:
        raise HTTPException(status_code=409, detail="Já existe um funcionário com esta matrícula.")
    if values["tax_id"] and session.exec(select(Employee).where(
        Employee.tenant_id == context.tenant_id,
        Employee.tax_id == values["tax_id"], Employee.id != employee.id,
    )).first():
        raise HTTPException(status_code=409, detail="Já existe um funcionário com este CPF.")
    previous_status = EmployeeStatusEnum(employee.status).value
    for field, value in values.items():
        setattr(employee, field, value)
    employee.updated_at = datetime.utcnow()
    if employee.user_id:
        user = session.get(User, employee.user_id)
        if user:
            user.full_name = employee.full_name
            user.is_active = employee.status == EmployeeStatusEnum.ACTIVE
            session.add(user)
    if previous_status != EmployeeStatusEnum(employee.status).value:
        employee_credentials = session.exec(select(OperationalCredential).where(
            OperationalCredential.employee_id == employee.id,
        )).all()
        for employee_credential in employee_credentials:
            operational_access_service.revoke_credential_sessions(
                session, employee_credential,
                reason=f"Cadastro funcional alterado para {EmployeeStatusEnum(employee.status).value}",
            )
    session.add(employee)
    _audit_employee(session, context, employee, "tenant.employee.updated", {
        "employee_id": str(employee.id), "previous_status": previous_status,
        "status": EmployeeStatusEnum(employee.status).value,
    })
    session.commit(); session.refresh(employee)
    return employee


@router.get("", response_model=list[TeamMemberRead])
def list_team(context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    memberships = session.exec(select(Membership).where(Membership.tenant_id == context.tenant_id)).all()
    return [_member_read(session, membership) for membership in memberships]


@router.post("/invitations", response_model=TeamMemberRead, status_code=201)
def invite_team_member(data: TeamInvite, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    if data.role not in EMAIL_ROLES:
        raise HTTPException(status_code=422, detail="Somente administradores e gerentes usam convite por e-mail. Conceda um acesso operacional ao colaborador.")
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
        raise HTTPException(status_code=422, detail="O acesso operacional é exclusivo de supervisor, caixa e atendente.")
    _validate_scope(session, context, data.role, data.store_id)
    _enforce_user_limit(session, context.tenant_id)
    employee = session.get(Employee, data.employee_id)
    if not employee or employee.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Funcionário não encontrado neste tenant.")
    if employee.status != EmployeeStatusEnum.ACTIVE:
        raise HTTPException(status_code=409, detail="Somente funcionários ativos podem receber acesso operacional.")
    if employee.home_store_id and employee.home_store_id != data.store_id:
        raise HTTPException(status_code=409, detail="A unidade do acesso difere da lotação do funcionário.")
    if session.exec(select(OperationalCredential).where(
        OperationalCredential.employee_id == employee.id,
        OperationalCredential.store_id == data.store_id,
    )).first():
        raise HTTPException(status_code=409, detail="Este funcionário já possui acesso operacional na unidade.")
    code = operational_access_service.normalize_employee_code(data.employee_code)
    if session.exec(select(OperationalCredential).where(
        OperationalCredential.tenant_id == context.tenant_id,
        OperationalCredential.store_id == data.store_id,
        OperationalCredential.employee_code == code,
    )).first():
        raise HTTPException(status_code=409, detail="Este código já identifica outro colaborador nesta unidade.")
    user = session.get(User, employee.user_id) if employee.user_id else None
    if user is None:
        user = User(email=None, full_name=employee.full_name, is_active=True)
        session.add(user); session.flush()
        employee.user_id = user.id
        employee.updated_at = datetime.utcnow()
        session.add(employee)
    membership = Membership(user_id=user.id, tenant_id=context.tenant_id, store_id=data.store_id, role=data.role, status=MembershipStatusEnum.ACTIVE)
    credential = OperationalCredential(
        tenant_id=context.tenant_id, store_id=data.store_id, user_id=user.id, membership_id=membership.id,
        employee_id=employee.id,
        employee_code=code,
    )
    activation_code, activation_hash, activation_expires_at = operational_access_service.issue_activation_secret(credential.id)
    credential.activation_secret_hash = activation_hash
    credential.activation_expires_at = activation_expires_at
    # Explicit flushes preserve FK order even though these identity models do
    # not expose credential relationships through the ORM.
    session.add(membership); session.flush()
    session.add(credential)
    payload = {
        "membership_id": str(membership.id), "employee_id": str(employee.id),
        "role": data.role.value, "store_id": str(data.store_id),
        "employee_code": code, "credential_state": "PENDING_ACTIVATION",
        "activation_expires_at": activation_expires_at.isoformat(),
    }
    _audit(session, context, membership, "tenant.team.operational_created", payload)
    session.commit(); session.refresh(membership)
    return _member_read(
        session, membership, activation_code=activation_code,
        activation_expires_at=activation_expires_at,
    )


@router.patch("/{membership_id}", response_model=TeamMemberRead)
def update_team_member(membership_id: uuid.UUID, data: TeamAccessUpdate, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    _validate_scope(session, context, data.role, data.store_id)
    membership = session.get(Membership, membership_id)
    if not membership or membership.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Membro não encontrado.")
    credential = _credential(session, membership.id)
    if credential and data.role not in OPERATIONAL_ROLES:
        raise HTTPException(status_code=409, detail="Um acesso operacional não pode ser convertido em acesso por e-mail.")
    if not credential and data.role not in EMAIL_ROLES:
        raise HTTPException(status_code=409, detail="Um acesso por e-mail não pode ser convertido em acesso operacional.")
    if membership.user_id == context.user_id and data.status in {MembershipStatusEnum.SUSPENDED, MembershipStatusEnum.REVOKED}:
        raise HTTPException(status_code=409, detail="O administrador não pode revogar a própria sessão.")
    previous = {"role": RoleEnum(membership.role).value, "status": MembershipStatusEnum(membership.status).value, "store_id": str(membership.store_id) if membership.store_id else None}
    membership.role = data.role; membership.status = data.status; membership.store_id = data.store_id; membership.updated_at = datetime.utcnow()
    session.add(membership)
    if credential:
        assert data.store_id is not None
        credential.store_id = data.store_id
        operational_access_service.revoke_credential_sessions(
            session, credential, reason=f"Acesso alterado: {data.reason}",
        )
    payload = {"membership_id": str(membership.id), "previous": previous, "current": {"role": data.role.value, "status": data.status.value, "store_id": str(data.store_id) if data.store_id else None}, "reason": data.reason}
    _audit(session, context, membership, "tenant.team.access_updated", payload)
    session.commit(); session.refresh(membership)
    return _member_read(session, membership)


@router.post("/{membership_id}/activation", response_model=TeamMemberRead)
def issue_operational_activation(membership_id: uuid.UUID, data: TeamActivationIssue, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    membership = session.get(Membership, membership_id)
    credential = _credential(session, membership_id)
    if not membership or membership.tenant_id != context.tenant_id or not credential:
        raise HTTPException(status_code=404, detail="Acesso operacional não encontrado.")
    operational_access_service.revoke_credential_sessions(
        session, credential, reason=f"Nova ativação de PIN solicitada: {data.reason}",
    )
    activation_code, activation_hash, activation_expires_at = operational_access_service.issue_activation_secret(credential.id)
    credential.pin_salt = None
    credential.pin_hash = None
    credential.pin_activated_at = None
    credential.activation_secret_hash = activation_hash
    credential.activation_expires_at = activation_expires_at
    credential.activation_failed_attempts = 0
    credential.failed_attempts = 0
    credential.locked_until = None
    credential.updated_at = datetime.utcnow()
    session.add(credential)
    _audit(session, context, membership, "tenant.team.pin_activation_issued", {
        "membership_id": str(membership.id), "reason": data.reason,
        "activation_expires_at": activation_expires_at.isoformat(),
    })
    session.commit()
    return _member_read(
        session, membership, activation_code=activation_code,
        activation_expires_at=activation_expires_at,
    )

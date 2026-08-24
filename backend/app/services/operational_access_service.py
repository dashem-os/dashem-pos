import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.context import TenantContext
from app.core.tenancy import set_tenant_db_context
from app.models.device import OperationalDevice, OperationalDeviceStatusEnum, OperationalDeviceTypeEnum
from app.models.identity import (
    Employee, EmployeeStatusEnum, Membership, MembershipStatusEnum,
    OperationalCredential, OperationalSession, OperationalSessionStatusEnum,
    RoleEnum, Store, Tenant, User,
)
from app.models.payment import Register
from app.services import reliability_service


PIN_ITERATIONS = 210_000
SESSION_HOURS = 12
TERMINAL_SESSION_DAYS = 90
OPERATIONAL_ROLES = {RoleEnum.SUPERVISOR, RoleEnum.CASHIER, RoleEnum.OPERATOR}
MANAGEMENT_ROLES = {RoleEnum.OWNER, RoleEnum.TENANT_OWNER, RoleEnum.ADMIN, RoleEnum.MANAGER}


def normalize_employee_code(value: str) -> str:
    normalized = re.sub(r"[^A-Z0-9_-]", "", value.strip().upper())
    if len(normalized) < 3 or len(normalized) > 20:
        raise HTTPException(status_code=422, detail="O código do colaborador deve possuir de 3 a 20 caracteres.")
    return normalized


def validate_pin(pin: str) -> str:
    if not re.fullmatch(r"\d{4,8}", pin):
        raise HTTPException(status_code=422, detail="O PIN deve possuir de 4 a 8 números.")
    if len(set(pin)) == 1 or pin in "01234567890123456789" or pin in "98765432109876543210":
        raise HTTPException(status_code=422, detail="Escolha um PIN que não seja repetido nem sequencial.")
    return pin


def new_pin_secret(pin: str) -> tuple[str, str, int]:
    validate_pin(pin)
    salt = secrets.token_hex(16)
    return salt, _derive(pin, salt, PIN_ITERATIONS), PIN_ITERATIONS


def _derive(pin: str, salt: str, iterations: int) -> str:
    material = f"{pin}:{settings.SECRET_KEY}".encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", material, bytes.fromhex(salt), iterations).hex()


def _matches(credential: OperationalCredential, pin: str) -> bool:
    return hmac.compare_digest(_derive(pin, credential.pin_salt, credential.pin_iterations), credential.pin_hash)


def _terminal_projection(session: Session, device: OperationalDevice) -> dict:
    tenant = session.get(Tenant, device.tenant_id)
    store = session.get(Store, device.store_id)
    register = session.get(Register, device.register_id) if device.register_id else None
    return {
        "device_id": device.id, "device_name": device.name,
        "tenant_id": device.tenant_id, "tenant_name": tenant.name if tenant else "Tenant",
        "store_id": device.store_id, "store_name": store.name if store else "Unidade",
        "register_id": device.register_id, "register_name": register.name if register else "Terminal",
    }


def authorize_terminal(session: Session, context: TenantContext, device_id: uuid.UUID) -> dict:
    """Pair one browser with infrastructure; this credential never identifies a person."""
    if context.role not in MANAGEMENT_ROLES or not context.user_id:
        raise HTTPException(status_code=403, detail="Somente gestores podem ativar um terminal.")
    device = session.get(OperationalDevice, device_id)
    if (
        not device or device.tenant_id != context.tenant_id or device.store_id != context.store_id
        or device.device_type != OperationalDeviceTypeEnum.POS
        or device.status != OperationalDeviceStatusEnum.ACTIVE or not device.register_id
    ):
        raise HTTPException(status_code=422, detail="Selecione um terminal POS ativo desta unidade.")
    register = session.get(Register, device.register_id)
    if not register or not register.is_active or register.store_id != device.store_id:
        raise HTTPException(status_code=422, detail="O caixa vinculado ao terminal não está disponível.")
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=TERMINAL_SESSION_DAYS)
    previous_sessions = session.exec(select(OperationalSession).where(
        OperationalSession.device_id == device.id,
        OperationalSession.status == OperationalSessionStatusEnum.ACTIVE,
    )).all()
    for previous in previous_sessions:
        previous.status = OperationalSessionStatusEnum.REVOKED
        previous.ended_at = now.replace(tzinfo=None)
        previous.end_reason = "Terminal reautorizado por gestor"
        session.add(previous)
    device.authorization_version += 1
    device.authorized_at = now.replace(tzinfo=None)
    device.authorized_by = context.user_id
    device.authorization_expires_at = expires_at.replace(tzinfo=None)
    device.last_seen_at = datetime.utcnow()
    device.updated_at = device.last_seen_at
    session.add(device)
    claims = {
        "sub": str(device.id), "aud": "dashem-terminal", "iss": "dashem-terminal",
        "iat": now, "exp": expires_at, "tenant_id": str(device.tenant_id),
        "store_id": str(device.store_id), "register_id": str(device.register_id),
        "device_id": str(device.id), "authorization_version": device.authorization_version,
    }
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=device.store_id,
        actor_id=context.user_id, action="operational_terminal.authorized", target=f"DEVICE-{device.id}",
        audit_payload={"register_id": str(device.register_id), "expires_at": expires_at.isoformat(), "authorization_version": device.authorization_version},
        aggregate_type="operational_terminal", aggregate_id=str(device.id), event_type="operational_terminal.authorized",
        outbox_payload={"device_id": str(device.id), "register_id": str(device.register_id), "authorization_version": device.authorization_version},
    )
    session.commit()
    return {**_terminal_projection(session, device), "terminal_token": token, "expires_at": expires_at}


def _decode_terminal_token(token: str) -> dict:
    try:
        return jwt.decode(
            token, settings.SECRET_KEY, algorithms=["HS256"], audience="dashem-terminal", issuer="dashem-terminal",
            options={"require": ["exp", "iat", "sub", "aud", "iss", "tenant_id", "store_id", "register_id", "device_id", "authorization_version"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="A autorização deste terminal expirou. Solicite nova ativação ao gestor.") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Autorização de terminal inválida.") from exc


def resolve_terminal(session: Session, token: str) -> tuple[TenantContext, OperationalDevice, dict]:
    claims = _decode_terminal_token(token)
    try:
        tenant_id = uuid.UUID(claims["tenant_id"])
        store_id = uuid.UUID(claims["store_id"])
        device_id = uuid.UUID(claims["device_id"])
        register_id = uuid.UUID(claims["register_id"])
        authorization_version = int(claims["authorization_version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Escopo do terminal inválido.") from exc
    set_tenant_db_context(session, tenant_id, store_id)
    device = session.get(OperationalDevice, device_id)
    if (
        not device or device.tenant_id != tenant_id or device.store_id != store_id
        or device.register_id != register_id or device.device_type != OperationalDeviceTypeEnum.POS
        or device.status != OperationalDeviceStatusEnum.ACTIVE
        or device.authorization_version != authorization_version
        or not device.authorization_expires_at or device.authorization_expires_at <= datetime.utcnow()
    ):
        raise HTTPException(status_code=403, detail="Este terminal foi pausado, revogado, reativado ou alterado pelo gestor.")
    register = session.get(Register, register_id)
    if not register or not register.is_active or register.tenant_id != tenant_id or register.store_id != store_id:
        raise HTTPException(status_code=403, detail="O caixa deste terminal não está disponível.")
    return TenantContext(tenant_id=tenant_id, store_id=store_id), device, _terminal_projection(session, device)


def terminal_status(session: Session, token: str) -> dict:
    _context, _device, projection = resolve_terminal(session, token)
    return projection


def activate_from_terminal(session: Session, *, terminal_token: str, employee_code: str, pin: str) -> dict:
    context, device, _projection = resolve_terminal(session, terminal_token)
    result = activate(session, context, employee_code=employee_code, pin=pin, store_id=device.store_id, register_id=device.register_id, device_id=device.id)
    device.last_seen_at = datetime.utcnow()
    device.updated_at = device.last_seen_at
    session.add(device)
    session.commit()
    return result


def activate(
    session: Session, context: TenantContext, *, employee_code: str, pin: str,
    store_id: uuid.UUID, register_id: uuid.UUID | None, device_id: uuid.UUID | None = None,
) -> dict:
    if not register_id or not device_id:
        raise HTTPException(status_code=403, detail="O PIN exige um terminal POS previamente autorizado.")
    code = normalize_employee_code(employee_code)
    credential = session.exec(select(OperationalCredential).where(
        OperationalCredential.tenant_id == context.tenant_id,
        OperationalCredential.store_id == store_id,
        OperationalCredential.employee_code == code,
    ).with_for_update()).first()
    generic = "Código ou PIN inválido para esta unidade."
    if not credential:
        raise HTTPException(status_code=401, detail=generic)
    now = datetime.utcnow()
    if credential.locked_until and credential.locked_until > now:
        raise HTTPException(status_code=429, detail="Acesso temporariamente bloqueado após tentativas inválidas.")
    membership = session.get(Membership, credential.membership_id)
    user = session.get(User, credential.user_id)
    employee = session.get(Employee, credential.employee_id)
    if (
        not membership or not user or not user.is_active or not employee or employee.status != EmployeeStatusEnum.ACTIVE
        or membership.status != MembershipStatusEnum.ACTIVE or membership.role not in OPERATIONAL_ROLES
        or membership.tenant_id != context.tenant_id or membership.store_id != store_id
    ):
        raise HTTPException(status_code=403, detail="Acesso operacional inativo ou fora da unidade.")
    device = session.get(OperationalDevice, device_id)
    register = session.get(Register, register_id)
    if (
        not device or device.tenant_id != context.tenant_id or device.store_id != store_id
        or device.register_id != register_id or device.status != OperationalDeviceStatusEnum.ACTIVE
        or not device.authorization_expires_at or device.authorization_expires_at <= now
        or not register or register.tenant_id != context.tenant_id or register.store_id != store_id or not register.is_active
    ):
        raise HTTPException(status_code=403, detail="Terminal fora da unidade ou sem autorização ativa.")
    if not _matches(credential, pin):
        credential.failed_attempts += 1
        if credential.failed_attempts >= 5:
            credential.locked_until = now + timedelta(minutes=15)
            credential.failed_attempts = 0
        credential.updated_at = now
        session.add(credential)
        session.commit()
        raise HTTPException(status_code=401, detail=generic)
    credential.failed_attempts = 0
    credential.locked_until = None
    credential.last_used_at = now
    credential.updated_at = now
    session.add(credential)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    operational_session = OperationalSession(
        tenant_id=context.tenant_id, store_id=store_id, register_id=register_id, device_id=device_id,
        user_id=user.id, membership_id=membership.id, credential_id=credential.id,
        terminal_authorization_version=device.authorization_version, credential_version=credential.session_version,
        expires_at=expires_at.replace(tzinfo=None),
    )
    session.add(operational_session)
    session.flush()
    session_id = str(operational_session.id)
    claims = {
        "sub": str(user.id), "aud": "dashem-pos", "iss": "dashem-operational",
        "iat": datetime.now(timezone.utc), "exp": expires_at, "session_id": session_id, "aal": "pin",
        "tenant_id": str(context.tenant_id), "store_id": str(store_id), "register_id": str(register_id),
        "device_id": str(device_id), "membership_id": str(membership.id), "role": RoleEnum(membership.role).value,
        "credential_id": str(credential.id), "credential_version": credential.session_version,
        "terminal_authorization_version": device.authorization_version, "app_metadata": {"provider": "operational"},
    }
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=store_id, actor_id=user.id,
        action="operational_access.activated", target=f"membership:{membership.id}",
        audit_payload={"membership_id": str(membership.id), "register_id": str(register_id), "device_id": str(device_id), "session_id": session_id, "expires_at": expires_at.isoformat()},
        aggregate_type="operational_access", aggregate_id=session_id, event_type="operational_access.activated",
        outbox_payload={"membership_id": str(membership.id), "store_id": str(store_id), "device_id": str(device_id), "session_id": session_id},
    )
    session.commit()
    return {
        "access_token": token, "token_type": "bearer", "expires_at": expires_at,
        "user_id": user.id, "membership_id": membership.id, "full_name": user.full_name,
        "role": RoleEnum(membership.role), "store_id": store_id, "register_id": register_id,
    }


def revoke_credential_sessions(session: Session, credential: OperationalCredential, *, reason: str) -> int:
    """Rotate PIN authority and revoke every live token minted from it."""
    now = datetime.utcnow()
    credential.session_version += 1
    credential.updated_at = now
    session.add(credential)
    active = session.exec(select(OperationalSession).where(
        OperationalSession.credential_id == credential.id,
        OperationalSession.status == OperationalSessionStatusEnum.ACTIVE,
    ).with_for_update()).all()
    for item in active:
        item.status = OperationalSessionStatusEnum.REVOKED
        item.ended_at = now
        item.end_reason = reason[:500]
        session.add(item)
    return len(active)


def end_operational_session(session: Session, context: TenantContext, *, reason: str) -> None:
    if not context.operational_session_id or not context.user_id:
        raise HTTPException(status_code=409, detail="Não existe turno operacional ativo para encerrar.")
    item = session.get(OperationalSession, context.operational_session_id)
    if (
        not item or item.tenant_id != context.tenant_id or item.store_id != context.store_id
        or item.user_id != context.user_id or item.status != OperationalSessionStatusEnum.ACTIVE
    ):
        raise HTTPException(status_code=409, detail="O turno operacional já foi encerrado ou revogado.")
    item.status = OperationalSessionStatusEnum.ENDED
    item.ended_at = datetime.utcnow()
    item.end_reason = reason[:500]
    session.add(item)
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=context.store_id, actor_id=context.user_id,
        action="operational_access.ended", target=f"session:{item.id}",
        audit_payload={"session_id": str(item.id), "device_id": str(item.device_id), "reason": reason},
        aggregate_type="operational_access", aggregate_id=str(item.id), event_type="operational_access.ended",
        outbox_payload={"session_id": str(item.id), "device_id": str(item.device_id)},
    )
    session.commit()

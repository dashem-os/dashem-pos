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
from app.models.identity import Membership, MembershipStatusEnum, OperationalCredential, RoleEnum, User
from app.models.payment import Register
from app.services import reliability_service


PIN_ITERATIONS = 210_000
SESSION_HOURS = 12
OPERATIONAL_ROLES = {RoleEnum.SUPERVISOR, RoleEnum.CASHIER, RoleEnum.OPERATOR}


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
    candidate = _derive(pin, credential.pin_salt, credential.pin_iterations)
    return hmac.compare_digest(candidate, credential.pin_hash)


def activate(
    session: Session,
    context: TenantContext,
    *,
    employee_code: str,
    pin: str,
    store_id: uuid.UUID,
    register_id: uuid.UUID | None,
) -> dict:
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
    if (not membership or not user or not user.is_active
            or membership.status != MembershipStatusEnum.ACTIVE
            or membership.role not in OPERATIONAL_ROLES
            or membership.tenant_id != context.tenant_id
            or membership.store_id != store_id):
        raise HTTPException(status_code=403, detail="Acesso operacional inativo ou fora da unidade.")
    if register_id:
        register = session.get(Register, register_id)
        if not register or register.tenant_id != context.tenant_id or register.store_id != store_id or not register.is_active:
            raise HTTPException(status_code=422, detail="Terminal não pertence à unidade selecionada.")
    if not _matches(credential, pin):
        credential.failed_attempts += 1
        if credential.failed_attempts >= 5:
            credential.locked_until = now + timedelta(minutes=15)
            credential.failed_attempts = 0
        credential.updated_at = now
        session.add(credential); session.commit()
        raise HTTPException(status_code=401, detail=generic)

    credential.failed_attempts = 0
    credential.locked_until = None
    credential.last_used_at = now
    credential.updated_at = now
    session.add(credential)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    session_id = str(uuid.uuid4())
    claims = {
        "sub": str(user.id),
        "aud": "dashem-pos",
        "iss": "dashem-operational",
        "iat": datetime.now(timezone.utc),
        "exp": expires_at,
        "session_id": session_id,
        "aal": "pin",
        "tenant_id": str(context.tenant_id),
        "store_id": str(store_id),
        "register_id": str(register_id) if register_id else None,
        "membership_id": str(membership.id),
        "role": RoleEnum(membership.role).value,
        "app_metadata": {"provider": "operational"},
    }
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")
    actor_id = context.user_id or user.id
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=store_id, actor_id=actor_id,
        action="operational_access.activated", target=f"membership:{membership.id}",
        audit_payload={"membership_id": str(membership.id), "register_id": str(register_id) if register_id else None,
                       "session_id": session_id, "expires_at": expires_at.isoformat()},
        aggregate_type="operational_access", aggregate_id=session_id,
        event_type="operational_access.activated",
        outbox_payload={"membership_id": str(membership.id), "store_id": str(store_id), "session_id": session_id},
    )
    session.commit()
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user_id": user.id,
        "membership_id": membership.id,
        "full_name": user.full_name,
        "role": RoleEnum(membership.role),
        "store_id": store_id,
        "register_id": register_id,
    }

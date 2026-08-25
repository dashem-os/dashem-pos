import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.core.tenancy import set_tenant_db_context
from app.models.identity import OperationalSession, OperationalSessionStatusEnum
from app.services import reliability_service


def mark_expired(
    session: Session,
    authority: OperationalSession,
    *,
    now: datetime | None = None,
    reason: str = "Prazo da sessão operacional encerrado",
) -> bool:
    """Transition an overdue live authority exactly once."""
    checked_at = now or datetime.utcnow()
    if (
        authority.status != OperationalSessionStatusEnum.ACTIVE
        or authority.expires_at > checked_at
    ):
        return False
    authority.status = OperationalSessionStatusEnum.EXPIRED
    authority.ended_at = checked_at
    authority.end_reason = reason[:500]
    session.add(authority)
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=authority.tenant_id,
        store_id=authority.store_id,
        actor_id=authority.user_id,
        action="operational_access.expired",
        target=f"session:{authority.id}",
        audit_payload={
            "session_id": str(authority.id),
            "device_id": str(authority.device_id),
            "register_id": str(authority.register_id),
            "expired_at": checked_at.isoformat(),
        },
        aggregate_type="operational_access",
        aggregate_id=str(authority.id),
        event_type="operational_access.expired",
        outbox_payload={
            "session_id": str(authority.id),
            "device_id": str(authority.device_id),
            "register_id": str(authority.register_id),
        },
    )
    return True


def persist_expired_from_claims(session: Session, claims: dict[str, Any]) -> bool:
    """Persist expiry after a correctly signed operational JWT is rejected."""
    try:
        tenant_id = uuid.UUID(str(claims["tenant_id"]))
        store_id = uuid.UUID(str(claims["store_id"]))
        user_id = uuid.UUID(str(claims["sub"]))
        session_id = uuid.UUID(str(claims["session_id"]))
    except (KeyError, TypeError, ValueError):
        return False
    set_tenant_db_context(session, tenant_id, store_id, user_id)
    authority = session.get(OperationalSession, session_id)
    if (
        not authority
        or authority.tenant_id != tenant_id
        or authority.store_id != store_id
        or authority.user_id != user_id
    ):
        return False
    changed = mark_expired(
        session,
        authority,
        reason="JWT da sessão operacional expirou",
    )
    if changed:
        session.commit()
    return changed

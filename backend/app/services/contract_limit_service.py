import uuid
from typing import Optional

from sqlmodel import Session

from app.services.contract_entitlement_service import contracted_limit


def effective_limit(session: Session, tenant_id: uuid.UUID, resource: str) -> Optional[int]:
    """Resolve only the immutable contract snapshot; never infer from a mutable plan."""
    return contracted_limit(session, tenant_id, resource)

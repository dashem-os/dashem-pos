import uuid
from typing import Optional

from sqlmodel import Session

from app.models.identity import ServicePlan, TenantSubscription


PLAN_LIMIT_FIELDS = {
    "users": ("contracted_user_limit", "user_limit"),
    "devices": ("contracted_device_limit", "terminal_limit"),
    "units": ("contracted_store_limit", "store_limit"),
}


def effective_limit(session: Session, tenant_id: uuid.UUID, resource: str) -> Optional[int]:
    """Resolve the latest contracted quota, falling back to the plan ceiling."""
    if resource not in PLAN_LIMIT_FIELDS:
        raise ValueError(f"Unsupported contractual resource: {resource}")

    subscription = session.get(TenantSubscription, tenant_id)
    contracted_field, plan_field = PLAN_LIMIT_FIELDS[resource]
    contracted = getattr(subscription, contracted_field) if subscription else None
    if contracted is not None:
        return contracted
    plan = session.get(ServicePlan, subscription.plan_id) if subscription and subscription.plan_id else None
    return getattr(plan, plan_field) if plan else None

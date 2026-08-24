from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.modules.capabilities.service import effective_capabilities
from app.models.platform import ModuleContribution, TenantProfileAssignment, CapabilityProfileRevision


router = APIRouter()


@router.get("/effective")
def get_effective_capabilities(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    capabilities = effective_capabilities(session, context.tenant_id, context.store_id)
    enabled_keys = set(capabilities)
    contributions = session.exec(
        select(ModuleContribution).where(ModuleContribution.is_active.is_(True)).order_by(ModuleContribution.sort_order)
    ).all()
    visible = [
        contribution for contribution in contributions
        if (contribution.capability_key is None or contribution.capability_key in enabled_keys)
        and (contribution.permission_key is None or contribution.permission_key in context.permissions)
    ]
    assignment = session.exec(select(TenantProfileAssignment).where(
        TenantProfileAssignment.tenant_id == context.tenant_id,
        TenantProfileAssignment.status == "ACTIVE",
    )).first()
    revision = session.get(CapabilityProfileRevision, assignment.revision_id) if assignment else None
    return {
        "capabilities": capabilities,
        "permissions": list(context.permissions),
        "contributions": visible,
        "profile": ({"key": revision.profile_key, "version": revision.version} if revision else None),
        "context": {
            "tenant_id": str(context.tenant_id),
            "store_id": str(context.store_id) if context.store_id else None,
            "membership_id": str(context.membership_id) if context.membership_id else None,
        },
    }

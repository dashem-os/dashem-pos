from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.modules.capabilities.service import effective_capabilities
from app.models.platform import ModuleContribution, TenantProfileAssignment, CapabilityProfileRevision
from app.services.contract_entitlement_service import resolve_contract_entitlements
from app.services.starter_catalog_service import is_homologation_tenant


router = APIRouter()


# Food service speaks of menus; a retail shop or a beauty reseller does not.
# The navigation label follows the contracted activity instead of assuming one.
NON_FOOD_LABELS = {
    "assortments": "Sortimentos e catálogos",
}


def _labelled(contribution, activities: set[str]):
    """A detached copy, so callers keep the model shape and the row stays clean."""
    if "FOOD_SERVICE" in activities:
        return contribution
    replacement = NON_FOOD_LABELS.get(contribution.contribution_key)
    if not replacement:
        return contribution
    return contribution.model_copy(update={"label": replacement})


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
    contract_snapshot = resolve_contract_entitlements(session, context.tenant_id)
    activities = set(contract_snapshot.activity_keys) if contract_snapshot else set()
    return {
        "capabilities": capabilities,
        "permissions": list(context.permissions),
        "contributions": [_labelled(item, activities) for item in visible],
        "activities": list(contract_snapshot.activity_keys) if contract_snapshot else [],
        # Lets the console offer the starter catalogue only where it belongs.
        "homologation": is_homologation_tenant(session, context.tenant_id),
        "contract": (
            {
                "id": str(contract_snapshot.contract_id),
                "version": contract_snapshot.contract_version,
                "schema_version": contract_snapshot.schema_version,
            }
            if contract_snapshot else None
        ),
        "profile": (
            {"key": revision.profile_key, "version": revision.version}
            if revision and contract_snapshot is None else None
        ),
        "context": {
            "tenant_id": str(context.tenant_id),
            "store_id": str(context.store_id) if context.store_id else None,
            "membership_id": str(context.membership_id) if context.membership_id else None,
        },
    }

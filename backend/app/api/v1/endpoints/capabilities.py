from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.modules.capabilities.service import effective_capabilities


router = APIRouter()


@router.get("/effective")
def get_effective_capabilities(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return {
        "capabilities": effective_capabilities(session, context.tenant_id, context.store_id),
        "permissions": list(context.permissions),
        "context": {
            "tenant_id": str(context.tenant_id),
            "store_id": str(context.store_id) if context.store_id else None,
            "membership_id": str(context.membership_id) if context.membership_id else None,
        },
    }

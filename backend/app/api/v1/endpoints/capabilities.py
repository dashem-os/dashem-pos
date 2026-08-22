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
    return {"capabilities": effective_capabilities(session, context.tenant_id, context.store_id)}

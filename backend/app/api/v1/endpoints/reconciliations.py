import uuid
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.reconciliation import FinancialReconciliation, ReconciliationStatusEnum
from app.services import reconciliation_service


router = APIRouter()


class ReconcileSaleDTO(BaseModel):
    actor_id: uuid.UUID
    provider_reported_total: Optional[Decimal] = None
    provider: Optional[str] = None
    provider_reference: Optional[str] = None
    notes: Optional[str] = None


@router.post("/sales/{sale_id}", response_model=FinancialReconciliation)
def reconcile_sale_endpoint(
    sale_id: uuid.UUID, data: ReconcileSaleDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return reconciliation_service.reconcile_sale(
        session, context, sale_id, actor_id=data.actor_id,
        provider_reported_total=data.provider_reported_total, provider=data.provider,
        provider_reference=data.provider_reference, notes=data.notes,
    )


@router.get("", response_model=list[FinancialReconciliation])
def list_reconciliations_endpoint(
    store_id: Optional[uuid.UUID] = None,
    status: Optional[ReconciliationStatusEnum] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return reconciliation_service.list_reconciliations(
        session, context, store_id=store_id, status_filter=status,
    )

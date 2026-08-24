import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context, resolve_actor
from app.core.database import get_session
from app.services import bi_service


router = APIRouter()


class DailyRevenue(BaseModel):
    date: str
    revenue: float
    sales: int


class ManagementOverview(BaseModel):
    generated_at: datetime
    projection_lag_seconds: int
    projection_version: int
    source_watermark: Optional[datetime]
    revenue_today: float
    revenue_30d: float
    sales_today: int
    sales_30d: int
    average_ticket_30d: float
    open_sales: int
    confirmed_receipts_30d: float
    refunds_30d: float
    receivables_issued_30d: float
    receivables_settled_30d: float
    marketplace_settled_30d: float
    table_sessions_closed_30d: int
    table_average_minutes_30d: float
    production_tickets_30d: int
    production_average_minutes_30d: float
    transfers_30d: int
    stockout_products: int
    active_cash_sessions: int
    products: int
    customers: int
    active_team_members: int
    daily_revenue: list[DailyRevenue]
    alerts: list[str]
    formulas: dict[str, str]


class ProjectionRefreshDTO(BaseModel):
    actor_id: uuid.UUID
    start_date: Optional[date] = None
    end_date: Optional[date] = None


def _store(context: TenantContext, requested: Optional[uuid.UUID]) -> uuid.UUID:
    store_id = requested or context.store_id
    if not store_id:
        raise HTTPException(status_code=400, detail="Selecione uma unidade para consultar o BI.")
    if context.store_id and store_id != context.store_id:
        raise HTTPException(status_code=403, detail="Unidade fora do contexto autorizado.")
    return store_id


@router.get("/overview", response_model=ManagementOverview)
def management_overview(
    days: int = 30, store_id: Optional[uuid.UUID] = None,
    register_id: Optional[uuid.UUID] = None, operator_id: Optional[uuid.UUID] = None,
    channel: Optional[str] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return ManagementOverview.model_validate(
        bi_service.summary(
            session, context, store_id=_store(context, store_id), days=days,
            register_id=register_id, operator_id=operator_id, channel=channel,
        )
    )


@router.post("/bi/refresh")
def refresh_projection(
    data: ProjectionRefreshDTO, store_id: Optional[uuid.UUID] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    actor_id = resolve_actor(context, data.actor_id)
    return bi_service.refresh_daily_projection(
        session, context, store_id=_store(context, store_id), actor_id=actor_id,
        start_date=data.start_date, end_date=data.end_date,
    )


@router.get("/bi/formulas")
def metric_formulas(context: TenantContext = Depends(get_tenant_context)):
    return {"version": "BI_V1", "formulas": bi_service.FORMULAS}


@router.get("/bi/drilldown")
def metric_drilldown(
    metric: str, competence_date: date, store_id: Optional[uuid.UUID] = None,
    offset: int = 0, limit: int = 50,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    if offset < 0 or limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="Paginação inválida.")
    return bi_service.drilldown(
        session, context, store_id=_store(context, store_id), metric=metric,
        competence_date=competence_date, offset=offset, limit=limit,
    )

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.catalog import Product
from app.models.identity import Membership, MembershipStatusEnum
from app.models.payment import CashSession, CashSessionStatusEnum, Payment, PaymentStatusEnum, Register
from app.models.sale import Customer, Sale, SaleStatusEnum


router = APIRouter()


class DailyRevenue(BaseModel):
    date: str
    revenue: float
    sales: int


class ManagementOverview(BaseModel):
    generated_at: datetime
    revenue_today: float
    revenue_30d: float
    sales_today: int
    sales_30d: int
    average_ticket_30d: float
    open_sales: int
    confirmed_receipts_30d: float
    active_cash_sessions: int
    products: int
    customers: int
    active_team_members: int
    daily_revenue: list[DailyRevenue]
    alerts: list[str]


@router.get("/overview", response_model=ManagementOverview)
def management_overview(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=29)
    completed = {SaleStatusEnum.PAID, SaleStatusEnum.COMPLETED}

    sales_rows = session.exec(select(Sale).where(
        Sale.tenant_id == context.tenant_id,
        Sale.created_at >= since,
        Sale.status.in_(completed),
    )).all()
    sales_today_rows = [sale for sale in sales_rows if sale.created_at >= today]
    revenue_30d = sum((Decimal(str(sale.net_total)) for sale in sales_rows), Decimal("0"))
    revenue_today = sum((Decimal(str(sale.net_total)) for sale in sales_today_rows), Decimal("0"))

    buckets = {(since + timedelta(days=offset)).date(): {"revenue": Decimal("0"), "sales": 0} for offset in range(30)}
    for sale in sales_rows:
        bucket = buckets[sale.created_at.date()]
        bucket["revenue"] += Decimal(str(sale.net_total))
        bucket["sales"] += 1

    open_sales = session.exec(select(func.count(Sale.id)).where(
        Sale.tenant_id == context.tenant_id,
        Sale.status.in_({SaleStatusEnum.DRAFT, SaleStatusEnum.CHECKOUT, SaleStatusEnum.AWAITING_PAYMENT}),
    )).one()
    receipts = session.exec(select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.tenant_id == context.tenant_id,
        Payment.status == PaymentStatusEnum.CONFIRMED,
        Payment.created_at >= since,
    )).one()
    active_cash = session.exec(select(func.count(CashSession.id)).where(
        CashSession.tenant_id == context.tenant_id,
        CashSession.status == CashSessionStatusEnum.OPEN,
    )).one()
    products = session.exec(select(func.count(Product.id)).where(Product.tenant_id == context.tenant_id)).one()
    customers = session.exec(select(func.count(Customer.id)).where(Customer.tenant_id == context.tenant_id)).one()
    members = session.exec(select(func.count(Membership.id)).where(
        Membership.tenant_id == context.tenant_id,
        Membership.status == MembershipStatusEnum.ACTIVE,
    )).one()
    terminal_count = session.exec(select(func.count(Register.id)).where(Register.tenant_id == context.tenant_id)).one()
    alerts = []
    if terminal_count == 0:
        alerts.append("Nenhum terminal de caixa está configurado no contexto autorizado.")
    if products == 0:
        alerts.append("O catálogo ainda não possui produtos.")

    sales_count = len(sales_rows)
    return ManagementOverview(
        generated_at=now,
        revenue_today=float(revenue_today),
        revenue_30d=float(revenue_30d),
        sales_today=len(sales_today_rows),
        sales_30d=sales_count,
        average_ticket_30d=float(revenue_30d / sales_count) if sales_count else 0,
        open_sales=open_sales,
        confirmed_receipts_30d=float(receipts),
        active_cash_sessions=active_cash,
        products=products,
        customers=customers,
        active_team_members=members,
        daily_revenue=[DailyRevenue(date=day.isoformat(), revenue=float(values["revenue"]), sales=values["sales"]) for day, values in sorted(buckets.items())],
        alerts=alerts,
    )

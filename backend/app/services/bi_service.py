import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, delete, select

from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.bi import BiDailyFact, BiFactScopeEnum, BiProjectionState
from app.models.catalog import InventoryBalance, Product
from app.models.channel_catalog import MarketplaceSettlement
from app.models.identity import Register, Membership, MembershipStatusEnum
from app.models.payment import CashSession, CashSessionStatusEnum, Payment, PaymentMethodEnum, PaymentStatusEnum
from app.models.production import ProductionTicket
from app.models.receivable import Receivable, ReceivableReceipt, ReceivableReceiptStatusEnum
from app.models.reconciliation import PaymentRefund
from app.models.sale import Customer, Sale, SaleStatusEnum
from app.models.table_service import TableSession
from app.models.transfer import TransferRecord
from app.services import reliability_service


ZERO = Decimal("0")
FORMULAS = {
    "net_revenue": "SUM(sales.net_total) para PAID/COMPLETED/PARTIALLY_REFUNDED/REFUNDED; estornos são exibidos separadamente",
    "average_ticket": "net_revenue / sales_count",
    "confirmed_receipts": "SUM(payments.amount) onde status = CONFIRMED",
    "refunds_total": "SUM(payment_refunds.amount); fato compensatório, sem apagar o pagamento",
    "table_average_minutes": "SUM(closed_at - opened_at) / table_sessions_closed / 60",
    "production_average_minutes": "SUM(delivered_at - created_at) / production_tickets_completed / 60",
    "receivables_issued": "SUM(receivables.principal_amount) por issued_at",
    "receivables_settled": "SUM(receivable_receipts.amount) onde status = CONFIRMED",
}


def _dimensions(sale: Sale) -> tuple[str, str, str]:
    return (str(sale.register_id) if sale.register_id else "UNASSIGNED",
            str(sale.seller_id) if sale.seller_id else "UNASSIGNED",
            str(sale.channel_id) if sale.channel_id else sale.source_type or "POS")


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def refresh_daily_projection(
    session: Session, context: TenantContext, *, store_id: uuid.UUID,
    actor_id: uuid.UUID, start_date: Optional[date] = None, end_date: Optional[date] = None,
) -> BiProjectionState:
    actor_id = resolve_actor(context, actor_id)
    state = session.exec(scope_tenant_query(select(BiProjectionState).where(
        BiProjectionState.store_id == store_id, BiProjectionState.projection_key == "BI_V1_DAILY",
    ), BiProjectionState, context).with_for_update()).first()
    today = datetime.utcnow().date()
    end = end_date or today
    start = start_date or ((state.last_competence if state and state.last_competence else today - timedelta(days=29)))
    if end < start or (end - start).days > 365:
        raise HTTPException(status_code=422, detail="Competência do BI deve possuir entre 1 e 366 dias.")
    start_dt = datetime.combine(start, time.min)
    end_exclusive = datetime.combine(end + timedelta(days=1), time.min)
    terminal_statuses = {SaleStatusEnum.PAID, SaleStatusEnum.COMPLETED, SaleStatusEnum.PARTIALLY_REFUNDED, SaleStatusEnum.REFUNDED}
    sales = session.exec(scope_tenant_query(select(Sale).where(
        Sale.store_id == store_id, Sale.occurred_at >= start_dt, Sale.occurred_at < end_exclusive,
        Sale.status.in_(terminal_statuses),
    ), Sale, context)).all()
    sale_map = {sale.id: sale for sale in sales}
    payments = session.exec(scope_tenant_query(select(Payment).where(
        Payment.store_id == store_id, Payment.sale_id.in_(list(sale_map) or [uuid.uuid4()]),
        Payment.status == PaymentStatusEnum.CONFIRMED,
    ), Payment, context)).all()
    refunds = session.exec(scope_tenant_query(select(PaymentRefund).where(
        PaymentRefund.store_id == store_id, PaymentRefund.created_at >= start_dt,
        PaymentRefund.created_at < end_exclusive,
    ), PaymentRefund, context)).all()
    receivables = session.exec(scope_tenant_query(select(Receivable).where(
        Receivable.store_id == store_id, Receivable.issued_at >= start_dt, Receivable.issued_at < end_exclusive,
    ), Receivable, context)).all()
    receipts = session.exec(scope_tenant_query(select(ReceivableReceipt).where(
        ReceivableReceipt.store_id == store_id, ReceivableReceipt.confirmed_at >= start_dt,
        ReceivableReceipt.confirmed_at < end_exclusive, ReceivableReceipt.status == ReceivableReceiptStatusEnum.CONFIRMED,
    ), ReceivableReceipt, context)).all()
    facts: dict[tuple, dict] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for sale in sales:
        key = (sale.occurred_at.date(), *_dimensions(sale))
        facts[key]["gross_revenue"] += _money(sale.gross_total)
        facts[key]["net_revenue"] += _money(sale.net_total)
        facts[key]["discount_total"] += _money(sale.discount_total)
        facts[key]["sales_count"] += 1
    for payment in payments:
        sale = sale_map.get(payment.sale_id)
        if not sale:
            continue
        key = (sale.occurred_at.date(), *_dimensions(sale))
        facts[key]["confirmed_receipts"] += _money(payment.amount)
        target = "cash_receipts" if payment.method == PaymentMethodEnum.CASH else "pix_receipts" if payment.method == PaymentMethodEnum.PIX else "card_receipts"
        facts[key][target] += _money(payment.amount)
    for refund in refunds:
        payment = next((item for item in payments if item.id == refund.payment_id), None)
        sale = sale_map.get(payment.sale_id) if payment else None
        key = (refund.created_at.date(), *(_dimensions(sale) if sale else ("UNASSIGNED", "UNASSIGNED", "UNKNOWN")))
        facts[key]["refunds_total"] += _money(refund.amount)
    for title in receivables:
        sale = sale_map.get(title.sale_id)
        key = (title.issued_at.date(), *(_dimensions(sale) if sale else ("UNASSIGNED", "UNASSIGNED", "CREDIT")))
        facts[key]["receivables_issued"] += _money(title.principal_amount)

    session.exec(delete(BiDailyFact).where(
        BiDailyFact.tenant_id == context.tenant_id, BiDailyFact.store_id == store_id,
        BiDailyFact.competence_date >= start, BiDailyFact.competence_date <= end,
    ))
    now = datetime.utcnow()
    # The watermark is the newest timestamp of a persisted source fact that
    # actually participated in this projection.  It must never be the time
    # at which the rebuild happened: that would report freshness even when the
    # tenant has no operational data (or when a connector has not delivered it).
    source_timestamps = [
        *(item.occurred_at for item in sales if item.occurred_at),
        *(item.created_at for item in payments if item.created_at),
        *(item.created_at for item in refunds if item.created_at),
        *(item.issued_at for item in receivables if item.issued_at),
        *(item.confirmed_at for item in receipts if item.confirmed_at),
    ]
    for (competence, register_key, operator_key, channel_key), values in facts.items():
        session.add(BiDailyFact(
            tenant_id=context.tenant_id, store_id=store_id, competence_date=competence,
            scope=BiFactScopeEnum.SALES, register_key=register_key, operator_key=operator_key,
            channel_key=channel_key, projected_at=now, **dict(values),
        ))
    day = start
    while day <= end:
        lower = datetime.combine(day, time.min); upper = lower + timedelta(days=1)
        table_rows = session.exec(scope_tenant_query(select(TableSession).where(
            TableSession.store_id == store_id, TableSession.closed_at >= lower, TableSession.closed_at < upper,
        ), TableSession, context)).all()
        tickets = session.exec(scope_tenant_query(select(ProductionTicket).where(
            ProductionTicket.store_id == store_id, ProductionTicket.delivered_at >= lower, ProductionTicket.delivered_at < upper,
        ), ProductionTicket, context)).all()
        transfers = session.exec(scope_tenant_query(select(TransferRecord).where(
            TransferRecord.store_id == store_id, TransferRecord.created_at >= lower, TransferRecord.created_at < upper,
        ), TransferRecord, context)).all()
        settlements = session.exec(scope_tenant_query(select(MarketplaceSettlement).where(
            MarketplaceSettlement.store_id == store_id, MarketplaceSettlement.competence_date == day,
        ), MarketplaceSettlement, context)).all()
        source_timestamps.extend(item.closed_at for item in table_rows if item.closed_at)
        source_timestamps.extend(item.delivered_at for item in tickets if item.delivered_at)
        source_timestamps.extend(item.created_at for item in transfers if item.created_at)
        day_receipts = [item for item in receipts if item.confirmed_at and item.confirmed_at.date() == day]
        stockouts = 0
        if day == today:
            balances = session.exec(select(InventoryBalance).where(
                InventoryBalance.tenant_id == context.tenant_id, InventoryBalance.store_id == store_id,
            )).all()
            stockouts = sum(1 for item in balances if item.quantity <= item.minimum_stock)
        session.add(BiDailyFact(
            tenant_id=context.tenant_id, store_id=store_id, competence_date=day,
            scope=BiFactScopeEnum.OPERATIONS, register_key="ALL", operator_key="ALL", channel_key="ALL",
            receivables_settled=sum((_money(item.amount) for item in day_receipts), ZERO),
            marketplace_settled=sum((_money(item.paid_amount) for item in settlements), ZERO),
            table_sessions_closed=len(table_rows),
            table_service_seconds=sum((max(0, int((item.closed_at - item.opened_at).total_seconds())) for item in table_rows if item.closed_at), 0),
            production_tickets_completed=len(tickets),
            production_seconds=sum((max(0, int((item.delivered_at - item.created_at).total_seconds())) for item in tickets if item.delivered_at), 0),
            transfers_count=len(transfers), stockout_products=stockouts, projected_at=now,
        ))
        day += timedelta(days=1)
    if not state:
        state = BiProjectionState(tenant_id=context.tenant_id, store_id=store_id)
    else:
        state.version += 1
    state.last_competence = end
    state.source_watermark = max(source_timestamps, default=None)
    state.projected_at = now
    state.status = "READY"; state.last_error = None
    session.add(state)
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=store_id, actor_id=actor_id,
        action="bi.projection.refreshed", target=f"BI-{store_id}",
        audit_payload={"start_date": start.isoformat(), "end_date": end.isoformat(), "version": state.version},
        aggregate_type="bi_projection", aggregate_id=str(store_id), event_type="bi.projection.refreshed",
        outbox_payload={"store_id": str(store_id), "last_competence": end.isoformat(), "version": state.version},
    )
    session.commit(); session.refresh(state)
    return state


def summary(
    session: Session, context: TenantContext, *, store_id: uuid.UUID, days: int = 30,
    register_id: Optional[uuid.UUID] = None, operator_id: Optional[uuid.UUID] = None,
    channel: Optional[str] = None,
) -> dict:
    if days < 1 or days > 366:
        raise HTTPException(status_code=422, detail="Período deve possuir entre 1 e 366 dias.")
    state = session.exec(scope_tenant_query(select(BiProjectionState).where(
        BiProjectionState.store_id == store_id, BiProjectionState.projection_key == "BI_V1_DAILY",
    ), BiProjectionState, context)).first()
    # States written before 5.4.2 used the rebuild instant as the watermark.
    # Rebuild those records once so an old, synthetic freshness claim cannot
    # survive merely because the projection itself is still recent.
    legacy_watermark = bool(state and state.source_watermark and state.source_watermark == state.projected_at)
    if not state or legacy_watermark or datetime.utcnow() - state.projected_at > timedelta(minutes=5):
        state = refresh_daily_projection(session, context, store_id=store_id, actor_id=resolve_actor(context))
    end = datetime.utcnow().date(); start = end - timedelta(days=days - 1)
    query = select(BiDailyFact).where(
        BiDailyFact.tenant_id == context.tenant_id, BiDailyFact.store_id == store_id,
        BiDailyFact.competence_date >= start, BiDailyFact.competence_date <= end,
    )
    rows = session.exec(query).all()
    sales_rows = [row for row in rows if row.scope == BiFactScopeEnum.SALES]
    if register_id: sales_rows = [row for row in sales_rows if row.register_key == str(register_id)]
    if operator_id: sales_rows = [row for row in sales_rows if row.operator_key == str(operator_id)]
    if channel: sales_rows = [row for row in sales_rows if row.channel_key == channel]
    operation_rows = [row for row in rows if row.scope == BiFactScopeEnum.OPERATIONS]
    daily = []
    day = start
    while day <= end:
        matching = [row for row in sales_rows if row.competence_date == day]
        daily.append({"date": day.isoformat(), "revenue": float(sum((row.net_revenue for row in matching), ZERO)), "sales": sum(row.sales_count for row in matching)})
        day += timedelta(days=1)
    revenue = sum((row.net_revenue for row in sales_rows), ZERO)
    sales_count = sum(row.sales_count for row in sales_rows)
    table_count = sum(row.table_sessions_closed for row in operation_rows)
    production_count = sum(row.production_tickets_completed for row in operation_rows)
    live_open_sales = session.exec(select(Sale).where(
        Sale.tenant_id == context.tenant_id, Sale.store_id == store_id,
        Sale.status.in_({SaleStatusEnum.DRAFT, SaleStatusEnum.CHECKOUT, SaleStatusEnum.AWAITING_PAYMENT}),
    )).all()
    today_rows = [row for row in sales_rows if row.competence_date == end]
    products = session.exec(select(Product).where(Product.tenant_id == context.tenant_id)).all()
    customers = session.exec(select(Customer).where(Customer.tenant_id == context.tenant_id)).all()
    members = session.exec(select(Membership).where(Membership.tenant_id == context.tenant_id, Membership.status == MembershipStatusEnum.ACTIVE)).all()
    active_cash = session.exec(select(CashSession).where(CashSession.tenant_id == context.tenant_id, CashSession.store_id == store_id, CashSession.status == CashSessionStatusEnum.OPEN)).all()
    terminals = session.exec(select(Register).where(Register.tenant_id == context.tenant_id, Register.store_id == store_id)).all()
    alerts = []
    if not terminals: alerts.append("Nenhum terminal de caixa está configurado no contexto autorizado.")
    if not products: alerts.append("O catálogo ainda não possui produtos.")
    if any(row.stockout_products for row in operation_rows if row.competence_date == end): alerts.append("Existem produtos no estoque mínimo ou em ruptura.")
    return {
        "generated_at": state.projected_at,
        "projection_lag_seconds": max(0, int((datetime.utcnow() - state.source_watermark).total_seconds())) if state.source_watermark else 0,
        "projection_version": state.version, "source_watermark": state.source_watermark,
        "revenue_today": float(sum((row.net_revenue for row in today_rows), ZERO)), "revenue_30d": float(revenue),
        "sales_today": sum(row.sales_count for row in today_rows), "sales_30d": sales_count,
        "average_ticket_30d": float(revenue / sales_count) if sales_count else 0, "open_sales": len(live_open_sales),
        "confirmed_receipts_30d": float(sum((row.confirmed_receipts for row in sales_rows), ZERO)),
        "refunds_30d": float(sum((row.refunds_total for row in sales_rows), ZERO)),
        "receivables_issued_30d": float(sum((row.receivables_issued for row in sales_rows), ZERO)),
        "receivables_settled_30d": float(sum((row.receivables_settled for row in operation_rows), ZERO)),
        "marketplace_settled_30d": float(sum((row.marketplace_settled for row in operation_rows), ZERO)),
        "table_sessions_closed_30d": table_count,
        "table_average_minutes_30d": (sum(row.table_service_seconds for row in operation_rows) / table_count / 60) if table_count else 0,
        "production_tickets_30d": production_count,
        "production_average_minutes_30d": (sum(row.production_seconds for row in operation_rows) / production_count / 60) if production_count else 0,
        "transfers_30d": sum(row.transfers_count for row in operation_rows),
        "stockout_products": next((row.stockout_products for row in operation_rows if row.competence_date == end), 0),
        "active_cash_sessions": len(active_cash), "products": len(products), "customers": len(customers),
        "active_team_members": len(members), "daily_revenue": daily, "alerts": alerts,
        "formulas": FORMULAS,
    }


def drilldown(session: Session, context: TenantContext, *, store_id: uuid.UUID, metric: str,
              competence_date: date, offset: int, limit: int) -> dict:
    if metric not in {"net_revenue", "discount_total", "receivables_issued"}:
        raise HTTPException(status_code=422, detail="Métrica não possui drill-down publicado.")
    lower = datetime.combine(competence_date, time.min); upper = lower + timedelta(days=1)
    if metric == "receivables_issued":
        rows = session.exec(scope_tenant_query(select(Receivable).where(
            Receivable.store_id == store_id, Receivable.issued_at >= lower, Receivable.issued_at < upper,
        ), Receivable, context).order_by(Receivable.issued_at.desc())).all()
        items = [{"source_type": "RECEIVABLE", "source_id": str(row.id), "occurred_at": row.issued_at, "amount": float(row.principal_amount)} for row in rows]
    else:
        rows = session.exec(scope_tenant_query(select(Sale).where(
            Sale.store_id == store_id, Sale.occurred_at >= lower, Sale.occurred_at < upper,
            Sale.status.in_({SaleStatusEnum.PAID, SaleStatusEnum.COMPLETED, SaleStatusEnum.PARTIALLY_REFUNDED, SaleStatusEnum.REFUNDED}),
        ), Sale, context).order_by(Sale.occurred_at.desc())).all()
        items = [{"source_type": "SALE", "source_id": str(row.id), "occurred_at": row.occurred_at,
                  "amount": float(row.net_total if metric == "net_revenue" else row.discount_total)} for row in rows]
    return {"metric": metric, "competence_date": competence_date, "total": len(items), "offset": offset, "limit": limit, "items": items[offset:offset + limit]}

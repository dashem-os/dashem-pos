import uuid
from decimal import Decimal

from sqlmodel import Session

from app.api.v1.endpoints.management import management_overview
from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.catalog import Product
from app.models.identity import Register, Membership, MembershipStatusEnum, RoleEnum, Store, Tenant, TenantStatusEnum, User
from app.models.payment import CashSession, Payment, PaymentMethodEnum, PaymentStatusEnum
from app.models.sale import Customer, Sale, SaleStatusEnum


def test_management_overview_is_aggregated_from_persisted_tenant_data():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"Overview {suffix}", slug=f"overview-{suffix}", status=TenantStatusEnum.ACTIVE)
        user = User(email=f"overview-{suffix}@example.test", full_name="Manager")
        session.add(tenant); session.add(user); session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"M-{suffix}")
        product = Product(tenant_id=tenant.id, name="Produto", sku=f"SKU-{suffix}")
        customer = Customer(tenant_id=tenant.id, name="Cliente")
        session.add(store); session.add(product); session.add(customer); session.flush()
        register = Register(tenant_id=tenant.id, store_id=store.id, name="Caixa", code=f"CX-{suffix}")
        session.add(register); session.flush()
        cash = CashSession(
            tenant_id=tenant.id, store_id=store.id, register_id=register.id,
            operator_id=user.id, opening_balance=Decimal("100"),
        )
        sale = Sale(
            tenant_id=tenant.id, store_id=store.id, customer_id=customer.id,
            status=SaleStatusEnum.COMPLETED, gross_total=Decimal("125"), net_total=Decimal("125"),
        )
        open_sale = Sale(tenant_id=tenant.id, store_id=store.id, status=SaleStatusEnum.DRAFT)
        membership = Membership(
            tenant_id=tenant.id, user_id=user.id, role=RoleEnum.MANAGER,
            status=MembershipStatusEnum.ACTIVE,
        )
        session.add(cash); session.add(sale); session.add(open_sale); session.add(membership); session.flush()
        session.add(Payment(
            tenant_id=tenant.id, store_id=store.id, sale_id=sale.id,
            cash_session_id=cash.id, method=PaymentMethodEnum.CASH,
            status=PaymentStatusEnum.CONFIRMED, amount=Decimal("125"),
        ))
        tenant_id, store_id, user_id = tenant.id, store.id, user.id
        session.commit()

    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_id, user_id)
        overview = management_overview(
            context=TenantContext(
                tenant_id=tenant_id, store_id=store_id, user_id=user_id,
                role=RoleEnum.MANAGER, permissions=("management.read",),
            ),
            session=session,
        )
        assert overview.revenue_today == 125
        assert overview.sales_today == 1
        assert overview.average_ticket_30d == 125
        assert overview.confirmed_receipts_30d == 125
        assert overview.open_sales == 1
        assert overview.active_cash_sessions == 1
        assert overview.products == 1
        assert overview.customers == 1
        assert overview.active_team_members == 1
        assert sum(day.sales for day in overview.daily_revenue) == 1
        assert overview.alerts == []

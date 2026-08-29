from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, text
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.identity import SubscriptionStatusEnum, TenantSubscription
from app.models.owner_finance import (
    SaasFinanceDailyMetric, SaasFinanceSubscriptionSnapshot,
    SaasMrrMovementTypeEnum,
)
from app.models.platform import PlatformRoleEnum, TenantContract
from app.services import owner_finance_service
from tests.test_owner_finance_f2 import _invoice_source, _platform_user


def _new_contract_version(session: Session, tenant_id, actor_id, amount: Decimal) -> TenantContract:
    previous = session.exec(select(TenantContract).where(
        TenantContract.tenant_id == tenant_id
    ).order_by(TenantContract.version.desc())).first()
    assert previous is not None
    limits = dict(previous.limits)
    limits["billing"] = dict(limits.get("billing") or {})
    limits["billing"]["monthly_amount"] = str(amount)
    contract = TenantContract(
        tenant_id=tenant_id,
        version=previous.version + 1,
        status="ACTIVE",
        plan_id=previous.plan_id,
        limits=limits,
        capability_keys=list(previous.capability_keys),
        starts_at=datetime.utcnow(),
        reason="Mudança controlada para validar projeção financeira.",
        created_by=actor_id,
    )
    session.add(contract)
    session.commit()
    return contract


def test_f4_projection_has_baseline_version_watermark_and_real_movements():
    with Session(engine) as session:
        _, actor = _platform_user(session, PlatformRoleEnum.PLATFORM_OWNER)
        set_platform_db_context(session, actor.id)
        session.exec(delete(SaasFinanceSubscriptionSnapshot))
        session.exec(delete(SaasFinanceDailyMetric))
        session.commit()
        tenant, _, _, _, _ = _invoice_source(session, actor)
        subscription = session.get(TenantSubscription, tenant.id)
        assert subscription is not None

        baseline = owner_finance_service.rebuild_finance_projection(
            session,
            metric_date=date(2028, 1, 1),
            actor_id=actor.id,
            idempotency_key="f4-projection-baseline-2028-01-01",
        )
        assert baseline.formula_version == owner_finance_service.SAAS_FINANCE_FORMULA_VERSION
        assert baseline.source_fingerprint and baseline.watermark
        assert baseline.projected_arr == baseline.contracted_mrr * 12
        assert baseline.new_mrr is None and baseline.churned_mrr is None
        baseline_detail = session.exec(select(SaasFinanceSubscriptionSnapshot).where(
            SaasFinanceSubscriptionSnapshot.metric_id == baseline.id,
            SaasFinanceSubscriptionSnapshot.tenant_id == tenant.id,
        )).one()
        assert baseline_detail.movement_type == SaasMrrMovementTypeEnum.BASELINE
        assert baseline_detail.previous_mrr is None
        assert baseline_detail.current_mrr == Decimal("249.90")

        replay = owner_finance_service.rebuild_finance_projection(
            session,
            metric_date=date(2028, 1, 1),
            actor_id=actor.id,
            idempotency_key="f4-projection-baseline-2028-01-01",
        )
        assert replay.id == baseline.id and replay.source_fingerprint == baseline.source_fingerprint

        subscription.monthly_amount = Decimal("349.90")
        subscription.gross_monthly_amount = Decimal("349.90")
        subscription.version += 1
        subscription.updated_at = datetime.utcnow()
        session.add(subscription); session.commit()
        _new_contract_version(session, tenant.id, actor.id, Decimal("349.90"))
        expanded = owner_finance_service.rebuild_finance_projection(
            session,
            metric_date=date(2028, 1, 2),
            actor_id=actor.id,
            idempotency_key="f4-projection-expanded-2028-01-02",
        )
        expansion = session.exec(select(SaasFinanceSubscriptionSnapshot).where(
            SaasFinanceSubscriptionSnapshot.metric_id == expanded.id,
            SaasFinanceSubscriptionSnapshot.tenant_id == tenant.id,
        )).one()
        assert expansion.movement_type == SaasMrrMovementTypeEnum.EXPANSION
        assert expansion.previous_mrr == Decimal("249.90")
        assert expansion.current_mrr == Decimal("349.90")
        assert expansion.movement_amount == Decimal("100.00")
        assert expanded.expansion_mrr == Decimal("100.00")
        assert expanded.net_new_mrr == Decimal("100.00")

        subscription.status = SubscriptionStatusEnum.CANCELED
        subscription.version += 1
        subscription.updated_at = datetime.utcnow()
        session.add(subscription); session.commit()
        _new_contract_version(session, tenant.id, actor.id, Decimal("349.90"))
        churned = owner_finance_service.rebuild_finance_projection(
            session,
            metric_date=date(2028, 1, 3),
            actor_id=actor.id,
            idempotency_key="f4-projection-churned-2028-01-03",
        )
        churn = session.exec(select(SaasFinanceSubscriptionSnapshot).where(
            SaasFinanceSubscriptionSnapshot.metric_id == churned.id,
            SaasFinanceSubscriptionSnapshot.tenant_id == tenant.id,
        )).one()
        assert churn.movement_type == SaasMrrMovementTypeEnum.CHURN
        assert churn.current_mrr == Decimal("0.00")
        assert churn.movement_amount == Decimal("349.90")
        assert churned.churned_mrr == Decimal("349.90")
        assert churned.net_new_mrr == Decimal("-349.90")


def test_f4_projection_tables_are_platform_only_and_formula_has_no_tenant_operations():
    with Session(engine) as session:
        rows = session.exec(text("""
            SELECT class.relname, class.relrowsecurity, class.relforcerowsecurity,
                   policy.polname
            FROM pg_class AS class
            JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
            LEFT JOIN pg_policy AS policy ON policy.polrelid = class.oid
            WHERE namespace.nspname = current_schema()
              AND class.relname IN (
                'saas_finance_daily_metrics',
                'saas_finance_subscription_snapshots'
              )
        """)).all()
    assert {row[0] for row in rows} == {
        "saas_finance_daily_metrics", "saas_finance_subscription_snapshots"
    }
    assert all(row[1] is True and row[2] is True for row in rows)
    assert all(row[3] == f"{row[0]}_platform_only" for row in rows)

    source = owner_finance_service.rebuild_finance_projection.__code__.co_names
    for forbidden in ("Sale", "CashSession", "InventoryBalance", "Receivable"):
        assert forbidden not in source


def test_f4_projection_daily_metric_is_rebuildable_not_duplicated():
    with Session(engine) as session:
        _, actor = _platform_user(session, PlatformRoleEnum.PLATFORM_OWNER)
        set_platform_db_context(session, actor.id)
        if not session.exec(select(TenantSubscription)).first():
            _invoice_source(session, actor)
        first = owner_finance_service.rebuild_finance_projection(
            session, metric_date=date(2028, 2, 1), actor_id=actor.id,
            idempotency_key="f4-rebuild-first-2028-02-01",
        )
        first_version = first.version
        rebuilt = owner_finance_service.rebuild_finance_projection(
            session, metric_date=date(2028, 2, 1), actor_id=actor.id,
            idempotency_key="f4-rebuild-second-2028-02-01",
        )
        assert rebuilt.id == first.id
        assert rebuilt.version == first_version + 1
        assert rebuilt.source_fingerprint == first.source_fingerprint
        assert len(session.exec(select(SaasFinanceDailyMetric).where(
            SaasFinanceDailyMetric.metric_date == date(2028, 2, 1)
        )).all()) == 1

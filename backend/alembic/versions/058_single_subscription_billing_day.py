"""Keep one persisted and configurable SaaS billing day.

Revision ID: 058_subscription_billing_day
Revises: 057_saas_billing_day_first
"""

from alembic import op
import sqlalchemy as sa


revision = "058_subscription_billing_day"
down_revision = "057_saas_billing_day_first"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE tenant_subscriptions AS subscription
        SET plan_id = latest_contract.plan_id,
            contracted_user_limit = COALESCE(
                subscription.contracted_user_limit,
                NULLIF(latest_contract.limits ->> 'users', '')::integer
            ),
            contracted_device_limit = COALESCE(
                subscription.contracted_device_limit,
                NULLIF(latest_contract.limits ->> 'devices', '')::integer
            ),
            contracted_store_limit = COALESCE(
                subscription.contracted_store_limit,
                NULLIF(latest_contract.limits ->> 'units', '')::integer
            )
        FROM (
            SELECT DISTINCT ON (tenant_id) tenant_id, plan_id, limits
            FROM tenant_contracts
            WHERE plan_id IS NOT NULL
            ORDER BY tenant_id, version DESC
        ) AS latest_contract
        WHERE subscription.tenant_id = latest_contract.tenant_id
          AND subscription.plan_id IS NULL
        """
    )
    op.drop_constraint(
        "ck_tenant_subscriptions_billing_day_first",
        "tenant_subscriptions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_tenant_subscriptions_billing_day_range",
        "tenant_subscriptions",
        "billing_day BETWEEN 1 AND 28",
    )
    op.drop_column("tenant_subscriptions", "next_due_date")


def downgrade() -> None:
    op.add_column(
        "tenant_subscriptions",
        sa.Column("next_due_date", sa.Date(), nullable=True),
    )
    op.drop_constraint(
        "ck_tenant_subscriptions_billing_day_range",
        "tenant_subscriptions",
        type_="check",
    )
    op.execute("UPDATE tenant_subscriptions SET billing_day = 1")
    op.create_check_constraint(
        "ck_tenant_subscriptions_billing_day_first",
        "tenant_subscriptions",
        "billing_day = 1",
    )

"""Fix SaaS contractual billing to the first day of every month.

Revision ID: 057_saas_billing_day_first
Revises: 056_owner_commercial_pricing
"""

from alembic import op


revision = "057_saas_billing_day_first"
down_revision = "056_owner_commercial_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE tenant_subscriptions SET billing_day = 1, next_due_date = NULL "
        "WHERE billing_day <> 1 OR next_due_date IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_tenant_subscriptions_billing_day_first",
        "tenant_subscriptions",
        "billing_day = 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tenant_subscriptions_billing_day_first",
        "tenant_subscriptions",
        type_="check",
    )

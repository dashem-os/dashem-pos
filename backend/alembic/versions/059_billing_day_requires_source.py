"""Require a persisted source for the SaaS billing day.

Revision ID: 059_billing_day_source
Revises: 058_subscription_billing_day
"""

from alembic import op
import sqlalchemy as sa


revision = "059_billing_day_source"
down_revision = "058_subscription_billing_day"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "tenant_subscriptions",
        "billing_day",
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )
    op.execute(
        """
        UPDATE tenant_subscriptions AS subscription
        SET billing_day = (
            SELECT CASE
                WHEN (contract.limits #>> '{billing,billing_day}') ~ '^[0-9]+$'
                 AND (contract.limits #>> '{billing,billing_day}')::integer BETWEEN 1 AND 28
                THEN (contract.limits #>> '{billing,billing_day}')::integer
                ELSE NULL
            END
            FROM tenant_contracts AS contract
            WHERE contract.tenant_id = subscription.tenant_id
            ORDER BY contract.version DESC
            LIMIT 1
        )
        """
    )


def downgrade() -> None:
    op.execute("UPDATE tenant_subscriptions SET billing_day = 1 WHERE billing_day IS NULL")
    op.alter_column(
        "tenant_subscriptions",
        "billing_day",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="1",
    )

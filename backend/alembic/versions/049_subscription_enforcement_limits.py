"""Persist tenant-readable contractual limits for runtime enforcement.

Revision ID: 049_subscription_limits
Revises: 048_owner_flexible_contract
"""

from alembic import op
import sqlalchemy as sa


revision = "049_subscription_limits"
down_revision = "048_owner_flexible_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_subscriptions", sa.Column("contracted_user_limit", sa.Integer(), nullable=True))
    op.add_column("tenant_subscriptions", sa.Column("contracted_device_limit", sa.Integer(), nullable=True))
    op.add_column("tenant_subscriptions", sa.Column("contracted_store_limit", sa.Integer(), nullable=True))
    op.execute("""
        UPDATE tenant_subscriptions AS subscription
        SET contracted_user_limit = (
                SELECT NULLIF(contract.limits->>'users', '')::integer
                FROM tenant_contracts AS contract
                WHERE contract.tenant_id = subscription.tenant_id
                ORDER BY contract.version DESC LIMIT 1
            ),
            contracted_device_limit = (
                SELECT NULLIF(contract.limits->>'devices', '')::integer
                FROM tenant_contracts AS contract
                WHERE contract.tenant_id = subscription.tenant_id
                ORDER BY contract.version DESC LIMIT 1
            ),
            contracted_store_limit = (
                SELECT NULLIF(contract.limits->>'units', '')::integer
                FROM tenant_contracts AS contract
                WHERE contract.tenant_id = subscription.tenant_id
                ORDER BY contract.version DESC LIMIT 1
            )
    """)


def downgrade() -> None:
    op.drop_column("tenant_subscriptions", "contracted_store_limit")
    op.drop_column("tenant_subscriptions", "contracted_device_limit")
    op.drop_column("tenant_subscriptions", "contracted_user_limit")

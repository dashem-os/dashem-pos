"""Flexible Owner contract, tenant classification and SaaS billing fields.

Revision ID: 048_owner_flexible_contract
Revises: 047_owner_p0_contract
"""

from alembic import op
import sqlalchemy as sa


revision = "048_owner_flexible_contract"
down_revision = "047_owner_p0_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_profiles", sa.Column("tenant_type", sa.String(), nullable=False, server_default="CUSTOMER"))
    op.add_column("tenant_profiles", sa.Column("lifecycle_phase", sa.String(), nullable=False, server_default="TEST"))
    op.create_index("ix_tenant_profiles_tenant_type", "tenant_profiles", ["tenant_type"])
    op.create_index("ix_tenant_profiles_lifecycle_phase", "tenant_profiles", ["lifecycle_phase"])
    op.execute("UPDATE tenant_profiles SET tenant_type = CASE WHEN customer_type = 'INTERNAL' THEN 'INTERNAL' ELSE 'CUSTOMER' END")
    op.execute("UPDATE tenant_profiles SET lifecycle_phase = CASE WHEN customer_type = 'PILOT' THEN 'PILOT' WHEN customer_type = 'CUSTOMER' THEN 'PRODUCTION' ELSE 'TEST' END")

    op.add_column("service_plans", sa.Column("monthly_price", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("tenant_subscriptions", sa.Column("monthly_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("tenant_subscriptions", sa.Column("billing_day", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("tenant_subscriptions", sa.Column("billing_status", sa.String(length=32), nullable=False, server_default="PENDING"))
    op.add_column("tenant_subscriptions", sa.Column("next_due_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_subscriptions", "next_due_date")
    op.drop_column("tenant_subscriptions", "billing_status")
    op.drop_column("tenant_subscriptions", "billing_day")
    op.drop_column("tenant_subscriptions", "monthly_amount")
    op.drop_column("service_plans", "monthly_price")
    op.drop_index("ix_tenant_profiles_lifecycle_phase", table_name="tenant_profiles")
    op.drop_index("ix_tenant_profiles_tenant_type", table_name="tenant_profiles")
    op.drop_column("tenant_profiles", "lifecycle_phase")
    op.drop_column("tenant_profiles", "tenant_type")

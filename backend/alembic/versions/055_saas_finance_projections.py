"""Add rebuildable SaaS financial projections and subscription drill-down.

Revision ID: 055_saas_finance_projections
Revises: 054_saas_receipts_collections
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "055_saas_finance_projections"
down_revision = "054_saas_receipts_collections"
branch_labels = None
depends_on = None


def _platform_table(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_platform_only ON {table} FOR ALL "
        "USING (current_setting('app.platform_access', true) = 'true') "
        "WITH CHECK (current_setting('app.platform_access', true) = 'true')"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    money = sa.Numeric(14, 2)
    rate = sa.Numeric(9, 6)
    op.create_table(
        "saas_finance_daily_metrics",
        sa.Column("id", uid, nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("formula_version", sa.String(40), nullable=False),
        sa.Column("watermark", sa.DateTime(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("rebuild_idempotency_key", sa.String(160), nullable=False),
        sa.Column("rebuild_request_hash", sa.String(64), nullable=False),
        sa.Column("active_subscriptions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("excluded_subscriptions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contracted_mrr", money, nullable=False),
        sa.Column("projected_arr", money, nullable=False),
        sa.Column("new_mrr", money, nullable=True),
        sa.Column("expansion_mrr", money, nullable=True),
        sa.Column("contraction_mrr", money, nullable=True),
        sa.Column("churned_mrr", money, nullable=True),
        sa.Column("net_new_mrr", money, nullable=True),
        sa.Column("logo_churn_rate", rate, nullable=True),
        sa.Column("invoiced_total", money, nullable=False),
        sa.Column("received_total", money, nullable=False),
        sa.Column("refunded_total", money, nullable=False),
        sa.Column("open_balance", money, nullable=False),
        sa.Column("overdue_balance", money, nullable=False),
        sa.Column("collection_rate", rate, nullable=True),
        sa.Column("delinquency_rate", rate, nullable=True),
        sa.Column("invoice_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paid_invoice_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overdue_invoice_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("calculated_by", uid, nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["calculated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("metric_date", name="uq_saas_finance_daily_metrics_date"),
        sa.UniqueConstraint(
            "rebuild_idempotency_key",
            name="uq_saas_finance_daily_metrics_rebuild_idempotency",
        ),
        sa.CheckConstraint("version >= 1", name="ck_saas_finance_daily_metrics_version_positive"),
    )
    for column in ("metric_date", "formula_version", "watermark", "calculated_by", "calculated_at"):
        op.create_index(f"ix_saas_finance_daily_metrics_{column}", "saas_finance_daily_metrics", [column])

    op.create_table(
        "saas_finance_subscription_snapshots",
        sa.Column("id", uid, nullable=False),
        sa.Column("metric_id", uid, nullable=False),
        sa.Column("tenant_id", uid, nullable=False),
        sa.Column("subscription_version", sa.Integer(), nullable=False),
        sa.Column("subscription_status", sa.String(32), nullable=False),
        sa.Column("contract_id", uid, nullable=True),
        sa.Column("contract_version", sa.Integer(), nullable=True),
        sa.Column("included_in_mrr", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("exclusion_reason", sa.String(80), nullable=True),
        sa.Column("previous_mrr", money, nullable=True),
        sa.Column("current_mrr", money, nullable=False),
        sa.Column("movement_type", sa.String(), nullable=False),
        sa.Column("movement_amount", money, nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["metric_id"], ["saas_finance_daily_metrics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["contract_id"], ["tenant_contracts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "metric_id", "tenant_id",
            name="uq_saas_finance_subscription_snapshot_metric_tenant",
        ),
    )
    for column in ("metric_id", "tenant_id", "subscription_status", "included_in_mrr", "movement_type"):
        op.create_index(
            f"ix_saas_finance_subscription_snapshots_{column}",
            "saas_finance_subscription_snapshots", [column],
        )

    _platform_table("saas_finance_daily_metrics")
    _platform_table("saas_finance_subscription_snapshots")


def downgrade() -> None:
    op.drop_table("saas_finance_subscription_snapshots")
    op.drop_table("saas_finance_daily_metrics")

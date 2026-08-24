"""Complete the platform Control contracts.

Revision ID: 037_control_completion
Revises: 036_employee_access_boundary
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "037_control_completion"
down_revision = "036_employee_access_boundary"
branch_labels = None
depends_on = None


def _index(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "tenant_contracts",
        sa.Column("id", uid, nullable=False), sa.Column("tenant_id", uid, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("plan_id", uid, nullable=True), sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("capability_keys", sa.JSON(), nullable=False), sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("ends_at", sa.DateTime(), nullable=True), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", uid, nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]), sa.ForeignKeyConstraint(["plan_id"], ["service_plans.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "version", name="uq_tenant_contract_version"),
    )
    _index("tenant_contracts", "tenant_id", "status", "plan_id", "created_by", "created_at")

    op.create_table(
        "tenant_onboarding_checkpoints",
        sa.Column("id", uid, nullable=False), sa.Column("tenant_id", uid, nullable=False),
        sa.Column("key", sa.String(80), nullable=False), sa.Column("label", sa.String(180), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("completed_by", uid, nullable=True), sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["completed_by"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_onboarding_checkpoint"),
    )
    _index("tenant_onboarding_checkpoints", "tenant_id", "key", "status", "completed_by")

    op.create_table(
        "identity_delivery_events",
        sa.Column("id", uid, nullable=False), sa.Column("tenant_id", uid, nullable=False),
        sa.Column("membership_id", uid, nullable=True), sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("recipient_masked", sa.String(254), nullable=False), sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("provider_message_id", sa.String(180), nullable=True),
        sa.Column("sanitized_detail", sa.String(500), nullable=True), sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]), sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("identity_delivery_events", "tenant_id", "membership_id", "kind", "status", "occurred_at")

    op.create_table(
        "assisted_support_grants",
        sa.Column("id", uid, nullable=False), sa.Column("tenant_id", uid, nullable=False),
        sa.Column("requested_by", uid, nullable=False), sa.Column("approved_by", uid, nullable=True),
        sa.Column("scope", sa.JSON(), nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False), sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True), sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]), sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("assisted_support_grants", "tenant_id", "requested_by", "approved_by", "status", "expires_at", "created_at")

    op.create_table(
        "platform_incidents",
        sa.Column("id", uid, nullable=False), sa.Column("tenant_id", uid, nullable=True),
        sa.Column("title", sa.String(180), nullable=False), sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(), nullable=False), sa.Column("component", sa.String(80), nullable=False),
        sa.Column("sanitized_summary", sa.Text(), nullable=False), sa.Column("correlation_id", sa.String(120), nullable=True),
        sa.Column("opened_by", uid, nullable=False), sa.Column("resolved_by", uid, nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=False), sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["opened_by"], ["users.id"]), sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("platform_incidents", "tenant_id", "severity", "status", "component", "correlation_id", "opened_by", "resolved_by", "opened_at")

    for table in ("tenant_contracts", "tenant_onboarding_checkpoints", "identity_delivery_events", "assisted_support_grants", "platform_incidents"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_platform_only ON {table} FOR ALL USING (current_setting('app.platform_access', true) = 'true') WITH CHECK (current_setting('app.platform_access', true) = 'true')")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")


def downgrade() -> None:
    for table in ("platform_incidents", "assisted_support_grants", "identity_delivery_events", "tenant_onboarding_checkpoints", "tenant_contracts"):
        op.drop_table(table)

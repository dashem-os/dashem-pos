"""Persist tenant commercial requests and append-only Owner decisions.

Revision ID: 063_commercial_requests
Revises: 062_contract_tenant_read
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "063_commercial_requests"
down_revision = "062_contract_tenant_read"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commercial_change_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_contract_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("requested_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('ACTIVITY', 'CAPABILITY', 'USER_LIMIT', 'DEVICE_LIMIT', "
            "'UNIT_LIMIT', 'STORAGE_LIMIT', 'INTEGRATION')",
            name="ck_commercial_change_request_kind",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'DECLINED', 'CANCELED')",
            name="ck_commercial_change_request_status",
        ),
        sa.CheckConstraint(
            "source_contract_version >= 1",
            name="ck_commercial_change_request_contract_version",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_contract_id"], ["tenant_contracts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "kind", "requested_by", "source_contract_id", "status", "requested_at", "decided_at"):
        op.create_index(f"ix_commercial_change_requests_{column}", "commercial_change_requests", [column])

    op.create_table(
        "commercial_change_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resulting_contract_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("decision IN ('APPROVE', 'DECLINE')", name="ck_commercial_change_decision_kind"),
        sa.ForeignKeyConstraint(["request_id"], ["commercial_change_requests.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["resulting_contract_id"], ["tenant_contracts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_commercial_change_decision_request"),
    )
    for column in ("request_id", "tenant_id", "decision", "decided_by", "resulting_contract_id", "decided_at"):
        op.create_index(f"ix_commercial_change_decisions_{column}", "commercial_change_decisions", [column])

    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    tenant_author = "requested_by = nullif(current_setting('app.user_id', true), '')::uuid"
    platform = "current_setting('app.platform_access', true) = 'true'"
    for table in ("commercial_change_requests", "commercial_change_decisions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_platform_all ON {table} FOR ALL "
            f"USING ({platform}) WITH CHECK ({platform})"
        )
        op.execute(
            f"CREATE POLICY {table}_tenant_read ON {table} FOR SELECT USING ({tenant})"
        )
    op.execute(
        "CREATE POLICY commercial_change_requests_tenant_insert ON commercial_change_requests "
        f"FOR INSERT WITH CHECK ({tenant} AND {tenant_author} AND status = 'PENDING')"
    )
    op.execute(
        "CREATE TRIGGER commercial_change_decisions_immutable "
        "BEFORE UPDATE OR DELETE ON commercial_change_decisions "
        "FOR EACH ROW EXECUTE FUNCTION dashem_reject_immutable_mutation()"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON commercial_change_requests TO dashem_runtime"
    )
    op.execute(
        "GRANT SELECT, INSERT ON commercial_change_decisions TO dashem_runtime"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS commercial_change_decisions_immutable ON commercial_change_decisions")
    op.drop_table("commercial_change_decisions")
    op.drop_table("commercial_change_requests")

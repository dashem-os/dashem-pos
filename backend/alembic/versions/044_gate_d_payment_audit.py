"""Add immutable payment audit facts and operational productivity projection.

Revision ID: 044_gate_d_audit
Revises: 043_payment_binding
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "044_gate_d_audit"
down_revision = "043_payment_binding"
branch_labels = None
depends_on = None


def _tenant_store_policy(table: str) -> None:
    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    expression = f"({platform}) OR (({tenant}) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store}))"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_isolation ON {table} FOR ALL "
        f"USING ({expression}) WITH CHECK ({expression})"
    )


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "payment_execution_events",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("register_id", uid, sa.ForeignKey("registers.id"), nullable=False),
        sa.Column("operational_device_id", uid, sa.ForeignKey("operational_devices.id"), nullable=False),
        sa.Column("operational_session_id", uid, sa.ForeignKey("operational_sessions.id"), nullable=True),
        sa.Column("operational_actor_id", uid, nullable=True),
        sa.Column("event_actor_id", uid, nullable=False),
        sa.Column("payment_intent_id", uid, sa.ForeignKey("payment_intents.id"), nullable=False),
        sa.Column("payment_device_binding_id", uid, sa.ForeignKey("payment_device_bindings.id"), nullable=False),
        sa.Column("provider_transaction_id", uid, sa.ForeignKey("provider_transactions.id"), nullable=False),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("outcome", sa.String(50), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider_transaction_id", "sequence", name="uq_payment_execution_event_sequence"),
    )
    for column in (
        "tenant_id", "store_id", "register_id", "operational_device_id",
        "operational_session_id", "operational_actor_id", "event_actor_id",
        "payment_intent_id", "payment_device_binding_id", "provider_transaction_id",
        "stage", "sequence", "outcome", "request_hash", "occurred_at",
    ):
        op.create_index(f"ix_payment_execution_events_{column}", "payment_execution_events", [column])

    op.create_table(
        "operational_productivity_projections",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("register_id", uid, sa.ForeignKey("registers.id"), nullable=False),
        sa.Column("operational_device_id", uid, sa.ForeignKey("operational_devices.id"), nullable=False),
        sa.Column("operational_session_id", uid, sa.ForeignKey("operational_sessions.id"), nullable=False),
        sa.Column("operator_id", uid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("approved_count", sa.Integer(), nullable=False),
        sa.Column("executed_count", sa.Integer(), nullable=False),
        sa.Column("confirmed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("requested_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("confirmed_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("first_event_at", sa.DateTime(), nullable=False),
        sa.Column("last_event_at", sa.DateTime(), nullable=False),
        sa.Column("projection_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "operational_session_id", name="uq_operational_productivity_session"),
    )
    for column in (
        "tenant_id", "store_id", "register_id", "operational_device_id",
        "operational_session_id", "operator_id", "first_event_at", "last_event_at", "updated_at",
    ):
        op.create_index(
            f"ix_operational_productivity_projections_{column}",
            "operational_productivity_projections", [column],
        )

    _tenant_store_policy("payment_execution_events")
    _tenant_store_policy("operational_productivity_projections")

    op.execute("""
        CREATE FUNCTION dashem_reject_immutable_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'immutable audit record cannot be changed' USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("audit_events", "provider_transaction_events", "payment_execution_events"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION dashem_reject_immutable_mutation()"
        )
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM dashem_runtime")
        op.execute(f"GRANT SELECT, INSERT ON {table} TO dashem_runtime")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON operational_productivity_projections TO dashem_runtime"
    )


def downgrade() -> None:
    for table in ("payment_execution_events", "provider_transaction_events", "audit_events"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS dashem_reject_immutable_mutation()")
    op.execute(
        "GRANT UPDATE, DELETE ON audit_events, provider_transaction_events TO dashem_runtime"
    )
    op.drop_table("operational_productivity_projections")
    op.drop_table("payment_execution_events")

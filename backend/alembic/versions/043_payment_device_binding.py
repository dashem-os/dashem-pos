"""Bind physical payment execution to a POS device and unit.

Revision ID: 043_payment_binding
Revises: 042_operational_authority
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "043_payment_binding"
down_revision = "042_operational_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "payment_device_bindings",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("register_id", uid, sa.ForeignKey("registers.id"), nullable=False),
        sa.Column("operational_device_id", uid, sa.ForeignKey("operational_devices.id"), nullable=False),
        sa.Column("provider_configuration_id", uid, sa.ForeignKey("payment_provider_configurations.id"), nullable=False),
        sa.Column("tef_bridge_terminal_id", uid, sa.ForeignKey("tef_bridge_terminals.id"), nullable=True),
        sa.Column("execution_mode", sa.String(50), nullable=False),
        sa.Column("external_device_reference", sa.String(160), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("configured_by", uid, nullable=False),
        sa.Column("paused_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "operational_device_id", name="uq_payment_binding_operational_device"),
        sa.UniqueConstraint(
            "tenant_id", "store_id", "provider_configuration_id", "external_device_reference",
            name="uq_payment_binding_provider_device_ref",
        ),
    )
    for column in (
        "tenant_id", "store_id", "register_id", "operational_device_id",
        "provider_configuration_id", "tef_bridge_terminal_id", "execution_mode",
        "external_device_reference", "status", "configured_by", "created_at",
    ):
        op.create_index(f"ix_payment_device_bindings_{column}", "payment_device_bindings", [column])

    op.add_column(
        "provider_transactions",
        sa.Column("payment_device_binding_id", uid, sa.ForeignKey("payment_device_bindings.id"), nullable=True),
    )
    op.create_index(
        "ix_provider_transactions_payment_device_binding_id",
        "provider_transactions", ["payment_device_binding_id"],
    )

    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    expression = f"({platform}) OR (({tenant}) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store}))"
    op.execute("ALTER TABLE payment_device_bindings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payment_device_bindings FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY payment_device_bindings_isolation ON payment_device_bindings "
        f"FOR ALL USING ({expression}) WITH CHECK ({expression})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON payment_device_bindings TO dashem_runtime")


def downgrade() -> None:
    op.drop_index("ix_provider_transactions_payment_device_binding_id", table_name="provider_transactions")
    op.drop_column("provider_transactions", "payment_device_binding_id")
    op.drop_table("payment_device_bindings")

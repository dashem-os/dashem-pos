"""S9 provider transactions and TEF bridge protocol.

Revision ID: 024_payment_providers_tef
Revises: 023_checkout_negotiation
Create Date: 2026-08-23 19:20:00.000000
"""

from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "024_payment_providers_tef"
down_revision: Union[str, None] = "023_checkout_negotiation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    now = datetime.utcnow()
    uid = postgresql.UUID(as_uuid=True)
    op.alter_column("payments", "provider", server_default="MANUAL_OPERATOR")
    op.create_table(
        "payment_provider_configurations",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("adapter_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("credentials_ref", sa.String(255), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("configured_by", uid, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "store_id", "provider_code", name="uq_store_provider_configuration"),
    )
    for col in ("tenant_id", "store_id", "provider_code", "status", "configured_by", "created_at"):
        op.create_index(f"ix_payment_provider_configurations_{col}", "payment_provider_configurations", [col])
    op.create_table(
        "tef_bridge_terminals",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("register_id", uid, sa.ForeignKey("registers.id"), nullable=False),
        sa.Column("provider_configuration_id", uid, sa.ForeignKey("payment_provider_configurations.id"), nullable=False),
        sa.Column("terminal_code", sa.String(80), nullable=False),
        sa.Column("pairing_secret_hash", sa.String(64), nullable=False),
        sa.Column("bridge_version", sa.String(40), nullable=True),
        sa.Column("protocol_version", sa.String(20), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("last_operation_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("paired_by", uid, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "store_id", "register_id", name="uq_tef_bridge_register"),
        sa.UniqueConstraint("tenant_id", "terminal_code", name="uq_tenant_bridge_terminal_code"),
    )
    for col in ("tenant_id", "store_id", "register_id", "provider_configuration_id", "terminal_code", "status", "last_heartbeat_at", "last_operation_at", "paired_by", "created_at"):
        op.create_index(f"ix_tef_bridge_terminals_{col}", "tef_bridge_terminals", [col])
    op.create_table(
        "provider_transactions",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("payment_intent_id", uid, sa.ForeignKey("payment_intents.id"), nullable=False),
        sa.Column("provider_configuration_id", uid, sa.ForeignKey("payment_provider_configurations.id"), nullable=False),
        sa.Column("bridge_terminal_id", uid, sa.ForeignKey("tef_bridge_terminals.id"), nullable=True),
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("adapter_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("external_transaction_id", sa.String(160), nullable=True),
        sa.Column("nsu", sa.String(80), nullable=True),
        sa.Column("authorization_code", sa.String(80), nullable=True),
        sa.Column("acquirer", sa.String(120), nullable=True),
        sa.Column("card_brand", sa.String(80), nullable=True),
        sa.Column("correlation_id", sa.String(160), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("sanitized_payload", sa.JSON(), nullable=False),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_by", uid, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_queried_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_provider_transaction_key"),
        sa.UniqueConstraint("tenant_id", "provider_code", "external_transaction_id", name="uq_provider_external_transaction"),
    )
    for col in ("tenant_id", "store_id", "payment_intent_id", "provider_configuration_id", "bridge_terminal_id", "provider_code", "status", "external_transaction_id", "nsu", "correlation_id", "idempotency_key", "created_by", "created_at", "last_queried_at", "completed_at"):
        op.create_index(f"ix_provider_transactions_{col}", "provider_transactions", [col])
    op.create_table(
        "provider_transaction_events",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("provider_transaction_id", uid, sa.ForeignKey("provider_transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor_id", uid, nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for col in ("tenant_id", "provider_transaction_id", "event_type", "actor_id", "created_at"):
        op.create_index(f"ix_provider_transaction_events_{col}", "provider_transaction_events", [col])

    permission_table = sa.table(
        "permissions", sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.Text), sa.column("capability_key", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    permissions = (
        ("provider.read", "Consultar providers e bridge"),
        ("provider.configure", "Configurar provider e parear bridge"),
        ("provider.execute", "Executar e reconciliar transação TEF"),
    )
    op.bulk_insert(permission_table, [{
        "key": key, "name": name, "description": name,
        "capability_key": "tef", "created_at": now,
    } for key, name in permissions])
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system = true AND p.key IN ('provider.read', 'provider.configure', 'provider.execute')
          AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER')
    """))
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system = true AND p.key IN ('provider.read', 'provider.execute')
          AND rp.code IN ('CASHIER', 'OPERATOR')
    """))
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'provider.read' FROM role_profiles rp
        WHERE rp.is_system = true AND rp.code = 'AUDITOR'
    """))

    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    for table in ("payment_provider_configurations", "tef_bridge_terminals", "provider_transactions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        expression = f"({platform}) OR (({tenant}) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store}))"
        op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({expression}) WITH CHECK ({expression})")
    op.execute("ALTER TABLE provider_transaction_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE provider_transaction_events FORCE ROW LEVEL SECURITY")
    parent = (
        "EXISTS (SELECT 1 FROM provider_transactions pt WHERE pt.id = provider_transaction_id "
        "AND pt.tenant_id = provider_transaction_events.tenant_id AND "
        "(nullif(current_setting('app.store_id', true), '') IS NULL OR "
        "pt.store_id = nullif(current_setting('app.store_id', true), '')::uuid))"
    )
    expression = f"({platform}) OR (({tenant}) AND ({parent}))"
    op.execute(f"CREATE POLICY provider_transaction_events_isolation ON provider_transaction_events FOR ALL USING ({expression}) WITH CHECK ({expression})")


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key LIKE 'provider.%'")
    op.execute("DELETE FROM permissions WHERE key LIKE 'provider.%'")
    op.drop_table("provider_transaction_events")
    op.drop_table("provider_transactions")
    op.drop_table("tef_bridge_terminals")
    op.drop_table("payment_provider_configurations")
    op.alter_column("payments", "provider", server_default="FAKE_PSP")

"""S10 channel hub, durable inbox and external order mapping.

Revision ID: 025_channel_hub
Revises: 024_payment_providers_tef
Create Date: 2026-08-23 19:35:00.000000
"""

from datetime import datetime
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "025_channel_hub"
down_revision: Union[str, None] = "024_payment_providers_tef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    now = datetime.utcnow(); uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "merchant_connections",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False), sa.Column("channel_id", uid, sa.ForeignKey("sales_channels.id"), nullable=False),
        sa.Column("provider_code", sa.String(80), nullable=False), sa.Column("adapter_version", sa.String(40), nullable=False),
        sa.Column("merchant_external_id", sa.String(160), nullable=False), sa.Column("status", sa.String(50), nullable=False),
        sa.Column("credentials_ref", sa.String(255), nullable=True), sa.Column("webhook_secret_hash", sa.String(64), nullable=False),
        sa.Column("service_actor_id", uid, nullable=False), sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("configured_by", uid, nullable=False),
        sa.Column("last_validated_at", sa.DateTime(), nullable=True), sa.Column("last_event_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True), sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "provider_code", "merchant_external_id", name="uq_provider_merchant_connection"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_merchant_connection_key"),
    )
    _indexes("merchant_connections", ("tenant_id", "store_id", "channel_id", "provider_code", "merchant_external_id", "status", "service_actor_id", "idempotency_key", "configured_by", "last_validated_at", "last_event_at", "created_at"))
    op.create_table(
        "channel_inbox_events",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("merchant_connection_id", uid, sa.ForeignKey("merchant_connections.id"), nullable=False),
        sa.Column("provider_event_id", sa.String(160), nullable=False), sa.Column("external_order_id", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False), sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False), sa.Column("status", sa.String(50), nullable=False),
        sa.Column("order_id", uid, sa.ForeignKey("orders.id"), nullable=True), sa.Column("quarantine_code", sa.String(80), nullable=True),
        sa.Column("quarantine_reason", sa.Text(), nullable=True), sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True), sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("merchant_connection_id", "provider_event_id", name="uq_connection_provider_event"),
    )
    _indexes("channel_inbox_events", ("tenant_id", "store_id", "merchant_connection_id", "provider_event_id", "external_order_id", "event_type", "status", "order_id", "received_at", "acknowledged_at", "processed_at"))
    op.create_table(
        "external_order_mappings",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("merchant_connection_id", uid, sa.ForeignKey("merchant_connections.id"), nullable=False),
        sa.Column("external_order_id", sa.String(160), nullable=False), sa.Column("order_id", uid, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("payment_origin", sa.String(80), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("merchant_connection_id", "external_order_id", name="uq_connection_external_order"),
        sa.UniqueConstraint("tenant_id", "order_id", name="uq_tenant_external_order_mapping"),
    )
    _indexes("external_order_mappings", ("tenant_id", "store_id", "merchant_connection_id", "external_order_id", "order_id", "payment_origin", "created_at"))
    op.create_table(
        "channel_outbound_messages",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("merchant_connection_id", uid, sa.ForeignKey("merchant_connections.id"), nullable=False),
        sa.Column("order_id", uid, sa.ForeignKey("orders.id"), nullable=False), sa.Column("message_type", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("status", sa.String(50), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False), sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True), sa.Column("created_by", uid, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_channel_outbound_key"),
    )
    _indexes("channel_outbound_messages", ("tenant_id", "store_id", "merchant_connection_id", "order_id", "message_type", "status", "idempotency_key", "next_retry_at", "created_by", "created_at"))

    permissions = sa.table("permissions", sa.column("key", sa.String), sa.column("name", sa.String), sa.column("description", sa.Text), sa.column("capability_key", sa.String), sa.column("created_at", sa.DateTime))
    rows = (("channel.read", "Consultar Channel Hub"), ("channel.configure", "Configurar canais"), ("channel.manage", "Gerenciar inbox e outbound"))
    op.bulk_insert(permissions, [{"key": key, "name": name, "description": name, "capability_key": "delivery_orders", "created_at": now} for key, name in rows])
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system=true AND p.key IN ('channel.read','channel.configure','channel.manage')
          AND rp.code IN ('OWNER','TENANT_OWNER','ADMIN','MANAGER')
    """))
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'channel.read' FROM role_profiles rp
        WHERE rp.is_system=true AND rp.code IN ('CASHIER','OPERATOR','AUDITOR')
    """))
    platform = "current_setting('app.platform_access', true) = 'true'"; tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"; store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    for table in ("merchant_connections", "channel_inbox_events", "external_order_mappings", "channel_outbound_messages"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"); op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        expression = f"({platform}) OR (({tenant}) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store}))"
        op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({expression}) WITH CHECK ({expression})")


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key LIKE 'channel.%'")
    op.execute("DELETE FROM permissions WHERE key LIKE 'channel.%'")
    op.drop_table("channel_outbound_messages")
    op.drop_table("external_order_mappings")
    op.drop_table("channel_inbox_events")
    op.drop_table("merchant_connections")

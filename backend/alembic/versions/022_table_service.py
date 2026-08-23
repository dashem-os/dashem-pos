"""S7 table service, sessions and operational commands.

Revision ID: 022_table_service
Revises: 021_order_foundation
Create Date: 2026-08-23 22:10:00.000000
"""

from datetime import datetime
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "022_table_service"
down_revision: Union[str, None] = "021_order_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_PERMISSIONS = (
    ("table.read", "Consultar mesas e comandas"),
    ("table.manage", "Configurar mesas"),
    ("table.session.open", "Abrir mesa ou comanda"),
    ("table.session.update", "Atualizar atendimento e comandas"),
    ("table.session.close", "Encerrar mesa ou comanda"),
)


def upgrade() -> None:
    now = datetime.utcnow()
    capability_definitions = sa.table(
        "capability_definitions",
        sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("version", sa.String), sa.column("description", sa.String),
        sa.column("scope", sa.String), sa.column("status", sa.String),
        sa.column("configuration_schema", sa.JSON),
        sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(capability_definitions, [{
        "key": "table_service", "name": "Mesas e comandas", "version": "1.0.0",
        "description": "Atendimento de mesa e comandas individuais com ciclo operacional rastreável.",
        "scope": "STORE", "status": "ACTIVE", "configuration_schema": {},
        "created_at": now, "updated_at": now,
    }])
    op.execute(sa.text("""
        INSERT INTO capability_dependencies
            (id, capability_key, requires_key, minimum_version)
        VALUES (gen_random_uuid(), 'table_service', 'catalog', '1.0.0')
    """))
    op.execute(sa.text("""
        INSERT INTO tenant_capabilities
            (id, tenant_id, key, enabled, configuration, status, contract_limits, created_at, updated_at)
        SELECT gen_random_uuid(), t.id, 'table_service', true, '{}'::json, 'ACTIVE', '{}'::json, now(), now()
        FROM tenants t
    """))

    op.create_table(
        "service_tables",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("area", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("creation_idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("creation_request_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("capacity > 0", name="ck_service_table_capacity_positive"),
        sa.CheckConstraint("version > 0", name="ck_service_table_version_positive"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "store_id", "code", name="uq_service_table_store_code"),
        sa.UniqueConstraint("tenant_id", "creation_idempotency_key", name="uq_service_table_creation_key"),
    )
    op.create_table(
        "table_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_table_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("display_label", sa.String(length=120), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attendant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opened_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("closed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("close_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("open_idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("open_request_hash", sa.String(length=64), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_table_session_version_positive"),
        sa.CheckConstraint(
            "(kind = 'TABLE' AND service_table_id IS NOT NULL) OR "
            "(kind = 'INDIVIDUAL_TAB' AND service_table_id IS NULL)",
            name="ck_table_session_kind_resource",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["service_table_id"], ["service_tables.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "open_idempotency_key", name="uq_table_session_open_key"),
    )
    op.create_index(
        "uq_active_table_session", "table_sessions", ["tenant_id", "store_id", "service_table_id"],
        unique=True,
        postgresql_where=sa.text("service_table_id IS NOT NULL AND status IN ('OPEN', 'IN_SERVICE', 'PARTIALLY_PAID', 'CLOSING')"),
    )
    op.create_table(
        "table_session_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("table_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=True),
        sa.Column("to_status", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["table_session_id"], ["table_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "table_session_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("table_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("command_type", sa.String(length=80), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("result_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["table_session_id"], ["table_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_table_session_command_key"),
    )
    for table, columns in {
        "service_tables": ("tenant_id", "store_id", "code", "name", "area", "status", "is_active", "creation_idempotency_key", "created_at"),
        "table_sessions": ("tenant_id", "store_id", "service_table_id", "kind", "status", "display_label", "customer_id", "attendant_id", "opened_by", "closed_by", "open_idempotency_key", "opened_at", "closed_at"),
        "table_session_events": ("tenant_id", "table_session_id", "event_type", "actor_id", "created_at"),
        "table_session_commands": ("tenant_id", "table_session_id", "idempotency_key", "command_type", "result_entity_id", "actor_id", "created_at"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")

    # Preserve any S6 placeholder table links by materializing auditable legacy
    # resources before the foreign key becomes enforceable.
    op.execute(sa.text("""
        INSERT INTO service_tables
            (id, tenant_id, store_id, code, name, capacity, area, status, version, is_active, creation_idempotency_key, creation_request_hash, created_at, updated_at)
        SELECT DISTINCT o.table_id, o.tenant_id, o.store_id,
            'LEGACY-' || left(o.table_id::text, 8),
            'Mesa migrada ' || left(o.table_id::text, 8),
            1, 'MIGRADO', 'AVAILABLE', 1, true,
            'legacy-table-' || o.table_id::text,
            encode(sha256(('legacy-table-' || o.table_id::text)::bytea), 'hex'),
            now(), now()
        FROM orders o
        WHERE o.table_id IS NOT NULL
    """))
    op.add_column("orders", sa.Column("table_session_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_orders_table_session_id", "orders", ["table_session_id"])
    op.create_foreign_key("fk_orders_table_id_service_table", "orders", "service_tables", ["table_id"], ["id"])
    op.create_foreign_key("fk_orders_table_session_id", "orders", "table_sessions", ["table_session_id"], ["id"])

    permission_table = sa.table(
        "permissions", sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.Text), sa.column("capability_key", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(permission_table, [
        {"key": key, "name": name, "description": name, "capability_key": "table_service", "created_at": now}
        for key, name in TABLE_PERMISSIONS
    ])
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key
        FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system = true
          AND p.key IN ('table.read', 'table.manage', 'table.session.open', 'table.session.update', 'table.session.close')
          AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER', 'CASHIER', 'OPERATOR')
    """))
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'table.read'
        FROM role_profiles rp WHERE rp.is_system = true AND rp.code = 'AUDITOR'
    """))

    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    for table in ("service_tables", "table_sessions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        expression = f"({platform}) OR (({tenant}) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store}))"
        op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({expression}) WITH CHECK ({expression})")
    for table in ("table_session_events", "table_session_commands"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        parent = (
            f"EXISTS (SELECT 1 FROM table_sessions ts WHERE ts.id = table_session_id AND ts.tenant_id = {table}.tenant_id "
            "AND (nullif(current_setting('app.store_id', true), '') IS NULL "
            "OR ts.store_id = nullif(current_setting('app.store_id', true), '')::uuid))"
        )
        expression = f"({platform}) OR (({tenant}) AND ({parent}))"
        op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({expression}) WITH CHECK ({expression})")


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key LIKE 'table.%'")
    op.execute("DELETE FROM permissions WHERE key LIKE 'table.%'")
    op.drop_constraint("fk_orders_table_session_id", "orders", type_="foreignkey")
    op.drop_constraint("fk_orders_table_id_service_table", "orders", type_="foreignkey")
    op.drop_index("ix_orders_table_session_id", table_name="orders")
    op.drop_column("orders", "table_session_id")
    op.drop_table("table_session_commands")
    op.drop_table("table_session_events")
    op.drop_index("uq_active_table_session", table_name="table_sessions")
    op.drop_table("table_sessions")
    op.drop_table("service_tables")
    op.execute("DELETE FROM tenant_capabilities WHERE key = 'table_service'")
    op.execute("DELETE FROM capability_dependencies WHERE capability_key = 'table_service'")
    op.execute("DELETE FROM capability_definitions WHERE key = 'table_service'")

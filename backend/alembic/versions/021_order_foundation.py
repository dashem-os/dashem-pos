"""Order aggregate, idempotent commands and authorization.

Revision ID: 021_order_foundation
Revises: 020_counter_operation
Create Date: 2026-08-23 20:10:00.000000
"""

from datetime import datetime
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "021_order_foundation"
down_revision: Union[str, None] = "020_counter_operation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ORDER_PERMISSIONS = (
    ("order.read", "Consultar pedidos"),
    ("order.create", "Abrir pedidos"),
    ("order.item.update", "Lançar e alterar itens do pedido"),
    ("order.cancel", "Cancelar itens e pedidos"),
)


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("register_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("table_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sale_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("fulfillment", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("external_reference", sa.String(length=160), nullable=True),
        sa.Column("opened_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["register_id"], ["registers.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"]),
        sa.ForeignKeyConstraint(["channel_id"], ["sales_channels.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_order_idempotency"),
    )
    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("unit_snapshot", sa.String(length=16), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("modifier_snapshot", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("production_destination", sa.String(length=80), nullable=True),
        sa.Column("production_state", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("added_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canceled_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("canceled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "order_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("command_type", sa.String(length=80), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("result_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_order_command_key"),
    )
    for table, columns in {
        "orders": ("tenant_id", "store_id", "register_id", "customer_id", "table_id", "sale_id", "channel_id", "origin", "fulfillment", "status", "idempotency_key", "external_reference", "opened_by", "created_at"),
        "order_items": ("tenant_id", "order_id", "product_id", "production_state", "status", "added_by", "canceled_by", "created_at"),
        "order_commands": ("tenant_id", "order_id", "idempotency_key", "command_type", "result_entity_id", "actor_id", "created_at"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")

    permission_table = sa.table(
        "permissions", sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.Text), sa.column("capability_key", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    now = datetime.utcnow()
    op.bulk_insert(permission_table, [
        {"key": key, "name": name, "description": name, "capability_key": "counter_order", "created_at": now}
        for key, name in ORDER_PERMISSIONS
    ])
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key
        FROM role_profiles rp
        CROSS JOIN permissions p
        WHERE rp.is_system = true
          AND p.key IN ('order.read', 'order.create', 'order.item.update', 'order.cancel')
          AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER', 'CASHIER', 'OPERATOR')
    """))
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'order.read'
        FROM role_profiles rp WHERE rp.is_system = true AND rp.code = 'AUDITOR'
    """))

    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "(nullif(current_setting('app.store_id', true), '') IS NULL OR store_id = nullif(current_setting('app.store_id', true), '')::uuid)"
    op.execute("ALTER TABLE orders ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE orders FORCE ROW LEVEL SECURITY")
    expression = f"({platform}) OR (({tenant}) AND ({store}))"
    op.execute(f"CREATE POLICY orders_isolation ON orders FOR ALL USING ({expression}) WITH CHECK ({expression})")
    for table in ("order_items", "order_commands"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        parent = (
            f"EXISTS (SELECT 1 FROM orders o WHERE o.id = order_id AND o.tenant_id = {table}.tenant_id "
            "AND (nullif(current_setting('app.store_id', true), '') IS NULL "
            "OR o.store_id = nullif(current_setting('app.store_id', true), '')::uuid))"
        )
        child_expression = f"({platform}) OR (({tenant}) AND ({parent}))"
        op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({child_expression}) WITH CHECK ({child_expression})")


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key IN ('order.read', 'order.create', 'order.item.update', 'order.cancel')")
    op.execute("DELETE FROM permissions WHERE key IN ('order.read', 'order.create', 'order.item.update', 'order.cancel')")
    op.drop_table("order_commands")
    op.drop_table("order_items")
    op.drop_table("orders")

"""S11 production routing, durable tickets and concurrent KDS.

Revision ID: 026_production_routing_kds
Revises: 025_channel_hub
Create Date: 2026-08-23 21:00:00.000000
"""
from datetime import datetime
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "026_production_routing_kds"
down_revision: Union[str, None] = "025_channel_hub"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns: op.create_index(f"ix_{table}_{column}", table, [column])

def upgrade() -> None:
    now = datetime.utcnow(); uid = postgresql.UUID(as_uuid=True)
    op.add_column("order_items", sa.Column("production_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("modifiers", sa.Column("production_destination", sa.String(80), nullable=True))
    op.create_table("production_points",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False), sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("point_type", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("printer_configuration_ref", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "store_id", "code", name="uq_store_production_point_code"))
    _indexes("production_points", ("tenant_id","store_id","code","point_type","is_active","created_at"))
    op.create_table("production_routing_rules",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("production_point_id", uid, sa.ForeignKey("production_points.id"), nullable=False),
        sa.Column("product_id", uid, sa.ForeignKey("products.id")), sa.Column("modifier_id", uid, sa.ForeignKey("modifiers.id")),
        sa.Column("fulfillment", sa.String(50)), sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("(product_id IS NOT NULL) <> (modifier_id IS NOT NULL)", name="ck_production_rule_one_subject"))
    _indexes("production_routing_rules", ("tenant_id","store_id","production_point_id","product_id","modifier_id","fulfillment","priority","is_active","created_at"))
    op.create_table("production_dispatches",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False), sa.Column("order_id", uid, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", uid, nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_production_dispatch_key"))
    _indexes("production_dispatches", ("tenant_id","store_id","order_id","idempotency_key","actor_id","created_at"))
    op.create_table("production_tickets",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False), sa.Column("order_id", uid, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("dispatch_id", uid, sa.ForeignKey("production_dispatches.id"), nullable=False),
        sa.Column("production_point_id", uid, sa.ForeignKey("production_points.id"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False), sa.Column("priority", sa.Integer(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime()), sa.Column("preparing_at", sa.DateTime()), sa.Column("ready_at", sa.DateTime()),
        sa.Column("delivered_at", sa.DateTime()), sa.Column("canceled_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("dispatch_id", "production_point_id", name="uq_dispatch_production_point"))
    _indexes("production_tickets", ("tenant_id","store_id","order_id","dispatch_id","production_point_id","status","priority","created_at"))
    op.create_table("production_ticket_items",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("ticket_id", uid, sa.ForeignKey("production_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_item_id", uid, sa.ForeignKey("order_items.id"), nullable=False), sa.Column("item_version", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(50), nullable=False), sa.Column("quantity", sa.Numeric(14,4), nullable=False),
        sa.Column("product_name_snapshot", sa.String(200), nullable=False), sa.Column("modifier_snapshot", sa.JSON(), nullable=False),
        sa.Column("notes_snapshot", sa.Text()), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("ticket_id","order_item_id","item_version","operation", name="uq_ticket_item_version_operation"))
    _indexes("production_ticket_items", ("tenant_id","ticket_id","order_item_id","operation","created_at"))
    op.create_table("production_transitions",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("ticket_id", uid, sa.ForeignKey("production_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(50), nullable=False), sa.Column("to_status", sa.String(50), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False), sa.Column("resulting_version", sa.Integer(), nullable=False),
        sa.Column("actor_id", uid, nullable=False), sa.Column("device_id", sa.String(160), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_production_transition_key"))
    _indexes("production_transitions", ("tenant_id","store_id","ticket_id","to_status","actor_id","device_id","idempotency_key","created_at"))
    permissions = sa.table("permissions", sa.column("key", sa.String), sa.column("name", sa.String), sa.column("description", sa.Text), sa.column("capability_key", sa.String), sa.column("created_at", sa.DateTime))
    rows = (("production.read","Consultar produção"),("production.configure","Configurar roteamento"),("production.operate","Operar KDS"))
    op.bulk_insert(permissions, [{"key": k,"name": n,"description": n,"capability_key":"kitchen_routing","created_at":now} for k,n in rows])
    op.execute(sa.text("""INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system=true AND p.key IN ('production.read','production.configure','production.operate')
          AND rp.code IN ('OWNER','TENANT_OWNER','ADMIN','MANAGER')"""))
    op.execute(sa.text("""INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system=true AND p.key IN ('production.read','production.operate')
          AND rp.code IN ('CASHIER','OPERATOR')"""))
    platform = "current_setting('app.platform_access', true) = 'true'"; tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"; store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    for table in ("production_points","production_routing_rules","production_dispatches","production_tickets","production_transitions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"); op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        exp=f"({platform}) OR (({tenant}) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store}))"
        op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({exp}) WITH CHECK ({exp})")
    op.execute("ALTER TABLE production_ticket_items ENABLE ROW LEVEL SECURITY"); op.execute("ALTER TABLE production_ticket_items FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY production_ticket_items_isolation ON production_ticket_items FOR ALL USING (({platform}) OR ({tenant})) WITH CHECK (({platform}) OR ({tenant}))")

def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key LIKE 'production.%'")
    op.execute("DELETE FROM permissions WHERE key LIKE 'production.%'")
    for table in ("production_transitions","production_ticket_items","production_tickets","production_dispatches","production_routing_rules","production_points"):
        op.drop_table(table)
    op.drop_column("modifiers","production_destination"); op.drop_column("order_items","production_version")

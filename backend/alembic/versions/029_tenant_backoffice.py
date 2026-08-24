"""S13.1 tenant backoffice, service topology and devices.

Revision ID: 029_tenant_backoffice
Revises: 028_channel_catalog
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "029_tenant_backoffice"
down_revision = "028_channel_catalog"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def _tenant_rls(table: str, *, store_scoped: bool = True) -> None:
    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    expression = f"({platform}) OR (({tenant})"
    if store_scoped:
        expression += f" AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store})"
    expression += ")"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({expression}) WITH CHECK ({expression})")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    now = datetime.utcnow()

    op.create_table(
        "service_areas",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uuid_type, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "store_id", "code", name="uq_service_area_store_code"),
    )
    _indexes("service_areas", ("tenant_id", "store_id", "code", "name", "kind", "sort_order", "is_active", "created_at"))
    _tenant_rls("service_areas")

    op.add_column("service_tables", sa.Column("area_id", uuid_type, nullable=True))
    op.add_column("service_tables", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("service_tables", sa.Column("blocking_reason", sa.Text(), nullable=True))
    op.create_foreign_key("fk_service_tables_area", "service_tables", "service_areas", ["area_id"], ["id"])
    op.create_index("ix_service_tables_area_id", "service_tables", ["area_id"])
    op.create_index("ix_service_tables_sort_order", "service_tables", ["sort_order"])
    op.alter_column("service_tables", "sort_order", server_default=None)
    op.execute(sa.text("""
        INSERT INTO service_areas
            (id, tenant_id, store_id, code, name, kind, sort_order, is_active, created_at, updated_at)
        SELECT gen_random_uuid(), tenant_id, store_id,
               'LEGACY-' || left(encode(sha256(area::bytea), 'hex'), 12), area, 'FLEXIBLE', 100, true, now(), now()
        FROM service_tables
        WHERE area IS NOT NULL AND btrim(area) <> ''
        GROUP BY tenant_id, store_id, area
    """))
    op.execute(sa.text("""
        UPDATE service_tables st
        SET area_id = sa.id
        FROM service_areas sa
        WHERE sa.tenant_id = st.tenant_id AND sa.store_id = st.store_id AND sa.name = st.area
    """))

    op.create_table(
        "table_reservations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uuid_type, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("service_table_id", uuid_type, sa.ForeignKey("service_tables.id"), nullable=False),
        sa.Column("customer_name", sa.String(160), nullable=False),
        sa.Column("customer_phone", sa.String(40), nullable=True),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("reserved_for", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by", uuid_type, nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("party_size > 0", name="ck_table_reservation_party_size_positive"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_table_reservation_key"),
    )
    _indexes("table_reservations", ("tenant_id", "store_id", "service_table_id", "customer_name", "reserved_for", "status", "created_by", "idempotency_key", "created_at"))
    _tenant_rls("table_reservations")

    op.create_table(
        "operational_devices",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uuid_type, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("device_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("register_id", uuid_type, sa.ForeignKey("registers.id"), nullable=True),
        sa.Column("production_point_id", uuid_type, sa.ForeignKey("production_points.id"), nullable=True),
        sa.Column("configuration_ref", sa.String(255), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "store_id", "code", name="uq_operational_device_store_code"),
    )
    _indexes("operational_devices", ("tenant_id", "store_id", "code", "name", "device_type", "status", "register_id", "production_point_id", "last_seen_at", "created_at"))
    _tenant_rls("operational_devices")

    permission_table = sa.table(
        "permissions", sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.Text), sa.column("capability_key", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    rows = (
        ("table.state.update", "Sinalizar disponibilidade de mesas", "table_service"),
        ("table.reservation.manage", "Gerenciar reservas de mesas", "table_service"),
        ("device.read", "Consultar terminais e dispositivos", None),
        ("device.configure", "Configurar terminais e dispositivos", None),
        ("device.heartbeat", "Reportar presença de dispositivo", None),
    )
    op.bulk_insert(permission_table, [
        {"key": key, "name": name, "description": name, "capability_key": capability, "created_at": now}
        for key, name, capability in rows
    ])
    op.execute(sa.text("""
        DELETE FROM role_profile_permissions rpp
        USING role_profiles rp
        WHERE rpp.role_profile_id = rp.id AND rp.is_system = true
          AND rp.code IN ('CASHIER', 'OPERATOR') AND rpp.permission_key = 'table.manage'
    """))
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'device.heartbeat'
        FROM role_profiles rp WHERE rp.is_system = true
          AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER', 'CASHIER', 'OPERATOR')
    """))
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key
        FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system = true
          AND p.key IN ('table.state.update', 'table.reservation.manage')
          AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER', 'CASHIER', 'OPERATOR')
    """))
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key
        FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system = true AND p.key IN ('device.read', 'device.configure')
          AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER')
    """))
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'device.read'
        FROM role_profiles rp WHERE rp.is_system = true AND rp.code = 'AUDITOR'
    """))


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key IN ('table.state.update','table.reservation.manage','device.read','device.configure','device.heartbeat')")
    op.execute("DELETE FROM permissions WHERE key IN ('table.state.update','table.reservation.manage','device.read','device.configure','device.heartbeat')")
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), id, 'table.manage' FROM role_profiles
        WHERE is_system = true AND code IN ('CASHIER', 'OPERATOR')
          AND NOT EXISTS (SELECT 1 FROM role_profile_permissions rpp WHERE rpp.role_profile_id = role_profiles.id AND rpp.permission_key = 'table.manage')
    """))
    op.drop_table("operational_devices")
    op.drop_table("table_reservations")
    op.drop_index("ix_service_tables_sort_order", table_name="service_tables")
    op.drop_index("ix_service_tables_area_id", table_name="service_tables")
    op.drop_constraint("fk_service_tables_area", "service_tables", type_="foreignkey")
    op.drop_column("service_tables", "blocking_reason")
    op.drop_column("service_tables", "sort_order")
    op.drop_column("service_tables", "area_id")
    op.drop_table("service_areas")

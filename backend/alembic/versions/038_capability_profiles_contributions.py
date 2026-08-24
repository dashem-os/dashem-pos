"""Versioned capability profiles and module contributions.

Revision ID: 038_capability_profiles
Revises: 037_control_completion
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "038_capability_profiles"
down_revision = "037_control_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "capability_profile_revisions",
        sa.Column("id", uid, nullable=False), sa.Column("profile_key", sa.String(80), nullable=False),
        sa.Column("version", sa.String(32), nullable=False), sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_key", "version", name="uq_capability_profile_revision"),
    )
    for column in ("profile_key", "version", "status"):
        op.create_index(f"ix_capability_profile_revisions_{column}", "capability_profile_revisions", [column])
    op.create_table(
        "capability_profile_revision_items",
        sa.Column("id", uid, nullable=False), sa.Column("revision_id", uid, nullable=False),
        sa.Column("capability_key", sa.String(80), nullable=False), sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("default_configuration", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["capability_profile_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capability_key"], ["capability_definitions.key"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("revision_id", "capability_key", name="uq_capability_profile_revision_item"),
    )
    op.create_index("ix_capability_profile_revision_items_revision_id", "capability_profile_revision_items", ["revision_id"])
    op.create_index("ix_capability_profile_revision_items_capability_key", "capability_profile_revision_items", ["capability_key"])
    op.create_table(
        "tenant_profile_assignments",
        sa.Column("id", uid, nullable=False), sa.Column("tenant_id", uid, nullable=False),
        sa.Column("revision_id", uid, nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False), sa.Column("assigned_by", uid, nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False), sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["revision_id"], ["capability_profile_revisions.id"]),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "revision_id", "status", "assigned_by", "assigned_at"):
        op.create_index(f"ix_tenant_profile_assignments_{column}", "tenant_profile_assignments", [column])
    op.create_index("uq_tenant_active_profile_assignment", "tenant_profile_assignments", ["tenant_id"], unique=True, postgresql_where=sa.text("status = 'ACTIVE'"))
    op.create_table(
        "module_contributions",
        sa.Column("id", uid, nullable=False), sa.Column("capability_key", sa.String(80), nullable=True),
        sa.Column("surface", sa.String(60), nullable=False), sa.Column("contribution_key", sa.String(100), nullable=False),
        sa.Column("label", sa.String(160), nullable=False), sa.Column("group_key", sa.String(80), nullable=True),
        sa.Column("route", sa.String(180), nullable=True), sa.Column("permission_key", sa.String(120), nullable=True),
        sa.Column("implementation_key", sa.String(120), nullable=False), sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["capability_key"], ["capability_definitions.key"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("surface", "contribution_key", name="uq_module_contribution_surface_key"),
    )
    for column in ("capability_key", "surface", "contribution_key", "is_active"):
        op.create_index(f"ix_module_contributions_{column}", "module_contributions", [column])
    op.create_table(
        "capability_conflicts",
        sa.Column("id", uid, nullable=False), sa.Column("capability_key", sa.String(80), nullable=False),
        sa.Column("conflicts_with_key", sa.String(80), nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["capability_key"], ["capability_definitions.key"]),
        sa.ForeignKeyConstraint(["conflicts_with_key"], ["capability_definitions.key"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capability_key", "conflicts_with_key", name="uq_capability_conflict"),
    )
    op.create_index("ix_capability_conflicts_capability_key", "capability_conflicts", ["capability_key"])
    op.create_index("ix_capability_conflicts_conflicts_with_key", "capability_conflicts", ["conflicts_with_key"])

    op.execute("ALTER TABLE tenant_profile_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_profile_assignments FORCE ROW LEVEL SECURITY")
    policy = "current_setting('app.platform_access', true) = 'true' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(f"CREATE POLICY tenant_profile_assignments_scope ON tenant_profile_assignments FOR SELECT USING ({policy})")
    op.execute("CREATE POLICY tenant_profile_assignments_platform_write ON tenant_profile_assignments FOR INSERT WITH CHECK (current_setting('app.platform_access', true) = 'true')")
    op.execute("CREATE POLICY tenant_profile_assignments_platform_update ON tenant_profile_assignments FOR UPDATE USING (current_setting('app.platform_access', true) = 'true') WITH CHECK (current_setting('app.platform_access', true) = 'true')")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_profile_assignments TO dashem_runtime")
    for table in ("capability_profile_revisions", "capability_profile_revision_items", "module_contributions", "capability_conflicts"):
        op.execute(f"GRANT SELECT ON {table} TO dashem_runtime")

    profiles = {
        "10000000-0000-0000-0000-000000000001": ("FOOD_SERVICE", "Food Service", "ACTIVE", ["catalog", "customer", "cash_management", "payments", "modifiers", "combos", "kitchen_routing", "delivery_orders", "counter_order", "table_service", "supervisor_override"]),
        "10000000-0000-0000-0000-000000000002": ("RETAIL", "Varejo", "ACTIVE", ["catalog", "inventory", "customer", "cash_management", "payments", "barcode_scanning", "counter_order", "high_speed_checkout", "supervisor_override", "receivables"]),
        "10000000-0000-0000-0000-000000000003": ("GROCERY", "Mercado", "DRAFT", ["catalog", "inventory", "customer", "cash_management", "payments", "barcode_scanning", "counter_order", "weighted_products", "batch_tracking", "high_speed_checkout"]),
    }
    for revision_id, (key, name, status, items) in profiles.items():
        op.execute(sa.text("INSERT INTO capability_profile_revisions (id, profile_key, version, name, description, status, created_at) VALUES (:id, :key, '1.0.0', :name, :description, :status, now())").bindparams(id=revision_id, key=key, name=name, description=f"Composição versionada {name} 1.0.0.", status=status))
        for capability in items:
            op.execute(sa.text("INSERT INTO capability_profile_revision_items (id, revision_id, capability_key, required, default_configuration) VALUES (gen_random_uuid(), :revision_id, :capability, true, '{}'::json)").bindparams(revision_id=revision_id, capability=capability))

    contributions = [
        (None, "MANAGEMENT_NAV", "overview", "Visão geral", "VISÃO", "management.read", "overview", 10),
        ("counter_order", "MANAGEMENT_NAV", "sales", "Vendas", "OPERAÇÃO", "sale.read", "sales", 20),
        ("cash_management", "MANAGEMENT_NAV", "cash", "Caixas", "OPERAÇÃO", "cash.read", "cash", 30),
        ("delivery_orders", "MANAGEMENT_NAV", "channels", "Canais de venda", "OPERAÇÃO", "channel.read", "channels", 40),
        ("receivables", "MANAGEMENT_NAV", "receivables", "Crediário e recebíveis", "FINANCEIRO", "receivable.read", "receivables", 50),
        ("catalog", "MANAGEMENT_NAV", "products", "Produtos e preços", "MERCADORIAS", "catalog.read", "products", 60),
        ("catalog", "MANAGEMENT_NAV", "categories", "Categorias", "MERCADORIAS", "catalog.read", "categories", 70),
        ("inventory", "MANAGEMENT_NAV", "inventory", "Estoque", "MERCADORIAS", "inventory.read", "inventory", 80),
        ("table_service", "MANAGEMENT_NAV", "tables", "Ambientes e mesas", "ESTRUTURA", "table.read", "tables", 90),
        (None, "MANAGEMENT_NAV", "devices", "Terminais e produção", "ESTRUTURA", "device.read", "devices", 100),
        (None, "MANAGEMENT_NAV", "team", "Equipe e funções", "ACESSOS", "team.read", "team", 110),
        ("kitchen_routing", "HEALTH", "production_worker", "Produção", "OPERAÇÃO", "production.read", "production_worker", 200),
        ("tef", "HEALTH", "tef_bridge", "TEF Bridge", "PAGAMENTOS", "provider.read", "tef_bridge", 210),
        ("delivery_orders", "HEALTH", "channel_hub", "Channel Hub", "CANAIS", "channel.read", "channel_hub", 220),
        ("fiscal_nfce", "HEALTH", "fiscal_gateway", "Fiscal", "FISCAL", "fiscal.read", "fiscal_gateway", 230),
        ("counter_order", "REPORTING", "sales_revenue", "Vendas e faturamento", "COMERCIAL", "management.read", "sales_revenue", 300),
        ("table_service", "REPORTING", "table_occupancy", "Ocupação de mesas", "FOOD SERVICE", "management.read", "table_occupancy", 310),
        ("kitchen_routing", "REPORTING", "production_throughput", "Tempo de produção", "FOOD SERVICE", "management.read", "production_throughput", 320),
        ("receivables", "REPORTING", "receivable_exposure", "Exposição de crediário", "FINANCEIRO", "receivable.read", "receivable_exposure", 330),
        ("delivery_orders", "REPORTING", "channel_backlog", "Backlog de canais", "CANAIS", "channel.read", "channel_backlog", 340),
    ]
    for capability, surface, key, label, group_key, permission, implementation, order in contributions:
        route = f"/manage/{key}" if surface == "MANAGEMENT_NAV" else None
        op.execute(sa.text("INSERT INTO module_contributions (id, capability_key, surface, contribution_key, label, group_key, route, permission_key, implementation_key, sort_order, metadata_json, is_active) VALUES (gen_random_uuid(), :capability, :surface, :key, :label, :group_key, :route, :permission, :implementation, :sort_order, '{}'::json, true)").bindparams(capability=capability, surface=surface, key=key, label=label, group_key=group_key, route=route, permission=permission, implementation=implementation, sort_order=order))


def downgrade() -> None:
    op.drop_table("capability_conflicts")
    op.drop_table("module_contributions")
    op.drop_index("uq_tenant_active_profile_assignment", table_name="tenant_profile_assignments")
    op.drop_table("tenant_profile_assignments")
    op.drop_table("capability_profile_revision_items")
    op.drop_table("capability_profile_revisions")

"""Database tenant/site isolation and capability mesh contracts.

Revision ID: 012_tenant_rls_capability_mesh
Revises: 011_owner_onboarding
Create Date: 2026-08-21 23:30:00.000000
"""

from datetime import datetime
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "012_tenant_rls_capability_mesh"
down_revision: Union[str, None] = "011_owner_onboarding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_TABLES = (
    "agent_runs", "agent_tool_calls", "approval_requests", "audit_events",
    "cash_movements", "cash_sessions", "categories", "context_edges",
    "customers", "fiscal_documents", "fiscal_events", "idempotency_records",
    "inventory_balances", "inventory_movements", "memberships", "outbox_events",
    "payments", "product_prices", "products", "registers", "sale_items", "sales",
    "sales_channels", "stores", "tenant_capabilities", "store_capability_overrides",
)

STORE_TABLES = {
    "agent_runs", "agent_tool_calls", "approval_requests", "audit_events",
    "cash_movements", "cash_sessions", "context_edges", "fiscal_documents",
    "fiscal_events", "inventory_balances", "inventory_movements", "memberships",
    "outbox_events", "payments", "product_prices", "registers", "sales",
    "sales_channels", "store_capability_overrides", "stores",
}


# Immutable product contracts introduced by this revision. Commercial
# profiles and tenant entitlements remain data, not migration defaults.
CAPABILITIES = (
    ("catalog", "Catálogo", "TENANT", "Produtos, serviços, preços e categorias.", ()),
    ("inventory", "Estoque", "STORE", "Saldos e razão de movimentações por site.", ("catalog",)),
    ("customer", "Clientes", "TENANT", "Cadastro e contexto comercial de clientes.", ()),
    ("cash_management", "Gestão de caixa", "STORE", "Sessões, sangrias, suprimentos e conferência.", ()),
    ("payments", "Pagamentos", "STORE", "Orquestração de recebimentos e split.", ()),
    ("barcode_scanning", "Leitura de código de barras", "TERMINAL", "Entrada rápida por EAN, SKU ou leitor.", ("catalog",)),
    ("quotes", "Orçamentos", "TENANT", "Propostas comerciais convertíveis em venda.", ("catalog", "customer")),
    ("modifiers", "Modificadores", "TENANT", "Adicionais e escolhas aplicáveis a itens.", ("catalog",)),
    ("combos", "Combos", "TENANT", "Composição comercial de produtos e opções.", ("catalog", "modifiers")),
    ("kitchen_routing", "Roteamento de cozinha", "STORE", "Direcionamento de produção por estação.", ("catalog",)),
    ("delivery_orders", "Pedidos de delivery", "STORE", "Entrada e acompanhamento de canais de entrega.", ("catalog", "customer")),
    ("counter_order", "Pedido de balcão", "STORE", "Fluxo ágil de pedido e retirada.", ("catalog", "payments")),
    ("weighted_products", "Produtos pesáveis", "STORE", "Venda por peso e leitura de etiqueta de balança.", ("catalog",)),
    ("high_speed_checkout", "Checkout de alta velocidade", "TERMINAL", "Fluxo otimizado para grande volume.", ("barcode_scanning", "payments")),
    ("supervisor_override", "Autorização de supervisor", "STORE", "Elevação auditada para operações sensíveis.", ()),
    ("customer_display", "Display do cliente", "TERMINAL", "Espelhamento seguro da venda para o consumidor.", ()),
    ("self_checkout", "Autoatendimento", "TERMINAL", "Fluxo de compra sem operador dedicado.", ("barcode_scanning", "payments")),
    ("serial_tracking", "Rastreio por série", "STORE", "Controle unitário por número serial.", ("inventory",)),
    ("batch_tracking", "Rastreio por lote", "STORE", "Controle de lote, validade e origem.", ("inventory",)),
    ("multi_price", "Múltiplas tabelas de preço", "TENANT", "Preços por canal, site ou segmento.", ("catalog",)),
    ("pix", "PIX", "STORE", "Recebimento e conciliação PIX.", ("payments",)),
    ("tef", "TEF", "TERMINAL", "Integração de transferência eletrônica de fundos.", ("payments",)),
    ("fiscal_nfce", "NFC-e", "STORE", "Emissão fiscal de consumidor.", ("payments",)),
    ("fiscal_nfe", "NF-e", "STORE", "Emissão fiscal de mercadorias.", ("payments",)),
)


def _tenant_expression(table: str) -> str:
    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    if table == "memberships":
        own = "user_id = nullif(current_setting('app.user_id', true), '')::uuid"
        tenant = f"(({tenant}) OR ({own}))"
    elif table == "sale_items":
        # sale_items deliberately inherits its site boundary from the sale.
        # Keeping store_id out of each line avoids duplicated operational data,
        # but the RLS policy must still prevent a store-scoped session from
        # reading or writing lines that belong to a sibling site.
        site = """(
            nullif(current_setting('app.store_id', true), '') IS NULL
            OR EXISTS (
                SELECT 1 FROM sales parent_sale
                WHERE parent_sale.id = sale_items.sale_id
                  AND parent_sale.tenant_id = sale_items.tenant_id
                  AND parent_sale.store_id = nullif(current_setting('app.store_id', true), '')::uuid
            )
        )"""
        tenant = f"({tenant}) AND ({site})"
    if table == "stores":
        site = """(
            nullif(current_setting('app.store_id', true), '') IS NULL
            OR id = nullif(current_setting('app.store_id', true), '')::uuid
        )"""
        tenant = f"({tenant}) AND ({site})"
    elif table in STORE_TABLES:
        valid_store = f"""(
            store_id IS NULL
            OR EXISTS (
                SELECT 1 FROM stores owning_store
                WHERE owning_store.id = {table}.store_id
                  AND owning_store.tenant_id = {table}.tenant_id
            )
        )"""
        site = """(
            nullif(current_setting('app.store_id', true), '') IS NULL
            OR store_id IS NULL
            OR store_id = nullif(current_setting('app.store_id', true), '')::uuid
        )"""
        tenant = f"({tenant}) AND ({valid_store}) AND ({site})"
    return f"({platform}) OR ({tenant})"


def _enable_rls(table: str) -> None:
    expression = _tenant_expression(table)
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'''CREATE POLICY dashem_isolation ON "{table}"
            FOR ALL
            USING ({expression})
            WITH CHECK ({expression})'''
    )


def upgrade() -> None:
    op.create_table(
        "capability_definitions",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("configuration_schema", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_capability_definitions_scope", "capability_definitions", ["scope"])
    op.create_index("ix_capability_definitions_status", "capability_definitions", ["status"])
    definitions = sa.table(
        "capability_definitions",
        sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("version", sa.String), sa.column("description", sa.String),
        sa.column("scope", sa.String), sa.column("status", sa.String),
        sa.column("configuration_schema", sa.JSON),
        sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
    )
    now = datetime.utcnow()
    op.bulk_insert(definitions, [
        {
            "key": key, "name": name, "version": "1.0.0",
            "description": description, "scope": scope, "status": "ACTIVE",
            "configuration_schema": {}, "created_at": now, "updated_at": now,
        }
        for key, name, scope, description, _requires in CAPABILITIES
    ])
    op.create_table(
        "capability_dependencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability_key", sa.String(length=80), nullable=False),
        sa.Column("requires_key", sa.String(length=80), nullable=False),
        sa.Column("minimum_version", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["capability_key"], ["capability_definitions.key"]),
        sa.ForeignKeyConstraint(["requires_key"], ["capability_definitions.key"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capability_key", "requires_key", name="uq_capability_dependency"),
    )
    op.create_index("ix_capability_dependencies_capability_key", "capability_dependencies", ["capability_key"])
    op.create_index("ix_capability_dependencies_requires_key", "capability_dependencies", ["requires_key"])
    dependencies = sa.table(
        "capability_dependencies",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("capability_key", sa.String), sa.column("requires_key", sa.String),
        sa.column("minimum_version", sa.String),
    )
    op.bulk_insert(dependencies, [
        {
            "id": uuid.uuid4(), "capability_key": key,
            "requires_key": required, "minimum_version": "1.0.0",
        }
        for key, _name, _scope, _description, requires in CAPABILITIES
        for required in requires
    ])
    op.create_table(
        "capability_profiles",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_capability_profiles_is_active", "capability_profiles", ["is_active"])
    op.create_table(
        "capability_profile_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_key", sa.String(length=80), nullable=False),
        sa.Column("capability_key", sa.String(length=80), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("default_configuration", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["capability_key"], ["capability_definitions.key"]),
        sa.ForeignKeyConstraint(["profile_key"], ["capability_profiles.key"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_key", "capability_key", name="uq_capability_profile_item"),
    )
    op.create_index("ix_capability_profile_items_profile_key", "capability_profile_items", ["profile_key"])
    op.create_index("ix_capability_profile_items_capability_key", "capability_profile_items", ["capability_key"])

    op.add_column("tenant_capabilities", sa.Column("status", sa.String(), server_default="ACTIVE", nullable=False))
    op.add_column("tenant_capabilities", sa.Column("contract_limits", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False))
    op.create_index("ix_tenant_capabilities_status", "tenant_capabilities", ["status"])
    op.create_foreign_key(
        "fk_tenant_capabilities_key_definition",
        "tenant_capabilities", "capability_definitions", ["key"], ["key"],
    )

    op.create_table(
        "store_capability_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["key"], ["capability_definitions.key"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "store_id", "key", name="uq_store_capability_override"),
    )
    for column in ("tenant_id", "store_id", "key", "enabled"):
        op.create_index(f"ix_store_capability_overrides_{column}", "store_capability_overrides", [column])

    # Alembic connects with the schema-owner credential. The API assumes this
    # non-login role on every pooled connection, so even an owner connection
    # cannot accidentally bypass RLS while serving a request.
    op.execute('''DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashem_runtime') THEN
            CREATE ROLE dashem_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
        END IF;
        EXECUTE format('GRANT dashem_runtime TO %I', current_user);
    END $$''')
    op.execute("GRANT USAGE ON SCHEMA public TO dashem_runtime")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO dashem_runtime")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO dashem_runtime")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dashem_runtime")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO dashem_runtime")

    # The platform plane can address tenant rows only after explicit platform
    # RBAC sets app.platform_access. Ordinary requests are denied by default.
    op.execute('ALTER TABLE "tenants" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "tenants" FORCE ROW LEVEL SECURITY')
    op.execute('''CREATE POLICY dashem_isolation ON "tenants" FOR ALL
        USING (
            current_setting('app.platform_access', true) = 'true'
            OR id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR EXISTS (
                SELECT 1 FROM memberships m
                WHERE m.tenant_id = tenants.id
                  AND m.user_id = nullif(current_setting('app.user_id', true), '')::uuid
            )
        )
        WITH CHECK (
            current_setting('app.platform_access', true) = 'true'
            OR id = nullif(current_setting('app.tenant_id', true), '')::uuid
        )''')
    for table in TENANT_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS dashem_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.execute('DROP POLICY IF EXISTS dashem_isolation ON "tenants"')
    op.execute('ALTER TABLE "tenants" DISABLE ROW LEVEL SECURITY')
    for column in ("enabled", "key", "store_id", "tenant_id"):
        op.drop_index(f"ix_store_capability_overrides_{column}", table_name="store_capability_overrides")
    op.drop_table("store_capability_overrides")
    op.execute(
        "ALTER TABLE tenant_capabilities "
        "DROP CONSTRAINT IF EXISTS fk_tenant_capabilities_key_definition"
    )
    op.drop_index("ix_tenant_capabilities_status", table_name="tenant_capabilities")
    op.drop_column("tenant_capabilities", "contract_limits")
    op.drop_column("tenant_capabilities", "status")
    op.drop_index("ix_capability_profile_items_capability_key", table_name="capability_profile_items")
    op.drop_index("ix_capability_profile_items_profile_key", table_name="capability_profile_items")
    op.drop_table("capability_profile_items")
    op.drop_index("ix_capability_profiles_is_active", table_name="capability_profiles")
    op.drop_table("capability_profiles")
    op.drop_index("ix_capability_dependencies_requires_key", table_name="capability_dependencies")
    op.drop_index("ix_capability_dependencies_capability_key", table_name="capability_dependencies")
    op.drop_table("capability_dependencies")
    op.drop_index("ix_capability_definitions_status", table_name="capability_definitions")
    op.drop_index("ix_capability_definitions_scope", table_name="capability_definitions")
    op.drop_table("capability_definitions")

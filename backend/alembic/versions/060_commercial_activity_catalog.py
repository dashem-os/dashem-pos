"""Persist the Owner commercial activity and capability matrix.

Revision ID: 060_commercial_catalog
Revises: 059_billing_day_source
"""

from alembic import op
import sqlalchemy as sa


revision = "060_commercial_catalog"
down_revision = "059_billing_day_source"
branch_labels = None
depends_on = None


ACTIVITY_KEYS = '["FOOD_SERVICE", "RETAIL", "BEAUTY_RESELLER"]'


def upgrade() -> None:
    op.create_table(
        "commercial_activities",
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("version >= 1", name="ck_commercial_activity_version_positive"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')",
            name="ck_commercial_activity_status",
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_commercial_activities_name", "commercial_activities", ["name"])
    op.create_index("ix_commercial_activities_status", "commercial_activities", ["status"])
    op.create_table(
        "commercial_activity_capabilities",
        sa.Column("activity_key", sa.String(80), nullable=False),
        sa.Column("capability_key", sa.String(80), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("default_selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("configuration", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "role IN ('REQUIRED', 'OPTIONAL')",
            name="ck_commercial_activity_capability_role",
        ),
        sa.ForeignKeyConstraint(["activity_key"], ["commercial_activities.key"]),
        sa.ForeignKeyConstraint(["capability_key"], ["capability_definitions.key"]),
        sa.PrimaryKeyConstraint("activity_key", "capability_key"),
    )
    op.create_index(
        "ix_commercial_activity_capabilities_capability_key",
        "commercial_activity_capabilities",
        ["capability_key"],
    )

    op.execute(
        """
        INSERT INTO commercial_activities (key, name, description, status, version)
        VALUES
          ('FOOD_SERVICE', 'Food Service', 'Atendimento de alimentação com delivery; mesas e produção são opções contratuais.', 'ACTIVE', 1),
          ('RETAIL', 'Retail', 'Varejo com estoque, checkout e canais de venda.', 'ACTIVE', 1),
          ('BEAUTY_RESELLER', 'Beauty Reseller', 'Revenda de beleza com catálogo, estoque e pedidos online.', 'ACTIVE', 1)
        """
    )
    op.execute(
        """
        INSERT INTO commercial_activity_capabilities
            (activity_key, capability_key, role, default_selected)
        VALUES
          ('FOOD_SERVICE', 'catalog', 'REQUIRED', true),
          ('FOOD_SERVICE', 'customer', 'REQUIRED', true),
          ('FOOD_SERVICE', 'cash_management', 'REQUIRED', true),
          ('FOOD_SERVICE', 'payments', 'REQUIRED', true),
          ('FOOD_SERVICE', 'counter_order', 'REQUIRED', true),
          ('FOOD_SERVICE', 'delivery_orders', 'REQUIRED', true),
          ('FOOD_SERVICE', 'modifiers', 'OPTIONAL', false),
          ('FOOD_SERVICE', 'combos', 'OPTIONAL', false),
          ('FOOD_SERVICE', 'table_service', 'OPTIONAL', false),
          ('FOOD_SERVICE', 'kitchen_routing', 'OPTIONAL', false),
          ('FOOD_SERVICE', 'supervisor_override', 'OPTIONAL', false),
          ('FOOD_SERVICE', 'tef', 'OPTIONAL', false),
          ('FOOD_SERVICE', 'fiscal_nfce', 'OPTIONAL', false),
          ('RETAIL', 'catalog', 'REQUIRED', true),
          ('RETAIL', 'inventory', 'REQUIRED', true),
          ('RETAIL', 'customer', 'REQUIRED', true),
          ('RETAIL', 'cash_management', 'REQUIRED', true),
          ('RETAIL', 'payments', 'REQUIRED', true),
          ('RETAIL', 'barcode_scanning', 'REQUIRED', true),
          ('RETAIL', 'counter_order', 'REQUIRED', true),
          ('RETAIL', 'delivery_orders', 'REQUIRED', true),
          ('RETAIL', 'high_speed_checkout', 'OPTIONAL', false),
          ('RETAIL', 'supervisor_override', 'OPTIONAL', false),
          ('RETAIL', 'tef', 'OPTIONAL', false),
          ('RETAIL', 'fiscal_nfce', 'OPTIONAL', false),
          ('RETAIL', 'receivables', 'OPTIONAL', false),
          ('BEAUTY_RESELLER', 'catalog', 'REQUIRED', true),
          ('BEAUTY_RESELLER', 'inventory', 'REQUIRED', true),
          ('BEAUTY_RESELLER', 'customer', 'REQUIRED', true),
          ('BEAUTY_RESELLER', 'cash_management', 'REQUIRED', true),
          ('BEAUTY_RESELLER', 'payments', 'REQUIRED', true),
          ('BEAUTY_RESELLER', 'delivery_orders', 'REQUIRED', true),
          ('BEAUTY_RESELLER', 'barcode_scanning', 'OPTIONAL', false),
          ('BEAUTY_RESELLER', 'counter_order', 'OPTIONAL', false),
          ('BEAUTY_RESELLER', 'supervisor_override', 'OPTIONAL', false),
          ('BEAUTY_RESELLER', 'tef', 'OPTIONAL', false),
          ('BEAUTY_RESELLER', 'fiscal_nfce', 'OPTIONAL', false),
          ('BEAUTY_RESELLER', 'receivables', 'OPTIONAL', false)
        """
    )

    op.add_column(
        "service_plans",
        sa.Column("activity_keys", sa.JSON(), nullable=False, server_default=ACTIVITY_KEYS),
    )
    op.add_column(
        "service_plan_revisions",
        sa.Column("activity_keys", sa.JSON(), nullable=False, server_default=ACTIVITY_KEYS),
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON commercial_activities, "
        "commercial_activity_capabilities TO dashem_runtime"
    )


def downgrade() -> None:
    op.drop_column("service_plan_revisions", "activity_keys")
    op.drop_column("service_plans", "activity_keys")
    op.drop_index(
        "ix_commercial_activity_capabilities_capability_key",
        table_name="commercial_activity_capabilities",
    )
    op.drop_table("commercial_activity_capabilities")
    op.drop_index("ix_commercial_activities_status", table_name="commercial_activities")
    op.drop_index("ix_commercial_activities_name", table_name="commercial_activities")
    op.drop_table("commercial_activities")

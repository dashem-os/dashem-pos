"""Truth of assortment by context.

Revision ID: 069_assortment_by_context
Revises: 068_tenant_governance_nav
Create Date: 2026-09-02 08:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "069_assortment_by_context"
down_revision: Union[str, None] = "068_tenant_governance_nav"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tenant_rls(table: str) -> None:
    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    expression = f"({platform}) OR ({tenant})"
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY dashem_isolation ON "{table}" FOR ALL '
        f'USING ({expression}) WITH CHECK ({expression})'
    )


def upgrade() -> None:
    # 1. Create assortments table
    op.create_table(
        "assortments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="ACTIVE"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("version > 0", name="ck_assortment_version_positive"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_tenant_assortment_code"),
    )
    for col in ("tenant_id", "code", "name", "status", "created_at"):
        op.create_index(f"ix_assortments_{col}", "assortments", [col])

    # 2. Create assortment_scopes table
    op.create_table(
        "assortment_scopes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assortment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sales_context", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["assortment_id"], ["assortments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["sales_channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("tenant_id", "assortment_id", "store_id", "channel_id", "sales_context", "created_at"):
        op.create_index(f"ix_assortment_scopes_{col}", "assortment_scopes", [col])
    op.create_index(
        "uq_assortment_scope_channel",
        "assortment_scopes",
        ["tenant_id", "assortment_id", "store_id", "sales_context", "channel_id"],
        unique=True,
        postgresql_where=sa.text("channel_id IS NOT NULL"),
    )
    op.create_index(
        "uq_assortment_scope_no_channel",
        "assortment_scopes",
        ["tenant_id", "assortment_id", "store_id", "sales_context"],
        unique=True,
        postgresql_where=sa.text("channel_id IS NULL"),
    )

    # 3. Create assortment_products table
    op.create_table(
        "assortment_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assortment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("sort_order >= 0", name="ck_assortment_product_sort_order"),
        sa.ForeignKeyConstraint(["assortment_id"], ["assortments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "assortment_id", "product_id", name="uq_tenant_assortment_product"),
    )
    for col in ("tenant_id", "assortment_id", "product_id", "sort_order", "created_at"):
        op.create_index(f"ix_assortment_products_{col}", "assortment_products", [col])

    # 4. Enable RLS
    for table in ("assortments", "assortment_scopes", "assortment_products"):
        _tenant_rls(table)

    # 5. Honest data migration for existing active products
    # The backfill is a migration-authorized write. Keep it explicit instead
    # of relying on the migration role being a superuser, because FORCE RLS
    # must remain effective for non-superuser migration credentials too.
    op.execute("SELECT set_config('app.platform_access', 'true', true)")
    op.execute(
        sa.text("""
        DO $$
        DECLARE
            r RECORD;
            v_assortment_id UUID;
            s RECORD;
        BEGIN
            FOR r IN SELECT DISTINCT p.tenant_id FROM products p WHERE p.is_active = true AND p.available_for_sale = true LOOP
                IF EXISTS (SELECT 1 FROM stores WHERE tenant_id = r.tenant_id AND is_active = true) THEN
                    v_assortment_id := gen_random_uuid();
                    INSERT INTO assortments (id, tenant_id, code, name, description, status, version, created_at, updated_at)
                    VALUES (
                        v_assortment_id,
                        r.tenant_id,
                        'LEGACY-DEFAULT',
                        'Sortimento Legado — Balcão e Retirada',
                        'Materializado na migração 069 para preservar a publicação pré-existente de balcão e retirada sem classificação presumida.',
                        'ACTIVE',
                        1,
                        now(),
                        now()
                    )
                    ON CONFLICT (tenant_id, code) DO NOTHING;

                    SELECT id INTO v_assortment_id FROM assortments WHERE tenant_id = r.tenant_id AND code = 'LEGACY-DEFAULT';

                    FOR s IN SELECT id FROM stores WHERE tenant_id = r.tenant_id AND is_active = true LOOP
                        INSERT INTO assortment_scopes (id, tenant_id, assortment_id, store_id, channel_id, sales_context, created_at)
                        SELECT gen_random_uuid(), r.tenant_id, v_assortment_id, s.id, NULL, 'COUNTER', now()
                        WHERE NOT EXISTS (
                            SELECT 1 FROM assortment_scopes
                            WHERE tenant_id = r.tenant_id AND assortment_id = v_assortment_id
                              AND store_id = s.id AND sales_context = 'COUNTER' AND channel_id IS NULL
                        );

                        INSERT INTO assortment_scopes (id, tenant_id, assortment_id, store_id, channel_id, sales_context, created_at)
                        SELECT gen_random_uuid(), r.tenant_id, v_assortment_id, s.id, NULL, 'TAKEAWAY', now()
                        WHERE NOT EXISTS (
                            SELECT 1 FROM assortment_scopes
                            WHERE tenant_id = r.tenant_id AND assortment_id = v_assortment_id
                              AND store_id = s.id AND sales_context = 'TAKEAWAY' AND channel_id IS NULL
                        );
                    END LOOP;

                    INSERT INTO assortment_products (id, tenant_id, assortment_id, product_id, sort_order, created_at)
                    SELECT gen_random_uuid(), r.tenant_id, v_assortment_id, p.id, 100, now()
                    FROM products p
                    WHERE p.tenant_id = r.tenant_id
                      AND p.is_active = true
                      AND p.available_for_sale = true
                    ON CONFLICT (tenant_id, assortment_id, product_id) DO NOTHING;
                END IF;
            END LOOP;
        END $$;
        """)
    )

    # 6. Module contribution in Gestão navigation
    op.execute(
        sa.text(
            """
            INSERT INTO module_contributions (
                id, capability_key, surface, contribution_key, label, group_key,
                route, permission_key, implementation_key, sort_order,
                metadata_json, is_active
            )
            SELECT gen_random_uuid(), 'catalog', 'MANAGEMENT_NAV', 'assortments',
                   'Sortimentos e cardápios', 'MERCADORIAS', '/manage/assortments',
                   'catalog.read', 'assortments', 65, '{}'::json, true
            WHERE NOT EXISTS (
                SELECT 1 FROM module_contributions
                WHERE surface = 'MANAGEMENT_NAV'
                  AND contribution_key = 'assortments'
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM module_contributions "
            "WHERE surface = 'MANAGEMENT_NAV' AND contribution_key = 'assortments'"
        )
    )
    op.drop_table("assortment_products")
    op.drop_table("assortment_scopes")
    op.drop_table("assortments")

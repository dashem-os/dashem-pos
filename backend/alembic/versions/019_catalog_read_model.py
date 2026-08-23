"""Operational catalog read model, quick access, modifiers and combos.

Revision ID: 019_catalog_read_model
Revises: 018_management_overview
Create Date: 2026-08-23 18:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "019_catalog_read_model"
down_revision: Union[str, None] = "018_management_overview"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tenant_rls(table: str, store_scoped: bool = False) -> None:
    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    expression = f"({platform}) OR (({tenant})" + (f" AND ({store})" if store_scoped else "") + ")"
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY dashem_isolation ON "{table}" FOR ALL '
        f'USING ({expression}) WITH CHECK ({expression})'
    )


def upgrade() -> None:
    op.add_column("categories", sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("categories", sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column("categories", sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False))
    op.create_foreign_key("fk_categories_parent", "categories", "categories", ["parent_id"], ["id"])
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"])
    op.create_index("ix_categories_is_active", "categories", ["is_active"])

    for column in (
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("unit", sa.String(length=16), server_default="UN", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("available_for_sale", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("allows_multi_flavor", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("production_destination", sa.String(length=80), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    ):
        op.add_column("products", column)
    op.create_index("ix_products_is_active", "products", ["is_active"])
    op.create_index("ix_products_available_for_sale", "products", ["available_for_sale"])

    op.add_column("product_prices", sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False))
    # Old writes inserted a new row at every price change. Keep the newest row
    # before establishing the canonical one-price-per-scope contract.
    op.execute(sa.text("""
        DELETE FROM product_prices older
        USING product_prices newer
        WHERE older.tenant_id = newer.tenant_id
          AND older.product_id = newer.product_id
          AND older.store_id IS NOT DISTINCT FROM newer.store_id
          AND (older.created_at, older.id) < (newer.created_at, newer.id)
    """))
    op.create_index(
        "uq_product_prices_store", "product_prices",
        ["tenant_id", "store_id", "product_id"], unique=True,
        postgresql_where=sa.text("store_id IS NOT NULL"),
    )
    op.create_index(
        "uq_product_prices_global", "product_prices",
        ["tenant_id", "product_id"], unique=True,
        postgresql_where=sa.text("store_id IS NULL"),
    )

    op.create_table(
        "quick_access_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("position BETWEEN 1 AND 99", name="ck_quick_access_position"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "store_id", "membership_id", "product_id", name="uq_quick_access_product"),
        sa.UniqueConstraint("tenant_id", "store_id", "membership_id", "position", name="uq_quick_access_position"),
    )

    op.create_table(
        "modifier_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("minimum_choices", sa.Integer(), nullable=False),
        sa.Column("maximum_choices", sa.Integer(), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("minimum_choices >= 0 AND maximum_choices >= 1 AND minimum_choices <= maximum_choices", name="ck_modifier_group_choices"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tenant_modifier_group_name"),
    )
    op.create_table(
        "modifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("price_delta", sa.Numeric(14, 4), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["modifier_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "group_id", "name", name="uq_modifier_group_name"),
    )
    op.create_table(
        "product_modifier_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("modifier_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("position >= 1", name="ck_product_modifier_position"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["modifier_group_id"], ["modifier_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "product_id", "modifier_group_id", name="uq_product_modifier_group"),
    )
    op.create_table(
        "combos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_combos_product_id"),
    )
    op.create_table(
        "combo_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("combo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_combo_item_quantity"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["combo_id"], ["combos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("combo_id", "product_id", name="uq_combo_item_product"),
    )

    for table, columns in {
        "quick_access_products": ("tenant_id", "store_id", "membership_id", "product_id"),
        "modifier_groups": ("tenant_id", "is_active"),
        "modifiers": ("tenant_id", "group_id", "is_active"),
        "product_modifier_groups": ("tenant_id", "product_id", "modifier_group_id"),
        "combos": ("tenant_id", "product_id", "is_active"),
        "combo_items": ("tenant_id", "combo_id", "product_id"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")
        _tenant_rls(table, store_scoped=table == "quick_access_products")


def downgrade() -> None:
    for table in ("combo_items", "combos", "product_modifier_groups", "modifiers", "modifier_groups", "quick_access_products"):
        op.drop_table(table)
    op.drop_index("uq_product_prices_global", table_name="product_prices")
    op.drop_index("uq_product_prices_store", table_name="product_prices")
    op.drop_column("product_prices", "updated_at")
    op.drop_index("ix_products_available_for_sale", table_name="products")
    op.drop_index("ix_products_is_active", table_name="products")
    for column in ("updated_at", "production_destination", "allows_multi_flavor", "available_for_sale", "is_active", "unit", "image_url"):
        op.drop_column("products", column)
    op.drop_index("ix_categories_is_active", table_name="categories")
    op.drop_index("ix_categories_parent_id", table_name="categories")
    op.drop_constraint("fk_categories_parent", "categories", type_="foreignkey")
    for column in ("updated_at", "is_active", "parent_id"):
        op.drop_column("categories", column)

"""S23 — a unit's shop window, and the personal band beside it.

Quick access existed and was personal only: `quick_access_products` is keyed by
tenant, store and membership, with no arrangement belonging to the unit. So the
first screen of the operation could not be arranged by whoever knows the
movement, and every operator started from an alphabetical list.

Three things change here.

The unit gets its own layout, scoped by sales context and business activity,
with a versioned header so a reorder is one transaction with an expected
version instead of a sequence of position writes.

The personal table stops pretending to be the arrangement and becomes what it
always was — that person's shortcuts — gaining the same context and activity
scope, because someone who works the counter and the takeaway had ambiguous
positions before.

And both position uniques become DEFERRABLE INITIALLY DEFERRED. This is the
change that makes dragging possible at all: PostgreSQL checks a non-deferred
unique during the statement, so permuting positions violates it halfway through
even inside a single transaction. Only the position constraint is deferred; the
product constraint stays immediate, because deferring it would widen the window
for a real error with no benefit.

Backfill note. The activity column is NOT NULL with an `ALL` sentinel rather
than nullable. A NULL never collides in a unique constraint, so a nullable
activity would silently leave positions unprotected — and a unique CONSTRAINT
cannot be expressed over COALESCE, while a unique INDEX that could be cannot be
deferred. Existing rows are backfilled to COUNTER/ALL: they were created with no
notion of context or activity, so they legitimately belong to every activity.
There is no primary activity on a store to read instead — activity lives on the
assortment and on the tenant's contract.
"""

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "073_store_catalog_layout"
down_revision: Union[str, None] = "072_payment_provider_nav"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SALES_CONTEXTS = "('COUNTER', 'TAKEAWAY', 'TABLE', 'DELIVERY', 'ECOMMERCE')"
ACTIVITIES = "('FOOD_SERVICE', 'RETAIL', 'BEAUTY_RESELLER', 'ALL')"

PERMISSIONS = (
    (
        "catalog.layout.manage",
        "Ordenar a vitrine da unidade",
        "Define a ordem dos produtos na tela inicial da unidade, por contexto de venda e atividade.",
        "catalog",
    ),
    (
        "catalog.layout.personalize",
        "Ordenar os próprios atalhos",
        "Mantém a faixa pessoal de atalhos do colaborador, sem conceder poder sobre o catálogo.",
        "catalog",
    ),
)


def _tenant_rls(table: str) -> None:
    """Every tenant-aware table is forced through the database boundary.

    Not a formality: `test_every_tenant_table_is_forced_through_rls` caught these
    two tables bypassing it, which would have let the arrangement of one unit be
    read across tenants by any query that forgot its scope.
    """
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
    op.create_table(
        "store_catalog_layouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("sales_context", sa.String(length=40), nullable=False),
        sa.Column("business_activity", sa.String(length=40), nullable=False, server_default="ALL"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "tenant_id", "store_id", "sales_context", "business_activity",
            name="uq_store_catalog_layout_scope",
        ),
        sa.CheckConstraint(f"sales_context IN {SALES_CONTEXTS}", name="ck_store_catalog_layout_context"),
        sa.CheckConstraint(f"business_activity IN {ACTIVITIES}", name="ck_store_catalog_layout_activity"),
        sa.CheckConstraint("version > 0", name="ck_store_catalog_layout_version"),
    )
    op.create_index("ix_store_catalog_layouts_tenant_id", "store_catalog_layouts", ["tenant_id"])
    op.create_index("ix_store_catalog_layouts_store_id", "store_catalog_layouts", ["store_id"])

    op.create_table(
        "store_catalog_layout_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "layout_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("store_catalog_layouts.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "product_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("layout_id", "product_id", name="uq_store_catalog_layout_product"),
        sa.CheckConstraint("position BETWEEN 1 AND 99", name="ck_store_catalog_layout_position"),
    )
    op.create_index("ix_store_catalog_layout_items_tenant_id", "store_catalog_layout_items", ["tenant_id"])
    op.create_index("ix_store_catalog_layout_items_layout_id", "store_catalog_layout_items", ["layout_id"])
    # The one that makes dragging possible: checked at COMMIT, not per statement.
    op.execute(
        "ALTER TABLE store_catalog_layout_items "
        "ADD CONSTRAINT uq_store_catalog_layout_position UNIQUE (layout_id, position) "
        "DEFERRABLE INITIALLY DEFERRED"
    )

    _tenant_rls("store_catalog_layouts")
    _tenant_rls("store_catalog_layout_items")

    # The personal table becomes explicitly personal, and gains the same scope.
    op.add_column("quick_access_products", sa.Column("sales_context", sa.String(length=40), nullable=True))
    op.add_column("quick_access_products", sa.Column("business_activity", sa.String(length=40), nullable=True))
    op.execute("UPDATE quick_access_products SET sales_context = 'COUNTER' WHERE sales_context IS NULL")
    op.execute("UPDATE quick_access_products SET business_activity = 'ALL' WHERE business_activity IS NULL")
    op.alter_column("quick_access_products", "sales_context", nullable=False, server_default="COUNTER")
    op.alter_column("quick_access_products", "business_activity", nullable=False, server_default="ALL")
    op.create_check_constraint(
        "ck_quick_access_context", "quick_access_products", f"sales_context IN {SALES_CONTEXTS}"
    )
    op.create_check_constraint(
        "ck_quick_access_activity", "quick_access_products", f"business_activity IN {ACTIVITIES}"
    )

    op.drop_constraint("uq_quick_access_product", "quick_access_products", type_="unique")
    op.drop_constraint("uq_quick_access_position", "quick_access_products", type_="unique")
    op.create_unique_constraint(
        "uq_quick_access_product", "quick_access_products",
        ["tenant_id", "store_id", "membership_id", "sales_context", "business_activity", "product_id"],
    )
    op.execute(
        "ALTER TABLE quick_access_products "
        "ADD CONSTRAINT uq_quick_access_position UNIQUE "
        "(tenant_id, store_id, membership_id, sales_context, business_activity, position) "
        "DEFERRABLE INITIALLY DEFERRED"
    )

    permissions = sa.table(
        "permissions",
        sa.column("key", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("capability_key", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    now = datetime.utcnow()
    op.bulk_insert(permissions, [
        {
            "key": key, "name": name, "description": description,
            "capability_key": capability, "created_at": now,
        }
        for key, name, description, capability in PERMISSIONS
    ])

    # Whoever already administers the catalogue arranges the unit's window.
    op.execute("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rpp.role_profile_id, 'catalog.layout.manage'
        FROM role_profile_permissions rpp
        WHERE rpp.permission_key = 'catalog.update'
        ON CONFLICT DO NOTHING
    """)
    # Whoever can start a sale keeps their own shortcuts, without catalogue power.
    op.execute("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rpp.role_profile_id, 'catalog.layout.personalize'
        FROM role_profile_permissions rpp
        WHERE rpp.permission_key = 'sale.create'
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_profile_permissions "
        "WHERE permission_key IN ('catalog.layout.manage', 'catalog.layout.personalize')"
    )
    op.execute(
        "DELETE FROM permissions WHERE key IN ('catalog.layout.manage', 'catalog.layout.personalize')"
    )

    op.drop_constraint("uq_quick_access_position", "quick_access_products", type_="unique")
    op.drop_constraint("uq_quick_access_product", "quick_access_products", type_="unique")
    # Restoring the previous scope can collide: two rows that differed only by
    # context would become duplicates. Keep the first of each group, which is
    # what the table meant before this migration existed.
    op.execute("""
        DELETE FROM quick_access_products q USING (
            SELECT id, row_number() OVER (
                PARTITION BY tenant_id, store_id, membership_id, position ORDER BY created_at, id
            ) AS rn
            FROM quick_access_products
        ) dup
        WHERE q.id = dup.id AND dup.rn > 1
    """)
    op.create_unique_constraint(
        "uq_quick_access_product", "quick_access_products",
        ["tenant_id", "store_id", "membership_id", "product_id"],
    )
    op.create_unique_constraint(
        "uq_quick_access_position", "quick_access_products",
        ["tenant_id", "store_id", "membership_id", "position"],
    )
    op.drop_constraint("ck_quick_access_activity", "quick_access_products", type_="check")
    op.drop_constraint("ck_quick_access_context", "quick_access_products", type_="check")
    op.drop_column("quick_access_products", "business_activity")
    op.drop_column("quick_access_products", "sales_context")

    op.drop_table("store_catalog_layout_items")
    op.drop_table("store_catalog_layouts")

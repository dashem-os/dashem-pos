"""S24 — a product's picture becomes a persisted fact, not a typed address.

Until now `products.image_url` held a string somebody pasted. It stays, and it
stays working: every address registered before today keeps rendering, and this
migration neither rewrites nor deletes one. What it adds is a place to say which
stored file belongs to a product.

Two tables, and the difference between them is the whole contract.

`media_assets` belongs to a tenant. Its rows point either at a file the
shopkeeper uploaded into their own namespace, or at a picture they chose from
the platform library — the second costs them no storage, because nothing was
copied. Either way the row is theirs.

`platform_media_assets` is the DASHEM library: written only by the platform,
readable by every tenant, tagged by activity and by theme so a shop selling
lamps is not offered a hamburger. It is a shelf of ideas, never a fallback: a
product with no chosen picture shows its initial, and the system never decides
what someone's item looks like.

The row level security here departs from the house pattern on purpose. Every
other tenant table carries an `app.platform_access` clause so the Owner can
read across tenants for governance. `media_assets` does not. A shopkeeper's
photographs are not governance data, and nobody outside the tenant sees them —
DASHEM included. The Owner keeps measuring bytes for quota through
`storage_measurements`, because measuring a size is not looking at a file.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "074_product_media"
down_revision: Union[str, None] = "073_store_catalog_layout"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SOURCES = "('TENANT_UPLOAD', 'DASHEM_LIBRARY')"


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("bucket_id", sa.String(length=80), nullable=False),
        sa.Column("object_path", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("original_filename", sa.String(length=260), nullable=True),
        # Set when the row points at a library picture, so the catalogue can say
        # where the image came from without reading the platform's tables.
        sa.Column("library_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "bucket_id", "object_path", name="uq_media_asset_object"),
        sa.CheckConstraint(f"source IN {SOURCES}", name="ck_media_asset_source"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_media_asset_size"),
    )
    op.create_index("ix_media_assets_tenant_id", "media_assets", ["tenant_id"])

    # The tenant's own pictures. No platform clause: see the module docstring.
    tenant_only = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    op.execute('ALTER TABLE "media_assets" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "media_assets" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY dashem_tenant_private ON "media_assets" FOR ALL '
        f"USING ({tenant_only}) WITH CHECK ({tenant_only})"
    )

    op.create_table(
        "platform_media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("bucket_id", sa.String(length=80), nullable=False),
        sa.Column("object_path", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        # Suggested, never enforced: a lamp shop may take a picture filed under
        # food service if it wants to, and the search only ranks by these.
        sa.Column("suggested_activities", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("collection", sa.String(length=80), nullable=False, server_default="GENERIC"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("code", name="uq_platform_media_asset_code"),
        sa.CheckConstraint("version > 0", name="ck_platform_media_asset_version"),
    )
    op.create_index("ix_platform_media_assets_collection", "platform_media_assets", ["collection"])
    # No tenant_id: the library belongs to nobody and is offered to everybody.
    # It carries no tenant data, so it needs no isolation — only the write side
    # is restricted, and that lives in the permission engine.

    # The foreign key is declared inline so its generated name matches the one
    # SQLModel derives from the same column; a hand-named constraint reads as
    # drift to `alembic check`.
    op.add_column(
        "products",
        sa.Column(
            "primary_media_asset_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("products", "primary_media_asset_id")
    op.drop_table("platform_media_assets")
    op.execute('DROP POLICY IF EXISTS dashem_tenant_private ON "media_assets"')
    op.drop_table("media_assets")

"""Owner customer master data and contractual subscription.

Revision ID: 015_owner_customer_master
Revises: 014_enforce_store_ownership_rls
Create Date: 2026-08-23 13:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "015_owner_customer_master"
down_revision: Union[str, None] = "014_enforce_store_ownership_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enable_tenant_rls(table: str) -> None:
    expression = """(
        current_setting('app.platform_access', true) = 'true'
        OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
    )"""
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'''CREATE POLICY dashem_isolation ON "{table}"
            FOR ALL USING ({expression}) WITH CHECK ({expression})'''
    )


def upgrade() -> None:
    op.create_table(
        "tenant_profiles",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_type", sa.String(), nullable=False, server_default="TEST"),
        sa.Column("trade_name", sa.String(length=160), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=True),
        sa.Column("tax_id", sa.String(length=14), nullable=True),
        sa.Column("state_registration", sa.String(length=32), nullable=True),
        sa.Column("municipal_registration", sa.String(length=32), nullable=True),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("company_email", sa.String(length=254), nullable=True),
        sa.Column("company_phone", sa.String(length=32), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.UniqueConstraint("tax_id", name="uq_tenant_profiles_tax_id"),
    )
    for column in ("customer_type", "trade_name", "legal_name", "tax_id", "industry", "company_email", "company_phone"):
        op.create_index(f"ix_tenant_profiles_{column}", "tenant_profiles", [column])

    # Preserve existing organizations without inventing legal or commercial data.
    op.execute("""
        INSERT INTO tenant_profiles (tenant_id, customer_type, trade_name, legal_name)
        SELECT id, 'TEST', name, legal_name FROM tenants
    """)

    op.create_table(
        "tenant_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("job_title", sa.String(length=120), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "full_name", "email", "phone", "is_primary", "is_active"):
        op.create_index(f"ix_tenant_contacts_{column}", "tenant_contacts", [column])
    op.create_index(
        "uq_tenant_primary_contact", "tenant_contacts", ["tenant_id"], unique=True,
        postgresql_where=sa.text("is_primary = true AND is_active = true"),
    )

    op.create_table(
        "service_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("store_limit", sa.Integer(), nullable=True),
        sa.Column("user_limit", sa.Integer(), nullable=True),
        sa.Column("terminal_limit", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_service_plans_code"),
    )
    for column in ("code", "name", "is_active"):
        op.create_index(f"ix_service_plans_{column}", "service_plans", [column])

    op.create_table(
        "tenant_subscriptions",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(), nullable=True),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["plan_id"], ["service_plans.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_index("ix_tenant_subscriptions_plan_id", "tenant_subscriptions", ["plan_id"])
    op.create_index("ix_tenant_subscriptions_status", "tenant_subscriptions", ["status"])

    store_columns = (
        sa.Column("is_headquarters", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("legal_name", sa.String(length=200), nullable=True),
        sa.Column("tax_id", sa.String(length=14), nullable=True),
        sa.Column("state_registration", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("postal_code", sa.String(length=8), nullable=True),
        sa.Column("street", sa.String(length=200), nullable=True),
        sa.Column("street_number", sa.String(length=32), nullable=True),
        sa.Column("address_complement", sa.String(length=120), nullable=True),
        sa.Column("district", sa.String(length=120), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=2), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="BR"),
    )
    for column in store_columns:
        op.add_column("stores", column)
    op.create_index("ix_stores_is_headquarters", "stores", ["is_headquarters"])
    op.create_index("ix_stores_tax_id", "stores", ["tax_id"])
    op.create_index(
        "uq_tenant_headquarters", "stores", ["tenant_id"], unique=True,
        postgresql_where=sa.text("is_headquarters = true"),
    )
    op.execute("""
        WITH ranked AS (
            SELECT id, row_number() OVER (PARTITION BY tenant_id ORDER BY created_at, id) AS position
            FROM stores
        )
        UPDATE stores SET is_headquarters = true
        FROM ranked WHERE stores.id = ranked.id AND ranked.position = 1
    """)

    for table in ("tenant_profiles", "tenant_contacts", "tenant_subscriptions"):
        _enable_tenant_rls(table)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_profiles, tenant_contacts, service_plans, tenant_subscriptions TO dashem_runtime")


def downgrade() -> None:
    for table in ("tenant_subscriptions", "tenant_contacts", "tenant_profiles"):
        op.execute(f'DROP POLICY IF EXISTS dashem_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_index("uq_tenant_headquarters", table_name="stores")
    op.drop_index("ix_stores_tax_id", table_name="stores")
    op.drop_index("ix_stores_is_headquarters", table_name="stores")
    for column in (
        "country_code", "state", "city", "district", "address_complement",
        "street_number", "street", "postal_code", "phone", "email",
        "state_registration", "tax_id", "legal_name", "is_headquarters",
    ):
        op.drop_column("stores", column)
    op.drop_table("tenant_subscriptions")
    op.drop_table("service_plans")
    op.drop_index("uq_tenant_primary_contact", table_name="tenant_contacts")
    op.drop_table("tenant_contacts")
    op.drop_table("tenant_profiles")

"""Add the platform-owned SaaS billing account and subscription version.

Revision ID: 050_saas_finance_foundation
Revises: 049_subscription_limits
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "050_saas_finance_foundation"
down_revision = "049_subscription_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.add_column(
        "tenant_subscriptions",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        "ck_tenant_subscriptions_version_positive",
        "tenant_subscriptions",
        "version >= 1",
    )
    # The legacy manual status could claim CURRENT/OVERDUE without an invoice.
    # Remove it now; financial status will be derived from immutable invoice
    # facts in the invoicing phase.
    op.drop_column("tenant_subscriptions", "billing_status")

    op.create_table(
        "saas_billing_accounts",
        sa.Column("id", uid, nullable=False),
        sa.Column("tenant_id", uid, nullable=False),
        sa.Column("legal_name", sa.String(200), nullable=True),
        sa.Column("tax_id", sa.String(14), nullable=True),
        sa.Column("contact_name", sa.String(160), nullable=True),
        sa.Column("contact_email", sa.String(254), nullable=True),
        sa.Column("contact_phone", sa.String(32), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="BRL"),
        sa.Column("provider_customer_reference", sa.String(180), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_saas_billing_accounts_tenant"),
        sa.CheckConstraint("version >= 1", name="ck_saas_billing_accounts_version_positive"),
    )
    op.create_index(
        "ix_saas_billing_accounts_tenant_id",
        "saas_billing_accounts",
        ["tenant_id"],
    )

    # Backfill only from persisted contractual/customer-master data. No tenant
    # operational table participates in this projection.
    op.execute("""
        INSERT INTO saas_billing_accounts (
            id, tenant_id, legal_name, tax_id, contact_name, contact_email,
            contact_phone, currency, version, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), tenant.id,
            COALESCE(profile.legal_name, tenant.legal_name), profile.tax_id,
            latest.limits->'billing'->>'contact_name',
            latest.limits->'billing'->>'email',
            latest.limits->'billing'->>'phone',
            'BRL', 1, now(), now()
        FROM tenants AS tenant
        JOIN LATERAL (
            SELECT contract.limits
            FROM tenant_contracts AS contract
            WHERE contract.tenant_id = tenant.id
            ORDER BY contract.version DESC
            LIMIT 1
        ) AS latest ON true
        LEFT JOIN tenant_profiles AS profile ON profile.tenant_id = tenant.id
    """)

    op.execute("ALTER TABLE saas_billing_accounts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE saas_billing_accounts FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY saas_billing_accounts_platform_only
        ON saas_billing_accounts FOR ALL
        USING (current_setting('app.platform_access', true) = 'true')
        WITH CHECK (current_setting('app.platform_access', true) = 'true')
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON saas_billing_accounts TO dashem_runtime")


def downgrade() -> None:
    op.drop_table("saas_billing_accounts")
    op.add_column(
        "tenant_subscriptions",
        sa.Column("billing_status", sa.String(length=32), nullable=False, server_default="PENDING"),
    )
    op.drop_constraint(
        "ck_tenant_subscriptions_version_positive",
        "tenant_subscriptions",
        type_="check",
    )
    op.drop_column("tenant_subscriptions", "version")

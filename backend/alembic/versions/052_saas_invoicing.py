"""Add platform-owned SaaS invoices and immutable invoice lines.

Revision ID: 052_saas_invoicing
Revises: 051_platform_finance_permissions
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "052_saas_invoicing"
down_revision = "051_platform_finance_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    money = sa.Numeric(14, 2)
    op.create_table(
        "saas_invoices",
        sa.Column("id", uid, nullable=False),
        sa.Column("public_number", sa.String(40), nullable=False),
        sa.Column("tenant_id", uid, nullable=False),
        sa.Column("billing_account_id", uid, nullable=False),
        sa.Column("subscription_id", uid, nullable=False),
        sa.Column("contract_id", uid, nullable=False),
        sa.Column("plan_id", uid, nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="BRL"),
        sa.Column("subtotal", money, nullable=False),
        sa.Column("discount_amount", money, nullable=False, server_default="0"),
        sa.Column("tax_amount", money, nullable=False, server_default="0"),
        sa.Column("total_amount", money, nullable=False),
        sa.Column("balance_amount", money, nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="DRAFT"),
        sa.Column("generation_key", sa.String(64), nullable=False),
        sa.Column("generation_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("plan_code_snapshot", sa.String(60), nullable=False),
        sa.Column("plan_name_snapshot", sa.String(120), nullable=False),
        sa.Column("description_snapshot", sa.String(240), nullable=False),
        sa.Column("billing_legal_name_snapshot", sa.String(200), nullable=False),
        sa.Column("billing_tax_id_snapshot", sa.String(14), nullable=False),
        sa.Column("billing_contact_email_snapshot", sa.String(254), nullable=False),
        sa.Column("fiscal_reference", sa.String(180), nullable=True),
        sa.Column("provider_reference", sa.String(180), nullable=True),
        sa.Column("issued_at", sa.DateTime(), nullable=True),
        sa.Column("issued_by", uid, nullable=True),
        sa.Column("issue_idempotency_key", sa.String(160), nullable=True),
        sa.Column("issue_request_hash", sa.String(64), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", uid, nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("void_idempotency_key", sa.String(160), nullable=True),
        sa.Column("void_request_hash", sa.String(64), nullable=True),
        sa.Column("created_by", uid, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["billing_account_id"], ["saas_billing_accounts.id"]),
        sa.ForeignKeyConstraint(["subscription_id"], ["tenant_subscriptions.tenant_id"]),
        sa.ForeignKeyConstraint(["contract_id"], ["tenant_contracts.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["service_plans.id"]),
        sa.ForeignKeyConstraint(["issued_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_number", name="uq_saas_invoices_public_number"),
        sa.UniqueConstraint("generation_key", name="uq_saas_invoices_generation_key"),
        sa.UniqueConstraint("issue_idempotency_key", name="uq_saas_invoices_issue_idempotency"),
        sa.UniqueConstraint("void_idempotency_key", name="uq_saas_invoices_void_idempotency"),
        sa.UniqueConstraint(
            "subscription_id", "period_start", "generation_revision",
            name="uq_saas_invoice_subscription_period_revision",
        ),
        sa.CheckConstraint("tenant_id = subscription_id", name="ck_saas_invoice_subscription_tenant"),
        sa.CheckConstraint("period_start = date_trunc('month', period_start)::date", name="ck_saas_invoice_period_start"),
        sa.CheckConstraint(
            "period_end = (date_trunc('month', period_start) + interval '1 month - 1 day')::date",
            name="ck_saas_invoice_period_end",
        ),
        sa.CheckConstraint("subtotal >= 0", name="ck_saas_invoice_subtotal_nonnegative"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_saas_invoice_discount_nonnegative"),
        sa.CheckConstraint("tax_amount >= 0", name="ck_saas_invoice_tax_nonnegative"),
        sa.CheckConstraint("total_amount >= 0", name="ck_saas_invoice_total_nonnegative"),
        sa.CheckConstraint("balance_amount >= 0 AND balance_amount <= total_amount", name="ck_saas_invoice_balance"),
        sa.CheckConstraint("total_amount = subtotal - discount_amount + tax_amount", name="ck_saas_invoice_total_formula"),
        sa.CheckConstraint("version >= 1", name="ck_saas_invoice_version_positive"),
        sa.CheckConstraint("generation_revision >= 1", name="ck_saas_invoice_generation_revision_positive"),
    )
    for column in (
        "public_number", "tenant_id", "billing_account_id", "subscription_id",
        "contract_id", "plan_id", "period_start", "period_end", "due_date",
        "status", "issued_at", "issued_by", "voided_at", "voided_by", "created_by", "created_at",
    ):
        op.create_index(f"ix_saas_invoices_{column}", "saas_invoices", [column])
    op.create_index(
        "ix_saas_invoices_period_status", "saas_invoices", ["period_start", "status"]
    )

    op.create_table(
        "saas_invoice_lines",
        sa.Column("id", uid, nullable=False),
        sa.Column("invoice_id", uid, nullable=False),
        sa.Column("line_type", sa.String(), nullable=False),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("unit_amount", money, nullable=False),
        sa.Column("total_amount", money, nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["invoice_id"], ["saas_invoices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantity > 0", name="ck_saas_invoice_line_quantity_positive"),
        sa.CheckConstraint("total_amount = quantity * unit_amount", name="ck_saas_invoice_line_total_formula"),
    )
    op.create_index("ix_saas_invoice_lines_invoice_id", "saas_invoice_lines", ["invoice_id"])
    op.create_index("ix_saas_invoice_lines_line_type", "saas_invoice_lines", ["line_type"])

    for table in ("saas_invoices", "saas_invoice_lines"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_platform_only ON {table} FOR ALL "
            "USING (current_setting('app.platform_access', true) = 'true') "
            "WITH CHECK (current_setting('app.platform_access', true) = 'true')"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")

    op.execute("""
        CREATE FUNCTION protect_issued_saas_invoice_snapshot() RETURNS trigger AS $$
        BEGIN
            IF OLD.status <> 'DRAFT' AND (
                NEW.public_number IS DISTINCT FROM OLD.public_number OR
                NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR
                NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id OR
                NEW.subscription_id IS DISTINCT FROM OLD.subscription_id OR
                NEW.contract_id IS DISTINCT FROM OLD.contract_id OR
                NEW.plan_id IS DISTINCT FROM OLD.plan_id OR
                NEW.period_start IS DISTINCT FROM OLD.period_start OR
                NEW.period_end IS DISTINCT FROM OLD.period_end OR
                NEW.due_date IS DISTINCT FROM OLD.due_date OR
                NEW.currency IS DISTINCT FROM OLD.currency OR
                NEW.subtotal IS DISTINCT FROM OLD.subtotal OR
                NEW.discount_amount IS DISTINCT FROM OLD.discount_amount OR
                NEW.tax_amount IS DISTINCT FROM OLD.tax_amount OR
                NEW.total_amount IS DISTINCT FROM OLD.total_amount OR
                NEW.generation_key IS DISTINCT FROM OLD.generation_key OR
                NEW.generation_revision IS DISTINCT FROM OLD.generation_revision OR
                NEW.contract_version IS DISTINCT FROM OLD.contract_version OR
                NEW.plan_code_snapshot IS DISTINCT FROM OLD.plan_code_snapshot OR
                NEW.plan_name_snapshot IS DISTINCT FROM OLD.plan_name_snapshot OR
                NEW.description_snapshot IS DISTINCT FROM OLD.description_snapshot OR
                NEW.billing_legal_name_snapshot IS DISTINCT FROM OLD.billing_legal_name_snapshot OR
                NEW.billing_tax_id_snapshot IS DISTINCT FROM OLD.billing_tax_id_snapshot OR
                NEW.billing_contact_email_snapshot IS DISTINCT FROM OLD.billing_contact_email_snapshot
                OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
                OR NEW.issued_by IS DISTINCT FROM OLD.issued_by
                OR NEW.issue_idempotency_key IS DISTINCT FROM OLD.issue_idempotency_key
                OR NEW.issue_request_hash IS DISTINCT FROM OLD.issue_request_hash
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
            ) THEN
                RAISE EXCEPTION 'issued SaaS invoice snapshot is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_protect_issued_saas_invoice_snapshot
        BEFORE UPDATE ON saas_invoices
        FOR EACH ROW EXECUTE FUNCTION protect_issued_saas_invoice_snapshot()
    """)
    op.execute("""
        CREATE FUNCTION protect_issued_saas_invoice_line() RETURNS trigger AS $$
        DECLARE invoice_status text;
        DECLARE target_invoice_id uuid;
        BEGIN
            target_invoice_id := CASE
                WHEN TG_OP = 'INSERT' THEN NEW.invoice_id
                ELSE OLD.invoice_id
            END;
            SELECT status INTO invoice_status
            FROM saas_invoices WHERE id = target_invoice_id;
            IF invoice_status <> 'DRAFT' THEN
                RAISE EXCEPTION 'issued SaaS invoice lines are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_protect_issued_saas_invoice_line
        BEFORE INSERT OR UPDATE OR DELETE ON saas_invoice_lines
        FOR EACH ROW EXECUTE FUNCTION protect_issued_saas_invoice_line()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_protect_issued_saas_invoice_line ON saas_invoice_lines")
    op.execute("DROP FUNCTION IF EXISTS protect_issued_saas_invoice_line()")
    op.execute("DROP TRIGGER IF EXISTS trg_protect_issued_saas_invoice_snapshot ON saas_invoices")
    op.execute("DROP FUNCTION IF EXISTS protect_issued_saas_invoice_snapshot()")
    op.drop_table("saas_invoice_lines")
    op.drop_table("saas_invoices")

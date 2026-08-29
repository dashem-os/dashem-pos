"""Add real SaaS receipts, allocations, refunds, and collection events.

Revision ID: 054_saas_receipts_collections
Revises: 053_secure_function_paths
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "054_saas_receipts_collections"
down_revision = "053_secure_function_paths"
branch_labels = None
depends_on = None


def _platform_table(table: str, *, append_only: bool = False) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_platform_only ON {table} FOR ALL "
        "USING (current_setting('app.platform_access', true) = 'true') "
        "WITH CHECK (current_setting('app.platform_access', true) = 'true')"
    )
    if append_only:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION dashem_reject_immutable_mutation()"
        )
        op.execute(f"GRANT SELECT, INSERT ON {table} TO dashem_runtime")
    else:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    money = sa.Numeric(14, 2)
    op.add_column("saas_invoices", sa.Column("paid_at", sa.DateTime(), nullable=True))
    op.create_index("ix_saas_invoices_paid_at", "saas_invoices", ["paid_at"])

    op.create_table(
        "saas_payments",
        sa.Column("id", uid, nullable=False),
        sa.Column("tenant_id", uid, nullable=False),
        sa.Column("billing_account_id", uid, nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("provider_payment_reference", sa.String(180), nullable=True),
        sa.Column("external_event_id", sa.String(180), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("reconcile_idempotency_key", sa.String(160), nullable=True),
        sa.Column("reconcile_request_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="BRL"),
        sa.Column("amount", money, nullable=False),
        sa.Column("payment_method_summary", sa.String(80), nullable=True),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("evidence_reference", sa.String(240), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("succeeded_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", uid, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["billing_account_id"], ["saas_billing_accounts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_saas_payments_idempotency_key"),
        sa.UniqueConstraint(
            "reconcile_idempotency_key", name="uq_saas_payments_reconcile_idempotency"
        ),
        sa.UniqueConstraint(
            "provider", "provider_payment_reference",
            name="uq_saas_payments_provider_reference",
        ),
        sa.CheckConstraint("amount > 0", name="ck_saas_payments_amount_positive"),
        sa.CheckConstraint("version >= 1", name="ck_saas_payments_version_positive"),
    )
    for column in (
        "tenant_id", "billing_account_id", "provider", "provider_payment_reference",
        "external_event_id", "status", "received_at", "succeeded_at", "created_by",
        "created_at",
    ):
        op.create_index(f"ix_saas_payments_{column}", "saas_payments", [column])
    op.create_index(
        "ix_saas_payments_received_status", "saas_payments", ["received_at", "status"]
    )

    op.create_table(
        "saas_payment_allocations",
        sa.Column("id", uid, nullable=False),
        sa.Column("payment_id", uid, nullable=False),
        sa.Column("invoice_id", uid, nullable=False),
        sa.Column("amount", money, nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("allocated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["payment_id"], ["saas_payments.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["saas_invoices.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_saas_payment_allocations_idempotency_key"),
        sa.CheckConstraint("amount > 0", name="ck_saas_payment_allocations_amount_positive"),
    )
    op.create_index("ix_saas_payment_allocations_payment_id", "saas_payment_allocations", ["payment_id"])
    op.create_index("ix_saas_payment_allocations_invoice_id", "saas_payment_allocations", ["invoice_id"])
    op.create_index("ix_saas_payment_allocations_allocated_at", "saas_payment_allocations", ["allocated_at"])

    op.create_table(
        "saas_refunds",
        sa.Column("id", uid, nullable=False),
        sa.Column("payment_id", uid, nullable=False),
        sa.Column("invoice_id", uid, nullable=False),
        sa.Column("amount", money, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.String(240), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("refunded_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", uid, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["payment_id"], ["saas_payments.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["saas_invoices.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_saas_refunds_idempotency_key"),
        sa.CheckConstraint("amount > 0", name="ck_saas_refunds_amount_positive"),
    )
    for column in ("payment_id", "invoice_id", "refunded_at", "created_by"):
        op.create_index(f"ix_saas_refunds_{column}", "saas_refunds", [column])

    op.create_table(
        "saas_collection_events",
        sa.Column("id", uid, nullable=False),
        sa.Column("invoice_id", uid, nullable=False),
        sa.Column("tenant_id", uid, nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("outcome", sa.String(80), nullable=False),
        sa.Column("recipient_masked", sa.String(160), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.String(240), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("actor_id", uid, nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["invoice_id"], ["saas_invoices.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_saas_collection_events_idempotency_key"),
    )
    for column in ("invoice_id", "tenant_id", "event_type", "actor_id", "occurred_at"):
        op.create_index(f"ix_saas_collection_events_{column}", "saas_collection_events", [column])

    _platform_table("saas_payments")
    for table in ("saas_payment_allocations", "saas_refunds", "saas_collection_events"):
        _platform_table(table, append_only=True)

    op.execute("""
        CREATE FUNCTION protect_succeeded_saas_payment() RETURNS trigger AS $$
        BEGIN
            IF OLD.status IN ('SUCCEEDED', 'PARTIALLY_REFUNDED', 'REFUNDED') AND (
                NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR
                NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id OR
                NEW.provider IS DISTINCT FROM OLD.provider OR
                NEW.provider_payment_reference IS DISTINCT FROM OLD.provider_payment_reference OR
                NEW.external_event_id IS DISTINCT FROM OLD.external_event_id OR
                NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR
                NEW.request_hash IS DISTINCT FROM OLD.request_hash OR
                NEW.currency IS DISTINCT FROM OLD.currency OR
                NEW.amount IS DISTINCT FROM OLD.amount OR
                NEW.payment_method_summary IS DISTINCT FROM OLD.payment_method_summary OR
                NEW.evidence_reference IS DISTINCT FROM OLD.evidence_reference OR
                NEW.received_at IS DISTINCT FROM OLD.received_at OR
                NEW.succeeded_at IS DISTINCT FROM OLD.succeeded_at OR
                NEW.created_by IS DISTINCT FROM OLD.created_by
            ) THEN
                RAISE EXCEPTION 'succeeded SaaS payment facts are immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, public
    """)
    op.execute("""
        CREATE TRIGGER trg_protect_succeeded_saas_payment
        BEFORE UPDATE ON saas_payments
        FOR EACH ROW EXECUTE FUNCTION protect_succeeded_saas_payment()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_protect_succeeded_saas_payment ON saas_payments")
    op.execute("DROP FUNCTION IF EXISTS protect_succeeded_saas_payment()")
    for table in ("saas_collection_events", "saas_refunds", "saas_payment_allocations"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.drop_table("saas_collection_events")
    op.drop_table("saas_refunds")
    op.drop_table("saas_payment_allocations")
    op.drop_table("saas_payments")
    op.drop_index("ix_saas_invoices_paid_at", table_name="saas_invoices")
    op.drop_column("saas_invoices", "paid_at")

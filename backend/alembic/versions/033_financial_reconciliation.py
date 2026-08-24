"""S16 cash closing, fiscal retry and financial reconciliation.

Revision ID: 033_financial_reconciliation
Revises: 032_receivable_settlement
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "033_financial_reconciliation"
down_revision = "032_receivable_settlement"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def _tenant_rls(table: str) -> None:
    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    expression = f"({platform}) OR (({tenant}) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store}))"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({expression}) WITH CHECK ({expression})")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.add_column("cash_sessions", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("cash_sessions", sa.Column("blind_count", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("cash_sessions", sa.Column("closing_started_at", sa.DateTime(), nullable=True))
    op.add_column("cash_sessions", sa.Column("closing_started_by", uid, nullable=True))
    op.add_column("cash_sessions", sa.Column("divergence_reason", sa.Text(), nullable=True))
    op.create_index("ix_cash_sessions_closing_started_by", "cash_sessions", ["closing_started_by"])

    op.add_column("cash_movements", sa.Column("source_type", sa.String(), nullable=True))
    op.add_column("cash_movements", sa.Column("source_id", sa.String(), nullable=True))
    op.add_column("cash_movements", sa.Column("idempotency_key", sa.String(), nullable=True))
    _indexes("cash_movements", ("source_type", "source_id", "idempotency_key"))
    op.create_unique_constraint("uq_tenant_cash_movement_key", "cash_movements", ["tenant_id", "idempotency_key"])

    op.add_column("fiscal_documents", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("fiscal_documents", sa.Column("last_attempt_at", sa.DateTime(), nullable=True))
    op.create_index("ix_fiscal_documents_last_attempt_at", "fiscal_documents", ["last_attempt_at"])

    op.create_table(
        "financial_reconciliations",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("sale_id", uid, sa.ForeignKey("sales.id"), nullable=False),
        sa.Column("negotiation_id", uid, sa.ForeignKey("checkout_negotiations.id"), nullable=True),
        sa.Column("fiscal_document_id", uid, sa.ForeignKey("fiscal_documents.id"), nullable=True),
        sa.Column("cash_session_id", uid, sa.ForeignKey("cash_sessions.id"), nullable=True),
        sa.Column("expected_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("payment_total", sa.Numeric(14, 4), nullable=False),
        sa.Column("receivable_total", sa.Numeric(14, 4), nullable=False),
        sa.Column("provider_reported_total", sa.Numeric(14, 4), nullable=True),
        sa.Column("difference", sa.Numeric(14, 4), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("provider_reference", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("actor_id", uid, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "sale_id", name="uq_tenant_sale_reconciliation"),
    )
    _indexes("financial_reconciliations", ("tenant_id", "store_id", "sale_id", "negotiation_id", "fiscal_document_id", "cash_session_id", "status", "provider", "provider_reference", "actor_id", "checked_at"))
    _tenant_rls("financial_reconciliations")

    op.create_table(
        "reconciliation_events",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("reconciliation_id", uid, sa.ForeignKey("financial_reconciliations.id"), nullable=False),
        sa.Column("actor_id", uid, nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("expected_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("observed_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("difference", sa.Numeric(14, 4), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("provider_reference", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    _indexes("reconciliation_events", ("tenant_id", "store_id", "reconciliation_id", "actor_id", "status", "created_at"))
    _tenant_rls("reconciliation_events")

    op.create_table(
        "payment_refunds",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("payment_id", uid, sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("cash_session_id", uid, sa.ForeignKey("cash_sessions.id"), nullable=True),
        sa.Column("cash_movement_id", uid, sa.ForeignKey("cash_movements.id"), nullable=True, unique=True),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("provider_reference", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("actor_id", uid, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_payment_refund_amount_positive"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_payment_refund_key"),
    )
    _indexes("payment_refunds", ("tenant_id", "store_id", "payment_id", "cash_session_id", "provider_reference", "idempotency_key", "actor_id", "created_at"))
    _tenant_rls("payment_refunds")

    permission = sa.table("permissions", sa.column("key", sa.String), sa.column("name", sa.String), sa.column("description", sa.Text), sa.column("capability_key", sa.String), sa.column("created_at", sa.DateTime))
    now = datetime.utcnow()
    op.bulk_insert(permission, [
        {"key": "reconciliation.read", "name": "Consultar conciliações", "description": "Consultar conciliações financeiras", "capability_key": "payments", "created_at": now},
        {"key": "reconciliation.manage", "name": "Executar conciliação", "description": "Registrar resultado sem alterar o fato financeiro", "capability_key": "payments", "created_at": now},
    ])
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system = true AND rp.code IN ('OWNER','TENANT_OWNER','ADMIN','MANAGER','AUDITOR')
          AND p.key IN ('reconciliation.read','reconciliation.manage')
    """))


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key IN ('reconciliation.read','reconciliation.manage')")
    op.execute("DELETE FROM permissions WHERE key IN ('reconciliation.read','reconciliation.manage')")
    op.drop_table("payment_refunds")
    op.drop_table("reconciliation_events")
    op.drop_table("financial_reconciliations")
    op.drop_index("ix_fiscal_documents_last_attempt_at", table_name="fiscal_documents")
    op.drop_column("fiscal_documents", "last_attempt_at")
    op.drop_column("fiscal_documents", "attempt_count")
    op.drop_constraint("uq_tenant_cash_movement_key", "cash_movements", type_="unique")
    for column in ("idempotency_key", "source_id", "source_type"):
        op.drop_index(f"ix_cash_movements_{column}", table_name="cash_movements")
        op.drop_column("cash_movements", column)
    op.drop_index("ix_cash_sessions_closing_started_by", table_name="cash_sessions")
    for column in ("divergence_reason", "closing_started_by", "closing_started_at", "blind_count", "version"):
        op.drop_column("cash_sessions", column)

"""S15 receivable settlements, collection and agreements.

Revision ID: 032_receivable_settlement
Revises: 031_credit_receivables
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "032_receivable_settlement"
down_revision = "031_credit_receivables"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def _tenant_rls(table: str, store_scoped: bool = True) -> None:
    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    expression = f"({platform}) OR (({tenant})"
    if store_scoped:
        store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
        expression += f" AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store})"
    expression += ")"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({expression}) WITH CHECK ({expression})")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    now = datetime.utcnow()
    op.create_table(
        "receivable_agreements",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("customer_id", uid, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("original_principal", sa.Numeric(14, 4), nullable=False),
        sa.Column("interest_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("fine_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("discount_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("agreement_total", sa.Numeric(14, 4), nullable=False),
        sa.Column("installment_count", sa.Integer(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", uid, nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("original_principal > 0", name="ck_agreement_principal_positive"),
        sa.CheckConstraint("agreement_total > 0", name="ck_agreement_total_positive"),
        sa.CheckConstraint("installment_count > 0", name="ck_agreement_installments_positive"),
        sa.CheckConstraint("version > 0", name="ck_agreement_version_positive"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_receivable_agreement_key"),
    )
    _indexes("receivable_agreements", ("tenant_id", "store_id", "customer_id", "status", "idempotency_key", "actor_id", "created_at")); _tenant_rls("receivable_agreements")

    op.alter_column("receivables", "negotiation_id", nullable=True)
    op.add_column("receivables", sa.Column("agreement_id", uid, nullable=True))
    op.add_column("receivables", sa.Column("agreement_installment_number", sa.Integer(), nullable=True))
    op.add_column("receivables", sa.Column("origin_receivable_id", uid, nullable=True))
    op.create_foreign_key("fk_receivable_agreement", "receivables", "receivable_agreements", ["agreement_id"], ["id"])
    op.create_foreign_key("fk_receivable_origin", "receivables", "receivables", ["origin_receivable_id"], ["id"])
    op.create_index("ix_receivables_agreement_id", "receivables", ["agreement_id"])
    op.create_index("ix_receivables_agreement_installment_number", "receivables", ["agreement_installment_number"])
    op.create_index("ix_receivables_origin_receivable_id", "receivables", ["origin_receivable_id"])

    op.create_table(
        "receivable_receipts",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("customer_id", uid, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False), sa.Column("method", sa.String(40), nullable=False),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("cash_session_id", uid, sa.ForeignKey("cash_sessions.id"), nullable=True),
        sa.Column("cash_movement_id", uid, sa.ForeignKey("cash_movements.id"), nullable=True, unique=True),
        sa.Column("provider", sa.String(80), nullable=False), sa.Column("provider_reference", sa.String(160), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", uid, nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_receivable_receipt_amount_positive"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_receivable_receipt_key"),
    )
    _indexes("receivable_receipts", ("tenant_id", "store_id", "customer_id", "status", "method", "cash_session_id", "provider", "provider_reference", "idempotency_key", "actor_id", "confirmed_at", "created_at")); _tenant_rls("receivable_receipts")

    op.create_table(
        "receivable_receipt_allocations",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("receipt_id", uid, sa.ForeignKey("receivable_receipts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("receivable_id", uid, sa.ForeignKey("receivables.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("principal_amount", sa.Numeric(14, 4), nullable=False), sa.Column("interest_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("fine_amount", sa.Numeric(14, 4), nullable=False), sa.Column("discount_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("abatement_amount", sa.Numeric(14, 4), nullable=False), sa.Column("net_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("principal_amount > 0", name="ck_receipt_allocation_principal_positive"),
        sa.CheckConstraint("interest_amount >= 0 AND fine_amount >= 0 AND discount_amount >= 0 AND abatement_amount >= 0", name="ck_receipt_allocation_adjustments_nonnegative"),
        sa.CheckConstraint("net_amount >= 0", name="ck_receipt_allocation_net_nonnegative"),
        sa.UniqueConstraint("receipt_id", "receivable_id", name="uq_receipt_receivable_allocation"),
    )
    _indexes("receivable_receipt_allocations", ("tenant_id", "receipt_id", "receivable_id", "created_at")); _tenant_rls("receivable_receipt_allocations", False)

    op.create_table(
        "receivable_agreement_items",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("agreement_id", uid, sa.ForeignKey("receivable_agreements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("receivable_id", uid, sa.ForeignKey("receivables.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("principal_selected", sa.Numeric(14, 4), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("agreement_id", "receivable_id", name="uq_agreement_receivable"),
    )
    _indexes("receivable_agreement_items", ("tenant_id", "agreement_id", "receivable_id", "created_at")); _tenant_rls("receivable_agreement_items", False)

    op.create_table(
        "receivable_collection_events",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("customer_id", uid, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("receivable_id", uid, sa.ForeignKey("receivables.id"), nullable=True),
        sa.Column("agreement_id", uid, sa.ForeignKey("receivable_agreements.id"), nullable=True),
        sa.Column("event_type", sa.String(60), nullable=False), sa.Column("promised_for", sa.DateTime(), nullable=True),
        sa.Column("actor_id", uid, nullable=False), sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    _indexes("receivable_collection_events", ("tenant_id", "store_id", "customer_id", "receivable_id", "agreement_id", "event_type", "promised_for", "actor_id", "created_at")); _tenant_rls("receivable_collection_events")

    permission = sa.table("permissions", sa.column("key", sa.String), sa.column("name", sa.String), sa.column("description", sa.Text), sa.column("capability_key", sa.String), sa.column("created_at", sa.DateTime))
    keys = (("receivable.settle", "Liquidar contas a receber"), ("receivable.agreement", "Criar renegociação"), ("receivable.collect", "Registrar ação de cobrança"))
    op.bulk_insert(permission, [{"key": key, "name": name, "description": name, "capability_key": "receivables", "created_at": now} for key, name in keys])
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system = true AND rp.code IN ('OWNER','TENANT_OWNER','ADMIN','MANAGER')
          AND p.key IN ('receivable.settle','receivable.agreement','receivable.collect')
    """))


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key IN ('receivable.settle','receivable.agreement','receivable.collect')")
    op.execute("DELETE FROM permissions WHERE key IN ('receivable.settle','receivable.agreement','receivable.collect')")
    op.drop_table("receivable_collection_events")
    op.drop_table("receivable_agreement_items")
    op.drop_table("receivable_receipt_allocations")
    op.drop_table("receivable_receipts")
    op.drop_index("ix_receivables_origin_receivable_id", table_name="receivables")
    op.drop_index("ix_receivables_agreement_installment_number", table_name="receivables")
    op.drop_index("ix_receivables_agreement_id", table_name="receivables")
    op.drop_constraint("fk_receivable_origin", "receivables", type_="foreignkey")
    op.drop_constraint("fk_receivable_agreement", "receivables", type_="foreignkey")
    op.drop_column("receivables", "origin_receivable_id")
    op.drop_column("receivables", "agreement_installment_number")
    op.drop_column("receivables", "agreement_id")
    op.alter_column("receivables", "negotiation_id", nullable=False)
    op.drop_table("receivable_agreements")
